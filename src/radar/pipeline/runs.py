"""Persistence helpers for observable pipeline runs and events."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from radar.db.models import PipelineRun, RunEvent


def create_pipeline_run(
    session: Session,
    *,
    config_hash: str,
    stage: str,
    started_at: datetime,
) -> PipelineRun:
    run = PipelineRun(
        status="running",
        current_stage=stage,
        config_hash=config_hash,
        started_at=started_at,
        finished_at=None,
        summary={},
    )
    session.add(run)
    session.flush()
    return run


def add_run_event(
    session: Session,
    *,
    run_id: UUID,
    stage: str,
    event_type: str,
    level: str,
    message: str,
    created_at: datetime,
    error_type: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        RunEvent(
            pipeline_run_id=run_id,
            stage=stage,
            event_type=event_type,
            level=level,
            message=message,
            error_type=error_type,
            details=details or {},
            created_at=created_at,
        )
    )


def finish_pipeline_run(
    session: Session,
    run: PipelineRun,
    *,
    status: str,
    summary: dict[str, Any],
    finished_at: datetime,
) -> None:
    run.status = status
    run.current_stage = None
    run.summary = summary
    run.finished_at = finished_at
