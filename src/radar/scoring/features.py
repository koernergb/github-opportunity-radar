"""Normalized feature extraction for deterministic opportunity scoring."""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from radar.db.models import Issue, IssueFilterResult, Repository, RepositoryMetricSnapshot
from radar.settings import RadarConfig


@dataclass(frozen=True)
class FitResult:
    value: float
    components: dict[str, float]
    missing: tuple[str, ...]
    penalties: dict[str, float]


def personal_fit(
    analysis: dict[str, Any], repository: Repository, config: RadarConfig
) -> FitResult:
    """Combine known fit evidence without treating unknown language as zero."""
    components = {
        "interest_match": _unit(analysis["interest_fit"]),
        "career_relevance": _unit(analysis["career_relevance"]),
        "task_type_preference": config.user.preferred_task_types.get(
            str(analysis["task_type"]), 0.5
        ),
        "domain_match": _term_match(
            analysis.get("required_domains", []), config.user.interests + config.user.career_targets
        ),
    }
    missing: list[str] = []
    if repository.primary_language is None:
        missing.append("repository_language")
    else:
        components["language_proficiency"] = config.user.languages.get(
            repository.primary_language.casefold(), 0.5
        )
    penalties: dict[str, float] = {}
    semantic_text = " ".join(
        [
            str(analysis.get("task_type", "")),
            *analysis.get("required_domains", []),
            *analysis.get("required_skills", []),
            str(analysis.get("short_summary", "")),
        ]
    ).casefold()
    avoid_matches = sum(term.casefold() in semantic_text for term in config.user.avoid)
    if avoid_matches:
        penalties["avoid_match"] = min(0.6, 0.2 * avoid_matches)
    hardware_required = bool(analysis.get("hardware_required"))
    if hardware_required:
        notes = str(analysis.get("hardware_notes") or "").casefold()
        available = any(item.casefold() in notes for item in config.user.available_hardware)
        components["hardware_availability"] = 1.0 if available else 0.25
    value = sum(components.values()) / len(components)
    value *= 1 - sum(penalties.values())
    return FitResult(_unit(value), components, tuple(missing), penalties)


def timeliness(issue: Issue, now: datetime) -> float:
    """Decay issue freshness smoothly with a 90-day half-life."""
    age_days = max(0.0, (now - issue.github_updated_at).total_seconds() / 86_400)
    return math.exp(-math.log(2) * age_days / 90)


def issue_completeness(issue: Issue) -> float:
    values = [bool(issue.title.strip()), len((issue.body or "").strip()) >= 40]
    return sum(values) / len(values)


def timeline_completeness(issue: Issue, stored_comment_count: int) -> float:
    if issue.comment_count == 0:
        return 1.0
    return min(1.0, stored_comment_count / issue.comment_count)


def filter_rule_evidence(result: IssueFilterResult | None, code: str) -> dict[str, Any]:
    if result is None:
        return {}
    rules = result.evidence.get("rules", [])
    return next(
        (rule.get("evidence", {}) for rule in rules if rule.get("code") == code),
        {},
    )


def repository_prior(
    metric: RepositoryMetricSnapshot | None, config: RadarConfig
) -> tuple[float, float, int]:
    if metric is None:
        return config.scoring.global_merge_prior, 0.25, 0
    return metric.shrunk_merge_rate, metric.data_confidence, metric.external_pr_count


def _term_match(required: list[str], preferred: tuple[str, ...]) -> float:
    if not required:
        return 0.5
    preferred_tokens = set(re.findall(r"[a-z0-9]+", " ".join(preferred).casefold()))
    matches = [
        bool(set(re.findall(r"[a-z0-9]+", term.casefold())) & preferred_tokens) for term in required
    ]
    return sum(matches) / len(matches)


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
