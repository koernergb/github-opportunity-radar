"""Deterministic low-confidence analysis used when providers are unavailable."""

from typing import Any

from radar.analysis.schemas import IssueAnalysisOutput
from radar.settings import RadarConfig


def deterministic_fallback(context: dict[str, Any], config: RadarConfig) -> IssueAnalysisOutput:
    """Build conservative neutral features while retaining deterministic warnings."""
    filter_result = context.get("deterministic_filter") or {}
    reason_codes = set(filter_result.get("reason_codes", []))
    rules = filter_result.get("evidence", {}).get("rules", [])
    claim_evidence: dict[str, Any] = next(
        (rule.get("evidence", {}) for rule in rules if rule.get("code") == "soft_claim"),
        {},
    )
    likely_claimed = "soft_claim" in reason_codes
    hardware_required = "special_hardware" in reason_codes
    max_hours = config.user.max_estimated_hours
    return IssueAnalysisOutput(
        task_type="unknown",
        short_summary="Provider analysis unavailable; deterministic fallback used.",
        likely_work=("Investigate the issue and validate scope before implementation.",),
        required_skills=(),
        required_domains=(),
        effort_low_hours=max(1.0, max_hours * 0.25),
        effort_high_hours=max_hours,
        effort_confidence=0.1,
        ambiguity=0.5,
        design_dependency=0.5,
        environment_difficulty=0.5,
        hardware_required=hardware_required,
        hardware_notes=(
            "Deterministic filter flagged special hardware." if hardware_required else None
        ),
        reproduction_clarity=0.5,
        acceptance_criteria_clarity=0.5,
        test_plan_clarity=0.5,
        technical_depth=0.5,
        project_impact=0.5,
        learning_value=0.5,
        portfolio_explainability=0.5,
        visibility=0.5,
        interest_fit=0.5,
        career_relevance=0.5,
        maintainer_intent=0.5,
        maintainer_intent_confidence=0.1,
        likely_claimed=likely_claimed,
        claim_confidence=float(claim_evidence.get("confidence", 0.1 if likely_claimed else 0.0)),
        questions=("What scope and acceptance criteria will maintainers confirm?",),
        risks=("Semantic provider output was unavailable.",),
        positive_signals=(),
        suggested_first_move=(
            "Reproduce or inspect the relevant code path and ask a focused question."
        ),
        rationale="Neutral values avoid inventing semantic certainty when analysis fails.",
        investigation_steps=("Review issue evidence and contribution guidance.",),
        overall_confidence=0.1,
    )
