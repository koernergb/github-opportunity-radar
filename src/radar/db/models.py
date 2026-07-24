"""SQLAlchemy models separating upstream observations from derived artifacts."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

JsonObject = dict[str, Any]


class UTCDateTime(TypeDecorator[datetime]):
    """Portable timestamp type that rejects naive values and returns UTC."""

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetimes cannot be persisted; use timezone-aware UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Declarative base for all persisted models."""


class UUIDPrimaryKey:
    """UUID primary-key mixin."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Repository(UUIDPrimaryKey, Base):
    __tablename__ = "repositories"

    github_id: Mapped[int] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True)
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(511), unique=True)
    url: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255))
    primary_language: Mapped[str | None] = mapped_column(String(255))
    stars: Mapped[int] = mapped_column(default=0)
    forks: Mapped[int] = mapped_column(default=0)
    archived: Mapped[bool] = mapped_column(default=False)
    disabled: Mapped[bool] = mapped_column(default=False)
    is_fork: Mapped[bool] = mapped_column(default=False)
    pushed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    github_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_synced_at: Mapped[datetime] = mapped_column(UTCDateTime())
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class RepositoryConfig(UUIDPrimaryKey, Base):
    __tablename__ = "repository_configs"

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), unique=True
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    include_labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclude_labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_issue_age_minutes: Mapped[int] = mapped_column(default=30)
    max_issue_age_days: Mapped[int] = mapped_column(default=730)
    max_estimated_hours: Mapped[float | None]
    pr_history_limit: Mapped[int] = mapped_column(default=300)
    pr_history_days: Mapped[int] = mapped_column(default=365)
    custom_weights: Mapped[JsonObject] = mapped_column(JSON, default=dict)


class RepositoryDocument(UUIDPrimaryKey, Base):
    __tablename__ = "repository_documents"
    __table_args__ = (UniqueConstraint("repository_id", "document_type", "path", "sha"),)

    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    document_type: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    sha: Mapped[str] = mapped_column(String(64))
    decoded_text: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Issue(UUIDPrimaryKey, Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repository_id", "number"),
        Index("ix_issues_repo_state_updated", "repository_id", "state", "github_updated_at"),
    )

    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    github_id: Mapped[int] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32))
    state_reason: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(String(255))
    author_association: Mapped[str | None] = mapped_column(String(32))
    locked: Mapped[bool] = mapped_column(default=False)
    comment_count: Mapped[int] = mapped_column(default=0)
    github_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    inaccessible_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_pull_request: Mapped[bool] = mapped_column(default=False)
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class IssueLabel(UUIDPrimaryKey, Base):
    __tablename__ = "issue_labels"
    __table_args__ = (UniqueConstraint("issue_id", "name"),)

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    color: Mapped[str | None] = mapped_column(String(16))
    description: Mapped[str | None] = mapped_column(Text)


class IssueAssignee(UUIDPrimaryKey, Base):
    __tablename__ = "issue_assignees"
    __table_args__ = (UniqueConstraint("issue_id", "login"),)

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    login: Mapped[str] = mapped_column(String(255))


class IssueComment(UUIDPrimaryKey, Base):
    __tablename__ = "issue_comments"
    __table_args__ = (
        UniqueConstraint("issue_id", "github_id"),
        Index("ix_comments_issue_created", "issue_id", "github_created_at"),
    )

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    github_id: Mapped[int] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True)
    body: Mapped[str] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(String(255))
    author_association: Mapped[str | None] = mapped_column(String(32))
    github_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class IssueLink(UUIDPrimaryKey, Base):
    __tablename__ = "issue_links"
    __table_args__ = (
        UniqueConstraint(
            "source_issue_id",
            "target_repository",
            "target_number",
            "relation_type",
            "url",
        ),
    )

    source_issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    target_repository: Mapped[str] = mapped_column(String(511))
    target_number: Mapped[int]
    target_type: Mapped[str] = mapped_column(String(32))
    relation_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(32))
    merged: Mapped[bool | None]
    url: Mapped[str] = mapped_column(Text)
    evidence_strength: Mapped[float]
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PullRequest(UUIDPrimaryKey, Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repository_id", "number"),
        Index("ix_prs_repo_created", "repository_id", "github_created_at"),
        Index("ix_prs_repo_merged_association", "repository_id", "merged", "author_association"),
    )

    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    linked_issue_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL")
    )
    github_id: Mapped[int] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True)
    number: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(String(255))
    author_association: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    draft: Mapped[bool] = mapped_column(default=False)
    merged: Mapped[bool] = mapped_column(default=False)
    github_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    merged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    additions: Mapped[int | None]
    deletions: Mapped[int | None]
    changed_files: Mapped[int | None]
    commit_count: Mapped[int | None]
    comment_count: Mapped[int | None]
    review_comment_count: Mapped[int | None]
    first_maintainer_response_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    first_maintainer_review_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class PullRequestReview(UUIDPrimaryKey, Base):
    __tablename__ = "pull_request_reviews"
    __table_args__ = (UniqueConstraint("pull_request_id", "github_id"),)

    pull_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE")
    )
    github_id: Mapped[int] = mapped_column(unique=True)
    node_id: Mapped[str] = mapped_column(String(255), unique=True)
    author_login: Mapped[str | None] = mapped_column(String(255))
    author_association: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    body: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class PullRequestComment(UUIDPrimaryKey, Base):
    __tablename__ = "pull_request_comments"
    __table_args__ = (UniqueConstraint("pull_request_id", "github_id"),)

    pull_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE")
    )
    github_id: Mapped[int] = mapped_column(unique=True)
    author_login: Mapped[str | None] = mapped_column(String(255))
    author_association: Mapped[str | None] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    comment_type: Mapped[str] = mapped_column(String(32))
    github_created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    github_updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    raw_json: Mapped[JsonObject] = mapped_column(JSON)


class SyncCursor(UUIDPrimaryKey, Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (UniqueConstraint("scope_type", "scope_key"),)

    scope_type: Mapped[str] = mapped_column(String(64))
    scope_key: Mapped[str] = mapped_column(String(511))
    time_cursor: Mapped[datetime | None] = mapped_column(UTCDateTime())
    token_cursor: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cursor_metadata: Mapped[JsonObject] = mapped_column("metadata", JSON, default=dict)


class EtagCache(UUIDPrimaryKey, Base):
    __tablename__ = "etag_cache"

    request_key: Mapped[str] = mapped_column(Text, unique=True)
    etag: Mapped[str] = mapped_column(Text)
    last_checked_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PipelineRun(UUIDPrimaryKey, Base):
    __tablename__ = "pipeline_runs"

    status: Mapped[str] = mapped_column(String(32))
    current_stage: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    summary: Mapped[JsonObject] = mapped_column(JSON, default=dict)


class RunEvent(UUIDPrimaryKey, Base):
    __tablename__ = "run_events"

    pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[JsonObject] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class RepositoryMetricSnapshot(UUIDPrimaryKey, Base):
    __tablename__ = "repository_metric_snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "metric_version", "window_start", "window_end"),
    )

    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    metric_version: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    external_pr_count: Mapped[int]
    merged_external_count: Mapped[int]
    external_merge_rate: Mapped[float | None]
    shrunk_merge_rate: Mapped[float]
    closed_unmerged_rate: Mapped[float | None]
    median_first_response_hours: Mapped[float | None]
    median_merge_hours: Mapped[float | None]
    p75_merge_hours: Mapped[float | None]
    active_maintainer_count: Mapped[int]
    recent_activity: Mapped[float | None]
    documentation_score: Mapped[float | None]
    data_confidence: Mapped[float]
    metrics_json: Mapped[JsonObject] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class IssueFilterResult(UUIDPrimaryKey, Base):
    __tablename__ = "issue_filter_results"
    __table_args__ = (
        UniqueConstraint("issue_id", "filter_version"),
        Index("ix_filters_status_evaluated", "status", "evaluated_at"),
    )

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    filter_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[JsonObject] = mapped_column(JSON, default=dict)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class IssueAnalysis(UUIDPrimaryKey, Base):
    __tablename__ = "issue_analyses"
    __table_args__ = (
        UniqueConstraint(
            "issue_id",
            "content_hash",
            "schema_version",
            "prompt_version",
            "provider",
            "model_version",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1"),
    )

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    content_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    analysis_json: Mapped[JsonObject] = mapped_column(JSON)
    raw_response: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float]
    usage_json: Mapped[JsonObject] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float | None]
    analyzed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class IssueScore(UUIDPrimaryKey, Base):
    __tablename__ = "issue_scores"
    __table_args__ = (
        UniqueConstraint("issue_id", "score_version", "profile_hash"),
        Index("ix_scores_total_scored", "total", "scored_at"),
        CheckConstraint("total >= 0 AND total <= 100"),
    )

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    metric_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("repository_metric_snapshots.id", ondelete="SET NULL")
    )
    analysis_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("issue_analyses.id", ondelete="SET NULL")
    )
    score_version: Mapped[str] = mapped_column(String(64))
    profile_hash: Mapped[str] = mapped_column(String(64))
    total: Mapped[float]
    raw_value: Mapped[float]
    merge_estimate: Mapped[float]
    merge_band: Mapped[str] = mapped_column(String(32))
    effort_midpoint: Mapped[float]
    payoff: Mapped[float]
    fit: Mapped[float]
    risk: Mapped[float]
    confidence: Mapped[float]
    feature_values: Mapped[JsonObject] = mapped_column(JSON)
    explanation: Mapped[JsonObject] = mapped_column(JSON)
    scored_at: Mapped[datetime] = mapped_column(UTCDateTime())


class UserFeedback(UUIDPrimaryKey, Base):
    __tablename__ = "user_feedback"
    __table_args__ = (Index("ix_feedback_issue_created", "issue_id", "created_at"),)

    issue_id: Mapped[UUID] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    pr_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
