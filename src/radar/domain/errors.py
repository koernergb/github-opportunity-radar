"""Typed errors shared across transport-independent domain services."""

from datetime import datetime


class RadarError(Exception):
    """Base error for expected application failures."""


class GitHubError(RadarError):
    """Base error for failures reported by the GitHub gateway."""


class GitHubAPIError(GitHubError):
    """Unexpected GitHub API response without transport-library coupling."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id


class AuthenticationError(GitHubAPIError):
    """Credentials are missing or invalid."""


class PermissionDeniedError(GitHubAPIError):
    """Credentials are valid but cannot access the requested resource."""


class NotFoundError(GitHubAPIError):
    """The requested GitHub resource does not exist or is inaccessible."""


class RateLimitError(GitHubAPIError):
    """GitHub rate limits prevent the operation from proceeding immediately."""

    def __init__(
        self,
        message: str,
        *,
        reset_at: datetime | None = None,
        retry_after_seconds: float | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=403, request_id=request_id)
        self.reset_at = reset_at
        self.retry_after_seconds = retry_after_seconds


class EntityParseError(GitHubError):
    """An upstream entity could not be converted into a valid DTO."""


class PaginationLimitError(GitHubError):
    """A bounded traversal reached its configured page or item limit."""
