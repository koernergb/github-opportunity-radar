"""Rate-limit evidence and retry-delay parsing."""

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def has_rate_limit_evidence(
    status_code: int,
    headers: Mapping[str, str],
    message: str = "",
) -> bool:
    """Return whether a response credibly indicates primary or secondary limiting."""
    if status_code == 429:
        return True
    if status_code != 403:
        return False
    remaining = headers.get("x-ratelimit-remaining")
    return (
        remaining == "0"
        or "retry-after" in headers
        or "rate limit" in message.casefold()
        or "abuse detection" in message.casefold()
    )


def parse_retry_after(value: str, *, now: datetime) -> float | None:
    """Parse Retry-After seconds or an HTTP date."""
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - now).total_seconds())


def parse_rate_limit_reset(value: str | None) -> datetime | None:
    """Parse GitHub's epoch reset header into UTC."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def retry_delay(
    *,
    headers: Mapping[str, str],
    now: datetime,
    attempt: int,
    jitter: float,
    rate_limited: bool,
) -> float:
    """Choose a delay, giving Retry-After precedence over every other signal."""
    retry_after = headers.get("retry-after")
    if retry_after is not None:
        parsed = parse_retry_after(retry_after, now=now)
        if parsed is not None:
            return parsed

    if rate_limited:
        reset_at = parse_rate_limit_reset(headers.get("x-ratelimit-reset"))
        if reset_at is not None:
            return max(0.0, (reset_at - now).total_seconds())

    return min(60.0, 2.0 ** (attempt - 1)) + max(0.0, jitter)
