"""Contract tests for provider-neutral HTTP adapters and credential resolution."""

import json
from typing import Any

import httpx
import pytest

from radar.analysis.provider import AnalysisProviderError
from radar.assistant.provider import ProviderCompleted, ProviderTextDelta, ProviderToolCall
from radar.llm.http_providers import (
    AnthropicAnalysisProvider,
    AnthropicAssistantProvider,
    GoogleAnalysisProvider,
    GoogleAssistantProvider,
    WaferAnalysisProvider,
    WaferAssistantProvider,
)
from radar.llm.registry import ProviderCredentialError, ProviderRegistry
from radar.llm.secrets import (
    CredentialResolver,
    KeyringSecretStore,
    NullSecretStore,
    ProviderName,
    SecretStoreUnavailableError,
)
from radar.settings import EnvironmentSettings


def _analysis() -> dict[str, Any]:
    return {
        "schema_version": "issue_analysis_v1",
        "task_type": "bug_fix",
        "short_summary": "Fix a parser bug.",
        "likely_work": ["reproduce", "patch", "test"],
        "required_skills": ["python"],
        "required_domains": ["parsing"],
        "effort_low_hours": 2,
        "effort_high_hours": 5,
        "effort_confidence": 0.8,
        "ambiguity": 0.2,
        "design_dependency": 0.1,
        "environment_difficulty": 0.2,
        "hardware_required": False,
        "hardware_notes": None,
        "reproduction_clarity": 0.8,
        "acceptance_criteria_clarity": 0.7,
        "test_plan_clarity": 0.7,
        "technical_depth": 0.6,
        "project_impact": 0.5,
        "learning_value": 0.6,
        "portfolio_explainability": 0.7,
        "visibility": 0.4,
        "interest_fit": 0.8,
        "career_relevance": 0.7,
        "maintainer_intent": 0.6,
        "maintainer_intent_confidence": 0.5,
        "likely_claimed": False,
        "claim_confidence": 0.6,
        "questions": [],
        "risks": [],
        "positive_signals": ["reproduction"],
        "suggested_first_move": "Run the reproduction.",
        "rationale": "The issue is bounded.",
        "investigation_steps": ["run tests"],
        "overall_confidence": 0.75,
    }


def _sync_client(payload: object, base_url: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )


def _async_client(payload: object, base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )


@pytest.mark.parametrize("provider_name", ["anthropic", "google", "wafer"])
def test_analysis_adapters_validate_provider_specific_responses(provider_name: str) -> None:
    analysis = _analysis()
    if provider_name == "anthropic":
        provider = AnthropicAnalysisProvider(
            api_key="secret",
            model="model-a",
            client=_sync_client(
                {
                    "content": [
                        {"type": "tool_use", "name": "emit_issue_analysis", "input": analysis}
                    ],
                    "usage": {"input_tokens": 2},
                },
                "https://api.anthropic.com",
            ),
        )
    elif provider_name == "google":
        provider = GoogleAnalysisProvider(
            api_key="secret",
            model="model-g",
            client=_sync_client(
                {
                    "candidates": [{"content": {"parts": [{"text": json.dumps(analysis)}]}}],
                    "usageMetadata": {"promptTokenCount": 2},
                },
                "https://generativelanguage.googleapis.com",
            ),
        )
    else:
        provider = WaferAnalysisProvider(
            api_key="secret",
            model="model-w",
            client=_sync_client(
                {
                    "choices": [{"message": {"content": json.dumps(analysis)}}],
                    "usage": {"prompt_tokens": 2},
                },
                "https://pass.wafer.ai",
            ),
        )

    result = provider.analyze(context_json="{}", system_prompt="system")

    assert result.analysis.task_type == "bug_fix"
    assert result.usage
    assert result.raw_response is not None


def test_malformed_gemini_analysis_fails_at_provider_boundary() -> None:
    provider = GoogleAnalysisProvider(
        api_key="secret",
        model="model",
        client=_sync_client({"candidates": []}, "https://generativelanguage.googleapis.com"),
    )
    with pytest.raises(AnalysisProviderError, match="omitted"):
        provider.analyze(context_json="{}", system_prompt="system", repair_feedback="bad")


async def _events(provider: Any) -> list[object]:
    return [
        event
        async for event in provider.stream(
            messages=[
                {"role": "developer", "content": "system"},
                {"role": "user", "content": "question"},
            ],
            tools=[
                {
                    "name": "inspect_runs",
                    "description": "Inspect runs",
                    "parameters": {"type": "object"},
                }
            ],
            max_output_tokens=20,
        )
    ]


