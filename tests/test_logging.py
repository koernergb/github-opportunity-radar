"""Tests for structured logging and credential redaction."""

import io
import json
import logging
from collections.abc import Iterator

import pytest

from radar.logging import REDACTED, configure_logging, redact


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers = root.handlers.copy()
    level = root.level
    yield
    root.handlers = handlers
    root.setLevel(level)


@pytest.mark.parametrize(
    ("value", "secret"),
    [
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("token=plain-secret", "plain-secret"),
        ("github_pat_123456789abcdef", "github_pat_123456789abcdef"),
        ("ghp_123456789abcdef", "ghp_123456789abcdef"),
    ],
)
def test_redact_removes_secrets_from_strings(value: str, secret: str) -> None:
    result = redact(value)

    assert secret not in result
    assert REDACTED in result


def test_redact_handles_nested_sensitive_fields() -> None:
    result = redact(
        {
            "headers": {"Authorization": "Bearer top-secret"},
            "github_token": "top-secret",
            "safe": ["retained"],
        }
    )

    assert result["headers"]["Authorization"] == REDACTED
    assert result["github_token"] == REDACTED
    assert result["safe"] == ["retained"]


def test_configured_logger_emits_secret_safe_json() -> None:
    output = io.StringIO()
    configure_logging(stream=output)

    logging.getLogger("radar.test").info(
        "request Authorization: Bearer top-secret",
        extra={"repository": "owner/repo", "api_key": "top-secret"},
    )

    payload = json.loads(output.getvalue())
    assert payload["level"] == "INFO"
    assert payload["logger"] == "radar.test"
    assert payload["repository"] == "owner/repo"
    assert payload["api_key"] == REDACTED
    assert "top-secret" not in output.getvalue()
