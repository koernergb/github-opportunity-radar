"""Incremental open-issue and changed-comment synchronization."""

from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    PipelineRun,
    Repository,
)
from radar.db.session import transaction
from radar.domain.errors import AuthenticationError, GitHubError
from radar.domain.schemas import IssueCommentDTO, IssueDTO
from radar.ingestion.comments import replace_weak_url_links, upsert_comment
from radar.ingestion.cursors import advance_cursor, cursor_since
from radar.pipeline.runs import add_run_event, create_pipeline_run, finish_pipeline_run
from radar.settings import RadarConfig

STAGE = "issues"


class IssueGateway(Protocol):
    async def list_issues(
        self,
        full_name: str,
        *,
        state: str,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueDTO]: ...

    async def list_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueCommentDTO]: ...


@dataclass
class IssueSyncSummary:
    issues_created: int = 0
    issues_updated: int = 0
    issues_unchanged: int = 0
    pull_requests_excluded: int = 0
    comments_created: int = 0
    comments_updated: int = 0
    comment_failures: int = 0
    repositories_failed: int = 0
    pull_requests_synced: int = 0
    reviews_stored: int = 0
    pr_comments_stored: int = 0
    issue_links_stored: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def sync_issues(
    config: RadarConfig,
    gateway: IssueGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    repository_filter: str | None = None,
    full: bool = False,
) -> IssueSyncSummary:
    """Synchronize each configured repository with independent cursor safety."""
    summary = IssueSyncSummary()
    with transaction(sessions) as session:
        run = create_pipeline_run(
            session,
            config_hash=config.config_hash,
            stage=STAGE,
            started_at=clock.now(),
        )
        run_id = run.id

    for configured in config.repositories:
        if not configured.enabled or (
            repository_filter is not None and configured.full_name != repository_filter
        ):
            continue
        started_at = clock.now()
        try:
            await _sync_one_repository(
                config,
                gateway,
                sessions,
                clock,
                configured.full_name,
                started_at,
                summary,
                run_id,
                full=full,
            )
        except AuthenticationError:
            _finish(sessions, clock, run_id, "failed", summary)
            raise
        except GitHubError as error:
            summary.repositories_failed += 1
            with transaction(sessions) as session:
                add_run_event(
                    session,
                    run_id=run_id,
                    stage=STAGE,
                    event_type="issue_sync_error",
                    level="error",
                    message=f"Failed to synchronize {configured.full_name}",
                    error_type=type(error).__name__,
                    details={"repository": configured.full_name},
                    created_at=clock.now(),
                )

    status = "partial" if summary.repositories_failed or summary.comment_failures else "success"
    _finish(sessions, clock, run_id, status, summary)
    return summary


async def _sync_one_repository(
    config: RadarConfig,
    gateway: IssueGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    full_name: str,
    started_at: datetime,
    summary: IssueSyncSummary,
    run_id: UUID,
    *,
    full: bool,
) -> None:
    with transaction(sessions) as session:
        repository = session.scalar(select(Repository).where(Repository.full_name == full_name))
        if repository is None:
            raise GitHubError(f"repository must be synchronized first: {full_name}")
        repository_id = repository.id
        since = cursor_since(
            session,
            scope_type="issues",
            scope_key=full_name,
            overlap_minutes=config.github.overlap_minutes,
            full=full,
        )

    iterator = await gateway.list_issues(
        full_name,
        state="open",
        since=since,
        max_pages=config.github.max_open_issue_pages,
    )
    changed_issues: list[tuple[UUID, IssueDTO]] = []
    async for observation in iterator:
        with transaction(sessions) as session:
            issue, created, changed = _upsert_issue(
                session, repository_id, observation, clock.now()
            )
            if observation.is_pull_request:
                summary.pull_requests_excluded += 1
            elif created:
                summary.issues_created += 1
            elif changed:
                summary.issues_updated += 1
            else:
                summary.issues_unchanged += 1
            if (created or changed) and not observation.is_pull_request:
                changed_issues.append((issue.id, observation))

    with transaction(sessions) as session:
        advance_cursor(
            session,
            scope_type="issues",
            scope_key=full_name,
            time_cursor=started_at,
            succeeded_at=clock.now(),
            metadata={"full": full},
        )

    for issue_id, observation in changed_issues:
        try:
            await _sync_issue_comments(
                config,
                gateway,
                sessions,
                clock,
                full_name,
                issue_id,
                observation,
                summary,
                full=full,
            )
        except AuthenticationError:
            raise
        except GitHubError as error:
            summary.comment_failures += 1
            with transaction(sessions) as session:
                add_run_event(
                    session,
                    run_id=run_id,
                    stage=STAGE,
                    event_type="comment_sync_error",
                    level="error",
                    message=f"Failed to synchronize comments for {full_name}#{observation.number}",
                    error_type=type(error).__name__,
                    details={"repository": full_name, "issue": observation.number},
                    created_at=clock.now(),
                )


