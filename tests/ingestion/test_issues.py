"""Integration tests for incremental issue and comment synchronization."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from radar.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    IssueLink,
    PipelineRun,
    Repository,
    SyncCursor,
)
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.domain.enums import AuthorAssociation, IssueState
from radar.domain.errors import GitHubAPIError
from radar.domain.schemas import IssueCommentDTO, IssueDTO, LabelDTO, UserDTO
from radar.ingestion.issues import mark_issue_inaccessible, sync_issues
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class FakeIssueGateway:
    def __init__(
        self,
        issues: list[IssueDTO],
        comments: dict[int, list[IssueCommentDTO]],
    ) -> None:
        self.issues = issues
        self.comments = comments
        self.issue_error_after: int | None = None
        self.comment_error = False
        self.issue_since: list[datetime | None] = []
        self.comment_since: list[datetime | None] = []

    async def list_issues(
        self,
        full_name: str,
        *,
        state: str,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueDTO]:
        self.issue_since.append(since)

        async def generate() -> AsyncIterator[IssueDTO]:
            for index, issue in enumerate(self.issues):
                if self.issue_error_after == index:
                    raise GitHubAPIError("page failed", status_code=500)
                yield issue

        return generate()

    async def list_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueCommentDTO]:
        self.comment_since.append(since)

        async def generate() -> AsyncIterator[IssueCommentDTO]:
            for comment in self.comments.get(number, []):
                yield comment
            if self.comment_error:
                raise GitHubAPIError("comments failed", status_code=500)

        return generate()


def _config() -> RadarConfig:
    config = load_config(Path("config/profile.example.yaml"))
    return config.model_copy(update={"repositories": (config.repositories[0],)})


def _sessions(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    with transaction(sessions) as session:
        session.add(
            Repository(
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
                raw_json={"id": 1},
            )
        )
    return sessions


def _issue(
    *,
    github_id: int = 10,
    number: int = 7,
    updated_at: datetime = NOW,
    body: str = "See https://github.com/other/project/issues/9",
    labels: tuple[LabelDTO, ...] = (LabelDTO(name="bug"),),
    assignees: tuple[UserDTO, ...] = (UserDTO(login="worker"),),
    is_pull_request: bool = False,
) -> IssueDTO:
    return IssueDTO(
        github_id=github_id,
        node_id=f"I_{github_id}",
        repository="ml-explore/mlx",
        number=number,
        title="Improve behavior",
        body=body,
        state=IssueState.OPEN,
        url=f"https://github.com/ml-explore/mlx/issues/{number}",
        author=UserDTO(login="author"),
        author_association=AuthorAssociation.CONTRIBUTOR,
        labels=labels,
        assignees=assignees,
        created_at=NOW - timedelta(days=1),
        updated_at=updated_at,
        is_pull_request=is_pull_request,
        raw_payload={"id": github_id, "body": body, "updated": updated_at.isoformat()},
    )


def _comment(*, body: str = "Initial", updated_at: datetime = NOW) -> IssueCommentDTO:
    return IssueCommentDTO(
        github_id=100,
        node_id="IC_100",
        issue_number=7,
        body=body,
        url="https://github.com/ml-explore/mlx/issues/7#issuecomment-100",
        author=UserDTO(login="commenter"),
        author_association=AuthorAssociation.NONE,
        created_at=NOW,
        updated_at=updated_at,
        raw_payload={"id": 100, "body": body},
    )


@pytest.mark.asyncio
async def test_repeat_sync_has_no_duplicates_and_excludes_pr_shapes(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeIssueGateway(
        [_issue(), _issue(github_id=11, number=8, is_pull_request=True)],
        {7: [_comment()]},
    )

    first = await sync_issues(_config(), gateway, sessions, MutableClock())
    second = await sync_issues(_config(), gateway, sessions, MutableClock())

    assert first.issues_created == 1
    assert first.pull_requests_excluded == 1
    assert first.comments_created == 1
    assert second.issues_unchanged == 1
    with transaction(sessions) as session:
        assert session.scalar(select(func.count()).select_from(Issue)) == 2
        assert session.scalar(select(func.count()).select_from(IssueComment)) == 1
        assert session.scalar(select(func.count()).select_from(IssueLabel)) == 2
        assert session.scalar(select(func.count()).select_from(IssueAssignee)) == 2
        assert session.scalar(select(func.count()).select_from(IssueLink)) == 1
    assert gateway.issue_since == [None, NOW - timedelta(minutes=10)]


@pytest.mark.asyncio
async def test_edited_comments_update_and_removed_relationships_are_reflected(
    tmp_path: Path,
) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeIssueGateway([_issue()], {7: [_comment()]})
    await sync_issues(_config(), gateway, sessions, MutableClock())
    later = NOW + timedelta(hours=1)
    gateway.issues = [_issue(updated_at=later, labels=(), assignees=())]
    gateway.comments = {7: [_comment(body="Edited", updated_at=later)]}

    result = await sync_issues(_config(), gateway, sessions, MutableClock(later))

    assert result.issues_updated == 1
    assert result.comments_updated == 1
    with transaction(sessions) as session:
        assert session.scalar(select(IssueComment.body)) == "Edited"
        assert session.scalar(select(func.count()).select_from(IssueLabel)) == 0
        assert session.scalar(select(func.count()).select_from(IssueAssignee)) == 0


@pytest.mark.asyncio
async def test_issue_cursor_moves_only_after_complete_traversal(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeIssueGateway([_issue(), _issue(github_id=12, number=12)], {})
    gateway.issue_error_after = 1

    result = await sync_issues(_config(), gateway, sessions, MutableClock())

    assert result.repositories_failed == 1
    with transaction(sessions) as session:
        cursor = session.scalar(select(SyncCursor).where(SyncCursor.scope_type == "issues"))
        assert cursor is None


@pytest.mark.asyncio
async def test_partial_comment_failure_keeps_comment_cursor_safe_and_is_recorded(
    tmp_path: Path,
) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeIssueGateway([_issue()], {7: [_comment()]})
    gateway.comment_error = True

    result = await sync_issues(_config(), gateway, sessions, MutableClock())

    assert result.comment_failures == 1
    with transaction(sessions) as session:
        issue_cursor = session.scalar(select(SyncCursor).where(SyncCursor.scope_type == "issues"))
        comment_cursor = session.scalar(
            select(SyncCursor).where(SyncCursor.scope_type == "comments")
        )
        run = session.scalar(select(PipelineRun))
        assert issue_cursor is not None
        assert comment_cursor is None
        assert run is not None
        assert run.status == "partial"
        assert run.summary["comment_failures"] == 1


def test_inaccessible_issue_is_soft_marked_not_deleted(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    repository_id = None
    with transaction(sessions) as session:
        repository = session.scalar(select(Repository))
        assert repository is not None
        repository_id = repository.id
        issue = _issue()
        from radar.ingestion.issues import _upsert_issue

        stored, _, _ = _upsert_issue(session, repository.id, issue, NOW)
        issue_id = stored.id

    with transaction(sessions) as session:
        assert repository_id is not None
        assert mark_issue_inaccessible(
            session,
            repository_id=repository_id,
            number=7,
            observed_at=NOW,
        )
    with transaction(sessions) as session:
        stored = session.get(Issue, issue_id)
        assert stored is not None
        assert stored.inaccessible_at == NOW
