"""Durable local schedule controls."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.scheduling import ScheduleValidationError, get_schedule, update_schedule

router = APIRouter(prefix="/schedule", tags=["schedule"])


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_id: UUID
    enabled: bool
    interval_minutes: int
    timezone: str
    next_run_at: datetime | None
    last_attempt_at: datetime | None
    last_status: str | None
    updated_at: datetime


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    interval_minutes: int = Field(ge=15, le=10_080)
    timezone: str = Field(min_length=1, max_length=128)


@router.get("", response_model=ScheduleResponse)
def read_schedule(services: Services) -> ScheduleResponse:
    timezone = services.config.user.timezone if services.config is not None else "UTC"
    return ScheduleResponse.model_validate(
        get_schedule(services.sessions, services.clock, timezone), from_attributes=True
    )


@router.put("", response_model=ScheduleResponse)
def save_schedule(body: ScheduleRequest, services: Services) -> ScheduleResponse:
    try:
        value = update_schedule(
            services.sessions,
            services.clock,
            enabled=body.enabled,
            interval_minutes=body.interval_minutes,
            timezone=body.timezone,
        )
    except ScheduleValidationError as error:
        raise ApiError(422, "schedule_invalid", "The local schedule is invalid.") from error
    return ScheduleResponse.model_validate(value, from_attributes=True)