def _upsert_issue(
    session: Session,
    repository_id: UUID,
    observation: IssueDTO,
    seen_at: datetime,
) -> tuple[Issue, bool, bool]:
    issue = session.scalar(select(Issue).where(Issue.github_id == observation.github_id))
    values = {
        "repository_id": repository_id,
        "node_id": observation.node_id,
        "number": observation.number,
        "title": observation.title,
        "body": observation.body,
        "state": observation.state.value,
        "state_reason": observation.state_reason,
        "url": observation.url,
        "author_login": observation.author.login if observation.author else None,
        "author_association": (
            observation.author_association.value if observation.author_association else None
        ),
        "locked": observation.locked,
        "comment_count": observation.comment_count,
        "github_created_at": observation.created_at,
        "github_updated_at": observation.updated_at,
        "github_closed_at": observation.closed_at,
        "inaccessible_at": None,
        "is_pull_request": observation.is_pull_request,
        "raw_json": observation.raw_payload,
    }
    created = issue is None
    if issue is None:
        issue = Issue(
            github_id=observation.github_id,
            last_seen_at=seen_at,
            **values,
        )
        session.add(issue)
        session.flush()
        changed = True
    else:
        changed = any(getattr(issue, key) != value for key, value in values.items())
        for key, value in values.items():
            setattr(issue, key, value)
        issue.last_seen_at = seen_at
    _replace_labels_and_assignees(session, issue.id, observation)
    return issue, created, changed


def _replace_labels_and_assignees(
    session: Session,
    issue_id: UUID,
    observation: IssueDTO,
) -> None:
    session.execute(delete(IssueLabel).where(IssueLabel.issue_id == issue_id))
    session.execute(delete(IssueAssignee).where(IssueAssignee.issue_id == issue_id))
    session.add_all(
        [
            IssueLabel(
                issue_id=issue_id,
                name=label.name,
                color=label.color,
                description=label.description,
            )
            for label in observation.labels
        ]
    )
    session.add_all(
        [IssueAssignee(issue_id=issue_id, login=user.login) for user in observation.assignees]
    )


async def _sync_issue_comments(
    config: RadarConfig,
    gateway: IssueGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    full_name: str,
    issue_id: UUID,
    issue: IssueDTO,
    summary: IssueSyncSummary,
    *,
    full: bool,
) -> None:
    scope_key = f"{full_name}#{issue.number}"
    with transaction(sessions) as session:
        since = cursor_since(
            session,
            scope_type="comments",
            scope_key=scope_key,
            overlap_minutes=config.github.overlap_minutes,
            full=full,
        )
    started_at = clock.now()
    iterator = await gateway.list_issue_comments(
        full_name,
        issue.number,
        since=since,
        max_pages=config.github.comment_max_pages,
    )
    async for comment in iterator:
        with transaction(sessions) as session:
            created, changed = upsert_comment(session, issue_id, comment)
            summary.comments_created += int(created)
            summary.comments_updated += int(changed)

    with transaction(sessions) as session:
        texts = [issue.body or ""]
        texts.extend(
            session.scalars(
                select(IssueComment.body).where(IssueComment.issue_id == issue_id)
            ).all()
        )
        replace_weak_url_links(
            session,
            issue_id,
            source_texts=texts,
            observed_at=clock.now(),
        )
        advance_cursor(
            session,
            scope_type="comments",
            scope_key=scope_key,
            time_cursor=started_at,
            succeeded_at=clock.now(),
        )


def mark_issue_inaccessible(
    session: Session,
    *,
    repository_id: UUID,
    number: int,
    observed_at: datetime,
) -> bool:
    """Soft-mark an inaccessible issue without deleting observations."""
    issue = session.scalar(
        select(Issue).where(
            Issue.repository_id == repository_id,
            Issue.number == number,
        )
    )
    if issue is None:
        return False
    issue.inaccessible_at = observed_at
    return True


def _finish(
    sessions: sessionmaker[Session],
    clock: Clock,
    run_id: UUID,
    status: str,
    summary: IssueSyncSummary,
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
