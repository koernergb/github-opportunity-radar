"""Tests for typed repository and rate-limit gateway endpoints."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from radar.domain.errors import EntityParseError
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def _repository_payload() -> dict[str, Any]:
    return {
        "id": 1,
        "node_id": "R_1",
        "owner": {"login": "openai"},
        "name": "example",
        "full_name": "openai/example",
        "html_url": "https://github.com/openai/example",
        "description": None,
        "default_branch": "main",
        "language": "Python",
        "stargazers_count": 20,
        "forks_count": 3,
        "archived": False,
        "disabled": False,
        "fork": False,
        "pushed_at": NOW.isoformat(),
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _transport(handler: Any) -> GitHubRestTransport:
    return GitHubRestTransport(
        token=None,
        api_version="2022-11-28",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_repository_endpoint_normalizes_and_preserves_raw_payload() -> None:
    payload = _repository_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/openai/example"
        return httpx.Response(200, json=payload)

    repository = await GitHubClient(_transport(handler)).get_repository("openai/example")

    assert repository.full_name == "openai/example"
    assert repository.primary_language == "Python"
    assert repository.raw_payload == payload


@pytest.mark.asyncio
async def test_rate_limit_endpoint_normalizes_windows() -> None:
    payload = {
        "resources": {
            "core": {"limit": 5000, "remaining": 4999, "used": 1, "reset": 1784898000},
            "search": {"limit": 30, "remaining": 30, "used": 0, "reset": 1784898000},
        }
    }

    rate = await GitHubClient(
        _transport(lambda request: httpx.Response(200, json=payload)),
        now=lambda: NOW,
    ).get_rate_limit()

    assert rate.core.limit == 5000
    assert rate.core.remaining == 4999
    assert rate.search is not None
    assert rate.graphql is None
    assert rate.observed_at == NOW
    assert rate.raw_payload == payload


@pytest.mark.asyncio
async def test_endpoint_rejects_invalid_object_payload() -> None:
    client = GitHubClient(_transport(lambda request: httpx.Response(200, json=[])))

    with pytest.raises(EntityParseError):
        await client.get_rate_limit()


@pytest.mark.asyncio
async def test_repository_normalizer_wraps_missing_required_fields() -> None:
    client = GitHubClient(_transport(lambda request: httpx.Response(200, json={"id": 1})))

    with pytest.raises(EntityParseError, match="repository payload"):
        await client.get_repository("openai/example")


@pytest.mark.asyncio
async def test_repository_content_endpoint_normalizes_file() -> None:
    payload = {
        "path": ".github/CONTRIBUTING.md",
        "sha": "abc",
        "content": "IyBIZWxsbw==",
        "encoding": "base64",
        "size": 7,
        "type": "file",
        "download_url": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/openai/example/contents/.github/CONTRIBUTING.md"
        return httpx.Response(200, json=payload)

    content = await GitHubClient(_transport(handler)).get_repository_content(
        "openai/example",
        ".github/CONTRIBUTING.md",
    )

    assert content is not None
    assert content.sha == "abc"
    assert content.raw_payload == payload


@pytest.mark.asyncio
async def test_missing_repository_content_is_normal() -> None:
    client = GitHubClient(
        _transport(lambda request: httpx.Response(404, json={"message": "Not Found"}))
    )

    assert await client.get_repository_content("openai/example", "SECURITY.md") is None


@pytest.mark.asyncio
async def test_readme_uses_special_github_endpoint() -> None:
    payload = {
        "path": "README.rst",
        "sha": "readme",
        "content": "UmVhZG1l",
        "encoding": "base64",
        "size": 6,
        "type": "file",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/openai/example/readme"
        return httpx.Response(200, json=payload)

    content = await GitHubClient(_transport(handler)).get_repository_content(
        "openai/example",
        "README",
    )

    assert content is not None
    assert content.path == "README.rst"


@pytest.mark.asyncio
async def test_issue_and_comment_endpoints_are_bounded_and_normalized() -> None:
    issue_payload = {
        "id": 10,
        "node_id": "I_10",
        "number": 7,
        "title": "Bug",
        "body": None,
        "state": "open",
        "html_url": "https://github.com/openai/example/issues/7",
        "user": {"login": "author", "id": 2, "node_id": "U_2", "type": "User"},
        "author_association": "CONTRIBUTOR",
        "labels": [{"name": "bug", "color": "ff0000"}],
        "assignees": [],
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        "comments": 1,
        "pull_request": {"url": "https://api.github.com/repos/openai/example/pulls/7"},
    }
    comment_payload = {
        "id": 20,
        "node_id": "IC_20",
        "body": "Updated",
        "html_url": "https://github.com/openai/example/issues/7#issuecomment-20",
        "user": {"login": "maintainer"},
        "author_association": "MEMBER",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            assert request.url.params["per_page"] == "100"
            return httpx.Response(200, json=[comment_payload])
        assert request.url.params["state"] == "open"
        assert request.url.params["since"].endswith("Z")
        return httpx.Response(200, json=[issue_payload])

    client = GitHubClient(_transport(handler))
    issues = [
        item
        async for item in await client.list_issues(
            "openai/example",
            state="open",
            since=NOW,
            max_pages=1,
        )
    ]
    comments = [
        item
        async for item in await client.list_issue_comments(
            "openai/example",
            7,
            since=None,
            max_pages=1,
        )
    ]

    assert issues[0].is_pull_request is True
    assert issues[0].labels[0].name == "bug"
    assert comments[0].body == "Updated"
    assert comments[0].author_association is not None
