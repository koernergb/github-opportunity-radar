"""Digest selection, rendering, confidence, and golden Markdown tests."""

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from radar.analysis.fallback import deterministic_fallback
from radar.db.models import Base, Issue, IssueAnalysis, IssueScore, Repository
from radar.digest.markdown import render_markdown
from radar.digest.models import build_digest
from radar.digest.terminal import render_terminal
from radar.scoring.engine import SCORE_VERSION
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


def _config() -> RadarConfig:
    path = Path(__file__).resolve().parents[2] / "config/profile.example.yaml"
    return load_config(path)


def _add_candidate(
    session: Session,
    config: RadarConfig,
    *,
    repository_name: str,
    number: int,
    confidence: float,
    eligible: bool,
) -> None:
    repository = Repository(
        github_id=number,
        node_id=f"R_{number}",
        owner="owner",
        name=repository_name,
        full_name=f"owner/{repository_name}",
        url=f"https://github.com/owner/{repository_name}",
        description="Repository",
        default_branch="main",
        primary_language="Python",
        stars=1,
        forks=0,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=NOW,
        github_created_at=NOW,
        github_updated_at=NOW,
        last_synced_at=NOW,
        raw_json={},
    )
    session.add(repository)
    session.flush()
    issue = Issue(
        repository_id=repository.id,
        github_id=100 + number,
        node_id=f"I_{number}",
        number=number,
        title=f"Candidate {number}",
        body="Clear bounded issue.",
        state="open",
        state_reason=None,
        url=f"https://github.com/owner/{repository_name}/issues/{number}",
        author_login="author",
        author_association="CONTRIBUTOR",
        locked=False,
        comment_count=0,
        github_created_at=NOW,
        github_updated_at=NOW,
        github_closed_at=None,
        last_seen_at=NOW,
        inaccessible_at=None,
        is_pull_request=False,
        raw_json={},
    )
    session.add(issue)
    session.flush()
    semantic = deterministic_fallback({}, config).model_copy(
        update={
            "effort_low_hours": 2.0,
            "effort_high_hours": 4.0,
            "positive_signals": ("Maintainer welcomed a focused change.",),
            "risks": ("Confirm the edge case.",),
            "suggested_first_move": "Write a minimal reproducer.",
            "investigation_steps": ("Locate the parser.", "Add a failing test."),
        }
    )
    analysis = IssueAnalysis(
        issue_id=issue.id,
        content_hash=f"{number:064x}",
        schema_version=semantic.schema_version,
        prompt_version="prompt-v1",
        provider="openai",
        model_version="model-v1",
        status="success",
        analysis_json=semantic.model_dump(mode="json"),
        raw_response=None,
        confidence=confidence,
        usage_json={},
        estimated_cost_usd=None,
        analyzed_at=NOW,
    )
    session.add(analysis)
    session.flush()
    session.add(
        IssueScore(
            issue_id=issue.id,
            metric_snapshot_id=None,
            analysis_id=analysis.id,
            score_version=SCORE_VERSION,
            profile_hash=config.profile_hash,
            total=50.0,
            raw_value=0.1,
            merge_estimate=0.55,
            merge_band="moderate",
            effort_midpoint=2.8,
            payoff=0.5,
            fit=0.5,
            risk=0.2,
            confidence=confidence,
            feature_values={},
            explanation={
                "ranking_eligible": eligible,
                "repository_prior": {"sample_size": 7},
                "payoff_contributions": {
                    "career_relevance": 0.22,
                    "technical_depth": 0.18,
                    "project_impact": 0.17,
                },
            },
            scored_at=NOW,
        )
    )


def test_digest_excludes_ineligible_and_resolves_ties_deterministically() -> None:
    config = _config()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _add_candidate(
            session,
            config,
            repository_name="zeta",
            number=2,
            confidence=0.8,
            eligible=True,
        )
        _add_candidate(
            session,
            config,
            repository_name="alpha",
            number=1,
            confidence=0.8,
            eligible=True,
        )
        _add_candidate(
            session,
            config,
            repository_name="excluded",
            number=3,
            confidence=1.0,
            eligible=False,
        )
        session.commit()

        digest = build_digest(session, config, generated_at=NOW)

    assert [(item.repository, item.number) for item in digest.items] == [
        ("owner/alpha", 1),
        ("owner/zeta", 2),
    ]


def test_low_confidence_is_explicit_in_terminal_and_golden_markdown() -> None:
    config = _config()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _add_candidate(
            session,
            config,
            repository_name="alpha",
            number=1,
            confidence=0.2,
            eligible=True,
        )
        session.commit()
        digest = build_digest(session, config, generated_at=NOW)

    terminal = Console(record=True, width=140)
    render_terminal(digest, terminal)
    assert "LOW" in terminal.export_text()
    rendered = render_markdown(digest)
    golden = Path(__file__).with_name("golden_digest.md").read_text(encoding="utf-8")
    assert rendered == golden
    assert "LOW CONFIDENCE" in rendered
    assert "heuristic estimate" in rendered


def test_empty_digest_explains_next_step() -> None:
    config = _config()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        digest = build_digest(session, config, generated_at=NOW)

    assert digest.items == ()
    assert "Run sync, filter, analyze, and score" in render_markdown(digest)
