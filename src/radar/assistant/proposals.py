"""Validated, expiring proposals that only a user-facing API may apply."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.config_store import ConfigConflictError, SqlAlchemyConfigurationStore
from radar.db.models import AssistantChangeProposal
from radar.settings import RadarConfig, RepositorySettings

PROPOSAL_SCHEMA_VERSION = "assistant_change_proposal_v1"
PROPOSAL_TTL_MINUTES = 15


class ProposalError(RuntimeError):
    pass


class PreferenceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interests: list[str] | None = Field(default=None, max_length=30)
    career_targets: list[str] | None = Field(default=None, max_length=30)
    max_estimated_hours: float | None = Field(default=None, gt=0, le=10_000)


class RepositoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["add", "update", "remove"]
    full_name: str
    enabled: bool = True


class PipelineArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["all"]
    deadline_seconds: int = Field(ge=30, le=3600)
    fallback_only: bool = False


def create_config_proposal(
    sessions: sessionmaker[Session], clock: Clock, conversation_id: UUID, kind: str, raw: object
) -> AssistantChangeProposal:
    store = SqlAlchemyConfigurationStore(sessions, clock)
    active = store.active_revision()
    if active is None:
        raise ProposalError("an active configuration is required")
    config = deepcopy(active.payload)
    if kind == "preferences":
        arguments = PreferenceArguments.model_validate(raw).model_dump(exclude_none=True)
        if not arguments:
            raise ProposalError("preference proposal has no changes")
        user = config["user"]
        for key, value in arguments.items():
            user[key] = value
        summary = "Update assistant-proposed preferences"
    elif kind == "repository":
        parsed = RepositoryArguments.model_validate(raw)
        arguments = parsed.model_dump(mode="json")
        repositories = config["repositories"]
        matches = [
            index
            for index, item in enumerate(repositories)
            if item["full_name"].casefold() == parsed.full_name.casefold()
        ]
        if parsed.action == "add":
            if matches:
                raise ProposalError("repository is already tracked")
            repositories.append(
                RepositorySettings(full_name=parsed.full_name, enabled=parsed.enabled).model_dump(
                    mode="json"
                )
            )
        elif parsed.action == "update":
            if not matches:
                raise ProposalError("repository is not tracked")
            repositories[matches[0]]["enabled"] = parsed.enabled
        else:
            if not matches:
                raise ProposalError("repository is not tracked")
            repositories.pop(matches[0])
        summary = f"{parsed.action.title()} tracked repository {parsed.full_name}"
    else:
        raise ProposalError("unsupported proposal kind")
    validated = RadarConfig.model_validate(config)
    return _persist(
        sessions,
        clock,
        conversation_id,
        active.id,
        kind,
        arguments,
        validated.model_dump(mode="json"),
        summary,
    )


def create_pipeline_proposal(
    sessions: sessionmaker[Session], clock: Clock, conversation_id: UUID, raw: object
) -> AssistantChangeProposal:
    active = SqlAlchemyConfigurationStore(sessions, clock).active_revision()
    if active is None:
        raise ProposalError("an active configuration is required")
    arguments = PipelineArguments.model_validate(raw).model_dump(mode="json")
    return _persist(
        sessions,
        clock,
        conversation_id,
        active.id,
        "pipeline",
        arguments,
        active.payload,
        "Run the bounded Radar pipeline",
    )


def _persist(
    sessions: sessionmaker[Session],
    clock: Clock,
    conversation_id: UUID,
    base_id: UUID,
    kind: str,
    arguments: dict[str, Any],
    proposed: dict[str, Any],
    summary: str,
) -> AssistantChangeProposal:
    canonical = json.dumps(
        {"schema": PROPOSAL_SCHEMA_VERSION, "kind": kind, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
    )
    proposal = AssistantChangeProposal(
        conversation_id=conversation_id,
        base_revision_id=base_id,
        resulting_revision_id=None,
        kind=kind,
        arguments_json=arguments,
        proposed_config=proposed,
        argument_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        summary=summary,
        status="pending",
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(minutes=PROPOSAL_TTL_MINUTES),
        resolved_at=None,
    )
    with sessions.begin() as session:
        session.add(proposal)
    return proposal


def list_proposals(
    sessions: sessionmaker[Session], conversation_id: UUID
) -> list[AssistantChangeProposal]:
    with sessions() as session:
        values = list(
            session.scalars(
                select(AssistantChangeProposal)
                .where(AssistantChangeProposal.conversation_id == conversation_id)
                .order_by(AssistantChangeProposal.created_at)
            )
        )
        for value in values:
            session.expunge(value)
        return values


def reject_proposal(
    sessions: sessionmaker[Session], clock: Clock, proposal_id: UUID
) -> AssistantChangeProposal:
    if _expire_if_needed(sessions, clock, proposal_id):
        raise ProposalError("proposal expired")
    with sessions.begin() as session:
        proposal = _pending(session, clock, proposal_id)
        proposal.status = "rejected"
        proposal.resolved_at = clock.now()
        session.flush()
        session.expunge(proposal)
        return proposal


def apply_config_proposal(
    sessions: sessionmaker[Session], clock: Clock, proposal_id: UUID
) -> AssistantChangeProposal:
    if _expire_if_needed(sessions, clock, proposal_id):
        raise ProposalError("proposal expired")
    with sessions() as session:
        proposal = _pending(session, clock, proposal_id)
        if proposal.kind == "pipeline":
            raise ProposalError("pipeline proposals require the run confirmation endpoint")
        base_id = proposal.base_revision_id
        payload = proposal.proposed_config
        summary = proposal.summary
    store = SqlAlchemyConfigurationStore(sessions, clock)
    if store.active_revision() is None or store.active_revision().id != base_id:  # type: ignore[union-attr]
        raise ConfigConflictError("active configuration changed")
    revision = store.create_revision(
        payload, source="assistant", summary=summary, supersedes_id=base_id
    )
    store.activate(revision.id, expected_active_id=base_id)
    with sessions.begin() as session:
        proposal = _pending(session, clock, proposal_id)
        proposal.status = "applied"
        proposal.resulting_revision_id = revision.id
        proposal.resolved_at = clock.now()
        session.flush()
        session.expunge(proposal)
        return proposal


def consume_pipeline_proposal(
    sessions: sessionmaker[Session], clock: Clock, proposal_id: UUID
) -> dict[str, Any]:
    if _expire_if_needed(sessions, clock, proposal_id):
        raise ProposalError("proposal expired")
    with sessions.begin() as session:
        proposal = _pending(session, clock, proposal_id)
        if proposal.kind != "pipeline":
            raise ProposalError("not a pipeline proposal")
        proposal.status = "applied"
        proposal.resolved_at = clock.now()
        arguments = dict(proposal.arguments_json)
    return arguments


def pipeline_proposal_arguments(
    sessions: sessionmaker[Session], clock: Clock, proposal_id: UUID
) -> dict[str, Any]:
    if _expire_if_needed(sessions, clock, proposal_id):
        raise ProposalError("proposal expired")
    with sessions() as session:
        proposal = _pending(session, clock, proposal_id)
        if proposal.kind != "pipeline":
            raise ProposalError("not a pipeline proposal")
        return dict(proposal.arguments_json)


def _pending(session: Session, clock: Clock, proposal_id: UUID) -> AssistantChangeProposal:
    proposal = session.get(AssistantChangeProposal, proposal_id)
    if proposal is None:
        raise ProposalError("proposal does not exist")
    if proposal.status != "pending":
        raise ProposalError("proposal has already been resolved")
    if proposal.expires_at <= clock.now():
        raise ProposalError("proposal expired")
    return proposal


def _expire_if_needed(sessions: sessionmaker[Session], clock: Clock, proposal_id: UUID) -> bool:
    with sessions.begin() as session:
        proposal = session.get(AssistantChangeProposal, proposal_id)
        if proposal is None or proposal.status != "pending":
            return False
        if proposal.expires_at > clock.now():
            return False
        proposal.status = "expired"
        proposal.resolved_at = clock.now()
        return True
