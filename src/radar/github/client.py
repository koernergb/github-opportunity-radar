"""Typed GitHub gateway endpoints built on the shared REST transport."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from radar.domain.errors import EntityParseError, NotFoundError
from radar.domain.schemas import (
    ContentDTO,
    RateLimitDTO,
    RepositoryDTO,
    validate_repository_name,
)
from radar.github.normalizers import normalize_content, normalize_rate_limit, normalize_repository
from radar.github.rest import GitHubRestTransport


class GitHubClient:
    """Read-only typed endpoints implemented in the current task card."""

    def __init__(
        self,
        transport: GitHubRestTransport,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._transport = transport
        self._now = now

    async def get_repository(self, full_name: str) -> RepositoryDTO:
        validate_repository_name(full_name)
        owner, repository = full_name.split("/")
        path = f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"
        response = await self._transport.get(path)
        return normalize_repository(_require_object(response.data))

    async def get_rate_limit(self) -> RateLimitDTO:
        response = await self._transport.get("/rate_limit")
        return normalize_rate_limit(_require_object(response.data), observed_at=self._now())

    async def get_repository_content(self, full_name: str, path: str) -> ContentDTO | None:
        """Fetch one optional repository document without treating 404 as failure."""
        validate_repository_name(full_name)
        owner, repository = full_name.split("/")
        repository_path = f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"
        endpoint = (
            f"{repository_path}/readme"
            if path == "README"
            else f"{repository_path}/contents/{quote(path, safe='/')}"
        )
        try:
            response = await self._transport.get(endpoint)
        except NotFoundError:
            return None
        return normalize_content(_require_object(response.data))


def _require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EntityParseError("GitHub response must be a JSON object")
    return value
