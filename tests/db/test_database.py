"""Database migration, transaction, portability, and entity tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.schema import CreateTable

from radar.db.models import Base, Issue, IssueLabel, Repository
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)

EXPECTED_TABLES = {
    "alembic_version",
    "assistant_tool_calls",
    "config_activations",
    "config_revisions",
    "conversation_messages",
    "conversations",
    "etag_cache",
    "issue_analyses",
    "issue_assignees",
    "issue_comments",
    "issue_filter_results",
    "issue_labels",
    "issue_links",
    "issue_scores",
    "issues",
    "pipeline_runs",
    "pull_request_comments",
    "pull_request_reviews",
    "pull_requests",
    "repositories",
    "repository_configs",
    "repository_documents",
    "repository_metric_snapshots",
    "run_events",
    "sync_cursors",
    "user_feedback",
}


def _database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'radar.sqlite'}"


def _repository(*, github_id: int = 1, full_name: str = "owner/repo") -> Repository:
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)
    owner, name = full_name.split("/")
    return Repository(
        github_id=github_id,
        node_id=f"R_{github_id}",
        owner=owner,
        name=name,
        full_name=full_name,
        url=f"https://github.com/{full_name}",
        description="A repository",
        default_branch="main",
        primary_language="Python",
        stars=10,
        forks=2,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=now,
        github_created_at=now,
        github_updated_at=now,
        last_synced_at=now,
        raw_json={"id": github_id, "source": "github"},
    )


def _issue(repository: Repository) -> Issue:
    now = datetime(2026, 7, 24, 13, tzinfo=UTC)
    return Issue(
        repository_id=repository.id,
        github_id=101,
        node_id="I_101",
        number=7,
        title="Improve the hot path",
        body="Bounded issue content",
        state="open",
        state_reason=None,
        url="https://github.com/owner/repo/issues/7",
        author_login="external",
        author_association="CONTRIBUTOR",
        locked=False,
        comment_count=0,
        github_created_at=now,
        github_updated_at=now,
        github_closed_at=None,
        last_seen_at=now,
        inaccessible_at=None,
        is_pull_request=False,
        raw_json={"id": 101},
    )


def test_migrate_zero_to_head_creates_complete_schema(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)

    migrate_database(database_url)

    engine = create_database_engine(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0003_assistant_conversations"
        )


def test_entities_round_trip_with_utc_and_raw_observation(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    migrate_database(database_url)
    factory = create_session_factory(create_database_engine(database_url))

    with transaction(factory) as session:
        repository = _repository()
        session.add(repository)
        session.flush()
        issue = _issue(repository)
        session.add(issue)
        session.flush()
        session.add(IssueLabel(issue_id=issue.id, name="help wanted", color="008672"))

    with transaction(factory) as session:
        stored = session.scalar(select(Repository).where(Repository.full_name == "owner/repo"))
        assert stored is not None
        assert stored.raw_json == {"id": 1, "source": "github"}
        assert stored.github_updated_at.tzinfo is UTC
        assert session.scalar(select(IssueLabel.name)) == "help wanted"


def test_uniqueness_violation_rolls_back_entire_transaction(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    migrate_database(database_url)
    factory = create_session_factory(create_database_engine(database_url))

    with pytest.raises(IntegrityError), transaction(factory) as session:
        session.add(_repository(github_id=1))
        session.add(_repository(github_id=2))

    with transaction(factory) as session:
        assert session.scalar(select(Repository)) is None


def test_transaction_rolls_back_on_application_error(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    migrate_database(database_url)
    factory = create_session_factory(create_database_engine(database_url))

    with pytest.raises(RuntimeError, match="stop"), transaction(factory) as session:
        session.add(_repository())
        raise RuntimeError("stop")

    with transaction(factory) as session:
        assert session.scalar(select(Repository)) is None


def test_naive_datetime_cannot_be_persisted(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    migrate_database(database_url)
    factory = create_session_factory(create_database_engine(database_url))
    repository = _repository()
    repository.github_updated_at = datetime(2026, 7, 24, 12)

    with (
        pytest.raises(StatementError, match="naive datetimes cannot be persisted"),
        transaction(factory) as session,
    ):
        session.add(repository)


def test_sqlite_foreign_keys_are_enabled(tmp_path: Path) -> None:
    engine = create_database_engine(_database_url(tmp_path))

    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1


def test_schema_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()

    for table in Base.metadata.sorted_tables:
        compiled = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in compiled


def test_initial_migration_downgrades_to_zero(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    migrate_database(database_url)
    project_root = Path(__file__).resolve().parents[2]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, "base")

    engine = create_database_engine(database_url)
    assert inspect(engine).get_table_names() == ["alembic_version"]
