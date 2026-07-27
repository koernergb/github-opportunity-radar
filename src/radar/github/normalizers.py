"""Normalize GitHub REST payloads into strict domain DTOs."""

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from radar.domain.errors import EntityParseError
from radar.domain.schemas import ContentDTO, RateLimitDTO, RateLimitWindowDTO, RepositoryDTO


def normalize_repository(payload: dict[str, Any]) -> RepositoryDTO:
    """Normalize a repository REST object while preserving its raw observation."""
    try:
        owner = payload["owner"]
        return RepositoryDTO(
            github_id=payload["id"],
            node_id=payload["node_id"],
            owner=owner["login"],
            name=payload["name"],
            full_name=payload["full_name"],
            url=payload["html_url"],
            description=payload.get("description"),
            default_branch=payload["default_branch"],
            primary_language=payload.get("language"),
            stars=payload.get("stargazers_count", 0),
            forks=payload.get("forks_count", 0),
            archived=payload.get("archived", False),
            disabled=payload.get("disabled", False),
            is_fork=payload.get("fork", False),
            pushed_at=payload.get("pushed_at"),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            raw_payload=payload,
        )
    except (KeyError, TypeError, ValidationError) as error:
        raise EntityParseError("invalid GitHub repository payload") from error


def normalize_rate_limit(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> RateLimitDTO:
    """Normalize selected GitHub rate-limit resource windows."""
    try:
        resources = payload["resources"]
        return RateLimitDTO(
            core=_normalize_window(resources["core"]),
            search=_normalize_window(resources["search"]) if "search" in resources else None,
            graphql=_normalize_window(resources["graphql"]) if "graphql" in resources else None,
            observed_at=observed_at,
            raw_payload=payload,
        )
    except (KeyError, TypeError, ValidationError, ValueError) as error:
        raise EntityParseError("invalid GitHub rate-limit payload") from error


def normalize_content(payload: dict[str, Any]) -> ContentDTO:
    """Normalize a repository contents response."""
    try:
        return ContentDTO(
            path=payload["path"],
            sha=payload["sha"],
            content=payload.get("content"),
            encoding=payload.get("encoding"),
            size=payload["size"],
            download_url=payload.get("download_url"),
            content_type=payload.get("type", "file"),
            raw_payload=payload,
        )
    except (KeyError, TypeError, ValidationError) as error:
        raise EntityParseError("invalid GitHub repository content payload") from error


def _normalize_window(payload: dict[str, Any]) -> RateLimitWindowDTO:
    return RateLimitWindowDTO(
        limit=payload["limit"],
        remaining=payload["remaining"],
        used=payload.get("used"),
        reset_at=datetime.fromtimestamp(payload["reset"], tz=UTC),
    )
