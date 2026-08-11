"""User-only confirmation boundary for assistant-created proposals."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.assistant.proposals import (
    ProposalError,
    apply_config_proposal,
    consume_pipeline_proposal,
    list_proposals,
    pipeline_proposal_arguments,
    reject_proposal,
)
from radar.config_store import ConfigConflictError, SqlAlchemyConfigurationStore
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport
from radar.llm.registry import ProviderCredentialError, ProviderRegistry
from radar.pipeline.background import BackgroundRunConflictError, BackgroundRunCoordinator
from radar.pipeline.orchestrator import run_pipeline

router = APIRouter(prefix="/assistant/proposals", tags=["assistant-proposals"])


class ProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    conversation_id: UUID
    base_revision_id: UUID
    resulting_revision_id: UUID | None
    kind: str
    arguments: dict[str, Any]
    argument_hash: str
    summary: str
    status: str
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


@router.get("/{conversation_id}", response_model=list[ProposalResponse])
def proposals(conversation_id: UUID, services: Services) -> list[ProposalResponse]:
    return [_response(value) for value in list_proposals(services.sessions, conversation_id)]


@router.post("/{proposal_id}/confirm", response_model=ProposalResponse)
def confirm(proposal_id: UUID, services: Services) -> ProposalResponse:
    try:
        return _response(apply_config_proposal(services.sessions, services.clock, proposal_id))
    except ConfigConflictError as error:
        raise ApiError(409, "proposal_stale", "The active configuration changed.") from error
    except ProposalError as error:
        raise ApiError(409, "proposal_unavailable", "The proposal cannot be applied.") from error


@router.post("/{proposal_id}/reject", response_model=ProposalResponse)
def reject(proposal_id: UUID, services: Services) -> ProposalResponse:
    try:
        return _response(reject_proposal(services.sessions, services.clock, proposal_id))
    except ProposalError as error:
        raise ApiError(409, "proposal_unavailable", "The proposal cannot be rejected.") from error


@router.post("/{proposal_id}/confirm-run", status_code=202)
def confirm_run(proposal_id: UUID, request: Request, services: Services) -> dict[str, str]:
    config = (
        SqlAlchemyConfigurationStore(services.sessions, services.clock).active_config()
        or services.config
    )
    if config is None or not services.environment.github_token:
        raise ApiError(503, "pipeline_unavailable", "Pipeline credentials are not configured.")
    try:
        arguments = pipeline_proposal_arguments(services.sessions, services.clock, proposal_id)
        coordinator: BackgroundRunCoordinator = request.app.state.run_coordinator
        run_id = coordinator.reserve(config.config_hash, arguments)
    except ProposalError as error:
        raise ApiError(
            409, "proposal_unavailable", "The run proposal cannot be applied."
        ) from error
    except BackgroundRunConflictError as error:
        raise ApiError(409, "pipeline_locked", "A pipeline run is already active.") from error
    try:
        consume_pipeline_proposal(services.sessions, services.clock, proposal_id)
    except ProposalError as error:
        raise ApiError(
            409, "proposal_unavailable", "The run proposal cannot be applied."
        ) from error

    try:
        analysis_provider = ProviderRegistry(services.credentials).analysis(
            config.llm.provider, config.llm.model
        )
    except ProviderCredentialError:
        analysis_provider = None

    async def work() -> None:
        assert services.environment.github_token is not None
        async with GitHubRestTransport(
            token=services.environment.github_token, api_version=config.github.api_version
        ) as transport:
            await run_pipeline(
                config,
                GitHubClient(transport),
                services.sessions,
                services.clock,
                provider=analysis_provider,
                fallback_only=bool(arguments["fallback_only"]),
                deadline_seconds=int(arguments["deadline_seconds"]),
                reserved_run_id=run_id,
                should_cancel=lambda: coordinator.should_cancel(run_id),
            )

    coordinator.launch(run_id, work)
    return {"run_id": str(run_id), "status": "queued"}


@router.post("/{proposal_id}/undo")
def undo(proposal_id: UUID, services: Services) -> dict[str, str]:
    proposal = next(
        (
            item
            for item in list_proposals(
                services.sessions, _proposal_conversation(services, proposal_id)
            )
            if item.id == proposal_id
        ),
        None,
    )
    if proposal is None or proposal.status != "applied" or proposal.resulting_revision_id is None:
        raise ApiError(409, "undo_unavailable", "This proposal cannot be undone.")
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    try:
        store.activate(proposal.base_revision_id, expected_active_id=proposal.resulting_revision_id)
    except ConfigConflictError as error:
        raise ApiError(409, "undo_stale", "The active configuration changed.") from error
    return {"status": "undone", "revision_id": str(proposal.base_revision_id)}


def _proposal_conversation(services: Services, proposal_id: UUID) -> UUID:
    from radar.db.models import AssistantChangeProposal

    with services.sessions() as session:
        proposal = session.get(AssistantChangeProposal, proposal_id)
        if proposal is None:
            raise ApiError(404, "proposal_not_found", "The proposal does not exist.")
        return proposal.conversation_id


def _response(value: Any) -> ProposalResponse:
    return ProposalResponse(
        proposal_id=value.id,
        conversation_id=value.conversation_id,
        base_revision_id=value.base_revision_id,
        resulting_revision_id=value.resulting_revision_id,
        kind=value.kind,
        arguments=value.arguments_json,
        argument_hash=value.argument_hash,
        summary=value.summary,
        status=value.status,
        created_at=value.created_at,
        expires_at=value.expires_at,
        resolved_at=value.resolved_at,
    )
