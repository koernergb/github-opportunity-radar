"""Composable deterministic exclusion and warning rules."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from radar.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLink,
    Repository,
    RepositoryMetricSnapshot,
    UserFeedback,
)
from radar.filtering.claims import detect_soft_claim
from radar.settings import RepositorySettings


class RuleAction(StrEnum):
    EXCLUDE = "exclude"
    WARN = "warn"


@dataclass(frozen=True)
class RuleResult:
    action: RuleAction
    code: str
    message: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class RuleContext:
    issue: Issue
    repository: Repository
    configured: RepositorySettings
    labels: set[str]
    assignees: list[IssueAssignee]
    comments: list[IssueComment]
    links: list[IssueLink]
    metric: RepositoryMetricSnapshot | None
    feedback: UserFeedback | None
    now: datetime


def evaluate_rules(context: RuleContext) -> list[RuleResult]:
    """Evaluate every v1 deterministic rule without short-circuiting evidence."""
    results: list[RuleResult] = []
    _exclude(results, context.issue.state != "open", "closed", "Issue is not open")
    _exclude(results, context.issue.is_pull_request, "pull_request", "Item is a pull request")
    _exclude(
        results,
        context.repository.archived or context.repository.disabled,
        "repository_inactive",
        "Repository is archived or disabled",
    )
    excluded_labels = {label.casefold() for label in context.configured.exclude_labels}
    _exclude(
        results,
        bool(context.labels & excluded_labels),
        "excluded_label",
        "Issue has a configured excluded label",
        {"labels": sorted(context.labels & excluded_labels)},
    )
    terminal_labels = {"duplicate", "invalid", "wontfix"}
    _exclude(
        results,
        bool(context.labels & terminal_labels),
        "terminal_label",
        "Issue is marked duplicate, invalid, or wontfix",
    )
    credible_active = [
        link
        for link in context.links
        if link.target_type == "pull_request"
        and link.state == "open"
        and link.merged is False
        and link.evidence_strength >= 0.8
    ]
    _exclude(
        results,
        bool(credible_active),
        "active_linked_pr",
        "A credibly linked pull request is active",
        {"links": [link.url for link in credible_active]},
    )
    _exclude(
        results,
        context.configured.exclude_assigned_to_others and bool(context.assignees),
        "assigned",
        "Issue is assigned to another person",
        {"assignees": [assignee.login for assignee in context.assignees]},
    )
    age = context.now - context.issue.github_created_at
    _exclude(
        results,
        age < timedelta(minutes=context.configured.min_issue_age_minutes),
        "too_new",
        "Issue is newer than the configured minimum age",
    )
    old_cutoff = context.now - timedelta(days=context.configured.max_issue_age_days)
    _exclude(
        results,
        context.issue.github_created_at < old_cutoff
        and context.issue.github_updated_at < old_cutoff,
        "too_old",
        "Issue is old without qualifying renewed activity",
    )
    _exclude(
        results,
        context.feedback is not None
        and context.feedback.status in {"rejected", "bad_repository_fit"},
        "feedback_rejected",
        "Latest user feedback permanently rejects this issue",
    )

    claim = detect_soft_claim(context.comments, now=context.now)
    _warn(
        results,
        claim.claimed,
        "soft_claim",
        "A recent comment may claim this issue",
        {"confidence": claim.confidence, "author": claim.author, "comment_id": claim.comment_id},
    )
    text = f"{context.issue.title}\n{context.issue.body or ''}".casefold()
    _warn(
        results,
        bool(re.search(r"\b(?:rfc|needs design|design decision|proposal)\b", text))
        or bool(context.labels & {"needs-design", "rfc"}),
        "needs_design",
        "Issue may require design or RFC work",
    )
    _warn(
        results,
        "stale" in context.labels,
        "stale",
        "Issue is marked stale",
    )
    _warn(
        results,
        len((context.issue.body or "").strip()) < 40,
        "weak_body",
        "Issue body is missing or weak",
    )
    maintainer_associations = {"OWNER", "MEMBER", "COLLABORATOR"}
    _warn(
        results,
        not any(
            comment.author_association in maintainer_associations for comment in context.comments
        ),
        "no_maintainer_response",
        "No credible maintainer response is observed",
    )
    _warn(
        results,
        bool(re.search(r"\b(?:cuda|gpu|apple silicon|m[1-9]|tpu|special hardware)\b", text)),
        "special_hardware",
        "Issue may require special hardware",
    )
    _warn(
        results,
        bool(re.search(r"\b(?:refactor all|entire|across the project|large[- ]scale)\b", text)),
        "broad_scope",
        "Issue appears broad in scope",
    )
    _warn(
        results,
        bool(re.search(r"\b(?:public api|breaking change|backward compatibility)\b", text)),
        "public_api_change",
        "Issue may change a public API",
    )
    _warn(
        results,
        context.metric is None or context.metric.external_pr_count < 5,
        "low_history_sample",
        "Repository contribution history has a small sample",
    )
    contention_pattern = r"(?i)\b(?:disagree|strongly oppose|not acceptable|controversial)\b"
    contentious = sum(bool(re.search(contention_pattern, c.body)) for c in context.comments)
    _warn(
        results,
        contentious >= 2,
        "contentious",
        "Comments show potentially contentious discussion",
    )
    _warn(
        results,
        any(
            link.target_type == "pull_request" and link.state == "closed" and link.merged is False
            for link in context.links
        ),
        "previous_closed_unmerged_pr",
        "A previous linked pull request closed without merge",
    )
    _warn(
        results,
        context.repository.primary_language is None,
        "unknown_language",
        "Repository implementation language is unknown",
    )
    return results


def _exclude(
    results: list[RuleResult],
    condition: bool,
    code: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    if condition:
        results.append(RuleResult(RuleAction.EXCLUDE, code, message, evidence or {}))


def _warn(
    results: list[RuleResult],
    condition: bool,
    code: str,
    message: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    if condition:
        results.append(RuleResult(RuleAction.WARN, code, message, evidence or {}))
