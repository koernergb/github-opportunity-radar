"""Append-only validated feedback and read-only outcome reporting."""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.clock import Clock
from radar.db.models import Issue, Repository, UserFeedback

FEEDBACK_VERSION: Final = "feedback_v1"
STATUSES: Final = {
    "interested",
    "too_hard",
    "too_vague",
    "low_value",
    "bad_repository_fit",
    "already_claimed",
    "not_enough_time",
    "investigating",
    "commented",
    "implementation_started",
    "pr_opened",
    "merged",
    "closed_unmerged",
    "abandoned",
    "rejected",
}
_PROGRESS = {
    "interested": 1,
    "investigating": 2,
    "commented": 3,
    "implementation_started": 4,
    "pr_opened": 5,
    "merged": 6,
    "closed_unmerged": 6,
    "abandoned": 6,
}
_PREFERENCE = {
    "too_hard",
    "too_vague",
    "low_value",
    "bad_repository_fit",
    "already_claimed",
    "not_enough_time",
    "rejected",
}
_TERMINAL = {"merged", "closed_unmerged", "abandoned"}
_PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*)/?$"
)
_ISSUE_REFERENCE_RE = re.compile(
    r"^(?P<repository>[A-Za-z0-9-]+/[A-Za-z0-9_.-]+)#(?P<number>[1-9][0-9]*)$"
)


class FeedbackValidationError(ValueError):
    """Feedback status, transition, reference, or PR URL is invalid."""


@dataclass(frozen=True)
class OutcomeReport:
    issue_count: int
    latest_status_counts: dict[str, int]
    progressed_count: int
    pr_opened_count: int
    merged_count: int
    merge_rate_after_pr: float | None


def record_feedback(
    session: Session,
    *,
    issue_id: UUID,
    status: str,
    clock: Clock,
    note: str | None = None,
    pr_url: str | None = None,
) -> UserFeedback:
    """Append one validated user claim without mutating observed GitHub entities."""
    if status not in STATUSES:
        raise FeedbackValidationError(f"unknown feedback status: {status}")
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise FeedbackValidationError(f"issue not found: {issue_id}")
    previous = latest_feedback(session, issue_id)
    _validate_transition(previous.status if previous else None, status)
    normalized_url = _validate_pr_url(pr_url)
    if status in {"pr_opened", "merged", "closed_unmerged"} and normalized_url is None:
        raise FeedbackValidationError(f"{status} requires --pr-url")
    feedback = UserFeedback(
        issue_id=issue_id,
        status=status,
        note=note.strip() if note and note.strip() else None,
        pr_url=normalized_url,
        created_at=clock.now(),
    )
    session.add(feedback)
    session.flush()
    return feedback


def latest_feedback(session: Session, issue_id: UUID) -> UserFeedback | None:
    """Return the latest appended state with UUID as a deterministic tie break."""
    return session.scalar(
        select(UserFeedback)
        .where(UserFeedback.issue_id == issue_id)
        .order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())
    )


def resolve_issue_reference(session: Session, reference: str) -> Issue:
    """Resolve the CLI owner/repository#number form without network access."""
    match = _ISSUE_REFERENCE_RE.fullmatch(reference)
    if match is None:
        raise FeedbackValidationError("issue must use owner/repository#number")
    issue = session.scalar(
        select(Issue)
        .join(Repository)
        .where(
            Repository.full_name == match.group("repository"),
            Issue.number == int(match.group("number")),
        )
    )
    if issue is None:
        raise FeedbackValidationError(f"issue not found: {reference}")
    return issue


def build_outcome_report(session: Session) -> OutcomeReport:
    """Aggregate latest user-reported states without claiming GitHub truth."""
    feedback = session.scalars(
        select(UserFeedback).order_by(
            UserFeedback.issue_id, UserFeedback.created_at.desc(), UserFeedback.id.desc()
        )
    ).all()
    latest: dict[UUID, UserFeedback] = {}
    ever: dict[UUID, set[str]] = {}
    for item in feedback:
        latest.setdefault(item.issue_id, item)
        ever.setdefault(item.issue_id, set()).add(item.status)
    counts = Counter(item.status for item in latest.values())
    progressed = sum(
        bool(statuses & {"investigating", "commented", "implementation_started"})
        for statuses in ever.values()
    )
    opened = sum(
        "pr_opened" in statuses or bool(statuses & {"merged", "closed_unmerged"})
        for statuses in ever.values()
    )
    merged = sum("merged" in statuses for statuses in ever.values())
    return OutcomeReport(
        issue_count=len(latest),
        latest_status_counts=dict(sorted(counts.items())),
        progressed_count=progressed,
        pr_opened_count=opened,
        merged_count=merged,
        merge_rate_after_pr=merged / opened if opened else None,
    )


def _validate_transition(previous: str | None, current: str) -> None:
    if previous is None:
        return
    if previous in _TERMINAL:
        raise FeedbackValidationError(f"cannot transition from terminal status {previous}")
    if current == previous:
        raise FeedbackValidationError(f"status is already {current}")
    if previous in _PREFERENCE or current in _PREFERENCE:
        return
    if _PROGRESS[current] < _PROGRESS[previous]:
        raise FeedbackValidationError(f"cannot move backward from {previous} to {current}")


def _validate_pr_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if _PR_URL_RE.fullmatch(normalized) is None:
        raise FeedbackValidationError("PR URL must be https://github.com/owner/repo/pull/NUMBER")
    return normalized.removesuffix("/")
