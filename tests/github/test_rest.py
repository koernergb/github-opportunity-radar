"""Exhaustive mocked tests for the bounded GitHub REST transport."""

import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from radar.domain.errors import (
    AuthenticationError,
    EntityParseError,
    GitHubAPIError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    TransportError,
)
from radar.github.pagination import paginate_json, parse_link_header
from radar.github.rate_limit import parse_retry_after, retry_delay
from radar.github.rest import GitHubRestTransport

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


async def _no_sleep(delay: float) -> None:
    return None


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_attempts: int = 5,
    sleep: Callable[[float], Any] = _no_sleep,
) -> GitHubRestTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GitHubRestTransport(
        token="github_pat_supersecret",
        api_version="2022-11-28",
        client=client,
        max_attempts=max_attempts,
        sleep=sleep,
        jitter=lambda: 0.25,
        now=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_required_headers_and_etag_are_sent(caplog: pytest.LogCaptureFixture) -> None:
    captured: httpx.Request | None = None
    caplog.set_level(logging.INFO, logger="radar.github")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json={"ok": True})

    response = await _transport(handler).get("/repos/openai/example", etag='"version-1"')

    assert response.data == {"ok": True}
    assert captured is not None
    assert captured.headers["accept"] == "application/vnd.github+json"
    assert captured.headers["authorization"] == "Bearer github_pat_supersecret"
    assert captured.headers["x-github-api-version"] == "2022-11-28"
    assert captured.headers["user-agent"].startswith("github-opportunity-radar/")
    assert captured.headers["if-none-match"] == '"version-1"'
    assert "github_pat_supersecret" not in caplog.text


@pytest.mark.asyncio
async def test_304_is_returned_without_json_decoding() -> None:
    transport = _transport(
        lambda request: httpx.Response(304, headers={"ETag": '"version-1"'}, content=b"")
    )

    response = await transport.get("/repos/openai/example")

    assert response.not_modified
    assert response.data is None
    assert response.headers["etag"] == '"version-1"'


@pytest.mark.asyncio
async def test_401_is_never_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(AuthenticationError) as caught:
        await _transport(handler).get("/rate_limit")

    assert caught.value.status_code == 401
    assert calls == 1


@pytest.mark.asyncio
async def test_permission_403_is_not_misclassified_or_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={"message": "Resource not accessible"})

    with pytest.raises(PermissionDeniedError):
        await _transport(handler).get("/repos/private/repo")

    assert calls == 1


@pytest.mark.asyncio
async def test_rate_limit_403_is_retried_then_typed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "2"},
            json={"message": "API rate limit exceeded"},
        )

    with pytest.raises(RateLimitError) as caught:
        await _transport(handler, max_attempts=2).get("/rate_limit")

    assert calls == 2
    assert caught.value.status_code == 403
    assert caught.value.retry_after_seconds == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503, 504])
async def test_every_retryable_status_can_recover(status_code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status_code, json={"message": "temporary"})
        return httpx.Response(200, json={"recovered": True})

    response = await _transport(handler, max_attempts=2).get("/rate_limit")

    assert response.data == {"recovered": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_after_wins_over_reset_exponential_and_jitter() -> None:
    delays: list[float] = []
    calls = 0

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={
                    "Retry-After": "7",
                    "X-RateLimit-Reset": str(int(NOW.timestamp()) + 500),
                },
                json={"message": "slow down"},
            )
        return httpx.Response(200, json={})

    await _transport(handler, max_attempts=2, sleep=capture_sleep).get("/rate_limit")

    assert delays == [7]


@pytest.mark.asyncio
async def test_transport_errors_are_bounded_and_typed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(TransportError):
        await _transport(handler, max_attempts=3).get("/rate_limit")

    assert calls == 3


@pytest.mark.asyncio
async def test_non_retryable_status_is_typed_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"message": "invalid"})

    with pytest.raises(GitHubAPIError) as caught:
        await _transport(handler).get("/repos/openai/example")

    assert caught.value.status_code == 422
    assert calls == 1


@pytest.mark.asyncio
async def test_404_is_a_typed_not_found_without_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(NotFoundError) as caught:
        await _transport(handler).get("/repos/missing/repo")

    assert caught.value.status_code == 404
    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_json_is_a_parse_error() -> None:
    transport = _transport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            text="{not-json",
        )
    )

    with pytest.raises(EntityParseError):
        await transport.get("/rate_limit")


@pytest.mark.asyncio
async def test_pagination_never_exceeds_max_pages() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        next_page = calls + 1
        return httpx.Response(
            200,
            headers={
                "Link": (
                    f'<https://api.github.com/items?page={next_page}>; rel="next", '
                    '<https://api.github.com/items?page=99>; rel="last"'
                )
            },
            json=[{"page": calls}],
        )

    items = [
        item
        async for item in paginate_json(
            _transport(handler),
            "/items",
            params={"per_page": 100},
            max_pages=2,
        )
    ]

    assert items == [{"page": 1}, {"page": 2}]
    assert calls == 2


@pytest.mark.asyncio
async def test_pagination_stops_on_304() -> None:
    transport = _transport(lambda request: httpx.Response(304))

    items = [item async for item in paginate_json(transport, "/items", max_pages=1)]

    assert items == []


@pytest.mark.asyncio
async def test_pagination_rejects_non_list_and_non_object_payloads() -> None:
    object_transport = _transport(lambda request: httpx.Response(200, json={"not": "a list"}))
    item_transport = _transport(lambda request: httpx.Response(200, json=["not an object"]))

    with pytest.raises(EntityParseError):
        await _consume(paginate_json(object_transport, "/items", max_pages=1))
    with pytest.raises(EntityParseError):
        await _consume(paginate_json(item_transport, "/items", max_pages=1))


async def _consume(iterator: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item async for item in iterator]


def test_link_parser_and_delay_helpers_handle_edge_cases() -> None:
    assert parse_link_header(None) == {}
    assert parse_link_header("invalid") == {}
    assert parse_retry_after("invalid", now=NOW) is None
    assert parse_retry_after("Fri, 24 Jul 2026 12:00:10 GMT", now=NOW) == 10
    assert (
        retry_delay(
            headers={"x-ratelimit-reset": str(int(NOW.timestamp()) + 20)},
            now=NOW,
            attempt=1,
            jitter=99,
            rate_limited=True,
        )
        == 20
    )


@pytest.mark.asyncio
async def test_transport_rejects_untrusted_absolute_urls_and_invalid_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        _transport(lambda request: httpx.Response(200), max_attempts=0)

    transport = _transport(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match=r"api.github.com"):
        await transport.get("https://evil.example/items")
