"""Integration tests for explicit read projections."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from radar.api.app import API_PREFIX
from radar.db.models import Issue, IssueScore, Repository, UserFeedback
from tests.api.test_preferences import _app

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _seed(app, *, eligible: tuple[bool, ...] = (True, False)) -> list[Issue]:
    sessions = app.state.services.sessions
    with sessions.begin() as session:
        repository = Repository(
            github_id=1,
            node_id="R_1",
            owner="owner",
            name="repo",
            full_name="owner/repo",
            url="https://github.com/owner/repo",
            description="Repository",
            default_branch="main",
            primary_language="Python",
            stars=100,
            forks=10,
            archived=False,
            disabled=False,
            is_fork=False,
            pushed_at=NOW,
            github_created_at=NOW - timedelta(days=100),
            github_updated_at=NOW,
            last_synced_at=NOW,
            raw_json={"private_upstream_payload": "never serialize"},
        )
        session.add(repository)
        session.flush()
        issues = []
        for index, ranking_eligible in enumerate(eligible, start=1):
            issue = Issue(
                repository_id=repository.id,
                github_id=100 + index,
                node_id=f"I_{index}",
                number=index,
                title=f"Issue {index}",
                body="Untrusted issue text <script>alert(1)</script>",
                state="open",
                state_reason=None,
                url=f"https://github.com/owner/repo/issues/{index}",
                author_login="author",
                author_association="NONE",
                locked=False,
                comment_count=0,
                github_created_at=NOW - timedelta(days=10),
                github_updated_at=NOW,
                github_closed_at=None,
                last_seen_at=NOW,
                inaccessible_at=None,
                is_pull_request=False,
                raw_json={"secret_raw": index},
            )
            session.add(issue)
            session.flush()
            session.add(
                IssueScore(
                    issue_id=issue.id,
                    metric_snapshot_id=None,
                    analysis_id=None,
                    score_version="effort_payoff_v1",
                    profile_hash=f"{index:064x}",
                    total=90.0 - index,
                    raw_value=1,
                    merge_estimate=0.5,
                    merge_band="moderate",
                    effort_midpoint=4,
                    payoff=0.8,
                    fit=0.7,
                    risk=0.2,
                    confidence=0.2 if index == 1 else 0.8,
                    feature_values={},
                    explanation={
                        "kind": "heuristic_estimate_not_calibrated_probability",
                        "ranking_eligible": ranking_eligible,
                        "missing_data": ["repository_history"] if index == 1 else [],
                        "filter_evidence": {},
                    },
                    scored_at=NOW,
                )
            )
            issues.append(issue)
    return issues


def test_empty_partial_and_diagnostic_opportunity_states() -> None:
    app = _app()
    client = TestClient(app)
    assert client.get(f"{API_PREFIX}/opportunities").json()["items"] == []
    _seed(app)

    default = client.get(f"{API_PREFIX}/opportunities").json()
    diagnostic = client.get(f"{API_PREFIX}/opportunities?diagnostic=all").json()

    assert default["meta"]["total"] == 1
    assert diagnostic["meta"]["total"] == 2
    assert default["items"][0]["merge_is_heuristic"] is True
    assert default["items"][0]["confidence"] == 0.2
    assert default["items"][0]["missing_evidence"] == ["repository_history"]


def test_opportunity_ordering_pagination_and_query_count_are_stable() -> None:
    app = _app()
    _seed(app, eligible=(True, True))
    engine = app.state.services.sessions.kw["bind"]
    queries = 0

    def count_queries(*args: object) -> None:
        nonlocal queries
        queries += 1

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        response = TestClient(app).get(f"{API_PREFIX}/opportunities?page=1&page_size=1")
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)

    assert response.status_code == 200
    assert response.json()["items"][0]["number"] == 1
    assert response.json()["meta"] == {"page": 1, "page_size": 1, "total": 2}
    assert queries == 1


def test_detail_and_feedback_do_not_mutate_or_leak_observed_payloads() -> None:
    app = _app()
    issue = _seed(app, eligible=(True,))[0]
    client = TestClient(app)

    detail = client.get(f"{API_PREFIX}/opportunities/{issue.id}")
    feedback = client.post(
        f"{API_PREFIX}/opportunities/{issue.id}/feedback",
        json={"status": "interested", "note": "Review later"},
    )

    assert detail.status_code == 200
    assert detail.json()["body_text"].startswith("Untrusted issue text")
    assert "secret_raw" not in detail.text
    assert "private_upstream_payload" not in detail.text
    assert feedback.status_code == 201
    with app.state.services.sessions() as session:
        stored = session.get(Issue, issue.id)
        appended = list(
            session.scalars(select(UserFeedback).where(UserFeedback.issue_id == issue.id))
        )
    assert stored.raw_json == {"secret_raw": 1}
    assert [item.status for item in appended] == ["interested"]


def test_unknown_read_resources_have_stable_not_found_codes() -> None:
    client = TestClient(_app())
    missing = "00000000-0000-0000-0000-000000000001"

    opportunity = client.get(f"{API_PREFIX}/opportunities/{missing}")
    repository = client.get(f"{API_PREFIX}/repositories/{missing}")
    run = client.get(f"{API_PREFIX}/runs/{missing}")

    assert opportunity.json()["error"]["code"] == "opportunity_not_found"
    assert repository.json()["error"]["code"] == "repository_not_found"
    assert run.json()["error"]["code"] == "run_not_found"


def test_dashboard_and_repository_partial_states_remain_explicit() -> None:
    app = _app()
    _seed(app, eligible=(True,))
    client = TestClient(app)

    dashboard = client.get(f"{API_PREFIX}/dashboard")
    repositories = client.get(f"{API_PREFIX}/repositories")
    forbidden_write = client.patch(
        f"{API_PREFIX}/github/issues/00000000-0000-0000-0000-000000000001"
    )

    assert dashboard.json()["tracked_repositories"] == 1
    assert dashboard.json()["latest_run_status"] is None
    assert repositories.json()[0]["health"] is None
    assert forbidden_write.status_code == 404
