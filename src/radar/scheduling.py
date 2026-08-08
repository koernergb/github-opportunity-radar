"""Durable timezone-aware local scheduling without a second run-lock domain."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import LocalSchedule

MIN_INTERVAL = 15
MAX_INTERVAL = 10_080


class ScheduleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduleView:
    schedule_id: UUID
    enabled: bool
    interval_minutes: int
    timezone: str
    next_run_at: datetime | None
    last_attempt_at: datetime | None
    last_status: str | None
    updated_at: datetime


def get_schedule(sessions: sessionmaker[Session], clock: Clock, timezone: str) -> ScheduleView:
    with sessions.begin() as session:
        schedule = session.scalar(select(LocalSchedule))
        if schedule is None:
            schedule = LocalSchedule(
                enabled=False,
                interval_minutes=60,
                timezone=timezone,
                next_run_at=None,
                last_attempt_at=None,
                last_status=None,
                updated_at=clock.now(),
            )
            session.add(schedule)
            session.flush()
        return _view(schedule)


def update_schedule(
    sessions: sessionmaker[Session],
    clock: Clock,
    *,
    enabled: bool,
    interval_minutes: int,
    timezone: str,
) -> ScheduleView:
    if not MIN_INTERVAL <= interval_minutes <= MAX_INTERVAL:
        raise ScheduleValidationError("interval is outside the supported range")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ScheduleValidationError("unknown IANA timezone") from error
    with sessions.begin() as session:
        schedule = session.scalar(select(LocalSchedule))
        if schedule is None:
            schedule = LocalSchedule(last_attempt_at=None, last_status=None)
            session.add(schedule)
        schedule.enabled = enabled
        schedule.interval_minutes = interval_minutes
        schedule.timezone = timezone
        schedule.next_run_at = (
            clock.now() + timedelta(minutes=interval_minutes) if enabled else None
        )
        schedule.updated_at = clock.now()
        session.flush()
        return _view(schedule)


def claim_due(sessions: sessionmaker[Session], clock: Clock) -> ScheduleView | None:
    with sessions.begin() as session:
        schedule = session.scalar(select(LocalSchedule))
        if (
            schedule is None
            or not schedule.enabled
            or schedule.next_run_at is None
            or schedule.next_run_at > clock.now()
        ):
            return None
        schedule.last_attempt_at = clock.now()
        schedule.last_status = "claimed"
        schedule.next_run_at = clock.now() + timedelta(minutes=schedule.interval_minutes)
        schedule.updated_at = clock.now()
        return _view(schedule)


def record_schedule_status(sessions: sessionmaker[Session], clock: Clock, status: str) -> None:
    with sessions.begin() as session:
        schedule = session.scalar(select(LocalSchedule))
        if schedule is not None:
            schedule.last_status = status
            schedule.updated_at = clock.now()


def _view(value: LocalSchedule) -> ScheduleView:
    return ScheduleView(
        value.id,
        value.enabled,
        value.interval_minutes,
        value.timezone,
        value.next_run_at,
        value.last_attempt_at,
        value.last_status,
        value.updated_at,
    )
