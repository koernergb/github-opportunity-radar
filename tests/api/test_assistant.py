"""Assistant HTTP boundary tests."""

from fastapi.testclient import TestClient

from radar.api.app import API_PREFIX
from radar.assistant.proposals import create_config_proposal
from radar.assistant.service import create_conversation
from radar.config_store import SqlAlchemyConfigurationStore
from radar.llm.secrets import CredentialResolver
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
        credentials=CredentialResolver(EnvironmentSettings(_env_file=None)),
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


def test_confirmation_uses_stored_exact_arguments_and_replay_fails() -> None:
    app = _app()
    services = app.state.services
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    base = store.create_revision(
        services.config.model_dump(mode="json"), source="bootstrap", summary="test"
    )
    store.activate(base.id, expected_active_id=None)
    conversation = create_conversation(services.sessions, services.clock)
    proposal = create_config_proposal(
        services.sessions,
        services.clock,
        conversation.id,
        "preferences",
        {"interests": ["safe-value"]},
    )
    client = TestClient(app)

    confirmed = client.post(
        f"{API_PREFIX}/assistant/proposals/{proposal.id}/confirm",
        json={"interests": ["altered-value"]},
    )
    replayed = client.post(f"{API_PREFIX}/assistant/proposals/{proposal.id}/confirm")

    assert confirmed.status_code == 200
    assert store.active_config().user.interests == ("safe-value",)  # type: ignore[union-attr]
    assert replayed.status_code == 409
