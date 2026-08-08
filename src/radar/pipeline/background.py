"""Bounded process-local execution with durable run and event records."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import PipelineRun
from radar.db.session import transaction
from radar.pipeline.runs import add_run_event


class BackgroundRunConflictError(RuntimeError):
    """A queued or active pipeline already owns the global run lock."""


class BackgroundRunCoordinator:
    """Own task handles while durable state remains in the database."""

    def __init__(self, sessions: sessionmaker[Session], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock
        self._tasks: dict[UUID, asyncio.Task[Any]] = {}
        self._cancel_requested: set[UUID] = set()

    def reserve(self, config_hash: str, summary: dict[str, Any]) -> UUID:
        with transaction(self._sessions) as session:
            active = session.scalar(
                select(PipelineRun).where(PipelineRun.status.in_({"queued", "running"}))
            )
            if active is not None:
                raise BackgroundRunConflictError(str(active.id))
            run = PipelineRun(
                status="queued",
                current_stage="orchestrator",
                config_hash=config_hash,
                started_at=self._clock.now(),
                finished_at=None,
                summary=summary,
            )
            session.add(run)
            session.flush()
            add_run_event(
                session,
                run_id=run.id,
                stage="orchestrator",
                event_type="run_queued",
                level="info",
                message="Pipeline run queued",
                created_at=self._clock.now(),
            )
            return run.id

    def launch(self, run_id: UUID, work: Callable[[], Awaitable[Any]]) -> None:
        async def execute() -> None:
            try:
                await work()
            finally:
                self._tasks.pop(run_id, None)
                self._cancel_requested.discard(run_id)

        self._tasks[run_id] = asyncio.create_task(execute(), name=f"radar-run-{run_id}")

    def request_cancel(self, run_id: UUID) -> bool:
        if run_id not in self._tasks:
            return False
        self._cancel_requested.add(run_id)
        return True

    def should_cancel(self, run_id: UUID) -> bool:
        return run_id in self._cancel_requested
