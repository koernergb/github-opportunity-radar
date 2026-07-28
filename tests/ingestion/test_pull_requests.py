"""Tests for PR history, maintainer evidence, and issue-link strength."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from radar.db.models import (
    Issue,
    IssueLink,
    PullRequest,
    PullRequestComment,
    PullRequestReview,
    Repository,
)
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.domain.enums import AuthorAssociation, PullRequestState
from radar.domain.schemas import (
    PullRequestCommentDTO,
    PullRequestDTO,
    ReviewDTO,
    UserDTO,
)
from radar.ingestion.pull_requests import (
    first_maintainer_response,
    is_external_contributor,
    sync_pull_request_history,
)
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakePullRequestGateway:
    def __init__(
        self,
        pull_requests: list[PullRequestDTO],
        reviews: dict[int, list[ReviewDTO]] | None = None,
        comments: dict[int, list[PullRequestCommentDTO]] | None = None,
    ) -> None:
        self.pull_requests = pull_requests
        self.reviews = reviews or {}
        self.comments = comments or {}
        self.max_items: int | None = None

    async def list_pull_requests(
        self,
        full_name: str,
        *,
        state: str,
        max_items: int,
    ) -> AsyncIterator[PullRequestDTO]:
        self.max_items = max_items

        async def generate() -> AsyncIterator[PullRequestDTO]:
            for pull_request in self.pull_requests:
                yield pull_request

        return generate()

    async def get_pull_request(self, full_name: str, number: int) -> PullRequestDTO:
        return next(item for item in self.pull_requests if item.number == number)

    async def list_pull_request_reviews(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[ReviewDTO]:
        async def generate() -> AsyncIterator[ReviewDTO]:
            for review in self.reviews.get(number, []):
                yield review

        return generate()

    async def list_pull_request_comments(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[PullRequestCommentDTO]:
        async def generate() -> AsyncIterator[PullRequestCommentDTO]:
            for comment in self.comments.get(number, []):
                yield comment

        return generate()


def _config() -> RadarConfig:
    config = load_config(Path("config/profile.example.yaml"))
    return config.model_copy(update={"repositories": (config.repositories[0],)})


def _sessions(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    with transaction(sessions) as session:
        repository = Repository(
            github_id=1,
            node_id="R_1",
            owner="ml-explore",
            name="mlx",
            full_name="ml-explore/mlx",
            url="https://github.com/ml-explore/mlx",
            description=None,
            default_branch="main",
            primary_language="C++",
            stars=1,
            forks=1,
            archived=False,
            disabled=False,
            is_fork=False,
            pushed_at=NOW,
            github_created_at=NOW - timedelta(days=100),
            github_updated_at=NOW,
            last_synced_at=NOW,
            raw_json={},
        )
        session.add(repository)
        session.flush()
        for number in (1, 2, 3):
            session.add(
                Issue(
                    repository_id=repository.id,
                    github_id=100 + number,
                    node_id=f"I_{number}",
                    number=number,
                    title=f"Issue {number}",
                    body=None,
                    state="open",
                    state_reason=None,
                    url=f"https://github.com/ml-explore/mlx/issues/{number}",
                    author_login="author",
                    author_association="NONE",
                    locked=False,
                    comment_count=0,
                    github_created_at=NOW - timedelta(days=2),
                    github_updated_at=NOW,
                    github_closed_at=None,
                    last_seen_at=NOW,
                    inaccessible_at=None,
                    is_pull_request=False,
                    raw_json={},
                )
            )
    return sessions


def _pull_request(
    number: int,
    *,
    body: str,
    state: PullRequestState,
    merged: bool,
) -> PullRequestDTO:
    return PullRequestDTO(
        github_id=200 + number,
        node_id=f"PR_{number}",
        repository="ml-explore/mlx",
        number=number,
        title=f"PR {number}",
        body=body,
        url=f"https://github.com/ml-explore/mlx/pull/{number}",
        author=UserDTO(login="external"),
        author_association=AuthorAssociation.CONTRIBUTOR,
        state=state,
        merged=merged,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW,
        closed_at=NOW if state is PullRequestState.CLOSED else None,
        merged_at=NOW if merged else None,
        additions=10,
        deletions=2,
        changed_files=1,
        commit_count=1,
        comment_count=1,
        review_comment_count=0,
        raw_payload={"number": number},
    )


def _review(
    association: AuthorAssociation,
    submitted_at: datetime,
    *,
    login: str = "reviewer",
) -> ReviewDTO:
    return ReviewDTO(
        github_id=int(submitted_at.timestamp()),
        node_id=f"RV_{submitted_at.timestamp()}",
        pull_request_number=10,
        author=UserDTO(login=login),
        author_association=association,
        state="COMMENTED",
        submitted_at=submitted_at,
    )


def _comment(
    association: AuthorAssociation,
    created_at: datetime,
    *,
    login: str = "commenter",
) -> PullRequestCommentDTO:
    return PullRequestCommentDTO(
        github_id=int(created_at.timestamp()),
        pull_request_number=10,
        author=UserDTO(login=login),
        author_association=association,
        body="response",
        comment_type="issue",
        created_at=created_at,
        updated_at=created_at,
    )


def test_contributor_remains_external() -> None:
    assert is_external_contributor(AuthorAssociation.CONTRIBUTOR)
    assert is_external_contributor(None)
    assert not is_external_contributor(AuthorAssociation.MEMBER)


def test_first_response_requires_post_creation_credible_non_bot_maintainer() -> None:
    created = NOW
    reviews = [
        _review(AuthorAssociation.MEMBER, created - timedelta(minutes=1)),
        _review(AuthorAssociation.CONTRIBUTOR, created + timedelta(minutes=1)),
        _review(
            AuthorAssociation.MEMBER,
            created + timedelta(minutes=2),
            login="github-actions[bot]",
        ),
        _review(AuthorAssociation.OWNER, created + timedelta(minutes=4)),
    ]
    comments = [
        _comment(AuthorAssociation.COLLABORATOR, created + timedelta(minutes=3)),
    ]

    response, review = first_maintainer_response(created, reviews, comments)

    assert response == created + timedelta(minutes=3)
    assert review == created + timedelta(minutes=4)


@pytest.mark.asyncio
async def test_links_distinguish_active_closed_merged_and_ambiguous(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    pull_requests = [
        _pull_request(10, body="Fixes #1", state=PullRequestState.OPEN, merged=False),
        _pull_request(11, body="Closes #2", state=PullRequestState.CLOSED, merged=False),
        _pull_request(12, body="Resolves #3", state=PullRequestState.CLOSED, merged=True),
        _pull_request(13, body="Related to #2", state=PullRequestState.OPEN, merged=False),
    ]
    gateway = FakePullRequestGateway(pull_requests)

    first = await sync_pull_request_history(_config(), gateway, sessions, FrozenClock())
    second = await sync_pull_request_history(_config(), gateway, sessions, FrozenClock())

    assert first.pull_requests_created == 4
    assert second.pull_requests_unchanged == 4
    assert gateway.max_items == _config().github.pr_history_limit
    with transaction(sessions) as session:
        links = session.scalars(select(IssueLink).order_by(IssueLink.target_number)).all()
        by_pr = {link.target_number: link for link in links}
        assert by_pr[10].state == "open" and by_pr[10].merged is False
        assert by_pr[11].state == "closed" and by_pr[11].merged is False
        assert by_pr[12].state == "closed" and by_pr[12].merged is True
        assert by_pr[13].relation_type == "text_reference"
        assert by_pr[13].evidence_strength == 0.25
        assert session.scalar(select(func.count()).select_from(PullRequest)) == 4
        assert session.scalar(select(func.count()).select_from(IssueLink)) == 4


@pytest.mark.asyncio
async def test_reviews_comments_and_first_response_are_persisted(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    pull_request = _pull_request(
        10,
        body="Fixes #1",
        state=PullRequestState.OPEN,
        merged=False,
    )
    response_at = pull_request.created_at + timedelta(hours=2)
    gateway = FakePullRequestGateway(
        [pull_request],
        reviews={10: [_review(AuthorAssociation.MEMBER, response_at)]},
        comments={
            10: [
                _comment(
                    AuthorAssociation.CONTRIBUTOR,
                    pull_request.created_at + timedelta(hours=1),
                )
            ]
        },
    )

    result = await sync_pull_request_history(_config(), gateway, sessions, FrozenClock())

    assert result.reviews_stored == 1
    assert result.comments_stored == 1
    with transaction(sessions) as session:
        stored = session.scalar(select(PullRequest))
        assert stored is not None
        assert stored.first_maintainer_response_at == response_at
        assert stored.first_maintainer_review_at == response_at
        assert session.scalar(select(func.count()).select_from(PullRequestReview)) == 1
        assert session.scalar(select(func.count()).select_from(PullRequestComment)) == 1
