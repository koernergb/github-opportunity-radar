"""Conservative soft-claim detection over untrusted comment text."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from radar.db.models import IssueComment

_CLAIM_RE = re.compile(
    r"(?i)\b(?:i(?:'ll| will| can|'m going to|'m) (?:work(?:ing)? on|take)"
    r"|assign (?:this|it) to me|opened? a pr|i have a pr)\b"
)
_WITHDRAW_RE = re.compile(
    r"(?i)\b(?:no longer working|can't work|cannot work|giving up|unassign me|available again)\b"
)


@dataclass(frozen=True)
class ClaimEvidence:
    claimed: bool
    confidence: float
    comment_id: str | None
    author: str | None
    observed_at: datetime | None


def detect_soft_claim(
    comments: list[IssueComment],
    *,
    now: datetime,
    max_age_days: int = 30,
) -> ClaimEvidence:
    """Detect recent unwithdrawn claims, ignoring quoted material."""
    cutoff = now - timedelta(days=max_age_days)
    active_by_author: dict[str, IssueComment] = {}
    for comment in sorted(comments, key=lambda item: item.github_created_at):
        if comment.github_created_at < cutoff or comment.author_login is None:
            continue
        text = _unquoted_text(comment.body)
        if _WITHDRAW_RE.search(text):
            active_by_author.pop(comment.author_login, None)
        elif _CLAIM_RE.search(text):
            active_by_author[comment.author_login] = comment
    if not active_by_author:
        return ClaimEvidence(False, 0.0, None, None, None)
    latest = max(active_by_author.values(), key=lambda item: item.github_created_at)
    age = now - latest.github_created_at
    confidence = 0.8 if age <= timedelta(days=14) else 0.5
    return ClaimEvidence(
        True,
        confidence,
        str(latest.github_id),
        latest.author_login,
        latest.github_created_at,
    )


def _unquoted_text(value: str) -> str:
    lines = []
    in_fence = False
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and not stripped.startswith(">"):
            lines.append(line)
    return "\n".join(lines)
