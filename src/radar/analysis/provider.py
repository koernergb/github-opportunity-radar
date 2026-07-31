"""Provider-neutral structured semantic-analysis boundary."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from radar.analysis.schemas import IssueAnalysisOutput


class AnalysisProviderError(RuntimeError):
    """A provider call failed or returned unusable structured output."""


@dataclass(frozen=True)
class ProviderResult:
    """Validated provider output plus non-semantic operational metadata."""

    analysis: IssueAnalysisOutput
    model_version: str
    raw_response: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    estimated_cost_usd: float | None = None


class AnalysisProvider(Protocol):
    """Provider contract used by the deterministic orchestration layer."""

    @property
    def provider_name(self) -> str:
        """Return the stable provider identifier."""
        ...

    @property
    def model_version(self) -> str:
        """Return the configured model identifier used for cache lookup."""
        ...

    def analyze(
        self,
        *,
        context_json: str,
        system_prompt: str,
        repair_feedback: str | None = None,
    ) -> ProviderResult:
        """Return strict structured features, optionally repairing one invalid output."""
        ...
