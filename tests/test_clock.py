"""Tests for injectable clocks."""

from datetime import UTC

from radar.clock import SystemClock


def test_system_clock_returns_timezone_aware_utc() -> None:
    current = SystemClock().now()

    assert current.tzinfo is UTC
