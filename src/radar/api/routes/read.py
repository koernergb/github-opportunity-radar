"""Explicit read projections for dashboard, opportunities, repositories, and runs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.db.models import (
    Issue,
    IssueAnalysis,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueScore,
    PipelineRun,
    PullRequest,
    Repository,
    RepositoryMetricSnapshot,
    RunEvent,
    UserFeedback,
)
from radar.feedback.service import FeedbackValidationError, record_feedback

router = APIRouter(tags=["radar"])


class PageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int
    page_size: int
    total: int


class OpportunitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_id: UUID
    repository: str
    number: int
    title: str
    url: str
    score: float
    confidence: float
    effort_low_hours: float | None
    effort_high_hours: float | None
    fit: float
    merge_estimate: float
    merge_band: str
    merge_is_heuristic: Literal[True] = True
    warnings: list[str]
    missing_evidence: list[str]
    updated_at: datetime
    scored_at: datetime


class OpportunityPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[OpportunitySummary]
    meta: PageMeta


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracked_repositories: int
    ranked_opportunities: int
    low_confidence_opportunities: int
    latest_run_status: str | None
    top_opportunities: list[OpportunitySummary]


class OpportunityDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: OpportunitySummary
    body_text: str | None
    labels: list[str]
    assignees: list[str]
    comments: list[dict[str, Any]]
    linked_pull_requests: list[dict[str, Any]]
    repository_health: dict[str, Any] | None
    analysis: dict[str, Any] | None
    explanation: dict[str, Any]
    feedback: list[dict[str, Any]]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    note: str | None = Field(default=None, max_length=10_000)
    pr_url: str | None = Field(default=None, max_length=2_000)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback_id: UUID
    issue_id: UUID
    status: str
    note: str | None
    pr_url: str | None
    created_at: datetime


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: UUID
    full_name: str
    enabled: bool
    primary_language: str | None
    candidate_count: int
    last_synced_at: datetime
    health: dict[str, Any] | None
    sync_status: Literal["current", "stale"]


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    status: str
    current_stage: str | None
    started_at: datetime
    finished_at: datetime | None
    summary: dict[str, Any]
    event_cursor: datetime | None


class RunEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    stage: str
    event_type: str
    level: str
    message: str
    error_type: str | None
    details: dict[str, Any]
    created_at: datetime


@router.get("/opportunities", response_model=OpportunityPage)
def opportunities(
    services: Services,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    repository: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    query: str | None = None,
    diagnostic: Literal["eligible", "all"] = "eligible",
) -> OpportunityPage:
    with services.sessions() as session:
        rows = session.execute(
            select(IssueScore, Issue, Repository, IssueAnalysis)
            .join(Issue, Issue.id == IssueScore.issue_id)
            .join(Repository, Repository.id == Issue.repository_id)
            .outerjoin(IssueAnalysis, IssueAnalysis.id == IssueScore.analysis_id)
        ).all()
    filtered = []
    for score, issue, repo, analysis in rows:
        if diagnostic == "eligible" and score.explanation.get("ranking_eligible") is not True:
            continue
        if repository is not None and repo.full_name != repository:
            continue
        if min_confidence is not None and score.confidence < min_confidence:
            continue
        if (
            query is not None
            and query.casefold() not in f"{repo.full_name} {issue.title}".casefold()
        ):
            continue
        filtered.append(_opportunity(score, issue, repo, analysis))
    filtered.sort(key=lambda item: (-item.score, -item.confidence, item.repository, item.number))
    start = (page - 1) * page_size
    return OpportunityPage(
        items=filtered[start : start + page_size],
        meta=PageMeta(page=page, page_size=page_size, total=len(filtered)),
    )


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(services: Services) -> DashboardResponse:
    page = opportunities(
        services,
        page=1,
        page_size=5,
        repository=None,
        min_confidence=None,
        query=None,
        diagnostic="eligible",
    )
    with services.sessions() as session:
        repositories = session.scalar(select(func.count()).select_from(Repository)) or 0
        latest_run = session.scalar(select(PipelineRun).order_by(PipelineRun.started_at.desc()))
    return DashboardResponse(
        tracked_repositories=repositories,
        ranked_opportunities=page.meta.total,
        low_confidence_opportunities=sum(
            item.confidence < 0.5
            for item in opportunities(
                services,
                page=1,
                page_size=100,
                repository=None,
                min_confidence=None,
                query=None,
                diagnostic="eligible",
            ).items
        ),
        latest_run_status=latest_run.status if latest_run else None,
        top_opportunities=page.items,
    )


@router.get("/opportunities/{issue_id}", response_model=OpportunityDetail)
def opportunity_detail(issue_id: UUID, services: Services) -> OpportunityDetail:
    with services.sessions() as session:
        issue = session.get(Issue, issue_id)
        if issue is None:
            raise ApiError(404, "opportunity_not_found", "The opportunity does not exist.")
        repo = session.get(Repository, issue.repository_id)
        score = session.scalar(
            select(IssueScore)
            .where(IssueScore.issue_id == issue.id)
            .order_by(IssueScore.scored_at.desc())
        )
        if repo is None or score is None:
            raise ApiError(404, "opportunity_not_scored", "The opportunity has no score.")
        analysis = session.get(IssueAnalysis, score.analysis_id) if score.analysis_id else None
        labels = list(session.scalars(select(IssueLabel).where(IssueLabel.issue_id == issue.id)))
        assignees = list(
            session.scalars(select(IssueAssignee).where(IssueAssignee.issue_id == issue.id))
        )
        comments = list(
            session.scalars(
                select(IssueComment)
                .where(IssueComment.issue_id == issue.id)
                .order_by(IssueComment.github_created_at)
            )
        )
        pull_requests = list(
            session.scalars(select(PullRequest).where(PullRequest.linked_issue_id == issue.id))
        )
        metric = session.scalar(
            select(RepositoryMetricSnapshot)
            .where(RepositoryMetricSnapshot.repository_id == repo.id)
            .order_by(RepositoryMetricSnapshot.calculated_at.desc())
        )
        feedback = list(
            session.scalars(
                select(UserFeedback)
                .where(UserFeedback.issue_id == issue.id)
                .order_by(UserFeedback.created_at)
            )
        )
    return OpportunityDetail(
        summary=_opportunity(score, issue, repo, analysis),
        body_text=issue.body,
        labels=[item.name for item in labels],
        assignees=[item.login for item in assignees],
        comments=[
            {
                "author_login": item.author_login,
                "body_text": item.body,
                "created_at": item.github_created_at.isoformat(),
            }
            for item in comments
        ],
        linked_pull_requests=[
            {"number": item.number, "title": item.title, "url": item.url, "state": item.state}
            for item in pull_requests
        ],
        repository_health=_metric(metric),
        analysis=analysis.analysis_json if analysis else None,
        explanation=score.explanation,
        feedback=[_feedback(item).model_dump(mode="json") for item in feedback],
    )


@router.get("/opportunities/{issue_id}/explanation")
def opportunity_explanation(issue_id: UUID, services: Services) -> dict[str, Any]:
    with services.sessions() as session:
        score = session.scalar(
            select(IssueScore)
            .where(IssueScore.issue_id == issue_id)
            .order_by(IssueScore.scored_at.desc())
        )
    if score is None:
        raise ApiError(404, "opportunity_not_scored", "The opportunity has no score.")
    return {"score_version": score.score_version, "explanation": score.explanation}


@router.post("/opportunities/{issue_id}/feedback", response_model=FeedbackResponse, status_code=201)
def append_feedback(issue_id: UUID, body: FeedbackRequest, services: Services) -> FeedbackResponse:
    try:
        with services.sessions.begin() as session:
            feedback = record_feedback(
                session,
                issue_id=issue_id,
                status=body.status,
                note=body.note,
                pr_url=body.pr_url,
                clock=services.clock,
            )
    except FeedbackValidationError as error:
        raise ApiError(422, "feedback_invalid", "The feedback transition is invalid.") from error
    return _feedback(feedback)


@router.get("/repositories", response_model=list[RepositoryResponse])
def repositories(services: Services) -> list[RepositoryResponse]:
    with services.sessions() as session:
        repos = list(session.scalars(select(Repository).order_by(Repository.full_name)))
        count_rows = session.execute(
            select(Issue.repository_id, func.count(IssueScore.id))
            .join(IssueScore, IssueScore.issue_id == Issue.id)
            .group_by(Issue.repository_id)
        ).all()
        counts: dict[UUID, int] = {repository_id: count for repository_id, count in count_rows}
        metrics = list(
            session.scalars(
                select(RepositoryMetricSnapshot).order_by(
                    RepositoryMetricSnapshot.calculated_at.desc()
                )
            )
        )
    latest_metrics: dict[UUID, RepositoryMetricSnapshot] = {}
    for metric in metrics:
        latest_metrics.setdefault(metric.repository_id, metric)
    now = services.clock.now()
    return [
        RepositoryResponse(
            repository_id=repo.id,
            full_name=repo.full_name,
            enabled=not repo.archived and not repo.disabled,
            primary_language=repo.primary_language,
            candidate_count=counts.get(repo.id, 0),
            last_synced_at=repo.last_synced_at,
            health=_metric(latest_metrics.get(repo.id)),
            sync_status="stale" if (now - repo.last_synced_at).days >= 1 else "current",
        )
        for repo in repos
    ]


@router.get("/repositories/{repository_id}", response_model=RepositoryResponse)
def repository_detail(repository_id: UUID, services: Services) -> RepositoryResponse:
    result = next(
        (item for item in repositories(services) if item.repository_id == repository_id), None
    )
    if result is None:
        raise ApiError(404, "repository_not_found", "The repository does not exist.")
    return result


@router.get("/runs", response_model=list[RunResponse])
def runs(services: Services) -> list[RunResponse]:
    with services.sessions() as session:
        values = list(session.scalars(select(PipelineRun).order_by(PipelineRun.started_at.desc())))
        cursor_rows = session.execute(
            select(RunEvent.pipeline_run_id, func.max(RunEvent.created_at)).group_by(
                RunEvent.pipeline_run_id
            )
        ).all()
        cursors: dict[UUID, datetime] = {
            run_id: cursor for run_id, cursor in cursor_rows if cursor is not None
        }
    return [_run(item, cursors.get(item.id)) for item in values]


@router.get("/runs/{run_id}", response_model=RunResponse)
def run_detail(run_id: UUID, services: Services) -> RunResponse:
    with services.sessions() as session:
        run = session.get(PipelineRun, run_id)
        cursor = session.scalar(
            select(func.max(RunEvent.created_at)).where(RunEvent.pipeline_run_id == run_id)
        )
    if run is None:
        raise ApiError(404, "run_not_found", "The run does not exist.")
    return _run(run, cursor)


@router.get("/runs/{run_id}/events", response_model=list[RunEventResponse])
def run_events(
    run_id: UUID, services: Services, after: datetime | None = None
) -> list[RunEventResponse]:
    statement = select(RunEvent).where(RunEvent.pipeline_run_id == run_id)
    if after is not None:
        statement = statement.where(RunEvent.created_at > after)
    statement = statement.order_by(RunEvent.created_at, RunEvent.id)
    with services.sessions() as session:
        if session.get(PipelineRun, run_id) is None:
            raise ApiError(404, "run_not_found", "The run does not exist.")
        events = list(session.scalars(statement))
    return [
        RunEventResponse(
            event_id=item.id,
            stage=item.stage,
            event_type=item.event_type,
            level=item.level,
            message=item.message,
            error_type=item.error_type,
            details=item.details,
            created_at=item.created_at,
        )
        for item in events
    ]


def _opportunity(
    score: IssueScore, issue: Issue, repo: Repository, analysis: IssueAnalysis | None
) -> OpportunitySummary:
    semantic = analysis.analysis_json if analysis else {}
    return OpportunitySummary(
        issue_id=issue.id,
        repository=repo.full_name,
        number=issue.number,
        title=issue.title,
        url=issue.url,
        score=score.total,
        confidence=score.confidence,
        effort_low_hours=_optional_float(semantic.get("effort_low_hours")),
        effort_high_hours=_optional_float(semantic.get("effort_high_hours")),
        fit=score.fit,
        merge_estimate=score.merge_estimate,
        merge_band=score.merge_band,
        warnings=list(score.explanation.get("filter_evidence", {})),
        missing_evidence=list(score.explanation.get("missing_data", [])),
        updated_at=issue.github_updated_at,
        scored_at=score.scored_at,
    )


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _metric(metric: RepositoryMetricSnapshot | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "metric_version": metric.metric_version,
        "merge_rate": metric.shrunk_merge_rate,
        "sample_size": metric.external_pr_count,
        "confidence": metric.data_confidence,
        "calculated_at": metric.calculated_at.isoformat(),
    }


def _feedback(item: UserFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=item.id,
        issue_id=item.issue_id,
        status=item.status,
        note=item.note,
        pr_url=item.pr_url,
        created_at=item.created_at,
    )


def _run(item: PipelineRun, cursor: datetime | None) -> RunResponse:
    return RunResponse(
        run_id=item.id,
        status=item.status,
        current_stage=item.current_stage,
        started_at=item.started_at,
        finished_at=item.finished_at,
        summary=item.summary,
        event_cursor=cursor,
    )
