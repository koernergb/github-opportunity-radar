"""Liveness and dependency-readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from radar import __version__
from radar.api.dependencies import Services

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Process liveness independent of external dependencies."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"
    version: str


class ReadinessCheck(BaseModel):
    """Sanitized state of one required dependency."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "missing", "invalid", "unavailable"]


class SecretStatus(BaseModel):
    """Presence state that can never contain credential material."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["configured", "missing", "invalid"]


class ReadinessResponse(BaseModel):
    """Application readiness with safe diagnostic categories."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ready", "not_ready"]
    checks: dict[str, ReadinessCheck]
    secrets: dict[str, SecretStatus]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Confirm that the HTTP process is alive."""
    return HealthResponse(version=__version__)


@router.get(
    "/readiness",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def readiness(response: Response, services: Services) -> ReadinessResponse:
    """Check local configuration and database availability."""
    config_status: Literal["ready", "missing", "invalid", "unavailable"] = "ready"
    if services.config is None:
        config_status = "invalid" if services.config_error is not None else "missing"

    database_status: Literal["ready", "missing", "invalid", "unavailable"] = "ready"
    try:
        with services.sessions() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"

    checks = {
        "config": ReadinessCheck(status=config_status),
        "database": ReadinessCheck(status=database_status),
    }
    ready = all(check.status == "ready" for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        checks=checks,
        secrets={
            "github_token": SecretStatus(status=_secret_status(services.environment.github_token)),
            "openai_api_key": SecretStatus(
                status=_secret_status(services.environment.openai_api_key)
            ),
        },
    )


def _secret_status(value: str | None) -> Literal["configured", "missing", "invalid"]:
    if value is None:
        return "missing"
    if not value.strip():
        return "invalid"
    return "configured"
