"""Observable bounded end-to-end radar pipeline orchestration."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.analysis.analyze import analyze_issue
from radar.analysis.provider import AnalysisProvider
from radar.clock import Clock
from radar.db.models import Issue, IssueFilterResult, PipelineRun, Repository
from radar.db.session import transaction
from radar.digest.markdown import render_markdown
from radar.digest.models import build_digest
from radar.domain.errors import AuthenticationError, GitHubError
from radar.filtering.engine import filter_issues
from radar.ingestion.issues import IssueGateway, sync_issues
from radar.ingestion.pull_requests import PullRequestGateway, sync_pull_request_history
from radar.ingestion.repositories import RepositoryGateway, sync_repositories
from radar.metrics.repository_health import calculate_repository_metrics
from radar.pipeline.runs import add_run_event, create_pipeline_run, finish_pipeline_run
from radar.scoring.engine import score_issue
from radar.settings import RadarConfig


class PipelineLockedError(RuntimeError):
    """Another orchestrator run is still active."""


class PipelineDeadlineError(RuntimeError):
    """The configured run deadline was reached safely."""


class PipelineCancelledError(RuntimeError):
    """Cancellation was observed at a documented safe boundary."""


class PipelineGateway(RepositoryGateway, IssueGateway, PullRequestGateway, Protocol):
    """Complete read-only gateway needed by an end-to-end pipeline run."""


@dataclass(frozen=True)
class PipelineOutcome:
    run_id: UUID
    status: str
    exit_code: int
    summary: dict[str, Any]
    markdown: str


async def run_pipeline(
    config: RadarConfig,
    gateway: PipelineGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    api_key: str | None = None,
    provider: AnalysisProvider | None = None,
    fallback_only: bool = False,
    deadline_seconds: int = 600,
    reserved_run_id: UUID | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> PipelineOutcome:
    """Run every stage with a global lock, deadline, budget, and safe partial results."""
    started_at = clock.now()
    run_id = _acquire_lock(sessions, config, started_at, reserved_run_id=reserved_run_id)
    summary: dict[str, Any] = {
        "repositories_failed": 0,
        "stage_failures": [],
        "analyzed": 0,
        "scored": 0,
        "analysis_budget": config.llm.max_candidates_per_run,
    }
    try:
        _stage(sessions, run_id, "sync", clock)
        _check_cancelled(should_cancel)
        repository_summary = await sync_repositories(config, gateway, sessions, clock)
        summary["repositories_failed"] = repository_summary.repositories_failed
        if repository_summary.repositories_failed or repository_summary.documents_failed:
            summary["stage_failures"].append("repository_sync_partial")

        for configured in config.repositories:
            if not configured.enabled:
                continue
            _check_deadline(clock, started_at, deadline_seconds)
            _check_cancelled(should_cancel)
            try:
                issue_summary = await sync_issues(
                    config,
                    gateway,
                    sessions,
                    clock,
                    repository_filter=configured.full_name,
                )
                if issue_summary.repositories_failed or issue_summary.comment_failures:
                    summary["stage_failures"].append(f"issue_sync_partial:{configured.full_name}")
                await sync_pull_request_history(
                    config,
                    gateway,
                    sessions,
                    clock,
                    repository_filter=configured.full_name,
                )
            except AuthenticationError:
                raise
            except GitHubError as error:
                _repository_failure(summary, configured.full_name, "sync", error)

        _stage(sessions, run_id, "metrics_filter", clock)
        for configured in config.repositories:
            if not configured.enabled:
                continue
            _check_deadline(clock, started_at, deadline_seconds)
            _check_cancelled(should_cancel)
            try:
                calculate_repository_metrics(
                    config,
                    sessions,
                    clock,
                    repository_filter=configured.full_name,
                )
                filter_issues(
                    config,
                    sessions,
                    clock,
                    repository_filter=configured.full_name,
                )
            except Exception as error:
                _repository_failure(summary, configured.full_name, "derive", error)

        _stage(sessions, run_id, "analyze_score", clock)
        candidates = _candidate_ids(sessions)
        for issue_id in candidates[: config.llm.max_candidates_per_run]:
            _check_deadline(clock, started_at, deadline_seconds)
            _check_cancelled(should_cancel)
            try:
                with transaction(sessions) as session:
                    analyze_issue(
                        session,
                        issue_id=issue_id,
                        config=config,
                        clock=clock,
                        api_key=api_key,
                        provider=provider,
                        fallback_only=fallback_only,
                    )
                summary["analyzed"] += 1
                with transaction(sessions) as session:
                    score_issue(session, issue_id=issue_id, config=config, clock=clock)
                summary["scored"] += 1
            except Exception as error:
                _issue_failure(summary, issue_id, error)

        _stage(sessions, run_id, "digest", clock)
        with sessions() as session:
            digest = build_digest(session, config, generated_at=clock.now())
            markdown = render_markdown(digest)
        status = "partial" if summary["stage_failures"] else "success"
        summary["digest_items"] = len(digest.items)
        _finish(sessions, run_id, status, summary, clock)
        return PipelineOutcome(
            run_id=run_id,
            status=status,
            exit_code=4 if status == "partial" else 0,
            summary=summary,
            markdown=markdown,
        )
    except AuthenticationError:
        summary["stage_failures"].append("authentication")
        _finish(sessions, run_id, "failed", summary, clock)
        raise
    except PipelineDeadlineError:
        summary["stage_failures"].append("deadline")
        _finish(sessions, run_id, "partial", summary, clock)
        return PipelineOutcome(run_id, "partial", 4, summary, "")
    except PipelineCancelledError:
        summary["stage_failures"].append("cancelled_at_safe_boundary")
        _finish(sessions, run_id, "cancelled", summary, clock)
        return PipelineOutcome(run_id, "cancelled", 4, summary, "")
    except Exception:
        _finish(sessions, run_id, "failed", summary, clock)
        raise


def _acquire_lock(
    sessions: sessionmaker[Session],
    config: RadarConfig,
    started_at: datetime,
    *,
    reserved_run_id: UUID | None = None,
) -> UUID:
    with transaction(sessions) as session:
        active = session.scalar(
            select(PipelineRun).where(
                PipelineRun.status.in_({"queued", "running"}),
                PipelineRun.current_stage == "orchestrator",
                PipelineRun.id != reserved_run_id,
            )
        )
        if active is not None:
            raise PipelineLockedError(f"pipeline run already active: {active.id}")
        if reserved_run_id is not None:
            run = session.get(PipelineRun, reserved_run_id)
            if run is None or run.status != "queued":
                raise PipelineLockedError("reserved pipeline run is unavailable")
            run.status = "running"
            run.started_at = started_at
            return run.id
        run = create_pipeline_run(
            session,
            config_hash=config.config_hash,
            stage="orchestrator",
            started_at=started_at,
        )
        return run.id


def _candidate_ids(sessions: sessionmaker[Session]) -> list[UUID]:
    with sessions() as session:
        return list(
            session.scalars(
                select(Issue.id)
                .join(Repository)
                .join(IssueFilterResult, IssueFilterResult.issue_id == Issue.id)
                .where(IssueFilterResult.status.in_({"eligible", "warning"}))
                .order_by(Repository.full_name, Issue.number)
            ).all()
        )


def _stage(sessions: sessionmaker[Session], run_id: UUID, stage: str, clock: Clock) -> None:
    with transaction(sessions) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        run.current_stage = stage
        add_run_event(
            session,
            run_id=run_id,
            stage=stage,
            event_type="stage_started",
            level="info",
            message=f"Started {stage}",
            created_at=clock.now(),
        )


def _finish(
    sessions: sessionmaker[Session],
    run_id: UUID,
    status: str,
    summary: dict[str, Any],
    clock: Clock,
) -> None:
    with transaction(sessions) as session:
        run = session.get(PipelineRun, run_id)
        assert run is not None
        finish_pipeline_run(
            session,
            run,
            status=status,
            summary=summary,
            finished_at=clock.now(),
        )


def _repository_failure(
    summary: dict[str, Any], repository: str, stage: str, error: Exception
) -> None:
    summary["repositories_failed"] += 1
    summary["stage_failures"].append(f"{stage}:{repository}:{type(error).__name__}")


def _issue_failure(summary: dict[str, Any], issue_id: UUID, error: Exception) -> None:
    summary["stage_failures"].append(f"analysis:{issue_id}:{type(error).__name__}")


def _check_deadline(clock: Clock, started_at: datetime, seconds: int) -> None:
    if clock.now() - started_at >= timedelta(seconds=seconds):
        raise PipelineDeadlineError(f"pipeline deadline reached after {seconds} seconds")


def _check_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise PipelineCancelledError("pipeline cancellation requested")
