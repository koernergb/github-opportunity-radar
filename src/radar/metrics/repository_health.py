"""Versioned deterministic repository contribution-health snapshots."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import (
    PullRequest,
    PullRequestComment,
    PullRequestReview,
    Repository,
    RepositoryDocument,
    RepositoryMetricSnapshot,
)
from radar.db.session import transaction
from radar.ingestion.pull_requests import MAINTAINER_ASSOCIATIONS, is_bot
from radar.metrics.merge_history import median, percentile
from radar.metrics.priors import shrunk_rate
from radar.settings import RadarConfig

METRIC_VERSION = "repository_health_v1"
_MAINTAINER_VALUES = {association.value for association in MAINTAINER_ASSOCIATIONS}
_DOCUMENT_TYPES = {
    "readme",
    "contributing",
    "code_of_conduct",
    "security",
    "pull_request_template",
}


@dataclass(frozen=True)
class RepositoryMetrics:
    external_pr_count: int
    merged_external_count: int
    external_merge_rate: float | None
    shrunk_merge_rate: float
    closed_unmerged_rate: float | None
    median_first_response_hours: float | None
    median_merge_hours: float | None
    p75_merge_hours: float | None
    active_maintainer_count: int
    recent_activity: float | None
    documentation_score: float | None
    data_confidence: float


def calculate_repository_metrics(
    config: RadarConfig,
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    repository_filter: str | None = None,
) -> list[RepositoryMetricSnapshot]:
    """Calculate and persist one deterministic snapshot per selected repository."""
    window_end = clock.now()
    window_start = window_end - timedelta(days=config.github.pr_history_days)
    snapshots: list[RepositoryMetricSnapshot] = []
    with transaction(sessions) as session:
        repositories = session.scalars(select(Repository).order_by(Repository.full_name)).all()
        for repository in repositories:
            if repository_filter is not None and repository.full_name != repository_filter:
                continue
            metrics = _calculate_one(session, repository, window_start, window_end, config)
            snapshot = _upsert_snapshot(
                session,
                repository,
                metrics,
                window_start,
                window_end,
                calculated_at=window_end,
            )
            snapshots.append(snapshot)
    return snapshots


def _calculate_one(
    session: Session,
    repository: Repository,
    window_start: datetime,
    window_end: datetime,
    config: RadarConfig,
) -> RepositoryMetrics:
    pull_requests = session.scalars(
        select(PullRequest).where(
            PullRequest.repository_id == repository.id,
            PullRequest.github_created_at >= window_start,
            PullRequest.github_created_at <= window_end,
        )
    ).all()
    external = [
        pull_request
        for pull_request in pull_requests
        if pull_request.author_association not in _MAINTAINER_VALUES
    ]
    merged = [pull_request for pull_request in external if pull_request.merged]
    closed_unmerged = [
        pull_request
        for pull_request in external
        if pull_request.state == "closed" and not pull_request.merged
    ]
    response_hours = [
        (pull_request.first_maintainer_response_at - pull_request.github_created_at).total_seconds()
        / 3600
        for pull_request in external
        if pull_request.first_maintainer_response_at is not None
        and pull_request.first_maintainer_response_at > pull_request.github_created_at
    ]
    merge_hours = [
        (pull_request.merged_at - pull_request.github_created_at).total_seconds() / 3600
        for pull_request in merged
        if pull_request.merged_at is not None
        and pull_request.merged_at > pull_request.github_created_at
    ]
    sample_size = len(external)
    raw_merge_rate = len(merged) / sample_size if sample_size else None
    raw_closed_rate = len(closed_unmerged) / sample_size if sample_size else None
    maintainers = _active_maintainers(session, [pull_request.id for pull_request in pull_requests])
    document_types = set(
        session.scalars(
            select(RepositoryDocument.document_type).where(
                RepositoryDocument.repository_id == repository.id
            )
        ).all()
    )
    docs_score = len(document_types & _DOCUMENT_TYPES) / len(_DOCUMENT_TYPES)
    recent_activity = min(1.0, len(pull_requests) / 20) if pull_requests else None
    history_confidence = min(1.0, sample_size / 20)
    completeness = (
        sum(
            value is not None
            for value in (raw_merge_rate, median(response_hours), median(merge_hours))
        )
        / 3
    )
    confidence = 0.7 * history_confidence + 0.3 * completeness
    return RepositoryMetrics(
        external_pr_count=sample_size,
        merged_external_count=len(merged),
        external_merge_rate=raw_merge_rate,
        shrunk_merge_rate=shrunk_rate(
            successes=len(merged),
            sample_size=sample_size,
            global_prior=config.scoring.global_merge_prior,
            prior_strength=config.scoring.prior_strength,
        ),
        closed_unmerged_rate=raw_closed_rate,
        median_first_response_hours=median(response_hours),
        median_merge_hours=median(merge_hours),
        p75_merge_hours=percentile(merge_hours, 0.75),
        active_maintainer_count=len(maintainers),
        recent_activity=recent_activity,
        documentation_score=docs_score,
        data_confidence=confidence,
    )


def _active_maintainers(session: Session, pull_request_ids: list[object]) -> set[str]:
    if not pull_request_ids:
        return set()
    review_logins = session.scalars(
        select(PullRequestReview.author_login).where(
            PullRequestReview.pull_request_id.in_(pull_request_ids),
            PullRequestReview.author_association.in_(_MAINTAINER_VALUES),
            PullRequestReview.author_login.is_not(None),
        )
    ).all()
    comment_logins = session.scalars(
        select(PullRequestComment.author_login).where(
            PullRequestComment.pull_request_id.in_(pull_request_ids),
            PullRequestComment.author_association.in_(_MAINTAINER_VALUES),
            PullRequestComment.author_login.is_not(None),
        )
    ).all()
    return {
        login
        for login in [*review_logins, *comment_logins]
        if login is not None and not is_bot(login)
    }


def _upsert_snapshot(
    session: Session,
    repository: Repository,
    metrics: RepositoryMetrics,
    window_start: datetime,
    window_end: datetime,
    *,
    calculated_at: datetime,
) -> RepositoryMetricSnapshot:
    snapshot = session.scalar(
        select(RepositoryMetricSnapshot).where(
            RepositoryMetricSnapshot.repository_id == repository.id,
            RepositoryMetricSnapshot.metric_version == METRIC_VERSION,
            RepositoryMetricSnapshot.window_start == window_start,
            RepositoryMetricSnapshot.window_end == window_end,
        )
    )
    values = asdict(metrics)
    if snapshot is None:
        snapshot = RepositoryMetricSnapshot(
            repository_id=repository.id,
            metric_version=METRIC_VERSION,
            window_start=window_start,
            window_end=window_end,
            metrics_json=values,
            calculated_at=calculated_at,
            **values,
        )
        session.add(snapshot)
        session.flush()
    else:
        for key, value in values.items():
            setattr(snapshot, key, value)
        snapshot.metrics_json = values
        snapshot.calculated_at = calculated_at
    return snapshot
