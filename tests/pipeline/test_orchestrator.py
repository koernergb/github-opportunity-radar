"""End-to-end pipeline isolation, authentication, locking, and idempotency tests."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from radar.db.models import IssueAnalysis, IssueScore, PipelineRun, Repository
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.domain.enums import AuthorAssociation, IssueState
from radar.domain.errors import AuthenticationError, GitHubAPIError
from radar.domain.schemas import (
    ContentDTO,
    IssueCommentDTO,
    IssueDTO,
    PullRequestCommentDTO,
    PullRequestDTO,
    RepositoryDTO,
    ReviewDTO,
    UserDTO,
)
from radar.pipeline.orchestrator import PipelineLockedError, run_pipeline
from radar.pipeline.runs import create_pipeline_run
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FixtureGateway:
    def __init__(self, *, fail_repository: str | None = None, authenticate: bool = True) -> None:
        self.fail_repository = fail_repository
        self.authenticate = authenticate

    async def get_repository(self, full_name: str) -> RepositoryDTO:
        if not self.authenticate:
            raise AuthenticationError("bad token", status_code=401)
        if full_name == self.fail_repository:
            raise GitHubAPIError("repository unavailable", status_code=500)
        owner, name = full_name.split("/")
        github_id = sum(ord(character) for character in full_name)
        return RepositoryDTO(
            github_id=github_id,
            node_id=f"R_{github_id}",
            owner=owner,
            name=name,
            full_name=full_name,
            url=f"https://github.com/{full_name}",
            description="A Python performance repository",
            default_branch="main",
            primary_language="Python",
            stars=100,
            forks=10,
            pushed_at=NOW,
            created_at=NOW - timedelta(days=500),
            updated_at=NOW,
            raw_payload={},
        )

    async def get_repository_content(self, full_name: str, path: str) -> ContentDTO | None:
        return None

    async def list_issues(
        self,
        full_name: str,
        *,
        state: str,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueDTO]:
        async def generate() -> AsyncIterator[IssueDTO]:
            github_id = sum(ord(character) for character in full_name) + 10_000
            yield IssueDTO(
                github_id=github_id,
                node_id=f"I_{github_id}",
                repository=full_name,
                number=1,
                title="Optimize the parser hot path",
                body="Reproduce the parser slowdown, implement a bounded fix, and add tests.",
                state=IssueState.OPEN,
                url=f"https://github.com/{full_name}/issues/1",
                author=UserDTO(login="author"),
                author_association=AuthorAssociation.CONTRIBUTOR,
                comment_count=0,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW - timedelta(hours=1),
                raw_payload={},
            )

        return generate()

    async def list_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueCommentDTO]:
        async def generate() -> AsyncIterator[IssueCommentDTO]:
            if False:
                yield

        return generate()

    async def list_pull_requests(
        self,
        full_name: str,
        *,
        state: str,
        max_items: int,
    ) -> AsyncIterator[PullRequestDTO]:
        async def generate() -> AsyncIterator[PullRequestDTO]:
            if False:
                yield

        return generate()

    async def get_pull_request(self, full_name: str, number: int) -> PullRequestDTO:
        raise AssertionError("empty pull request listing must not hydrate")

    async def list_pull_request_reviews(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[ReviewDTO]:
        raise AssertionError("empty pull request listing must not fetch reviews")

    async def list_pull_request_comments(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[PullRequestCommentDTO]:
        raise AssertionError("empty pull request listing must not fetch comments")


def _config(*, two_repositories: bool = False) -> RadarConfig:
    config = load_config(Path("config/profile.example.yaml"))
    repositories = config.repositories if two_repositories else (config.repositories[0],)
    llm = config.llm.model_copy(update={"max_candidates_per_run": 5})
    return config.model_copy(update={"repositories": repositories, "llm": llm})


def _sessions(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    return create_session_factory(create_database_engine(url))


@pytest.mark.asyncio
async def test_fixture_runs_end_to_end_and_rerun_is_idempotent(tmp_path: Path) -> None:
    config = _config()
    sessions = _sessions(tmp_path)
    gateway = FixtureGateway()

    first = await run_pipeline(config, gateway, sessions, FixedClock(), fallback_only=True)
    second = await run_pipeline(config, gateway, sessions, FixedClock(), fallback_only=True)

    assert first.status == second.status == "success"
    assert first.exit_code == second.exit_code == 0
    assert "Optimize the parser hot path" in first.markdown
    assert first.markdown == second.markdown
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Repository)) == 1
        assert session.scalar(select(func.count()).select_from(IssueAnalysis)) == 1
        assert session.scalar(select(func.count()).select_from(IssueScore)) == 1


@pytest.mark.asyncio
async def test_one_repository_failure_does_not_block_healthy_repository(tmp_path: Path) -> None:
    config = _config(two_repositories=True)
    failed = config.repositories[0].full_name
    healthy = config.repositories[1].full_name
    sessions = _sessions(tmp_path)

    outcome = await run_pipeline(
        config,
        FixtureGateway(fail_repository=failed),
        sessions,
        FixedClock(),
        fallback_only=True,
    )

    assert outcome.status == "partial"
    assert outcome.exit_code == 4
    assert healthy in outcome.markdown
    assert f"{failed}#1 —" not in outcome.markdown


@pytest.mark.asyncio
async def test_authentication_failure_stops_run_and_marks_it_failed(tmp_path: Path) -> None:
    config = _config()
    sessions = _sessions(tmp_path)

    with pytest.raises(AuthenticationError):
        await run_pipeline(
            config,
            FixtureGateway(authenticate=False),
            sessions,
            FixedClock(),
            fallback_only=True,
        )

    with sessions() as session:
        orchestrator = session.scalar(
            select(PipelineRun).where(PipelineRun.config_hash == config.config_hash)
        )
        assert orchestrator is not None
        assert orchestrator.status == "failed"


@pytest.mark.asyncio
async def test_overlapping_run_exits_cleanly_before_gateway_calls(tmp_path: Path) -> None:
    config = _config()
    sessions = _sessions(tmp_path)
    with transaction(sessions) as session:
        create_pipeline_run(
            session,
            config_hash=config.config_hash,
            stage="orchestrator",
            started_at=NOW,
        )

    with pytest.raises(PipelineLockedError):
        await run_pipeline(
            config,
            FixtureGateway(),
            sessions,
            FixedClock(),
            fallback_only=True,
        )
