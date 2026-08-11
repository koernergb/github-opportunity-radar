"""Central provider registry shared by CLI, API, scheduler, and pipeline."""

from dataclasses import dataclass
from typing import Literal

from radar.analysis.openai_provider import OpenAIAnalysisProvider
from radar.analysis.provider import AnalysisProvider
from radar.assistant.provider import AssistantProvider, OpenAIResponsesProvider
from radar.llm.http_providers import (
    AnthropicAnalysisProvider,
    AnthropicAssistantProvider,
    GoogleAnalysisProvider,
    GoogleAssistantProvider,
    WaferAnalysisProvider,
    WaferAssistantProvider,
)
from radar.llm.secrets import CredentialResolver, ProviderName

LLMProvider = Literal["openai", "anthropic", "google", "wafer"]


@dataclass(frozen=True)
class ProviderCapability:
    provider: LLMProvider
    display_name: str
    structured_analysis: bool
    assistant_tools: bool
    model_suggestions: tuple[str, ...]
    notes: str | None = None


CAPABILITIES: dict[LLMProvider, ProviderCapability] = {
    "openai": ProviderCapability("openai", "OpenAI", True, True, ("gpt-5-mini",)),
    "anthropic": ProviderCapability("anthropic", "Anthropic", True, True, ()),
    "google": ProviderCapability("google", "Google Gemini", True, True, ()),
    "wafer": ProviderCapability(
        "wafer",
        "Wafer",
        True,
        True,
        ("DeepSeek-V4-Flash-0731-Fast", "GLM-5.2", "Kimi-K3"),
        "Tool support varies by served model; test the selected model before use.",
    ),
}


class ProviderCredentialError(RuntimeError):
    pass


class ProviderRegistry:
    def __init__(self, credentials: CredentialResolver) -> None:
        self._credentials = credentials

    def analysis(self, provider: ProviderName, model: str) -> AnalysisProvider:
        key = self._required_key(provider)
        if provider == "openai":
            return OpenAIAnalysisProvider(api_key=key, model=model)
        if provider == "anthropic":
            return AnthropicAnalysisProvider(api_key=key, model=model)
        if provider == "google":
            return GoogleAnalysisProvider(api_key=key, model=model)
        return WaferAnalysisProvider(api_key=key, model=model)

    def assistant(self, provider: ProviderName, model: str) -> AssistantProvider:
        key = self._required_key(provider)
        if provider == "openai":
            return OpenAIResponsesProvider(api_key=key, model=model)
        if provider == "anthropic":
            return AnthropicAssistantProvider(api_key=key, model=model)
        if provider == "google":
            return GoogleAssistantProvider(api_key=key, model=model)
        return WaferAssistantProvider(api_key=key, model=model)

    def _required_key(self, provider: ProviderName) -> str:
        value = self._credentials.resolve(provider).value
        if value is None:
            raise ProviderCredentialError(f"{provider} credential is not configured")
        return value
