"""Integration tests for repository and contribution-document synchronization."""

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from radar.db.models import (
    PipelineRun,
    Repository,
    RepositoryConfig,
    RepositoryDocument,
    RunEvent,
)
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.domain.errors import AuthenticationError, EntityParseError, GitHubAPIError
from radar.domain.schemas import ContentDTO, RepositoryDTO
from radar.ingestion.documents import DOCUMENT_SPECS, decode_document
from radar.ingestion.repositories import sync_repositories
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class FrozenClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class FakeRepositoryGateway:
    def __init__(
        self,
        repository: RepositoryDTO,
        documents: dict[str, ContentDTO] | None = None,
    ) -> None:
        self.repository = repository
        self.documents = documents or {}
        self.repository_error: GitHubAPIError | None = None
        self.content_error: GitHubAPIError | None = None
        self.content_calls: list[str] = []

    async def get_repository(self, full_name: str) -> RepositoryDTO:
        if self.repository_error is not None:
            raise self.repository_error
        return self.repository

    async def get_repository_content(self, full_name: str, path: str) -> ContentDTO | None:
        self.content_calls.append(path)
        if self.content_error is not None:
            raise self.content_error
        return self.documents.get(path)


def _config() -> RadarConfig:
    config = load_config(Path("config/profile.example.yaml"))
    return config.model_copy(update={"repositories": (config.repositories[0],)})


def _repository(*, archived: bool = False, updated_at: datetime = NOW) -> RepositoryDTO:
    return RepositoryDTO(
        github_id=1,
        node_id="R_1",
        owner="ml-explore",
        name="mlx",
        full_name="ml-explore/mlx",
        url="https://github.com/ml-explore/mlx",
        description="Array framework",
        default_branch="main",
        primary_language="C++",
        stars=100,
        forks=10,
        archived=archived,
        disabled=False,
        is_fork=False,
        pushed_at=updated_at,
        created_at=NOW - timedelta(days=500),
        updated_at=updated_at,
        raw_payload={"id": 1, "archived": archived},
    )


def _content(*, sha: str = "abc123", text: str = "# Contributing") -> ContentDTO:
    encoded = base64.b64encode(text.encode()).decode()
    return ContentDTO(
        path="CONTRIBUTING.md",
        sha=sha,
        content=encoded,
        encoding="base64",
        size=len(text),
        content_type="file",
        raw_payload={"sha": sha},
    )


def _sessions(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    return create_session_factory(create_database_engine(url))


@pytest.mark.asyncio
async def test_repeat_sync_is_idempotent_and_missing_docs_are_normal(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(
        _repository(),
        {"CONTRIBUTING.md": _content()},
    )

    first = await sync_repositories(_config(), gateway, sessions, FrozenClock())
    second = await sync_repositories(_config(), gateway, sessions, FrozenClock())

    assert first.repositories_created == 1
    assert first.documents_stored == 1
    assert first.documents_missing == len(DOCUMENT_SPECS) - 1
    assert first.documents_failed == 0
    assert second.repositories_unchanged == 1
    assert second.documents_unchanged == 1
    assert second.documents_missing == len(DOCUMENT_SPECS) - 1
    with transaction(sessions) as session:
        assert session.scalar(select(func.count()).select_from(Repository)) == 1
        assert session.scalar(select(func.count()).select_from(RepositoryConfig)) == 1
        assert session.scalar(select(func.count()).select_from(RepositoryDocument)) == 1
        assert session.scalar(select(func.count()).select_from(PipelineRun)) == 2
        runs = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).all()
        assert all(run.status == "success" for run in runs)
        assert runs[-1].summary["repositories_unchanged"] == 1


@pytest.mark.asyncio
async def test_changed_repository_status_is_reflected(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(_repository())
    await sync_repositories(_config(), gateway, sessions, FrozenClock())
    gateway.repository = _repository(archived=True, updated_at=NOW + timedelta(hours=1))

    result = await sync_repositories(_config(), gateway, sessions, FrozenClock())

    assert result.repositories_updated == 1
    with transaction(sessions) as session:
        stored = session.scalar(select(Repository))
        assert stored is not None
        assert stored.archived is True
        assert stored.raw_json["archived"] is True


@pytest.mark.asyncio
async def test_changed_document_sha_creates_versioned_observation(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(
        _repository(),
        {"CONTRIBUTING.md": _content(sha="first", text="v1")},
    )
    await sync_repositories(_config(), gateway, sessions, FrozenClock())
    gateway.documents["CONTRIBUTING.md"] = _content(sha="second", text="v2")

    result = await sync_repositories(_config(), gateway, sessions, FrozenClock())

    assert result.documents_stored == 1
    with transaction(sessions) as session:
        documents = session.scalars(
            select(RepositoryDocument).order_by(RepositoryDocument.sha)
        ).all()
        assert [(document.sha, document.decoded_text) for document in documents] == [
            ("first", "v1"),
            ("second", "v2"),
        ]


@pytest.mark.asyncio
async def test_document_failures_are_recorded_as_partial_without_losing_repository(
    tmp_path: Path,
) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(_repository())
    gateway.content_error = GitHubAPIError("temporary", status_code=500)

    result = await sync_repositories(_config(), gateway, sessions, FrozenClock())

    assert result.repositories_created == 1
    assert result.documents_failed == len(DOCUMENT_SPECS)
    with transaction(sessions) as session:
        run = session.scalar(select(PipelineRun))
        assert run is not None
        assert run.status == "partial"
        assert session.scalar(select(func.count()).select_from(RunEvent)) == (
            len(DOCUMENT_SPECS) + 1
        )


@pytest.mark.asyncio
async def test_repository_failure_has_clear_counts_and_event(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(_repository())
    gateway.repository_error = GitHubAPIError("forbidden", status_code=403)

    result = await sync_repositories(_config(), gateway, sessions, FrozenClock())

    assert result.repositories_failed == 1
    assert result.repositories_created == 0
    with transaction(sessions) as session:
        run = session.scalar(select(PipelineRun))
        event = session.scalar(select(RunEvent))
        assert run is not None and run.status == "partial"
        assert event is not None and event.error_type == "GitHubAPIError"


@pytest.mark.asyncio
async def test_authentication_failure_stops_and_marks_run_failed(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    gateway = FakeRepositoryGateway(_repository())
    gateway.repository_error = AuthenticationError("bad token", status_code=401)

    with pytest.raises(AuthenticationError):
        await sync_repositories(_config(), gateway, sessions, FrozenClock())

    with transaction(sessions) as session:
        run = session.scalar(select(PipelineRun))
        assert run is not None
        assert run.status == "failed"


@pytest.mark.parametrize(
    "content",
    [
        ContentDTO(
            path="directory",
            sha="1",
            content="",
            encoding="base64",
            size=0,
            content_type="dir",
        ),
        ContentDTO(
            path="plain.txt",
            sha="2",
            content="plain",
            encoding="utf-8",
            size=5,
        ),
        ContentDTO(
            path="broken.md",
            sha="3",
            content="not base64!",
            encoding="base64",
            size=8,
        ),
    ],
)
def test_document_decoder_rejects_non_file_or_invalid_base64(content: ContentDTO) -> None:
    with pytest.raises(EntityParseError):
        decode_document(content)
