"""HTTP integration tests for configuration revisions."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from radar.api.app import API_PREFIX, create_app
from radar.db.models import Base
from radar.db.session import create_session_factory
from radar.settings import EnvironmentSettings, load_config


def _app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return create_app(
        environment=EnvironmentSettings(_env_file=None),
        sessions=create_session_factory(engine),
        config=load_config(Path("config/profile.example.yaml")),
    )


def _payload() -> dict[str, object]:
    value = yaml.safe_load(Path("config/profile.example.yaml").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_create_activate_export_and_undo_revision() -> None:
    client = TestClient(_app())
    first = client.post(
        f"{API_PREFIX}/preferences/proposals",
        json={
            "config": _payload(),
            "summary": "Initial",
            "expected_active_id": None,
            "activate": True,
        },
    )
    assert first.status_code == 201
    first_id = first.json()["revision_id"]
    changed = _payload()
    changed["user"]["interests"] = ["compilers"]  # type: ignore[index]
    second = client.post(
        f"{API_PREFIX}/preferences/proposals",
        json={
            "config": changed,
            "summary": "Changed",
            "expected_active_id": first_id,
            "activate": True,
        },
    )
    assert second.status_code == 201
    second_id = second.json()["revision_id"]

    stale = client.post(
        f"{API_PREFIX}/preferences/revisions/{first_id}/activate",
        json={"expected_active_id": first_id},
    )
    undo = client.post(
        f"{API_PREFIX}/preferences/revisions/{first_id}/activate",
        json={"expected_active_id": second_id},
    )
    exported = client.get(f"{API_PREFIX}/preferences/export")

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "config_conflict"
    assert undo.status_code == 200
    assert undo.json()["revision"]["revision_id"] == first_id
    assert yaml.safe_load(exported.text) == undo.json()["config"]
    assert len(client.get(f"{API_PREFIX}/preferences/revisions").json()) == 2


def test_invalid_and_secret_imports_cannot_be_activated() -> None:
    client = TestClient(_app())
    invalid = client.post(
        f"{API_PREFIX}/preferences/import",
        json={
            "yaml_text": "version: 1\ngithub_token: secret\n",
            "summary": "Unsafe",
            "expected_active_id": None,
            "activate": True,
        },
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "secret_field_forbidden"
    assert "never-store-me" not in invalid.text
