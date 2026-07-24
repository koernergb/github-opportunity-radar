"""Dependency-inversion protocols for external gateways."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from radar.domain.schemas import (
    ContentDTO,
    IssueCommentDTO,
    IssueDTO,
    PullRequestDTO,
    RateLimitDTO,
    RepositoryDTO,
    ReviewDTO,
    TimelineEventDTO,
)


class GitHubGateway(Protocol):
    """Read-only GitHub operations consumed by domain and ingestion services."""

    async def get_repository(self, full_name: str) -> RepositoryDTO: ...

    async def list_issues(
        self,
        full_name: str,
        *,
        state: str,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueDTO]: ...

    async def list_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        since: datetime | None,
        max_pages: int,
    ) -> AsyncIterator[IssueCommentDTO]: ...

    async def list_issue_timeline(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[TimelineEventDTO]: ...

    async def list_pull_requests(
        self,
        full_name: str,
        *,
        state: str,
        max_items: int,
    ) -> AsyncIterator[PullRequestDTO]: ...

    async def get_pull_request(self, full_name: str, number: int) -> PullRequestDTO: ...

    async def list_pull_request_reviews(
        self,
        full_name: str,
        number: int,
        *,
        max_pages: int,
    ) -> AsyncIterator[ReviewDTO]: ...

    async def get_repository_content(self, full_name: str, path: str) -> ContentDTO | None: ...

    async def get_rate_limit(self) -> RateLimitDTO: ...
