"""Append-only feedback validation, latest state, and outcome reporting tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from radar.db.models import Base, Issue, Repository, UserFeedback
from radar.feedback.service import (
    FeedbackValidationError,
    build_outcome_report,
    latest_feedback,
    record_feedback,
    resolve_issue_reference,
)

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class AdvancingClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        result = self.value
        self.value += timedelta(seconds=1)
        return result


@pytest.fixture
def seeded() -> tuple[Session, Issue]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = Repository(
        github_id=1,
        node_id="R_1",
        owner="owner",
        name="repo",
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description=None,
        default_branch="main",
        primary_language="Python",
        stars=0,
        forks=0,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=NOW,
        github_created_at=NOW,
        github_updated_at=NOW,
        last_synced_at=NOW,
        raw_json={"observed": True},
    )
    session.add(repository)
    session.flush()
    issue = Issue(
        repository_id=repository.id,
        github_id=2,
        node_id="I_2",
        number=2,
        title="Observed title",
        body="Observed body",
        state="open",
        state_reason=None,
        url="https://github.com/owner/repo/issues/2",
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
        raw_json={"observed": True},
    )
    session.add(issue)
    session.commit()
    yield session, issue
    session.close()


def test_feedback_is_append_only_latest_state_without_observation_mutation(
    seeded: tuple[Session, Issue],
) -> None:
    session, issue = seeded
    clock = AdvancingClock()
    original = (issue.state, issue.raw_json.copy(), issue.title)

    first = record_feedback(
        session, issue_id=issue.id, status="interested", note="  useful  ", clock=clock
    )
    second = record_feedback(session, issue_id=issue.id, status="investigating", clock=clock)
    session.commit()

    assert first.id != second.id
    assert session.scalar(select(func.count()).select_from(UserFeedback)) == 2
    assert latest_feedback(session, issue.id) == second
    assert first.note == "useful"
    assert (issue.state, issue.raw_json, issue.title) == original
    assert resolve_issue_reference(session, "owner/repo#2") == issue


def test_transitions_and_github_pull_request_urls_are_validated(
    seeded: tuple[Session, Issue],
) -> None:
    session, issue = seeded
    clock = AdvancingClock()
    record_feedback(session, issue_id=issue.id, status="implementation_started", clock=clock)

    with pytest.raises(FeedbackValidationError, match="backward"):
        record_feedback(session, issue_id=issue.id, status="commented", clock=clock)
    with pytest.raises(FeedbackValidationError, match="requires --pr-url"):
        record_feedback(session, issue_id=issue.id, status="pr_opened", clock=clock)
    with pytest.raises(FeedbackValidationError, match="PR URL"):
        record_feedback(
            session,
            issue_id=issue.id,
            status="pr_opened",
            pr_url="https://example.com/pull/3",
            clock=clock,
        )

    opened = record_feedback(
        session,
        issue_id=issue.id,
        status="pr_opened",
        pr_url="https://github.com/owner/repo/pull/3/",
        clock=clock,
    )
    record_feedback(
        session,
        issue_id=issue.id,
        status="merged",
        pr_url="https://github.com/owner/repo/pull/3",
        clock=clock,
    )
    with pytest.raises(FeedbackValidationError, match="terminal"):
        record_feedback(session, issue_id=issue.id, status="interested", clock=clock)
    assert opened.pr_url == "https://github.com/owner/repo/pull/3"


def test_outcome_report_uses_latest_states_and_user_reported_funnel(
    seeded: tuple[Session, Issue],
) -> None:
    session, issue = seeded
    clock = AdvancingClock()
    record_feedback(session, issue_id=issue.id, status="investigating", clock=clock)
    record_feedback(
        session,
        issue_id=issue.id,
        status="pr_opened",
        pr_url="https://github.com/owner/repo/pull/3",
        clock=clock,
    )
    record_feedback(
        session,
        issue_id=issue.id,
        status="merged",
        pr_url="https://github.com/owner/repo/pull/3",
        clock=clock,
    )
    session.commit()

    report = build_outcome_report(session)

    assert report.latest_status_counts == {"merged": 1}
    assert report.progressed_count == 1
    assert report.pr_opened_count == 1
    assert report.merged_count == 1
    assert report.merge_rate_after_pr == 1.0
