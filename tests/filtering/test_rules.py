"""Direct coverage for every deterministic exclusion and warning rule."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from radar.db.models import (
    Issue,
    IssueAssignee,
    IssueComment,
    IssueFilterResult,
    IssueLink,
    Repository,
    RepositoryMetricSnapshot,
    UserFeedback,
)
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
    transaction,
)
from radar.filtering.claims import detect_soft_claim
from radar.filtering.engine import FILTER_VERSION, filter_issues
from radar.filtering.rules import RuleAction, RuleContext, evaluate_rules
from radar.settings import load_config

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _repository() -> Repository:
    return Repository(
        id=uuid4(),
        github_id=1,
        node_id="R_1",
        owner="ml-explore",
        name="mlx",
        full_name="ml-explore/mlx",
        url="https://github.com/ml-explore/mlx",
        description=None,
        default_branch="main",
        primary_language="Python",
        stars=1,
        forks=0,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=NOW,
        github_created_at=NOW - timedelta(days=100),
        github_updated_at=NOW,
        last_synced_at=NOW,
        raw_json={},
    )


def _issue(repository: Repository) -> Issue:
    return Issue(
        id=uuid4(),
        repository_id=repository.id,
        github_id=10,
        node_id="I_10",
        number=7,
        title="Specific implementation bug",
        body="This has a concrete reproduction and acceptance criteria for a focused change.",
        state="open",
        state_reason=None,
        url="https://github.com/ml-explore/mlx/issues/7",
        author_login="author",
        author_association="NONE",
        locked=False,
        comment_count=1,
        github_created_at=NOW - timedelta(days=1),
        github_updated_at=NOW,
        github_closed_at=None,
        last_seen_at=NOW,
        inaccessible_at=None,
        is_pull_request=False,
        raw_json={},
    )


def _comment(
    issue: Issue,
    body: str,
    *,
    association: str = "MEMBER",
    author: str = "maintainer",
    created_at: datetime = NOW - timedelta(hours=1),
    github_id: int = 1,
) -> IssueComment:
    return IssueComment(
        id=uuid4(),
        issue_id=issue.id,
        github_id=github_id,
        node_id=f"IC_{github_id}",
        body=body,
        author_login=author,
        author_association=association,
        github_created_at=created_at,
        github_updated_at=created_at,
        raw_json={},
    )


def _metric(repository: Repository) -> RepositoryMetricSnapshot:
    return RepositoryMetricSnapshot(
        id=uuid4(),
        repository_id=repository.id,
        metric_version="v1",
        window_start=NOW - timedelta(days=365),
        window_end=NOW,
        external_pr_count=10,
        merged_external_count=5,
        external_merge_rate=0.5,
        shrunk_merge_rate=0.48,
        closed_unmerged_rate=0.2,
        median_first_response_hours=4,
        median_merge_hours=24,
        p75_merge_hours=48,
        active_maintainer_count=2,
        recent_activity=0.5,
        documentation_score=0.8,
        data_confidence=0.8,
        metrics_json={},
        calculated_at=NOW,
    )


def _context() -> RuleContext:
    repository = _repository()
    issue = _issue(repository)
    configured = load_config(Path("config/profile.example.yaml")).repositories[0]
    return RuleContext(
        issue=issue,
        repository=repository,
        configured=configured,
        labels=set(),
        assignees=[],
        comments=[_comment(issue, "Maintainer response")],
        links=[],
        metric=_metric(repository),
        feedback=None,
        now=NOW,
    )


def _codes(context: RuleContext) -> dict[str, RuleAction]:
    return {result.code: result.action for result in evaluate_rules(context)}


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("closed", "closed"),
        ("pull_request", "pull_request"),
        ("inactive_repo", "repository_inactive"),
        ("excluded_label", "excluded_label"),
        ("terminal_label", "terminal_label"),
        ("active_pr", "active_linked_pr"),
        ("assigned", "assigned"),
        ("too_new", "too_new"),
        ("too_old", "too_old"),
        ("feedback", "feedback_rejected"),
    ],
)
def test_each_exclusion_rule(case: str, code: str) -> None:
    context = _context()
    if case == "closed":
        context.issue.state = "closed"
    elif case == "pull_request":
        context.issue.is_pull_request = True
    elif case == "inactive_repo":
        context.repository.archived = True
    elif case == "excluded_label":
        context = replace(context, labels={"question"})
    elif case == "terminal_label":
        context = replace(context, labels={"duplicate"})
    elif case == "active_pr":
        context = replace(context, links=[_link(context.issue, state="open", strength=0.9)])
    elif case == "assigned":
        context = replace(
            context,
            assignees=[IssueAssignee(issue_id=context.issue.id, login="other")],
        )
    elif case == "too_new":
        context.issue.github_created_at = NOW - timedelta(minutes=1)
    elif case == "too_old":
        context.issue.github_created_at = NOW - timedelta(days=800)
        context.issue.github_updated_at = NOW - timedelta(days=800)
    elif case == "feedback":
        context = replace(
            context,
            feedback=UserFeedback(
                issue_id=context.issue.id,
                status="rejected",
                note=None,
                pr_url=None,
                created_at=NOW,
            ),
        )

    assert _codes(context)[code] is RuleAction.EXCLUDE


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("claim", "soft_claim"),
        ("design", "needs_design"),
        ("stale", "stale"),
        ("weak_body", "weak_body"),
        ("no_maintainer", "no_maintainer_response"),
        ("hardware", "special_hardware"),
        ("broad", "broad_scope"),
        ("api", "public_api_change"),
        ("low_history", "low_history_sample"),
        ("contentious", "contentious"),
        ("failed_pr", "previous_closed_unmerged_pr"),
        ("language", "unknown_language"),
    ],
)
def test_each_warning_rule_never_excludes(case: str, code: str) -> None:
    context = _context()
    if case == "claim":
        context = replace(
            context,
            comments=[
                *context.comments,
                _comment(context.issue, "I'll work on this", association="NONE", author="dev"),
            ],
        )
    elif case == "design":
        context.issue.body = "Needs design decision and an RFC before implementation."
    elif case == "stale":
        context = replace(context, labels={"stale"})
    elif case == "weak_body":
        context.issue.body = ""
    elif case == "no_maintainer":
        context = replace(context, comments=[])
    elif case == "hardware":
        context.issue.body = "This requires CUDA GPU benchmarking with specific reproduction steps."
    elif case == "broad":
        context.issue.body = "Refactor all components across the project with acceptance criteria."
    elif case == "api":
        context.issue.body = "This public API breaking change has detailed acceptance criteria."
    elif case == "low_history":
        context = replace(context, metric=None)
    elif case == "contentious":
        context = replace(
            context,
            comments=[
                _comment(context.issue, "I disagree", github_id=2),
                _comment(context.issue, "Strongly oppose", github_id=3),
            ],
        )
    elif case == "failed_pr":
        context = replace(context, links=[_link(context.issue, state="closed", strength=0.9)])
    elif case == "language":
        context.repository.primary_language = None

    actions = _codes(context)
    assert actions[code] is RuleAction.WARN
    assert RuleAction.EXCLUDE not in actions.values()


def _link(issue: Issue, *, state: str, strength: float) -> IssueLink:
    return IssueLink(
        source_issue_id=issue.id,
        target_repository="ml-explore/mlx",
        target_number=99,
        target_type="pull_request",
        relation_type="closing_keyword",
        state=state,
        merged=False,
        url="https://github.com/ml-explore/mlx/pull/99",
        evidence_strength=strength,
        observed_at=NOW,
    )


def test_weak_active_link_does_not_exclude() -> None:
    context = _context()
    context = replace(context, links=[_link(context.issue, state="open", strength=0.25)])

    assert "active_linked_pr" not in _codes(context)


def test_soft_claim_ignores_quotes_detects_withdrawal_and_decays() -> None:
    context = _context()
    quoted = _comment(
        context.issue,
        "> I'll work on this",
        association="NONE",
        author="dev",
        created_at=NOW - timedelta(days=1),
    )
    assert not detect_soft_claim([quoted], now=NOW).claimed
    claim = _comment(
        context.issue,
        "I'll work on this",
        association="NONE",
        author="dev",
        created_at=NOW - timedelta(days=20),
        github_id=2,
    )
    assert detect_soft_claim([claim], now=NOW).confidence == 0.5
    withdrawal = _comment(
        context.issue,
        "I can't work on this anymore",
        association="NONE",
        author="dev",
        created_at=NOW,
        github_id=3,
    )
    assert not detect_soft_claim([claim, withdrawal], now=NOW).claimed


def test_engine_upserts_exactly_one_current_result_per_version(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    repository = _repository()
    issue = _issue(repository)
    with transaction(sessions) as session:
        session.add(repository)
        session.flush()
        session.add(issue)
    config = load_config(Path("config/profile.example.yaml"))

    first = filter_issues(config, sessions, FrozenClock())
    second = filter_issues(config, sessions, FrozenClock())

    assert first == second
    with transaction(sessions) as session:
        result = session.scalar(select(IssueFilterResult))
        assert result is not None
        assert result.filter_version == FILTER_VERSION
        assert session.scalar(select(func.count()).select_from(IssueFilterResult)) == 1
