"""Durable local schedule validation and restart behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from radar.db.session import create_database_engine, create_session_factory, migrate_database
from radar.scheduling import ScheduleValidationError, claim_due, get_schedule, update_schedule


class MutableClock:
    value = datetime(2026, 8, 8, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def test_schedule_survives_session_factory_restart_and_claims_once(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    clock = MutableClock()
    first = create_session_factory(create_database_engine(url))
    saved = update_schedule(
        first, clock, enabled=True, interval_minutes=30, timezone="America/Detroit"
    )
    second = create_session_factory(create_database_engine(url))
    restored = get_schedule(second, clock, "UTC")
    assert restored.schedule_id == saved.schedule_id and restored.timezone == "America/Detroit"
    assert claim_due(second, clock) is None
    clock.value += timedelta(minutes=31)
    assert claim_due(second, clock) is not None
    assert claim_due(second, clock) is None


def test_schedule_rejects_bad_timezone_and_budget(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'radar.sqlite'}"
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    clock = MutableClock()
    with pytest.raises(ScheduleValidationError):
        update_schedule(sessions, clock, enabled=True, interval_minutes=1, timezone="UTC")
    with pytest.raises(ScheduleValidationError):
        update_schedule(sessions, clock, enabled=True, interval_minutes=60, timezone="Mars/Olympus")
