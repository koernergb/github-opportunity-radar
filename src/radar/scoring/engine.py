"""Versioned deterministic scoring, persistence, ranking, and explanations."""

import math
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.clock import Clock
from radar.db.models import (
    Issue,
    IssueAnalysis,
    IssueComment,
    IssueFilterResult,
    IssueScore,
    Repository,
    RepositoryMetricSnapshot,
    UserFeedback,
)
from radar.scoring.features import (
    filter_rule_evidence,
    issue_completeness,
    personal_fit,
    repository_prior,
    timeline_completeness,
    timeliness,
)
from radar.settings import RadarConfig

SCORE_VERSION = "v1_heuristic"
FEEDBACK_MODIFIER_VERSION = "preference_modifiers_v1"
_FEEDBACK_MULTIPLIERS = {
    "interested": 1.05,
    "too_hard": 0.75,
    "too_vague": 0.80,
    "low_value": 0.70,
    "bad_repository_fit": 0.0,
    "already_claimed": 0.50,
    "not_enough_time": 0.65,
    "investigating": 1.08,
    "commented": 1.08,
    "implementation_started": 1.10,
    "pr_opened": 1.10,
    "abandoned": 0.50,
    "rejected": 0.0,
}


@dataclass(frozen=True)
class ScoreCalculation:
    total: float
    raw_value: float
    merge_estimate: float
    merge_band: str
    effort_midpoint: float
    payoff: float
    fit: float
    risk: float
    confidence: float
    features: dict[str, Any]
    explanation: dict[str, Any]


