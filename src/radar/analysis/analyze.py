"""Cache-aware semantic-analysis orchestration with deterministic failure behavior."""

from uuid import UUID

from sqlalchemy.orm import Session

from radar.analysis.cache import find_cached_analysis
from radar.analysis.context import build_analysis_context, semantic_content_hash
from radar.analysis.fallback import deterministic_fallback
from radar.analysis.openai_provider import OpenAIAnalysisProvider
from radar.analysis.prompts import load_system_prompt
from radar.analysis.provider import AnalysisProvider, ProviderResult
from radar.analysis.schemas import ANALYSIS_SCHEMA_VERSION
from radar.clock import Clock
from radar.db.models import IssueAnalysis
from radar.settings import RadarConfig


def analyze_issue(
    session: Session,
    *,
    issue_id: UUID,
    config: RadarConfig,
    clock: Clock,
    api_key: str | None = None,
    provider: AnalysisProvider | None = None,
    fallback_only: bool = False,
) -> IssueAnalysis:
    """Analyze one issue, reusing exact cache entries and persisting the outcome."""
    prompt = load_system_prompt()
    context = build_analysis_context(session, issue_id, config)
    content_hash = semantic_content_hash(context, config=config, prompt=prompt)
    provider_name = provider.provider_name if provider is not None else config.llm.provider
    model_version = provider.model_version if provider is not None else config.llm.model
    cached = find_cached_analysis(
        session,
        issue_id=issue_id,
        content_hash=content_hash,
        schema_version=ANALYSIS_SCHEMA_VERSION,
        prompt_version=prompt.version,
        provider=provider_name,
        model_version=model_version,
    )
    if cached is not None:
        return cached

    active_provider = provider
    if active_provider is None and api_key is not None and not fallback_only:
        active_provider = OpenAIAnalysisProvider(
            api_key=api_key,
            model=config.llm.model,
        )

    result: ProviderResult | None = None
    errors: list[str] = []
    if active_provider is not None and not fallback_only:
        repair_feedback: str | None = None
        for _attempt in range(2):
            try:
                result = active_provider.analyze(
                    context_json=context.canonical_json,
                    system_prompt=prompt.text,
                    repair_feedback=repair_feedback,
                )
                break
            except Exception as error:  # provider boundary converts every failure to fallback
                repair_feedback = _safe_error(error)
                errors.append(repair_feedback)

    if result is None:
        fallback = deterministic_fallback(context.payload, config)
        result = ProviderResult(
            analysis=fallback,
            model_version=model_version,
            usage={"provider_attempts": len(errors), "errors": errors},
        )
        status = "fallback"
    else:
        status = "success"
        result = ProviderResult(
            analysis=result.analysis,
            model_version=result.model_version,
            raw_response=result.raw_response,
            usage={**result.usage, "provider_attempts": len(errors) + 1},
            estimated_cost_usd=result.estimated_cost_usd,
        )

    persisted = IssueAnalysis(
        issue_id=issue_id,
        content_hash=content_hash,
        schema_version=ANALYSIS_SCHEMA_VERSION,
        prompt_version=prompt.version,
        provider=provider_name,
        model_version=model_version,
        status=status,
        analysis_json=result.analysis.model_dump(mode="json"),
        raw_response=result.raw_response,
        confidence=result.analysis.overall_confidence,
        usage_json=result.usage,
        estimated_cost_usd=result.estimated_cost_usd,
        analyzed_at=clock.now(),
    )
    session.add(persisted)
    session.flush()
    return persisted


def _safe_error(error: Exception) -> str:
    """Keep repair/persistence diagnostics bounded and free of arbitrary repr output."""
    message = str(error).replace("\n", " ").strip()
    return f"{type(error).__name__}: {message[:500]}"
