"""Secret-safe LLM settings API tests."""

from fastapi.testclient import TestClient

from radar.api.app import API_PREFIX
from radar.assistant.provider import ProviderCompleted, ProviderTextDelta
from radar.llm.secrets import CredentialResolver, ProviderName
from tests.api.test_app import _app


class MemoryStore:
    def __init__(self) -> None:
        self.values: dict[ProviderName, str] = {}

    def get(self, provider: ProviderName) -> str | None:
        return self.values.get(provider)

    def set(self, provider: ProviderName, value: str) -> None:
        self.values[provider] = value

    def delete(self, provider: ProviderName) -> None:
        self.values.pop(provider, None)


def _client() -> tuple[TestClient, MemoryStore]:
    app = _app(origins=("http://localhost:5173",))
    store = MemoryStore()
    services = app.state.services
    app.state.services = services.__class__(
        environment=services.environment,
        config=services.config,
        config_error=services.config_error,
        sessions=services.sessions,
        clock=services.clock,
        credentials=CredentialResolver(services.environment, store),
        static_dir=services.static_dir,
    )
    return TestClient(app), store


def test_provider_statuses_are_capability_aware_and_secret_free() -> None:
    client, _ = _client()
    response = client.get(f"{API_PREFIX}/llm/providers")
    assert response.status_code == 200
    assert {item["provider"] for item in response.json()} == {
        "openai",
        "anthropic",
        "google",
        "wafer",
    }
    assert "openai-secret" not in response.text
    assert next(item for item in response.json() if item["provider"] == "openai")[
        "selected_for_analysis"
    ]


def test_credential_mutations_require_intent_and_allowed_origin() -> None:
    client, store = _client()
    path = f"{API_PREFIX}/llm/providers/anthropic/credential"
    assert client.put(path, json={"api_key": "anthropic-secret"}).status_code == 403
    headers = {
        "X-Radar-Secret-Intent": "update-provider-credential",
        "Origin": "https://hostile.example",
    }
    assert (
        client.put(path, json={"api_key": "anthropic-secret"}, headers=headers).status_code == 403
    )
    headers["Origin"] = "http://localhost:5173"
    saved = client.put(path, json={"api_key": "anthropic-secret"}, headers=headers)
    assert saved.json() == {
        "provider": "anthropic",
        "status": "configured",
        "source": "keychain",
    }
    assert "anthropic-secret" not in saved.text
    assert store.values["anthropic"] == "anthropic-secret"
    removed = client.delete(path, headers=headers)
    assert removed.status_code == 200
    assert "anthropic" not in store.values


def test_environment_credentials_cannot_be_removed_from_ui() -> None:
    client, _ = _client()
    response = client.delete(
        f"{API_PREFIX}/llm/providers/openai/credential",
        headers={"X-Radar-Secret-Intent": "update-provider-credential"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "environment_credential_read_only"


def test_provider_connection_test_is_bounded_and_sanitized(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Provider:
        async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["tools"] == []
            assert kwargs["max_output_tokens"] == 8
            yield ProviderTextDelta("OK")
            yield ProviderCompleted({"output_tokens": 1})

    monkeypatch.setattr("radar.api.routes.llm.ProviderRegistry.assistant", lambda *args: Provider())
    client, _ = _client()
    response = client.post(f"{API_PREFIX}/llm/providers/openai/test", json={"model": "gpt-test"})
    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert "openai-secret" not in response.text
