"""Bounded pull-request history, maintainer evidence, and issue links."""

import re
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import (
    Issue,
    IssueLink,
    PullRequest,
    PullRequestComment,
    PullRequestReview,
    Repository,
)
from radar.db.session import transaction
from radar.domain.enums import AuthorAssociation
from radar.domain.schemas import PullRequestCommentDTO, PullRequestDTO, ReviewDTO
from radar.settings import RadarConfig

MAINTAINER_ASSOCIATIONS = {
    AuthorAssociation.OWNER,
    AuthorAssociation.MEMBER,
    AuthorAssociation.COLLABORATOR,
}
_BOT_RE = re.compile(r"(?:\[bot\]$|^dependabot$|^github-actions$)", re.IGNORECASE)
_CLOSING_RE = re.compile(
    r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+"
    r"(?:(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+))?#(?P<number>[1-9][0-9]*)"
)
_PLAIN_RE = re.compile(r"(?<![A-Za-z0-9_/])#(?P<number>[1-9][0-9]*)")


class PullRequestGateway(Protocol):
    async def list_pull_requests(
        self,
        full_name: str,
        *,
        state: str,
        max_items: int,
    ) -> AsyncIterator[PullRequestDTO]: ...

    async def get_pull_request(self, full_name: str, number: int) -> PullRequestDTO: ...

    async def list_pull_request_reviews(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[ReviewDTO]: ...

    async def list_pull_request_comments(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[PullRequestCommentDTO]: ...


@dataclass
class PullRequestSyncSummary:
    pull_requests_created: int = 0
    pull_requests_updated: int = 0
    pull_requests_unchanged: int = 0
    reviews_stored: int = 0
    comments_stored: int = 0
    issue_links_stored: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


async def sync_pull_request_history(
    config: RadarConfig,
    gateway: PullRequestGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    repository_filter: str | None = None,
) -> PullRequestSyncSummary:
    """Synchronize bounded hydrated PR history for configured repositories."""
    summary = PullRequestSyncSummary()
    cutoff = clock.now() - timedelta(days=config.github.pr_history_days)
    for configured in config.repositories:
        if not configured.enabled or (
            repository_filter is not None and configured.full_name != repository_filter
        ):
            continue
        with transaction(sessions) as session:
            repository = session.scalar(
                select(Repository).where(Repository.full_name == configured.full_name)
            )
            if repository is None:
                continue
            repository_id = repository.id
        iterator = await gateway.list_pull_requests(
            configured.full_name,
            state="all",
            max_items=config.github.pr_history_limit,
        )
        async for partial in iterator:
            if partial.created_at < cutoff:
                break
            hydrated = await gateway.get_pull_request(configured.full_name, partial.number)
            await _store_pull_request(
                config,
                gateway,
                sessions,
                clock,
                configured.full_name,
                repository_id,
                hydrated,
                summary,
            )
    return summary


async def _store_pull_request(
    config: RadarConfig,
    gateway: PullRequestGateway,
    sessions: sessionmaker[Session],
    clock: Clock,
    full_name: str,
    repository_id: UUID,
    observation: PullRequestDTO,
    summary: PullRequestSyncSummary,
) -> None:
    with transaction(sessions) as session:
        pull_request, created, changed = _upsert_pull_request(session, repository_id, observation)
        pull_request_id = pull_request.id
    summary.pull_requests_created += int(created)
    summary.pull_requests_updated += int(changed and not created)
    summary.pull_requests_unchanged += int(not changed)

    reviews = [
        item
        async for item in await gateway.list_pull_request_reviews(
            full_name,
            observation.number,
            max_pages=config.github.comment_max_pages,
        )
    ]
    comments = [
        item
        async for item in await gateway.list_pull_request_comments(
            full_name,
            observation.number,
            max_pages=config.github.comment_max_pages,
        )
    ]
    with transaction(sessions) as session:
        summary.reviews_stored += _replace_reviews(session, pull_request_id, reviews)
        summary.comments_stored += _replace_comments(session, pull_request_id, comments)
        stored_pull_request = session.get(PullRequest, pull_request_id)
        assert stored_pull_request is not None
        response, review = first_maintainer_response(
            observation.created_at,
            reviews,
            comments,
        )
        stored_pull_request.first_maintainer_response_at = response
        stored_pull_request.first_maintainer_review_at = review
        summary.issue_links_stored += _replace_issue_links(
            session,
            repository_id,
            full_name,
            observation,
            observed_at=clock.now(),
        )


def is_credible_maintainer(
    association: AuthorAssociation | None,
    login: str | None,
) -> bool:
    """Require credible association evidence and reject common bot identities."""
    return (
        association in MAINTAINER_ASSOCIATIONS
        and login is not None
        and _BOT_RE.search(login) is None
    )


def is_external_contributor(association: AuthorAssociation | None) -> bool:
    """Classify CONTRIBUTOR and unknown associations as external by default."""
    return association not in MAINTAINER_ASSOCIATIONS


def first_maintainer_response(
    created_at: datetime,
    reviews: list[ReviewDTO],
    comments: list[PullRequestCommentDTO],
) -> tuple[datetime | None, datetime | None]:
    """Return earliest credible post-creation response and formal review."""
    review_times = [
        review.submitted_at
        for review in reviews
        if review.submitted_at is not None
        and review.submitted_at > created_at
        and is_credible_maintainer(
            review.author_association,
            review.author.login if review.author else None,
        )
    ]
    comment_times = [
        comment.created_at
        for comment in comments
        if comment.created_at > created_at
        and is_credible_maintainer(
            comment.author_association,
            comment.author.login if comment.author else None,
        )
    ]
    first_review = min(review_times, default=None)
    first_response = min([*review_times, *comment_times], default=None)
    return first_response, first_review


def _upsert_pull_request(
    session: Session,
    repository_id: UUID,
    observation: PullRequestDTO,
) -> tuple[PullRequest, bool, bool]:
    pull_request = session.scalar(
        select(PullRequest).where(PullRequest.github_id == observation.github_id)
    )
    values = {
        "repository_id": repository_id,
        "node_id": observation.node_id,
        "number": observation.number,
        "title": observation.title,
        "body": observation.body,
        "url": observation.url,
        "author_login": observation.author.login if observation.author else None,
        "author_association": (
            observation.author_association.value if observation.author_association else None
        ),
        "state": observation.state.value,
        "draft": observation.draft,
        "merged": observation.merged,
        "github_created_at": observation.created_at,
        "github_updated_at": observation.updated_at,
        "github_closed_at": observation.closed_at,
        "merged_at": observation.merged_at,
        "additions": observation.additions,
        "deletions": observation.deletions,
        "changed_files": observation.changed_files,
        "commit_count": observation.commit_count,
        "comment_count": observation.comment_count,
        "review_comment_count": observation.review_comment_count,
        "raw_json": observation.raw_payload,
    }
    created = pull_request is None
    if pull_request is None:
        pull_request = PullRequest(
            github_id=observation.github_id,
            linked_issue_id=None,
            first_maintainer_response_at=None,
            first_maintainer_review_at=None,
            **values,
        )
        session.add(pull_request)
        session.flush()
        return pull_request, True, True
    changed = any(getattr(pull_request, key) != value for key, value in values.items())
    for key, value in values.items():
        setattr(pull_request, key, value)
    return pull_request, created, changed


def _replace_reviews(session: Session, pull_request_id: UUID, reviews: list[ReviewDTO]) -> int:
    session.execute(
        delete(PullRequestReview).where(PullRequestReview.pull_request_id == pull_request_id)
    )
    for review in reviews:
        session.add(
            PullRequestReview(
                pull_request_id=pull_request_id,
                github_id=review.github_id,
                node_id=review.node_id,
                author_login=review.author.login if review.author else None,
                author_association=(
                    review.author_association.value if review.author_association else None
                ),
                state=review.state,
                body=review.body,
                submitted_at=review.submitted_at,
                raw_json=review.raw_payload,
            )
        )
    return len(reviews)


def _replace_comments(
    session: Session,
    pull_request_id: UUID,
    comments: list[PullRequestCommentDTO],
) -> int:
    session.execute(
        delete(PullRequestComment).where(PullRequestComment.pull_request_id == pull_request_id)
    )
    for comment in comments:
        session.add(
            PullRequestComment(
                pull_request_id=pull_request_id,
                github_id=comment.github_id,
                author_login=comment.author.login if comment.author else None,
                author_association=(
                    comment.author_association.value if comment.author_association else None
                ),
                body=comment.body,
                comment_type=comment.comment_type,
                github_created_at=comment.created_at,
                github_updated_at=comment.updated_at,
                raw_json=comment.raw_payload,
            )
        )
    return len(comments)


def _replace_issue_links(
    session: Session,
    repository_id: UUID,
    full_name: str,
    pull_request: PullRequestDTO,
    *,
    observed_at: datetime,
) -> int:
    body = pull_request.body or ""
    matches: list[tuple[str, int, str, float]] = []
    closing_numbers: set[int] = set()
    for match in _CLOSING_RE.finditer(body):
        repository = match.group("repository") or full_name
        number = int(match.group("number"))
        matches.append((repository, number, "closing_keyword", 0.9))
        if repository.casefold() == full_name.casefold():
            closing_numbers.add(number)
    for match in _PLAIN_RE.finditer(body):
        number = int(match.group("number"))
        if number not in closing_numbers:
            matches.append((full_name, number, "text_reference", 0.25))

    stored = 0
    for repository, number, relation, strength in matches:
        if repository.casefold() != full_name.casefold():
            continue
        issue = session.scalar(
            select(Issue).where(
                Issue.repository_id == repository_id,
                Issue.number == number,
            )
        )
        if issue is None:
            continue
        session.execute(
            delete(IssueLink).where(
                IssueLink.source_issue_id == issue.id,
                IssueLink.target_repository == full_name,
                IssueLink.target_number == pull_request.number,
                IssueLink.relation_type == relation,
            )
        )
        session.add(
            IssueLink(
                source_issue_id=issue.id,
                target_repository=full_name,
                target_number=pull_request.number,
                target_type="pull_request",
                relation_type=relation,
                state=pull_request.state.value,
                merged=pull_request.merged,
                url=pull_request.url,
                evidence_strength=strength,
                observed_at=observed_at,
            )
        )
        stored += 1
    return stored
