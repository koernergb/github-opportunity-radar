"""Contract tests for the local FastAPI foundation."""

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from radar.api.app import API_PREFIX, _default_static_dir, create_app
from radar.api.errors import ApiError
from radar.db.models import Base
from radar.db.session import create_session_factory
from radar.settings import ConfigLoadError, EnvironmentSettings, load_config


def _app(
    *,
    configured: bool = True,
    config_error: ConfigLoadError | None = None,
    origins: tuple[str, ...] = (),
    static_dir: Path | None = None,
) -> FastAPI:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    environment = EnvironmentSettings(
        _env_file=None,
        github_token="github-secret",
        openai_api_key="openai-secret",
    )
    return create_app(
        environment=environment,
        sessions=create_session_factory(engine),
        config=load_config(Path("config/profile.example.yaml")) if configured else None,
        config_error=config_error,
        allowed_origins=origins,
        static_dir=static_dir,
    )


def test_liveness_and_readiness_are_distinct_and_secrets_are_redacted() -> None:
    client = TestClient(_app())
    health = client.get(f"{API_PREFIX}/health")
    readiness = client.get(f"{API_PREFIX}/readiness")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ready",
        "checks": {"config": {"status": "ready"}, "database": {"status": "ready"}},
        "secrets": {
            "github_token": {"status": "configured"},
            "openai_api_key": {"status": "configured"},
            "anthropic_api_key": {"status": "missing"},
            "google_api_key": {"status": "missing"},
            "wafer_api_key": {"status": "missing"},
        },
    }
    assert "github-secret" not in readiness.text
    assert "openai-secret" not in readiness.text


def test_readiness_reports_invalid_config_without_leaking_error() -> None:
    response = TestClient(
        _app(configured=False, config_error=ConfigLoadError("secret configuration detail"))
    ).get(f"{API_PREFIX}/readiness")

    assert response.status_code == 503
    assert response.json()["checks"]["config"] == {"status": "invalid"}
    assert "secret configuration detail" not in response.text


def test_api_errors_have_stable_sanitized_shape() -> None:
    app = _app()
    test_router = APIRouter(prefix=API_PREFIX)

    @test_router.get("/expected-error")
    def expected_error() -> None:
        raise ApiError(409, "state_conflict", "The resource changed.")

    app.include_router(test_router)
    response = TestClient(app).get(
        f"{API_PREFIX}/expected-error", headers={"X-Request-ID": "request-123"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "state_conflict",
            "message": "The resource changed.",
            "request_id": "request-123",
        }
    }


def test_cors_allows_only_configured_local_origin() -> None:
    client = TestClient(_app(origins=("http://localhost:5173",)))
    headers = {"Access-Control-Request-Method": "GET"}
    allowed = client.options(
        f"{API_PREFIX}/health", headers={**headers, "Origin": "http://localhost:5173"}
    )
    denied = client.options(
        f"{API_PREFIX}/health", headers={**headers, "Origin": "https://example.com"}
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


def test_default_static_dir_points_at_repository_web_dist() -> None:
    static_dir = _default_static_dir()
    expected = Path(__file__).resolve().parents[2] / "web" / "dist"
    assert static_dir == expected
    assert (static_dir / "index.html").is_file()


def test_static_asset_hook_mounts_existing_build_assets(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("export {};", encoding="utf-8")

    response = TestClient(_app(static_dir=tmp_path)).get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "export {};"


def test_production_build_serves_root_and_deep_link_without_masking_api(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<main>Radar UI</main>", encoding="utf-8")
    client = TestClient(_app(static_dir=tmp_path))
    assert client.get("/").text == "<main>Radar UI</main>"
    assert client.get("/opportunities/issue-1").text == "<main>Radar UI</main>"
    assert client.get("/api/v1/not-real").status_code == 404


def test_openapi_schema_matches_snapshot() -> None:
    canonical = json.dumps(_app().openapi(), sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    expected = (Path(__file__).parent / "openapi.sha256").read_text(encoding="utf-8").strip()
    assert digest == expected
