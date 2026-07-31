"""Read-only digest projections built from persisted derived conclusions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from radar.db.models import Issue, IssueAnalysis, Repository
from radar.scoring.engine import SCORE_VERSION, rank_scores
from radar.settings import RadarConfig


@dataclass(frozen=True)
class DigestItem:
    rank: int
    repository: str
    number: int
    title: str
    url: str
    score: float
    confidence: float
    low_confidence: bool
    effort_low_hours: float
    effort_high_hours: float
    merge_estimate: float
    merge_band: str
    history_sample: int
    why_now: tuple[str, ...]
    positive_signals: tuple[str, ...]
    risks: tuple[str, ...]
    suggested_first_move: str
    investigation_steps: tuple[str, ...]
    issue_updated_at: str
    analyzed_at: str
    scored_at: str


@dataclass(frozen=True)
class Digest:
    generated_at: datetime
    items: tuple[DigestItem, ...]
    empty_message: str | None = None


def build_digest(
    session: Session,
    config: RadarConfig,
    *,
    generated_at: datetime,
    limit: int | None = None,
) -> Digest:
    """Select current-profile eligible scores and project deterministic digest rows."""
    bounded_limit = min(limit or config.scoring.digest_size, config.scoring.digest_size)
    scores = rank_scores(
        session,
        limit=bounded_limit,
        score_version=SCORE_VERSION,
        profile_hash=config.profile_hash,
    )
    items: list[DigestItem] = []
    for rank, score in enumerate(scores, start=1):
        issue = session.get(Issue, score.issue_id)
        assert issue is not None
        repository = session.get(Repository, issue.repository_id)
        assert repository is not None
        analysis = session.get(IssueAnalysis, score.analysis_id) if score.analysis_id else None
        semantic: dict[str, Any] = analysis.analysis_json if analysis is not None else {}
        prior = score.explanation.get("repository_prior", {})
        items.append(
            DigestItem(
                rank=rank,
                repository=repository.full_name,
                number=issue.number,
                title=issue.title,
                url=issue.url,
                score=score.total,
                confidence=score.confidence,
                low_confidence=score.confidence < config.scoring.minimum_confidence_to_surface,
                effort_low_hours=float(semantic.get("effort_low_hours", score.effort_midpoint)),
                effort_high_hours=float(semantic.get("effort_high_hours", score.effort_midpoint)),
                merge_estimate=score.merge_estimate,
                merge_band=score.merge_band,
                history_sample=int(prior.get("sample_size", 0)),
                why_now=_why_now(score.explanation),
                positive_signals=tuple(semantic.get("positive_signals", [])),
                risks=tuple(semantic.get("risks", [])),
                suggested_first_move=str(
                    semantic.get("suggested_first_move", "Investigate scope.")
                ),
                investigation_steps=tuple(semantic.get("investigation_steps", [])),
                issue_updated_at=issue.github_updated_at.isoformat(),
                analyzed_at=analysis.analyzed_at.isoformat() if analysis else "unknown",
                scored_at=score.scored_at.isoformat(),
            )
        )
    return Digest(
        generated_at=generated_at,
        items=tuple(items),
        empty_message=None
        if items
        else "No eligible scored opportunities. Run sync, filter, analyze, and score first.",
    )


def _why_now(explanation: dict[str, Any]) -> tuple[str, ...]:
    contributions = explanation.get("payoff_contributions", {})
    positive = sorted(contributions.items(), key=lambda item: (-float(item[1]), item[0]))
    return tuple(f"{name.replace('_', ' ')}: {float(value):.2f}" for name, value in positive[:3])
