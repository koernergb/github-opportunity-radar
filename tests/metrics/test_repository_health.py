"""Tests for deterministic versioned repository metrics."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from radar.db.models import (
    PullRequest,
    PullRequestReview,
    Repository,
    RepositoryDocument,
    RepositoryMetricSnapshot,
)
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.metrics.merge_history import median, percentile
from radar.metrics.priors import shrunk_rate
from radar.metrics.repository_health import METRIC_VERSION, calculate_repository_metrics
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _config() -> RadarConfig:
    return load_config(Path("config/profile.example.yaml"))


def _sessions(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    with transaction(sessions) as session:
        session.add(
            Repository(
                github_id=1,
                node_id="R_1",
                owner="owner",
                name="repo",
                full_name="owner/repo",
                url="https://github.com/owner/repo",
                description=None,
                default_branch="main",
                primary_language="Python",
                stars=1,
                forks=0,
                archived=False,
                disabled=False,
                is_fork=False,
                pushed_at=NOW,
                github_created_at=NOW - timedelta(days=500),
                github_updated_at=NOW,
                last_synced_at=NOW,
                raw_json={},
            )
        )
    return sessions


def _add_pr(
    session,
    repository_id,
    *,
    github_id: int,
    association: str | None,
    created_at: datetime,
    merged: bool,
    closed: bool,
    response_hours: float | None = None,
    merge_hours: float | None = None,
) -> PullRequest:
    pull_request = PullRequest(
        repository_id=repository_id,
        linked_issue_id=None,
        github_id=github_id,
        node_id=f"PR_{github_id}",
        number=github_id,
        title="PR",
        body=None,
        url=f"https://github.com/owner/repo/pull/{github_id}",
        author_login="author",
        author_association=association,
        state="closed" if closed else "open",
        draft=False,
        merged=merged,
        github_created_at=created_at,
        github_updated_at=NOW,
        github_closed_at=NOW if closed else None,
        merged_at=(
            created_at + timedelta(hours=merge_hours)
            if merged and merge_hours is not None
            else None
        ),
        additions=1,
        deletions=0,
        changed_files=1,
        commit_count=1,
        comment_count=0,
        review_comment_count=0,
        first_maintainer_response_at=(
            created_at + timedelta(hours=response_hours) if response_hours is not None else None
        ),
        first_maintainer_review_at=None,
        raw_json={},
    )
    session.add(pull_request)
    session.flush()
    return pull_request


def test_no_history_preserves_unknown_rates_and_global_prior(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)

    snapshots = calculate_repository_metrics(_config(), sessions, FrozenClock())

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.metric_version == METRIC_VERSION
    assert snapshot.external_pr_count == 0
    assert snapshot.external_merge_rate is None
    assert snapshot.closed_unmerged_rate is None
    assert snapshot.median_first_response_hours is None
    assert snapshot.median_merge_hours is None
    assert snapshot.shrunk_merge_rate == pytest.approx(0.45)
    assert snapshot.data_confidence == 0


def test_small_samples_shrink_and_distributions_use_defined_window(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)
    with transaction(sessions) as session:
        repository = session.scalar(select(Repository))
        assert repository is not None
        merged = _add_pr(
            session,
            repository.id,
            github_id=1,
            association="CONTRIBUTOR",
            created_at=NOW - timedelta(days=10),
            merged=True,
            closed=True,
            response_hours=2,
            merge_hours=8,
        )
        _add_pr(
            session,
            repository.id,
            github_id=2,
            association="NONE",
            created_at=NOW - timedelta(days=9),
            merged=False,
            closed=True,
            response_hours=4,
        )
        _add_pr(
            session,
            repository.id,
            github_id=3,
            association="MEMBER",
            created_at=NOW - timedelta(days=8),
            merged=True,
            closed=True,
            merge_hours=1,
        )
        _add_pr(
            session,
            repository.id,
            github_id=4,
            association="CONTRIBUTOR",
            created_at=NOW - timedelta(days=500),
            merged=True,
            closed=True,
            merge_hours=1,
        )
        session.add(
            PullRequestReview(
                pull_request_id=merged.id,
                github_id=100,
                node_id="RV_100",
                author_login="maintainer",
                author_association="MEMBER",
                state="APPROVED",
                body=None,
                submitted_at=NOW,
                raw_json={},
            )
        )
        session.add(
            RepositoryDocument(
                repository_id=repository.id,
                document_type="contributing",
                path="CONTRIBUTING.md",
                sha="abc",
                decoded_text="Contribute",
                fetched_at=NOW,
            )
        )

    snapshot = calculate_repository_metrics(_config(), sessions, FrozenClock())[0]

    assert snapshot.external_pr_count == 2
    assert snapshot.merged_external_count == 1
    assert snapshot.external_merge_rate == 0.5
    assert snapshot.closed_unmerged_rate == 0.5
    assert snapshot.shrunk_merge_rate == pytest.approx((1 + 20 * 0.45) / 22)
    assert snapshot.median_first_response_hours == 3
    assert snapshot.median_merge_hours == 8
    assert snapshot.p75_merge_hours == 8
    assert snapshot.active_maintainer_count == 1
    assert snapshot.documentation_score == 0.2


def test_repeated_fixed_window_upserts_one_deterministic_snapshot(tmp_path: Path) -> None:
    sessions = _sessions(tmp_path)

    first = calculate_repository_metrics(_config(), sessions, FrozenClock())[0]
    second = calculate_repository_metrics(_config(), sessions, FrozenClock())[0]

    assert first.id == second.id
    assert first.metrics_json == second.metrics_json
    with transaction(sessions) as session:
        assert session.scalar(select(func.count()).select_from(RepositoryMetricSnapshot)) == 1


def test_prior_and_distribution_validation() -> None:
    assert shrunk_rate(successes=0, sample_size=0, global_prior=0.45, prior_strength=20) == 0.45
    assert median([3, 1, 2, 4]) == 2.5
    assert percentile([0, 10], 0.75) == 7.5
    with pytest.raises(ValueError):
        shrunk_rate(successes=2, sample_size=1, global_prior=0.45, prior_strength=20)
    with pytest.raises(ValueError):
        percentile([1], 2)
