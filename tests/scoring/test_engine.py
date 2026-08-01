"""Deterministic scoring formulas, explanations, persistence, and golden ranking."""

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from radar.analysis.fallback import deterministic_fallback
from radar.clock import Clock
from radar.db.models import (
    Base,
    Issue,
    IssueAnalysis,
    IssueFilterResult,
    Repository,
    RepositoryMetricSnapshot,
    UserFeedback,
)
from radar.scoring.engine import calculate_score, rank_scores, score_issue
from radar.scoring.explanations import explain_score
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


def _config() -> RadarConfig:
    path = Path(__file__).resolve().parents[2] / "config/profile.example.yaml"
    return load_config(path)


def _repository(name: str = "repo") -> Repository:
    return Repository(
        github_id=sum((index + 1) * ord(character) for index, character in enumerate(name)),
        node_id=f"R_{name}",
        owner="owner",
        name=name,
        full_name=f"owner/{name}",
        url=f"https://github.com/owner/{name}",
        description="Python performance tools",
        default_branch="main",
        primary_language="Python",
        stars=100,
        forks=10,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=NOW,
        github_created_at=NOW - timedelta(days=1_000),
        github_updated_at=NOW,
        last_synced_at=NOW,
        raw_json={},
    )


def _issue(repository: Repository, number: int, title: str) -> Issue:
    return Issue(
        repository_id=repository.id,
        github_id=10_000 + number,
        node_id=f"I_{number}",
        number=number,
        title=title,
        body="Clear reproduction, acceptance criteria, and test plan for this bounded change.",
        state="open",
        state_reason=None,
        url=f"https://github.com/{repository.full_name}/issues/{number}",
        author_login="author",
        author_association="CONTRIBUTOR",
        locked=False,
        comment_count=0,
        github_created_at=NOW - timedelta(days=2),
        github_updated_at=NOW,
        github_closed_at=None,
        last_seen_at=NOW,
        inaccessible_at=None,
        is_pull_request=False,
        raw_json={},
    )


def _analysis(issue: Issue, config: RadarConfig, **updates: object) -> IssueAnalysis:
    semantic = deterministic_fallback({}, config).model_copy(
        update={
            "task_type": "performance",
            "effort_low_hours": 2.0,
            "effort_high_hours": 6.0,
            "effort_confidence": 0.9,
            "ambiguity": 0.1,
            "design_dependency": 0.1,
            "environment_difficulty": 0.1,
            "acceptance_criteria_clarity": 0.9,
            "test_plan_clarity": 0.9,
            "technical_depth": 0.8,
            "project_impact": 0.8,
            "learning_value": 0.8,
            "portfolio_explainability": 0.8,
            "visibility": 0.7,
            "interest_fit": 0.9,
            "career_relevance": 0.9,
            "maintainer_intent": 0.8,
            "maintainer_intent_confidence": 0.9,
            "overall_confidence": 0.9,
            **updates,
        }
    )
    return IssueAnalysis(
        issue_id=issue.id,
        content_hash=f"{issue.number:064x}",
        schema_version=semantic.schema_version,
        prompt_version="prompt-v1",
        provider="openai",
        model_version="test-model",
        status="success",
        analysis_json=semantic.model_dump(mode="json"),
        raw_response=None,
        confidence=semantic.overall_confidence,
        usage_json={},
        estimated_cost_usd=None,
        analyzed_at=NOW,
    )


def _metric(repository: Repository) -> RepositoryMetricSnapshot:
    return RepositoryMetricSnapshot(
        repository_id=repository.id,
        metric_version="repository_health_v1",
        window_start=NOW - timedelta(days=365),
        window_end=NOW,
        external_pr_count=20,
        merged_external_count=14,
        external_merge_rate=0.7,
        shrunk_merge_rate=0.6,
        closed_unmerged_rate=0.2,
        median_first_response_hours=4.0,
        median_merge_hours=48.0,
        p75_merge_hours=96.0,
        active_maintainer_count=3,
        recent_activity=0.8,
        documentation_score=1.0,
        data_confidence=0.9,
        metrics_json={},
        calculated_at=NOW,
    )


def _filter(issue: Issue, *codes: str) -> IssueFilterResult:
    status = "excluded" if "active_linked_pr" in codes else "warning" if codes else "eligible"
    return IssueFilterResult(
        issue_id=issue.id,
        filter_version="deterministic_filters_v1",
        status=status,
        reason_codes=list(codes),
        evidence={
            "rules": [
                {"action": "exclude", "code": code, "message": code, "evidence": {}}
                for code in codes
            ]
        },
        evaluated_at=NOW,
    )


def _calculate(
    issue: Issue,
    repository: Repository,
    analysis: IssueAnalysis,
    config: RadarConfig,
    *,
    metric: RepositoryMetricSnapshot | None,
    filter_result: IssueFilterResult | None,
):
    return calculate_score(
        issue=issue,
        repository=repository,
        analysis=analysis,
        metric=metric,
        filter_result=filter_result,
        stored_comment_count=0,
        config=config,
        clock=FixedClock(),
    )


