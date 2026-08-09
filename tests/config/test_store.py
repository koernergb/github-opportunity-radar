"""Tests for immutable configuration revision storage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from radar.config_store import (
    ConfigConflictError,
    InvalidRevisionError,
    SecretInConfigError,
    SqlAlchemyConfigurationStore,
)
from radar.db.models import Base, ConfigActivation, ConfigRevision
from radar.db.session import create_session_factory


class AdvancingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 5, tzinfo=UTC)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value


class FrozenClock:
    value = datetime(2026, 8, 5, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.fixture
def store() -> SqlAlchemyConfigurationStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return SqlAlchemyConfigurationStore(create_session_factory(engine), AdvancingClock())


def _payload() -> dict[str, object]:
    value = yaml.safe_load(Path("config/profile.example.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_every_edit_creates_an_immutable_revision(store: SqlAlchemyConfigurationStore) -> None:
    first = store.create_revision(_payload(), source="manual", summary="Initial")
    changed = _payload()
    changed["user"]["interests"] = ["compilers"]  # type: ignore[index]
    second = store.create_revision(
        changed, source="manual", summary="Interests", supersedes_id=first.id
    )

    assert first.id != second.id
    assert first.config_hash != second.config_hash
    assert second.supersedes_id == first.id
    assert len(store.list_revisions()) == 2


def test_invalid_revision_can_be_previewed_but_not_activated(
    store: SqlAlchemyConfigurationStore,
) -> None:
    payload = _payload()
    payload["scoring"]["global_merge_prior"] = 2  # type: ignore[index]
    revision = store.create_revision(payload, source="manual", summary="Invalid preview")

    assert revision.valid is False
    assert revision.validation_errors[0]["path"] == "scoring.global_merge_prior"
    with pytest.raises(InvalidRevisionError):
        store.activate(revision.id, expected_active_id=None)


def test_stale_activation_conflicts_and_undo_preserves_history(
    store: SqlAlchemyConfigurationStore,
) -> None:
    first = store.create_revision(_payload(), source="manual", summary="First")
    store.activate(first.id, expected_active_id=None)
    second = store.create_revision(
        _payload(), source="manual", summary="Second", supersedes_id=first.id
    )
    store.activate(second.id, expected_active_id=first.id)

    with pytest.raises(ConfigConflictError):
        store.activate(first.id, expected_active_id=None)
    store.activate(first.id, expected_active_id=second.id)

    assert store.active_revision().id == first.id  # type: ignore[union-attr]
    assert store.active_config().config_hash == first.config_hash  # type: ignore[union-attr]
    sessions = store._sessions
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConfigRevision)) == 2
        assert session.scalar(select(func.count()).select_from(ConfigActivation)) == 3


def test_equal_clock_values_still_make_latest_activation_authoritative() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = create_session_factory(engine)
    Base.metadata.create_all(engine)
    store = SqlAlchemyConfigurationStore(sessions, FrozenClock())
    first = store.create_revision(_payload(), source="bootstrap", summary="First")
    changed = _payload()
    changed["user"]["interests"] = ["compilers"]  # type: ignore[index]
    second = store.create_revision(changed, source="assistant", summary="Second")

    first_activation = store.activate(first.id, expected_active_id=None)
    second_activation = store.activate(second.id, expected_active_id=first.id)

    assert second_activation.created_at > first_activation.created_at
    assert store.active_revision().id == second.id  # type: ignore[union-attr]


def test_bootstrap_and_export_are_deterministic(
    store: SqlAlchemyConfigurationStore, tmp_path: Path
) -> None:
    source = tmp_path / "profile.yaml"
    source.write_text(Path("config/profile.example.yaml").read_text(encoding="utf-8"))

    revision = store.bootstrap(source)

    assert revision is not None
    assert store.bootstrap(source) is None
    exported = store.export_yaml()
    assert yaml.safe_load(exported) == revision.payload
    assert exported == store.export_yaml()


def test_secrets_never_enter_revision_rows(store: SqlAlchemyConfigurationStore) -> None:
    payload = _payload()
    payload["github_token"] = "never-store-me"

    with pytest.raises(SecretInConfigError):
        store.create_revision(payload, source="imported", summary="Unsafe")

    with store._sessions() as session:
        assert session.scalar(select(func.count()).select_from(ConfigRevision)) == 0
