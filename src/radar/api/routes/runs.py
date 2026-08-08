"""Background run starts, safe cancellation, and resumable event streaming."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.config_store import SqlAlchemyConfigurationStore
from radar.db.models import PipelineRun, RunEvent
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport
from radar.pipeline.background import BackgroundRunConflictError, BackgroundRunCoordinator
from radar.pipeline.orchestrator import run_pipeline

router = APIRouter(prefix="/runs", tags=["runs"])


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["all"] = "all"
    fallback_only: bool = False
    deadline_seconds: int = Field(default=600, ge=1, le=3600)


class StartRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    status: Literal["queued"] = "queued"


class CancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    status: Literal["cancellation_requested"] = "cancellation_requested"
    boundary: Literal["between_committed_units"] = "between_committed_units"


@router.post("", response_model=StartRunResponse, status_code=202)
async def start_run(
    body: StartRunRequest, request: Request, services: Services
) -> StartRunResponse:
    config = (
        SqlAlchemyConfigurationStore(services.sessions, services.clock).active_config()
        or services.config
    )
    if config is None:
        raise ApiError(503, "config_unavailable", "An active valid configuration is required.")
    if not services.environment.github_token:
        raise ApiError(503, "github_unavailable", "GitHub credentials are not configured.")
    coordinator: BackgroundRunCoordinator = request.app.state.run_coordinator
    try:
        run_id = coordinator.reserve(
            config.config_hash,
            {
                "scope": body.scope,
                "deadline_seconds": body.deadline_seconds,
                "fallback_only": body.fallback_only,
            },
        )
    except BackgroundRunConflictError as error:
        raise ApiError(409, "pipeline_locked", "A pipeline run is already active.") from error

    async def work() -> None:
        assert services.environment.github_token is not None
        async with GitHubRestTransport(
            token=services.environment.github_token,
            api_version=config.github.api_version,
        ) as transport:
            await run_pipeline(
                config,
                GitHubClient(transport),
                services.sessions,
                services.clock,
                api_key=services.environment.openai_api_key,
                fallback_only=body.fallback_only,
                deadline_seconds=body.deadline_seconds,
                reserved_run_id=run_id,
                should_cancel=lambda: coordinator.should_cancel(run_id),
            )

    coordinator.launch(run_id, work)
    return StartRunResponse(run_id=run_id)


@router.post("/{run_id}/cancel", response_model=CancelResponse, status_code=202)
def cancel_run(run_id: UUID, request: Request) -> CancelResponse:
    coordinator: BackgroundRunCoordinator = request.app.state.run_coordinator
    if not coordinator.request_cancel(run_id):
        raise ApiError(409, "run_not_cancellable", "The run is not active in this process.")
    return CancelResponse(run_id=run_id)


@router.get("/{run_id}/stream")
async def stream_run_events(
    run_id: UUID,
    request: Request,
    services: Services,
    after: datetime | None = None,
) -> StreamingResponse:
    with services.sessions() as session:
        if session.get(PipelineRun, run_id) is None:
            raise ApiError(404, "run_not_found", "The run does not exist.")
        last_event_id = request.headers.get("Last-Event-ID")
        if after is None and last_event_id:
            try:
                prior = session.get(RunEvent, UUID(last_event_id))
            except ValueError:
                prior = None
            if prior is not None and prior.pipeline_run_id == run_id:
                after = prior.created_at

    async def events() -> AsyncIterator[str]:
        cursor = after
        while not await request.is_disconnected():
            statement = select(RunEvent).where(RunEvent.pipeline_run_id == run_id)
            if cursor is not None:
                statement = statement.where(RunEvent.created_at > cursor)
            statement = statement.order_by(RunEvent.created_at, RunEvent.id)
            with services.sessions() as session:
                items = list(session.scalars(statement))
                run = session.get(PipelineRun, run_id)
            for item in items:
                cursor = item.created_at
                payload = {
                    "event_id": str(item.id),
                    "stage": item.stage,
                    "event_type": item.event_type,
                    "level": item.level,
                    "message": item.message,
                    "details": _sanitize(item.details, services),
                    "created_at": item.created_at.isoformat(),
                }
                yield f"id: {item.id}\nevent: {item.event_type}\ndata: {json.dumps(payload)}\n\n"
            if run is None or run.status not in {"queued", "running"}:
                break
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream")


def _sanitize(value: object, services: Services) -> object:
    secrets = {
        item
        for item in (
            services.environment.github_token,
            services.environment.openai_api_key,
        )
        if item
    }
    if isinstance(value, dict):
        return {key: _sanitize(child, services) for key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize(child, services) for child in value]
    if isinstance(value, str):
        sanitized = value
        for secret in secrets:
            sanitized = sanitized.replace(secret, "[REDACTED]")
        return sanitized
    return value
