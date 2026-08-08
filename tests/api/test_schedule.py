"""HTTP tests for durable local schedule controls."""

from fastapi.testclient import TestClient

from radar.api.app import API_PREFIX
from tests.api.test_app import _app


def test_schedule_defaults_to_profile_timezone_and_updates_with_bounds() -> None:
    client = TestClient(_app())
    initial = client.get(f"{API_PREFIX}/schedule")
    updated = client.put(
        f"{API_PREFIX}/schedule",
        json={"enabled": True, "interval_minutes": 45, "timezone": "America/Detroit"},
    )
    invalid = client.put(
        f"{API_PREFIX}/schedule",
        json={"enabled": True, "interval_minutes": 45, "timezone": "Not/AZone"},
    )

    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert updated.status_code == 200
    assert updated.json()["next_run_at"] is not None
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "schedule_invalid"
