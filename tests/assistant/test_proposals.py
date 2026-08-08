"""Single-use assistant proposal state-machine tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from radar.assistant.proposals import (
    ProposalError,
    apply_config_proposal,
    consume_pipeline_proposal,
    create_config_proposal,
    create_pipeline_proposal,
    reject_proposal,
)
from radar.assistant.service import create_conversation
from radar.assistant.tools import TOOL_SCHEMAS
from radar.config_store import ConfigConflictError, SqlAlchemyConfigurationStore
from radar.db.models import Base
from radar.db.session import create_session_factory
from radar.settings import load_config


class MutableClock:
    value = datetime(2026, 8, 8, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.fixture
def state() -> tuple[sessionmaker[Session], MutableClock]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    clock = MutableClock()
    store = SqlAlchemyConfigurationStore(sessions, clock)
    revision = store.create_revision(
        load_config(Path("config/profile.example.yaml")).model_dump(mode="json"),
        source="bootstrap",
        summary="test",
    )
    store.activate(revision.id, expected_active_id=None)
    return sessions, clock


def _proposal(state: tuple[sessionmaker[Session], MutableClock]):
    sessions, clock = state
    conversation = create_conversation(sessions, clock)
    return create_config_proposal(
        sessions, clock, conversation.id, "preferences", {"interests": ["compilers"]}
    )


def test_confirmation_applies_exact_immutable_payload_once_with_provenance(
    state: tuple[sessionmaker[Session], MutableClock],
) -> None:
    sessions, clock = state
    proposal = _proposal(state)
    applied = apply_config_proposal(sessions, clock, proposal.id)
    active = SqlAlchemyConfigurationStore(sessions, clock).active_revision()
    assert applied.status == "applied" and active is not None
    assert active.source == "assistant" and active.payload["user"]["interests"] == ["compilers"]
    assert applied.resulting_revision_id == active.id and len(applied.argument_hash) == 64
    with pytest.raises(ProposalError, match="resolved"):
        apply_config_proposal(sessions, clock, proposal.id)


def test_rejection_has_no_configuration_effect(
    state: tuple[sessionmaker[Session], MutableClock],
) -> None:
    sessions, clock = state
    store = SqlAlchemyConfigurationStore(sessions, clock)
    before = store.active_revision()
    rejected = reject_proposal(sessions, clock, _proposal(state).id)
    assert rejected.status == "rejected" and store.active_revision().id == before.id  # type: ignore[union-attr]


def test_stale_and_expired_proposals_fail_closed(
    state: tuple[sessionmaker[Session], MutableClock],
) -> None:
    sessions, clock = state
    stale = _proposal(state)
    store = SqlAlchemyConfigurationStore(sessions, clock)
    current = store.active_revision()
    assert current is not None
    clock.value += timedelta(seconds=1)
    other = store.create_revision(current.payload, source="manual", summary="concurrent")
    store.activate(other.id, expected_active_id=current.id)
    with pytest.raises(ConfigConflictError):
        apply_config_proposal(sessions, clock, stale.id)
    expiring = _proposal(state)
    clock.value += timedelta(minutes=16)
    with pytest.raises(ProposalError, match="expired"):
        reject_proposal(sessions, clock, expiring.id)
    with sessions() as session:
        assert session.get(type(expiring), expiring.id).status == "expired"  # type: ignore[union-attr]


def test_repository_validation_refuses_github_or_unknown_actions(
    state: tuple[sessionmaker[Session], MutableClock],
) -> None:
    sessions, clock = state
    conversation = create_conversation(sessions, clock)
    with pytest.raises(ValidationError):
        create_config_proposal(
            sessions,
            clock,
            conversation.id,
            "repository",
            {"action": "close_issue", "full_name": "owner/repo"},
        )


def test_model_tool_registry_has_no_apply_activate_or_github_mutation() -> None:
    names = {str(tool["name"]) for tool in TOOL_SCHEMAS}
    assert {"apply", "activate", "confirm", "close_issue", "comment_on_github"}.isdisjoint(names)
    assert {
        "propose_preference_change",
        "propose_repository_change",
        "propose_pipeline_run",
    } <= names


def test_repository_and_pipeline_proposals_are_bounded_and_separately_consumed(
    state: tuple[sessionmaker[Session], MutableClock],
) -> None:
    sessions, clock = state
    conversation = create_conversation(sessions, clock)
    repository = create_config_proposal(
        sessions,
        clock,
        conversation.id,
        "repository",
        {"action": "add", "full_name": "owner/new-repo", "enabled": True},
    )
    assert apply_config_proposal(sessions, clock, repository.id).status == "applied"
    active = SqlAlchemyConfigurationStore(sessions, clock).active_config()
    assert active is not None and active.repositories[-1].full_name == "owner/new-repo"
    pipeline = create_pipeline_proposal(
        sessions,
        clock,
        conversation.id,
        {"scope": "all", "deadline_seconds": 60, "fallback_only": True},
    )
    assert consume_pipeline_proposal(sessions, clock, pipeline.id) == {
        "scope": "all",
        "deadline_seconds": 60,
        "fallback_only": True,
    }
    with pytest.raises(ProposalError, match="resolved"):
        consume_pipeline_proposal(sessions, clock, pipeline.id)