def test_score_is_bounded_monotonic_and_fully_explainable() -> None:
    config = _config()
    repository = _repository()
    issue = _issue(repository, 1, "Performance improvement")
    strong = _analysis(issue, config)
    weak = _analysis(
        issue,
        config,
        effort_low_hours=12.0,
        effort_high_hours=24.0,
        ambiguity=0.9,
        design_dependency=0.9,
        technical_depth=0.2,
        project_impact=0.2,
        career_relevance=0.2,
        maintainer_intent=0.1,
    )
    metric = _metric(repository)
    filter_result = _filter(issue)

    strong_score = _calculate(
        issue, repository, strong, config, metric=metric, filter_result=filter_result
    )
    weak_score = _calculate(
        issue, repository, weak, config, metric=metric, filter_result=filter_result
    )

    assert 0 <= weak_score.total < strong_score.total <= 100
    assert strong_score.merge_estimate > weak_score.merge_estimate
    assert strong_score.risk < weak_score.risk
    explanation = strong_score.explanation
    assert sum(explanation["payoff_contributions"].values()) == pytest.approx(strong_score.payoff)
    merge = explanation["merge"]
    assert merge["prior_logit"] + sum(merge["contributions"].values()) == pytest.approx(
        merge["final_logit"]
    )
    expected = max(
        0,
        min(
            100,
            explanation["calibrated_base"]
            - explanation["risk_penalty"]
            - explanation["uncertainty_penalty"],
        ),
    )
    assert strong_score.total == pytest.approx(expected)


def test_missing_repository_metrics_lowers_confidence() -> None:
    config = _config()
    repository = _repository()
    issue = _issue(repository, 1, "Task")
    analysis = _analysis(issue, config)
    filter_result = _filter(issue)

    complete = _calculate(
        issue, repository, analysis, config, metric=_metric(repository), filter_result=filter_result
    )
    missing = _calculate(
        issue, repository, analysis, config, metric=None, filter_result=filter_result
    )

    assert missing.confidence < complete.confidence
    assert "repository_metrics" in missing.explanation["missing_data"]


def test_feedback_modifier_is_versioned_visible_and_monotonic() -> None:
    config = _config()
    repository = _repository()
    issue = _issue(repository, 1, "Task")
    analysis = _analysis(issue, config)
    metric = _metric(repository)
    filter_result = _filter(issue)
    feedback = UserFeedback(
        issue_id=issue.id,
        status="too_hard",
        note=None,
        pr_url=None,
        created_at=NOW,
    )

    baseline = _calculate(
        issue, repository, analysis, config, metric=metric, filter_result=filter_result
    )
    modified = calculate_score(
        issue=issue,
        repository=repository,
        analysis=analysis,
        metric=metric,
        filter_result=filter_result,
        stored_comment_count=0,
        config=config,
        clock=FixedClock(),
        feedback=feedback,
    )

    modifier = modified.explanation["feedback_modifier"]
    assert modified.total == pytest.approx(baseline.total * 0.75)
    assert modifier["version"] == "preference_modifiers_v1"
    assert modifier["status"] == "too_hard"
    assert modifier["score_before"] == baseline.total
    assert modifier["score_after"] == modified.total


def test_persistence_is_deterministic_and_golden_ranking_excludes_active_pr() -> None:
    config = _config()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = _repository("golden")
        session.add(repository)
        session.flush()
        session.add(_metric(repository))
        fixtures = [
            (1, "ideal", {}, ()),
            (2, "easy docs", {"technical_depth": 0.15, "project_impact": 0.2}, ()),
            (
                3,
                "architecture",
                {"design_dependency": 0.95, "ambiguity": 0.9, "technical_depth": 1.0},
                ("needs_design",),
            ),
            (4, "claimed", {"likely_claimed": True, "claim_confidence": 0.95}, ("soft_claim",)),
            (5, "active pr", {}, ("active_linked_pr",)),
        ]
        issues: dict[int, Issue] = {}
        for number, title, updates, codes in fixtures:
            issue = _issue(repository, number, title)
            session.add(issue)
            session.flush()
            issues[number] = issue
            session.add_all([_analysis(issue, config, **updates), _filter(issue, *codes)])
        session.commit()

        first_scores = [
            score_issue(session, issue_id=issue.id, config=config, clock=FixedClock())
            for issue in issues.values()
        ]
        session.commit()
        second_scores = [
            score_issue(session, issue_id=issue.id, config=config, clock=FixedClock())
            for issue in issues.values()
        ]
        session.commit()
        ranked = rank_scores(session)

        assert [score.id for score in first_scores] == [score.id for score in second_scores]
        ranked_numbers = [session.get(Issue, score.issue_id).number for score in ranked]  # type: ignore[union-attr]
        assert ranked_numbers == [1, 4, 2, 3]
        assert 5 not in ranked_numbers
        active_score = next(score for score in first_scores if score.issue_id == issues[5].id)
        assert active_score.total == 0
        assert explain_score(active_score)["explanation"]["ranking_eligible"] is False
        assert all(math.isfinite(score.total) and 0 <= score.total <= 100 for score in first_scores)
