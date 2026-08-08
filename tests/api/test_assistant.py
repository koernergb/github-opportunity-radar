"""Assistant HTTP boundary tests."""

from fastapi.testclient import TestClient

from radar.api.app import API_PREFIX
from radar.settings import EnvironmentSettings
from tests.api.test_app import _app


def test_missing_openai_key_only_disables_assistant() -> None:
    app = _app()
    services = app.state.services
    app.state.services = services.__class__(
        environment=EnvironmentSettings(_env_file=None, github_token="present"),
        config=services.config,
        config_error=services.config_error,
        sessions=services.sessions,
        clock=services.clock,
        static_dir=services.static_dir,
    )
    client = TestClient(app)
    created = client.post(f"{API_PREFIX}/conversations", json={"title": "Test"})
    response = client.post(
        f"{API_PREFIX}/conversations/{created.json()['conversation_id']}/messages",
        json={"content": "What should I work on?"},
    )

    assert created.status_code == 201
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_unavailable"
    assert client.get(f"{API_PREFIX}/health").status_code == 200
