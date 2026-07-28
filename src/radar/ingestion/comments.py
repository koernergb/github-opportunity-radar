"""Issue comment upserts and weak GitHub URL extraction."""

import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from radar.db.models import IssueComment, IssueLink
from radar.domain.schemas import IssueCommentDTO, parse_github_url

_GITHUB_URL_RE = re.compile(
    r"https://(?:www\.)?github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/[1-9][0-9]*"
)


def upsert_comment(
    session: Session,
    issue_id: UUID,
    observation: IssueCommentDTO,
) -> tuple[bool, bool]:
    """Insert or update a comment by immutable GitHub ID."""
    comment = session.scalar(
        select(IssueComment).where(IssueComment.github_id == observation.github_id)
    )
    values = {
        "node_id": observation.node_id,
        "body": observation.body,
        "author_login": observation.author.login if observation.author else None,
        "author_association": (
            observation.author_association.value if observation.author_association else None
        ),
        "github_created_at": observation.created_at,
        "github_updated_at": observation.updated_at,
        "raw_json": observation.raw_payload,
    }
    if comment is None:
        session.add(
            IssueComment(
                issue_id=issue_id,
                github_id=observation.github_id,
                **values,
            )
        )
        return True, False
    changed = any(getattr(comment, key) != value for key, value in values.items())
    for key, value in values.items():
        setattr(comment, key, value)
    return False, changed


def replace_weak_url_links(
    session: Session,
    issue_id: UUID,
    *,
    source_texts: list[str],
    observed_at: datetime,
) -> None:
    """Replace weak URL evidence extracted from bounded issue/comment text."""
    session.execute(
        delete(IssueLink).where(
            IssueLink.source_issue_id == issue_id,
            IssueLink.evidence_strength == 0.25,
        )
    )

    seen: set[tuple[str, int, str]] = set()
    for text in source_texts:
        for url in _GITHUB_URL_RE.findall(text):
            reference = parse_github_url(url)
            key = (reference.repository, reference.number, reference.kind.value)
            if key in seen:
                continue
            seen.add(key)
            session.add(
                IssueLink(
                    source_issue_id=issue_id,
                    target_repository=reference.repository,
                    target_number=reference.number,
                    target_type=reference.kind.value,
                    relation_type="weak_url_reference",
                    state=None,
                    merged=None,
                    url=url,
                    evidence_strength=0.25,
                    observed_at=observed_at,
                )
            )
