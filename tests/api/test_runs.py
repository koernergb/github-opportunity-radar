"""HTTP tests for queued runs, cancellation, and resumable sanitized SSE."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from radar.api.app import API_PREFIX
from radar.db.models import PipelineRun, RunEvent
from tests.api.test_app import _app

RUN_ID = UUID("00000000-0000-0000-0000-000000000040")


class FakeCoordinator:
    def __init__(self) -> None:
        self.launched = False

    def reserve(self, config_hash: str, summary: object) -> UUID:
        assert len(config_hash) == 64
        assert summary
        return RUN_ID

    def launch(self, run_id: UUID, work: object) -> None:
        assert run_id == RUN_ID
        assert work
        self.launched = True

    def request_cancel(self, run_id: UUID) -> bool:
        return run_id == RUN_ID


def test_start_returns_durable_id_immediately_and_cancel_documents_boundary() -> None:
    app = _app()
    coordinator = FakeCoordinator()
    app.state.run_coordinator = coordinator
    client = TestClient(app)

    started = client.post(
        f"{API_PREFIX}/runs",
        json={"scope": "all", "deadline_seconds": 60, "fallback_only": True},
    )
    cancelled = client.post(f"{API_PREFIX}/runs/{RUN_ID}/cancel")

    assert started.status_code == 202
    assert started.json() == {"run_id": str(RUN_ID), "status": "queued"}
    assert coordinator.launched is True
    assert cancelled.json()["boundary"] == "between_committed_units"


def test_sse_redacts_secrets_and_resume_cursor_has_no_duplicates() -> None:
    app = _app()
    now = datetime(2026, 8, 8, 12, tzinfo=UTC)
    with app.state.services.sessions.begin() as session:
        session.add(
            PipelineRun(
                id=RUN_ID,
                status="success",
                current_stage=None,
                config_hash="a" * 64,
                started_at=now,
                finished_at=now + timedelta(seconds=2),
                summary={},
            )
        )
        session.add_all(
            [
                RunEvent(
                    pipeline_run_id=RUN_ID,
                    stage="sync",
                    event_type="stage_started",
                    level="info",
                    message="Started sync",
                    error_type=None,
                    details={"credential": "github-secret"},
                    created_at=now,
                ),
                RunEvent(
                    pipeline_run_id=RUN_ID,
                    stage="digest",
                    event_type="stage_started",
                    level="info",
                    message="Started digest",
                    error_type=None,
                    details={},
                    created_at=now + timedelta(seconds=1),
                ),
            ]
        )
    client = TestClient(app)

    complete = client.get(f"{API_PREFIX}/runs/{RUN_ID}/stream")
    resumed = client.get(
        f"{API_PREFIX}/runs/{RUN_ID}/stream",
        params={"after": now.isoformat()},
    )

    assert complete.status_code == 200
    assert complete.text.count("event: stage_started") == 2
    assert "github-secret" not in complete.text
    assert "[REDACTED]" in complete.text
    assert resumed.text.count("event: stage_started") == 1
