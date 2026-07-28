"""Typed GitHub gateway endpoints built on the shared REST transport."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from radar.domain.errors import EntityParseError, NotFoundError
from radar.domain.schemas import (
    ContentDTO,
    IssueCommentDTO,
    IssueDTO,
    RateLimitDTO,
    RepositoryDTO,
    validate_repository_name,
)
from radar.github.normalizers import (
    normalize_content,
    normalize_issue,
    normalize_issue_comment,
    normalize_rate_limit,
    normalize_repository,
)
from radar.github.pagination import paginate_json
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

    async def list_issues(
        self,
        full_name: str,
        *,
        state: str,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueDTO]:
        """Return a bounded iterator over issue-shaped REST objects."""
        validate_repository_name(full_name)
        owner, repository = full_name.split("/")
        params: dict[str, str | int] = {
            "state": state,
            "sort": "updated",
            "direction": "asc",
            "per_page": 100,
        }
        if since is not None:
            params["since"] = since.isoformat().replace("+00:00", "Z")

        async def generate() -> AsyncIterator[IssueDTO]:
            async for payload in paginate_json(
                self._transport,
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/issues",
                params=params,
                max_pages=max_pages,
            ):
                yield normalize_issue(payload, repository=full_name)

        return generate()

    async def list_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueCommentDTO]:
        """Return a bounded iterator over one issue's comments."""
        validate_repository_name(full_name)
        owner, repository = full_name.split("/")
        params: dict[str, str | int] = {"per_page": 100}
        if since is not None:
            params["since"] = since.isoformat().replace("+00:00", "Z")

        async def generate() -> AsyncIterator[IssueCommentDTO]:
            path = (
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"
                f"/issues/{number}/comments"
            )
            async for payload in paginate_json(
                self._transport,
                path,
                params=params,
                max_pages=max_pages,
            ):
                yield normalize_issue_comment(payload, issue_number=number)

        return generate()


def _require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EntityParseError("GitHub response must be a JSON object")
    return value