def calculate_score(
    *,
    issue: Issue,
    repository: Repository,
    analysis: IssueAnalysis,
    metric: RepositoryMetricSnapshot | None,
    filter_result: IssueFilterResult | None,
    stored_comment_count: int,
    config: RadarConfig,
    clock: Clock,
    feedback: UserFeedback | None = None,
) -> ScoreCalculation:
    """Calculate a bounded score and retain every term used to derive it."""
    semantic = analysis.analysis_json
    freshness = timeliness(issue, clock.now())
    payoff_features = {
        "career_relevance": float(semantic["career_relevance"]),
        "technical_depth": float(semantic["technical_depth"]),
        "project_impact": float(semantic["project_impact"]),
        "portfolio_explainability": float(semantic["portfolio_explainability"]),
        "learning_value": float(semantic["learning_value"]),
        "visibility": float(semantic["visibility"]),
        "timeliness": freshness,
    }
    weights = config.scoring.payoff_weights.model_dump()
    payoff_contributions = {
        name: payoff_features[name] * float(weight) for name, weight in weights.items()
    }
    payoff = sum(payoff_contributions.values())
    fit_result = personal_fit(semantic, repository, config)
    prior, metric_confidence, history_sample = repository_prior(metric, config)
    reason_codes = set(filter_result.reason_codes if filter_result is not None else [])
    maintainer_activity = metric.recent_activity if metric and metric.recent_activity else 0.0
    documentation = metric.documentation_score if metric and metric.documentation_score else 0.0
    claim_probability = float(semantic["claim_confidence"]) if semantic["likely_claimed"] else 0.0
    active_linked_pr = "active_linked_pr" in reason_codes
    stale_without_maintainer = "stale" in reason_codes and maintainer_activity == 0
    merge_terms = {
        "explicit_pr_welcome": 1.20 * float(semantic["maintainer_intent"]),
        "recent_maintainer_activity": 0.55 * maintainer_activity,
        "acceptance_criteria_clarity": 0.50 * float(semantic["acceptance_criteria_clarity"]),
        "test_plan_clarity": 0.35 * float(semantic["test_plan_clarity"]),
        "contribution_documentation": 0.25 * documentation,
        "unresolved_design": -1.40 * float(semantic["design_dependency"]),
        "active_linked_pr": -1.60 if active_linked_pr else 0.0,
        "claim_probability": -1.10 * claim_probability,
        "stale_without_maintainer": -0.80 if stale_without_maintainer else 0.0,
        "public_api_risk": -0.60 if "public_api_change" in reason_codes else 0.0,
    }
    prior_logit = _logit(prior)
    merge_logit = prior_logit + sum(merge_terms.values())
    merge_estimate = _logistic(merge_logit)
    ambiguity = float(semantic["ambiguity"])
    environment = float(semantic["environment_difficulty"])
    effort_low = float(semantic["effort_low_hours"])
    effort_high = float(semantic["effort_high_hours"])
    effort_midpoint = math.sqrt(effort_low * effort_high)
    effort_feasibility = min(1.0, config.user.max_estimated_hours / effort_midpoint)
    completion_probability = (
        fit_result.value * (1 - 0.45 * ambiguity) * (1 - 0.35 * environment) * effort_feasibility
    )
    stale_evidence = 1.0 if "stale" in reason_codes else 0.0
    risk_terms = {
        "ambiguity": 0.30 * ambiguity,
        "design_dependency": 0.25 * float(semantic["design_dependency"]),
        "claim_probability": 0.20 * claim_probability,
        "environment_difficulty": 0.15 * environment,
        "stale_evidence": 0.10 * stale_evidence,
    }
    risk = sum(risk_terms.values())
    confidence_factors = {
        "analysis": float(semantic["overall_confidence"]),
        "repository_metrics": metric_confidence,
        "issue_completeness": issue_completeness(issue),
        "timeline_comments": timeline_completeness(issue, stored_comment_count),
        "effort": float(semantic["effort_confidence"]),
    }
    confidence = _geometric_mean(confidence_factors.values())
    raw_value = payoff * fit_result.value * merge_estimate * completion_probability
    effort_cost = (effort_midpoint + 2) ** 0.65
    base = 100 * raw_value / effort_cost
    risk_penalty = 20 * risk
    uncertainty_penalty = 10 * (1 - confidence)
    before_feedback = _clamp(
        0.0, 100.0, calibrated_scale(base) - risk_penalty - uncertainty_penalty
    )
    feedback_multiplier = _FEEDBACK_MULTIPLIERS.get(feedback.status, 1.0) if feedback else 1.0
    total = _clamp(0.0, 100.0, before_feedback * feedback_multiplier)
    ranking_eligible = filter_result is not None and filter_result.status != "excluded"
    if active_linked_pr:
        ranking_eligible = False
        total = 0.0
    if feedback is not None and feedback.status in {"bad_repository_fit", "rejected"}:
        ranking_eligible = False
    missing_data = list(fit_result.missing)
    if metric is None:
        missing_data.append("repository_metrics")
    if filter_result is None:
        missing_data.append("deterministic_filter")
    features = {
        "payoff": payoff_features,
        "fit": fit_result.components,
        "completion_probability": completion_probability,
        "effort_feasibility": effort_feasibility,
        "confidence_factors": confidence_factors,
        "reason_codes": sorted(reason_codes),
    }
    explanation = {
        "kind": "heuristic_estimate_not_calibrated_probability",
        "ranking_eligible": ranking_eligible,
        "versions": {
            "score": SCORE_VERSION,
            "analysis_schema": analysis.schema_version,
            "metric": metric.metric_version if metric else None,
            "filter": filter_result.filter_version if filter_result else None,
            "feedback_modifier": FEEDBACK_MODIFIER_VERSION,
        },
        "data_freshness": {
            "issue_updated_at": issue.github_updated_at.isoformat(),
            "analysis_at": analysis.analyzed_at.isoformat(),
            "metric_at": metric.calculated_at.isoformat() if metric else None,
        },
        "repository_prior": {"value": prior, "sample_size": history_sample},
        "payoff_weights": weights,
        "payoff_contributions": payoff_contributions,
        "fit_penalties": fit_result.penalties,
        "merge": {
            "prior_logit": prior_logit,
            "contributions": merge_terms,
            "final_logit": merge_logit,
        },
        "risk_contributions": risk_terms,
        "effort_cost": effort_cost,
        "base_before_penalties": base,
        "calibrated_base": calibrated_scale(base),
        "risk_penalty": risk_penalty,
        "uncertainty_penalty": uncertainty_penalty,
        "feedback_modifier": {
            "version": FEEDBACK_MODIFIER_VERSION,
            "status": feedback.status if feedback else None,
            "feedback_id": str(feedback.id) if feedback else None,
            "multiplier": feedback_multiplier,
            "score_before": before_feedback,
            "score_after": total,
        },
        "missing_data": missing_data,
        "filter_evidence": {
            code: filter_rule_evidence(filter_result, code) for code in sorted(reason_codes)
        },
    }
    return ScoreCalculation(
        total=total,
        raw_value=raw_value,
        merge_estimate=merge_estimate,
        merge_band=merge_band(merge_estimate),
        effort_midpoint=effort_midpoint,
        payoff=payoff,
        fit=fit_result.value,
        risk=risk,
        confidence=confidence,
        features=features,
        explanation=explanation,
    )


