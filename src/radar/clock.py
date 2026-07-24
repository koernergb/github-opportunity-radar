"""Injectable clocks for deterministic domain and pipeline behavior."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Source of timezone-aware current timestamps."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""
        ...


class SystemClock:
    """Production clock backed by the system UTC clock."""

    def now(self) -> datetime:
        """Return the current time in UTC."""
        return datetime.now(UTC)
