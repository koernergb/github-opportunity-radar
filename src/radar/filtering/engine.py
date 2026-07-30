"""Persisted deterministic filter evaluation."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueFilterResult,
    IssueLabel,
    IssueLink,
    Repository,
    RepositoryMetricSnapshot,
    UserFeedback,
)
from radar.db.session import transaction
from radar.filtering.rules import RuleAction, RuleContext, RuleResult, evaluate_rules
from radar.settings import RadarConfig, RepositorySettings

FILTER_VERSION = "deterministic_filters_v1"


def filter_issues(
    config: RadarConfig,
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    repository_filter: str | None = None,
) -> dict[str, int]:
    """Evaluate and upsert exactly one current result per issue/version."""
    counts = {"eligible": 0, "warning": 0, "excluded": 0}
    configured_by_name = {item.full_name: item for item in config.repositories}
    with transaction(sessions) as session:
        issues = session.scalars(
            select(Issue).join(Repository).order_by(Repository.full_name, Issue.number)
        ).all()
        for issue in issues:
            repository = session.get(Repository, issue.repository_id)
            assert repository is not None
            if repository_filter is not None and repository.full_name != repository_filter:
                continue
            configured = configured_by_name.get(repository.full_name)
            if configured is None:
                continue
            context = _context(session, issue, repository, configured, clock.now())
            rules = evaluate_rules(context)
            status = (
                "excluded"
                if any(rule.action is RuleAction.EXCLUDE for rule in rules)
                else "warning"
                if rules
                else "eligible"
            )
            counts[status] += 1
            _upsert_result(session, issue, status, rules, clock.now())
    return counts


def _context(
    session: Session,
    issue: Issue,
    repository: Repository,
    configured: RepositorySettings,
    now: datetime,
) -> RuleContext:
    labels = {
        label.casefold()
        for label in session.scalars(
            select(IssueLabel.name).where(IssueLabel.issue_id == issue.id)
        ).all()
    }
    assignees = session.scalars(
        select(IssueAssignee).where(IssueAssignee.issue_id == issue.id)
    ).all()
    comments = session.scalars(
        select(IssueComment)
        .where(IssueComment.issue_id == issue.id)
        .order_by(IssueComment.github_created_at)
    ).all()
    links = session.scalars(select(IssueLink).where(IssueLink.source_issue_id == issue.id)).all()
    metric = session.scalar(
        select(RepositoryMetricSnapshot)
        .where(RepositoryMetricSnapshot.repository_id == repository.id)
        .order_by(RepositoryMetricSnapshot.calculated_at.desc())
    )
    feedback = session.scalar(
        select(UserFeedback)
        .where(UserFeedback.issue_id == issue.id)
        .order_by(UserFeedback.created_at.desc())
    )
    return RuleContext(
        issue=issue,
        repository=repository,
        configured=configured,
        labels=labels,
        assignees=list(assignees),
        comments=list(comments),
        links=list(links),
        metric=metric,
        feedback=feedback,
        now=now,
    )


def _upsert_result(
    session: Session,
    issue: Issue,
    status: str,
    rules: list[RuleResult],
    evaluated_at: datetime,
) -> None:
    result = session.scalar(
        select(IssueFilterResult).where(
            IssueFilterResult.issue_id == issue.id,
            IssueFilterResult.filter_version == FILTER_VERSION,
        )
    )
    reason_codes = [rule.code for rule in rules]
    evidence = {
        "rules": [
            {
                "action": rule.action.value,
                "code": rule.code,
                "message": rule.message,
                "evidence": rule.evidence,
            }
            for rule in rules
        ]
    }
    if result is None:
        session.add(
            IssueFilterResult(
                issue_id=issue.id,
                filter_version=FILTER_VERSION,
                status=status,
                reason_codes=reason_codes,
                evidence=evidence,
                evaluated_at=evaluated_at,
            )
        )
    else:
        result.status = status
        result.reason_codes = reason_codes
        result.evidence = evidence
        result.evaluated_at = evaluated_at
