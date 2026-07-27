"""Bounded Link-header pagination for GitHub list endpoints."""

import re
from collections.abc import AsyncIterator, Mapping
from typing import Any

from radar.domain.errors import EntityParseError
from radar.github.rest import GitHubRestTransport

_LINK_RE = re.compile(r'<(?P<url>[^>]+)>\s*;\s*rel="(?P<relation>[^"]+)"')


def parse_link_header(value: str | None) -> dict[str, str]:
    """Parse GitHub Link relations without following unrecognized values."""
    if not value:
        return {}
    return {
        match.group("relation"): match.group("url")
        for part in value.split(",")
        if (match := _LINK_RE.search(part.strip())) is not None
    }


async def paginate_json(
    transport: GitHubRestTransport,
    path: str,
    *,
    params: Mapping[str, str | int] | None = None,
    max_pages: int,
    etag: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects while never traversing beyond `max_pages`."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")

    next_url: str | None = path
    page = 0
    while next_url is not None and page < max_pages:
        page += 1
        response = await transport.get(
            next_url,
            params=params if page == 1 else None,
            etag=etag if page == 1 else None,
        )
        if response.not_modified:
            return
        if not isinstance(response.data, list):
            raise EntityParseError("paginated GitHub response must be a JSON list")
        for item in response.data:
            if not isinstance(item, dict):
                raise EntityParseError("paginated GitHub items must be JSON objects")
            yield item
        next_url = parse_link_header(response.headers.get("link")).get("next")
