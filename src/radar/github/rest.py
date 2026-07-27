"""Read-only asynchronous GitHub REST transport."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from radar import __version__
from radar.domain.errors import (
    AuthenticationError,
    EntityParseError,
    GitHubAPIError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    TransportError,
)
from radar.github.rate_limit import (
    has_rate_limit_evidence,
    parse_rate_limit_reset,
    retry_delay,
)

JsonValue = Any
Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[], float]
Now = Callable[[], datetime]
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RestResponse:
    """Secret-free response data needed by gateway clients."""

    status_code: int
    data: JsonValue | None
    headers: Mapping[str, str]
    url: str

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


class GitHubRestTransport:
    """Bounded shared-client transport for read-only GitHub requests."""

    def __init__(
        self,
        *,
        token: str | None,
        api_version: str,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 5,
        sleep: Sleep = asyncio.sleep,
        jitter: Jitter = random.random,
        now: Now = lambda: datetime.now(UTC),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._token = token
        self._api_version = api_version
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._jitter = jitter
        self._now = now
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
            follow_redirects=False,
        )
        self._logger = logging.getLogger("radar.github")

    async def __aenter__(self) -> "GitHubRestTransport":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally owned shared client."""
        if self._owns_client:
            await self._client.aclose()

    async def get(
        self,
        path_or_url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        etag: str | None = None,
    ) -> RestResponse:
        """Perform a bounded GET with typed status and retry behavior."""
        url = _validated_api_url(path_or_url)
        headers = self._headers(etag)
        last_transport_error: httpx.TransportError | None = None

        for attempt in range(1, self._max_attempts + 1):
            self._logger.info(
                "github_request",
                extra={"method": "GET", "url": url, "attempt": attempt},
            )
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as error:
                last_transport_error = error
                if attempt == self._max_attempts:
                    break
                await self._sleep(
                    retry_delay(
                        headers={},
                        now=self._now(),
                        attempt=attempt,
                        jitter=self._jitter(),
                        rate_limited=False,
                    )
                )
                continue

            result = self._handle_response(response)
            if result is not None:
                return result

            message = _response_message(response)
            rate_limited = has_rate_limit_evidence(
                response.status_code,
                response.headers,
                message,
            )
            if attempt == self._max_attempts:
                self._raise_status_error(response, message, rate_limited=rate_limited)
            await self._sleep(
                retry_delay(
                    headers=response.headers,
                    now=self._now(),
                    attempt=attempt,
                    jitter=self._jitter(),
                    rate_limited=rate_limited,
                )
            )

        assert last_transport_error is not None
        raise TransportError(f"GitHub request failed: {type(last_transport_error).__name__}")

    def _headers(self, etag: str | None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
            "User-Agent": f"github-opportunity-radar/{__version__}",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    def _handle_response(self, response: httpx.Response) -> RestResponse | None:
        if response.status_code == 304:
            return RestResponse(
                status_code=304,
                data=None,
                headers=response.headers,
                url=str(response.url),
            )
        if 200 <= response.status_code < 300:
            try:
                data = response.json()
            except ValueError as error:
                raise EntityParseError("GitHub returned invalid JSON") from error
            return RestResponse(
                status_code=response.status_code,
                data=data,
                headers=response.headers,
                url=str(response.url),
            )
        if response.status_code == 401:
            raise AuthenticationError(
                _response_message(response),
                status_code=401,
                request_id=response.headers.get("x-github-request-id"),
            )
        if response.status_code == 403 and not has_rate_limit_evidence(
            403, response.headers, _response_message(response)
        ):
            raise PermissionDeniedError(
                _response_message(response),
                status_code=403,
                request_id=response.headers.get("x-github-request-id"),
            )
        if response.status_code == 404:
            raise NotFoundError(
                _response_message(response),
                status_code=404,
                request_id=response.headers.get("x-github-request-id"),
            )
        if response.status_code not in _RETRYABLE_STATUS_CODES and response.status_code != 403:
            raise GitHubAPIError(
                _response_message(response),
                status_code=response.status_code,
                request_id=response.headers.get("x-github-request-id"),
            )
        return None

    def _raise_status_error(
        self,
        response: httpx.Response,
        message: str,
        *,
        rate_limited: bool,
    ) -> None:
        request_id = response.headers.get("x-github-request-id")
        if rate_limited:
            delay = retry_delay(
                headers=response.headers,
                now=self._now(),
                attempt=self._max_attempts,
                jitter=0,
                rate_limited=True,
            )
            raise RateLimitError(
                message,
                reset_at=parse_rate_limit_reset(response.headers.get("x-ratelimit-reset")),
                retry_after_seconds=delay,
                request_id=request_id,
                status_code=response.status_code,
            )
        raise GitHubAPIError(message, status_code=response.status_code, request_id=request_id)


def _validated_api_url(path_or_url: str) -> str:
    url = urljoin("https://api.github.com/", path_or_url.lstrip("/"))
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or parsed.username is not None
        or parsed.port is not None
    ):
        raise ValueError("GitHub API URL must use https://api.github.com")
    return url


def _response_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"GitHub returned HTTP {response.status_code}"
    if isinstance(data, dict):
        message = data.get("message")
        if isinstance(message, str):
            return message
    return f"GitHub returned HTTP {response.status_code}"