def score_issue(
    session: Session,
    *,
    issue_id: UUID,
    config: RadarConfig,
    clock: Clock,
) -> IssueScore:
    """Calculate and upsert the current profile/version score for one issue."""
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise ValueError(f"issue not found: {issue_id}")
    repository = session.get(Repository, issue.repository_id)
    assert repository is not None
    analysis = session.scalar(
        select(IssueAnalysis)
        .where(IssueAnalysis.issue_id == issue.id)
        .order_by(IssueAnalysis.analyzed_at.desc())
    )
    if analysis is None:
        raise ValueError(f"analysis not found for issue: {issue_id}")
    metric = session.scalar(
        select(RepositoryMetricSnapshot)
        .where(RepositoryMetricSnapshot.repository_id == repository.id)
        .order_by(RepositoryMetricSnapshot.calculated_at.desc())
    )
    filter_result = session.scalar(
        select(IssueFilterResult)
        .where(IssueFilterResult.issue_id == issue.id)
        .order_by(IssueFilterResult.evaluated_at.desc())
    )
    feedback = session.scalar(
        select(UserFeedback)
        .where(UserFeedback.issue_id == issue.id)
        .order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())
    )
    stored_comments = session.scalar(
        select(func.count()).select_from(IssueComment).where(IssueComment.issue_id == issue.id)
    )
    calculation = calculate_score(
        issue=issue,
        repository=repository,
        analysis=analysis,
        metric=metric,
        filter_result=filter_result,
        stored_comment_count=stored_comments or 0,
        config=config,
        clock=clock,
        feedback=feedback,
    )
    score = session.scalar(
        select(IssueScore).where(
            IssueScore.issue_id == issue.id,
            IssueScore.score_version == SCORE_VERSION,
            IssueScore.profile_hash == config.profile_hash,
        )
    )
    values = asdict(calculation)
    if score is None:
        score = IssueScore(
            issue_id=issue.id,
            metric_snapshot_id=metric.id if metric else None,
            analysis_id=analysis.id,
            score_version=SCORE_VERSION,
            profile_hash=config.profile_hash,
            total=calculation.total,
            raw_value=calculation.raw_value,
            merge_estimate=calculation.merge_estimate,
            merge_band=calculation.merge_band,
            effort_midpoint=calculation.effort_midpoint,
            payoff=calculation.payoff,
            fit=calculation.fit,
            risk=calculation.risk,
            confidence=calculation.confidence,
            feature_values=calculation.features,
            explanation=calculation.explanation,
            scored_at=clock.now(),
        )
        session.add(score)
    else:
        for field in (
            "total",
            "raw_value",
            "merge_estimate",
            "merge_band",
            "effort_midpoint",
            "payoff",
            "fit",
            "risk",
            "confidence",
        ):
            setattr(score, field, values[field])
        score.metric_snapshot_id = metric.id if metric else None
        score.analysis_id = analysis.id
        score.feature_values = calculation.features
        score.explanation = calculation.explanation
        score.scored_at = clock.now()
    session.flush()
    return score


def rank_scores(
    session: Session,
    *,
    limit: int | None = None,
    score_version: str | None = None,
    profile_hash: str | None = None,
) -> list[IssueScore]:
    """Rank only eligible scores with deterministic repository/issue tie breaks."""
    statement = select(IssueScore)
    if score_version is not None:
        statement = statement.where(IssueScore.score_version == score_version)
    if profile_hash is not None:
        statement = statement.where(IssueScore.profile_hash == profile_hash)
    scores = session.scalars(statement).all()
    eligible = [score for score in scores if score.explanation.get("ranking_eligible") is True]

    def ordering(score: IssueScore) -> tuple[float, float, str, int]:
        issue = session.get(Issue, score.issue_id)
        assert issue is not None
        repository = session.get(Repository, issue.repository_id)
        assert repository is not None
        return (-score.total, -score.confidence, repository.full_name, issue.number)

    ranked = sorted(eligible, key=ordering)
    return ranked if limit is None else ranked[:limit]


def calibrated_scale(base: float) -> float:
    """Version-one monotonic display calibration against bounded synthetic fixtures."""
    return 100 * (1 - math.exp(-max(0.0, base) / 20))


def merge_band(value: float) -> str:
    if value < 0.20:
        return "very low"
    if value < 0.40:
        return "low"
    if value < 0.60:
        return "moderate"
    if value < 0.80:
        return "high"
    return "very high"


def _geometric_mean(values: Any) -> float:
    normalized = [max(1e-9, min(1.0, float(value))) for value in values]
    return math.prod(normalized) ** (1 / len(normalized))


def _logit(value: float) -> float:
    bounded = _clamp(1e-6, 1 - 1e-6, value)
    return math.log(bounded / (1 - bounded))


def _logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def _clamp(low: float, high: float, value: float) -> float:
    return max(low, min(high, value))
