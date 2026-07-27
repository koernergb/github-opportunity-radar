"""Repository and contribution-document synchronization stage."""

from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import PipelineRun
from radar.db.repositories import store_repository_document, upsert_repository
from radar.db.session import transaction
from radar.domain.errors import AuthenticationError, GitHubError
from radar.domain.schemas import ContentDTO, RepositoryDTO
from radar.ingestion.documents import DOCUMENT_SPECS, decode_document
from radar.pipeline.runs import add_run_event, create_pipeline_run, finish_pipeline_run
from radar.settings import RadarConfig

STAGE = "repositories"


class RepositoryGateway(Protocol):
    async def get_repository(self, full_name: str) -> RepositoryDTO: ...

    async def get_repository_content(self, full_name: str, path: str) -> ContentDTO | None: ...


@dataclass
class RepositorySyncSummary:
    repositories_created: int = 0
    repositories_updated: int = 0
    repositories_unchanged: int = 0
    repositories_failed: int = 0
    repositories_skipped: int = 0
    documents_stored: int = 0
    documents_unchanged: int = 0
    documents_missing: int = 0
    documents_failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def sync_repositories(
    config: RadarConfig,
    gateway: RepositoryGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
) -> RepositorySyncSummary:
    """Synchronize configured repositories independently with persisted run state."""
    summary = RepositorySyncSummary()
    with transaction(sessions) as session:
        run = create_pipeline_run(
            session,
            config_hash=config.config_hash,
            stage=STAGE,
            started_at=clock.now(),
        )
        run_id = run.id

    try:
        for configured in config.repositories:
            if not configured.enabled:
                summary.repositories_skipped += 1
                continue
            try:
                observation = await gateway.get_repository(configured.full_name)
                with transaction(sessions) as session:
                    upsert = upsert_repository(
                        session,
                        observation,
                        configured,
                        config.github,
                        synced_at=clock.now(),
                    )
                    repository_id = upsert.repository.id
                if upsert.created:
                    summary.repositories_created += 1
                elif upsert.changed:
                    summary.repositories_updated += 1
                else:
                    summary.repositories_unchanged += 1

                await _sync_documents(
                    gateway,
                    sessions,
                    clock,
                    run_id,
                    configured.full_name,
                    repository_id,
                    summary,
                )
                _record_repository_success(
                    sessions,
                    clock,
                    run_id,
                    configured.full_name,
                    created=upsert.created,
                    changed=upsert.changed,
                )
            except AuthenticationError:
                raise
            except GitHubError as error:
                summary.repositories_failed += 1
                _record_error(sessions, clock, run_id, configured.full_name, error)
    except AuthenticationError as error:
        _finish(sessions, clock, run_id, "failed", summary)
        _record_error(sessions, clock, run_id, "github", error)
        raise

    status = "partial" if summary.repositories_failed or summary.documents_failed else "success"
    _finish(sessions, clock, run_id, status, summary)
    return summary


async def _sync_documents(
    gateway: RepositoryGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    run_id: UUID,
    full_name: str,
    repository_id: UUID,
    summary: RepositorySyncSummary,
) -> None:
    for spec in DOCUMENT_SPECS:
        try:
            content = await gateway.get_repository_content(full_name, spec.path)
            if content is None:
                summary.documents_missing += 1
                continue
            decoded = decode_document(content)
            with transaction(sessions) as session:
                stored = store_repository_document(
                    session,
                    repository_id,
                    content,
                    document_type=spec.document_type,
                    decoded_text=decoded,
                    fetched_at=clock.now(),
                )
            if stored:
                summary.documents_stored += 1
            else:
                summary.documents_unchanged += 1
        except AuthenticationError:
            raise
        except GitHubError as error:
            summary.documents_failed += 1
            _record_error(sessions, clock, run_id, f"{full_name}:{spec.path}", error)


def _record_repository_success(
    sessions: sessionmaker[Session],
    clock: Clock,
    run_id: UUID,
    full_name: str,
    *,
    created: bool,
    changed: bool,
) -> None:
    state = "created" if created else "updated" if changed else "unchanged"
    with transaction(sessions) as session:
        add_run_event(
            session,
            run_id=run_id,
            stage=STAGE,
            event_type="repository_synced",
            level="info",
            message=f"{full_name} {state}",
            created_at=clock.now(),
            details={"repository": full_name, "state": state},
        )


def _record_error(
    sessions: sessionmaker[Session],
    clock: Clock,
    run_id: UUID,
    scope: str,
    error: Exception,
) -> None:
    with transaction(sessions) as session:
        add_run_event(
            session,
            run_id=run_id,
            stage=STAGE,
            event_type="sync_error",
            level="error",
            message=f"Failed to synchronize {scope}",
            error_type=type(error).__name__,
            details={"scope": scope},
            created_at=clock.now(),
        )


def _finish(
    sessions: sessionmaker[Session],
    clock: Clock,
    run_id: UUID,
    status: str,
    summary: RepositorySyncSummary,
) -> None:
    with transaction(sessions) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        finish_pipeline_run(
            session,
            run,
            status=status,
            summary=summary.to_dict(),
            finished_at=clock.now(),
        )
