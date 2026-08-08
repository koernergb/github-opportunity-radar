"""Tests for durable queued runs and safe process-local cancellation."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from radar.db.models import Base, PipelineRun
from radar.db.session import create_session_factory
from radar.pipeline.background import BackgroundRunConflictError, BackgroundRunCoordinator


class AdvancingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 8, tzinfo=UTC)

    def now(self) -> datetime:
        self.value += timedelta(microseconds=1)
        return self.value


@pytest.mark.asyncio
async def test_reservation_is_durable_and_global_lock_rejects_overlap() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    coordinator = BackgroundRunCoordinator(sessions, AdvancingClock())

    run_id = coordinator.reserve("a" * 64, {"deadline_seconds": 60})

    with pytest.raises(BackgroundRunConflictError):
        coordinator.reserve("a" * 64, {})
    with sessions() as session:
        run = session.get(PipelineRun, run_id)
    assert run is not None
    assert run.status == "queued"

    started = asyncio.Event()
    finish = asyncio.Event()

    async def work() -> None:
        started.set()
        await finish.wait()

    coordinator.launch(run_id, work)
    await started.wait()
    assert coordinator.request_cancel(run_id) is True
    assert coordinator.should_cancel(run_id) is True
    finish.set()
    await asyncio.sleep(0)
