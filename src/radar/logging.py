"""Structured logging with conservative credential redaction."""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, TextIO

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|token|secret|password|api[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})\b"),
    re.compile(
        r"(?i)\b(token|secret|password|api[_-]?key)\s*([=:])\s*"
        r"([^\s,;}\]]+)"
    ),
)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact credentials while retaining useful log structure."""
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if not isinstance(value, str):
        return value

    redacted = _SECRET_PATTERNS[0].sub(f"Bearer {REDACTED}", value)
    redacted = _SECRET_PATTERNS[1].sub(REDACTED, redacted)
    return _SECRET_PATTERNS[2].sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        redacted,
    )


class JsonFormatter(logging.Formatter):
    """Render one secret-safe JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and key not in {"message", "asctime"}:
                payload[key] = redact(value, key=key)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    stream: TextIO | None = None,
) -> None:
    """Configure the root logger for structured, secret-safe output."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
