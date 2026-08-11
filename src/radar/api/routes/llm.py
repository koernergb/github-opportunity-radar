"""Secret-safe local LLM provider configuration endpoints."""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.config_store import SqlAlchemyConfigurationStore
from radar.llm.registry import CAPABILITIES, ProviderCredentialError, ProviderRegistry
from radar.llm.secrets import ProviderName, SecretStoreUnavailableError

router = APIRouter(prefix="/llm/providers", tags=["llm-providers"])


class ProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName
    display_name: str
    credential_status: Literal["configured", "missing", "invalid"]
    credential_source: Literal["environment", "keychain"] | None
    structured_analysis: bool
    assistant_tools: bool
    model_suggestions: list[str]
    notes: str | None
    selected_for_analysis: bool
    selected_for_assistant: bool
    analysis_model: str | None
    assistant_model: str | None


class CredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=8, max_length=4096)


class TestProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=255)


class CredentialMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: ProviderName
    status: Literal["configured", "removed", "connected"]
    source: Literal["environment", "keychain"] | None = None


@router.get("", response_model=list[ProviderStatus])
def providers(services: Services) -> list[ProviderStatus]:
    config = (
        SqlAlchemyConfigurationStore(services.sessions, services.clock).active_config()
        or services.config
    )
    output: list[ProviderStatus] = []
    for name, capability in CAPABILITIES.items():
        try:
            credential = services.credentials.resolve(name)
            status: Literal["configured", "missing", "invalid"] = (
                "configured" if credential.value else "missing"
            )
            source = credential.source
        except SecretStoreUnavailableError:
            status = "invalid"
            source = None
        output.append(
            ProviderStatus(
                provider=name,
                display_name=capability.display_name,
                credential_status=status,
                credential_source=source,
                structured_analysis=capability.structured_analysis,
                assistant_tools=capability.assistant_tools,
                model_suggestions=list(capability.model_suggestions),
                notes=capability.notes,
                selected_for_analysis=config is not None and config.llm.provider == name,
                selected_for_assistant=(
                    config is not None and config.llm.resolved_assistant_provider == name
                ),
                analysis_model=(
                    config.llm.model if config is not None and config.llm.provider == name else None
                ),
                assistant_model=(
                    config.llm.resolved_assistant_model
                    if config is not None and config.llm.resolved_assistant_provider == name
                    else None
                ),
            )
        )
    return output


@router.put("/{provider}/credential", response_model=CredentialMutationResponse)
def save_credential(
    provider: ProviderName, body: CredentialRequest, request: Request, services: Services
) -> CredentialMutationResponse:
    _authorize_secret_mutation(request)
    try:
        services.credentials.save(provider, body.api_key)
    except (SecretStoreUnavailableError, ValueError) as error:
        raise ApiError(
            503, "credential_store_unavailable", "The local credential vault is unavailable."
        ) from error
    return CredentialMutationResponse(provider=provider, status="configured", source="keychain")


@router.delete("/{provider}/credential", response_model=CredentialMutationResponse)
def delete_credential(
    provider: ProviderName, request: Request, services: Services
) -> CredentialMutationResponse:
    _authorize_secret_mutation(request)
    if services.credentials.resolve(provider).source == "environment":
        raise ApiError(
            409,
            "environment_credential_read_only",
            "Environment credentials must be removed outside Radar.",
        )
    try:
        services.credentials.delete(provider)
    except SecretStoreUnavailableError as error:
        raise ApiError(
            503, "credential_store_unavailable", "The local credential vault is unavailable."
        ) from error
    return CredentialMutationResponse(provider=provider, status="removed")


@router.post("/{provider}/test", response_model=CredentialMutationResponse)
async def test_provider(
    provider: ProviderName, body: TestProviderRequest, services: Services
) -> CredentialMutationResponse:
    try:
        adapter = ProviderRegistry(services.credentials).assistant(provider, body.model.strip())
        found_text = False
        async for event in adapter.stream(
            messages=[{"role": "user", "content": "Reply with exactly OK."}],
            tools=[],
            max_output_tokens=8,
        ):
            found_text = found_text or getattr(event, "text", None) is not None
        if not found_text:
            raise RuntimeError("provider returned no text")
    except ProviderCredentialError as error:
        raise ApiError(409, "credential_missing", "This provider has no configured key.") from error
    except Exception as error:
        raise ApiError(502, "provider_connection_failed", "The provider test failed.") from error
    source = services.credentials.resolve(provider).source
    return CredentialMutationResponse(provider=provider, status="connected", source=source)


def _authorize_secret_mutation(request: Request) -> None:
    if request.headers.get("X-Radar-Secret-Intent") != "update-provider-credential":
        raise ApiError(403, "secret_intent_required", "Credential update intent is required.")
    origin = request.headers.get("Origin")
    allowed: tuple[str, ...] = request.app.state.allowed_origins
    if origin is not None and origin not in allowed:
        raise ApiError(403, "origin_forbidden", "This origin cannot change credentials.")
