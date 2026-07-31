"""Stable human-readable projections of persisted score explanations."""

from typing import Any

from radar.db.models import IssueScore


def explain_score(score: IssueScore) -> dict[str, Any]:
    """Return the complete versioned explanation without recomputing conclusions."""
    return {
        "score_version": score.score_version,
        "profile_hash": score.profile_hash,
        "total": score.total,
        "confidence": score.confidence,
        "merge_estimate": score.merge_estimate,
        "merge_band": score.merge_band,
        "effort_midpoint": score.effort_midpoint,
        "payoff": score.payoff,
        "fit": score.fit,
        "risk": score.risk,
        "features": score.feature_values,
        "explanation": score.explanation,
    }