@pytest.mark.asyncio
async def test_anthropic_assistant_translates_text_tools_and_usage() -> None:
    provider = AnthropicAssistantProvider(
        api_key="secret",
        model="claude-test",
        client=_async_client(
            {
                "content": [
                    {"type": "text", "text": "Checking."},
                    {"type": "tool_use", "id": "tool-1", "name": "inspect_runs", "input": {}},
                ],
                "usage": {"output_tokens": 3},
            },
            "https://api.anthropic.com",
        ),
    )
    events = await _events(provider)
    assert any(isinstance(event, ProviderTextDelta) for event in events)
    assert any(isinstance(event, ProviderToolCall) for event in events)
    assert isinstance(events[-1], ProviderCompleted)


@pytest.mark.asyncio
async def test_google_assistant_translates_text_tools_and_usage() -> None:
    provider = GoogleAssistantProvider(
        api_key="secret",
        model="gemini-test",
        client=_async_client(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Checking."},
                                {"functionCall": {"name": "inspect_runs", "args": {}}},
                            ]
                        }
                    }
                ],
                "usageMetadata": {"candidatesTokenCount": 3},
            },
            "https://generativelanguage.googleapis.com",
        ),
    )
    events = await _events(provider)
    assert [type(event) for event in events] == [
        ProviderTextDelta,
        ProviderToolCall,
        ProviderCompleted,
    ]


@pytest.mark.asyncio
async def test_wafer_assistant_translates_openai_compatible_message() -> None:
    provider = WaferAssistantProvider(
        api_key="secret",
        model="wafer-test",
        client=_async_client(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Checking.",
                            "tool_calls": [
                                {
                                    "id": "tool-1",
                                    "function": {"name": "inspect_runs", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"completion_tokens": 3},
            },
            "https://pass.wafer.ai",
        ),
    )
    events = await _events(provider)
    assert any(isinstance(event, ProviderToolCall) for event in events)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[ProviderName, str] = {}

    def get(self, provider: ProviderName) -> str | None:
        return self.values.get(provider)

    def set(self, provider: ProviderName, value: str) -> None:
        self.values[provider] = value

    def delete(self, provider: ProviderName) -> None:
        self.values.pop(provider, None)


def test_credential_resolver_prefers_environment_and_never_exposes_short_values() -> None:
    store = MemorySecretStore()
    store.values["openai"] = "keychain-secret"
    resolver = CredentialResolver(
        EnvironmentSettings(_env_file=None, openai_api_key="environment-secret"), store
    )
    assert resolver.resolve("openai").source == "environment"
    with pytest.raises(ValueError, match="8 to 4096"):
        resolver.save("wafer", "short")
    resolver.save("wafer", "wafer-secret")
    assert resolver.resolve("wafer").source == "keychain"
    assert "wafer-secret" in resolver.values_for_redaction()
    resolver.delete("wafer")
    assert resolver.resolve("wafer").value is None


def test_null_store_and_registry_fail_closed_without_credentials() -> None:
    resolver = CredentialResolver(EnvironmentSettings(_env_file=None), NullSecretStore())
    with pytest.raises(ProviderCredentialError, match="not configured"):
        ProviderRegistry(resolver).analysis("anthropic", "model")


def test_registry_constructs_every_provider_contract() -> None:
    store = MemorySecretStore()
    for name in ("openai", "anthropic", "google", "wafer"):
        store.values[name] = f"{name}-secret"
    registry = ProviderRegistry(CredentialResolver(EnvironmentSettings(_env_file=None), store))
    for name in ("openai", "anthropic", "google", "wafer"):
        analysis = registry.analysis(name, "test-model")
        assistant = registry.assistant(name, "test-model")
        assert analysis.provider_name == name
        assert assistant.provider_name == name


def test_keyring_store_wraps_backend_without_exposing_backend_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring

    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, user: values.get((service, user)))
    monkeypatch.setattr(
        keyring,
        "set_password",
        lambda service, user, value: values.__setitem__((service, user), value),
    )
    monkeypatch.setattr(
        keyring, "delete_password", lambda service, user: values.pop((service, user))
    )
    store = KeyringSecretStore()
    store.set("google", "google-secret")
    assert store.get("google") == "google-secret"
    store.delete("google")
    assert store.get("google") is None

    def fail(service: str, user: str) -> str | None:
        del service, user
        raise RuntimeError("backend detail")

    monkeypatch.setattr(keyring, "get_password", fail)
    with pytest.raises(SecretStoreUnavailableError, match="could not be read"):
        store.get("google")
