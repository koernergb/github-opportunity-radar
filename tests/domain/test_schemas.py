"""Tests for transport-neutral GitHub DTOs and references."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from radar.domain.enums import IssueState, ReferenceKind
from radar.domain.errors import AuthenticationError, RateLimitError
from radar.domain.schemas import (
    IssueDTO,
    PageMetadata,
    RepositoryDTO,
    parse_github_url,
    parse_issue_reference,
    validate_repository_name,
)

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def test_repository_dto_tolerates_documented_optional_and_future_fields() -> None:
    repository = RepositoryDTO.model_validate(
        {
            "github_id": 1,
            "node_id": "R_1",
            "owner": "openai",
            "name": "example",
            "full_name": "openai/example",
            "url": "https://github.com/openai/example",
            "default_branch": "main",
            "stars": 1,
            "forks": 0,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
            "future_github_field": {"safe": True},
        }
    )

    assert repository.description is None
    assert repository.pushed_at is None
    assert repository.created_at.tzinfo is not None
    assert not hasattr(repository, "future_github_field")


def test_issue_dto_tolerates_optional_fields() -> None:
    issue = IssueDTO(
        github_id=2,
        node_id="I_2",
        repository="openai/example",
        number=12,
        title="Specific bug",
        state=IssueState.OPEN,
        url="https://github.com/openai/example/issues/12",
        created_at=NOW,
        updated_at=NOW,
    )

    assert issue.body is None
    assert issue.author is None
    assert issue.labels == ()
    assert issue.assignees == ()
    assert issue.is_pull_request is False


@pytest.mark.parametrize(
    ("value", "repository", "number"),
    [
        ("openai/example#1", "openai/example", 1),
        ("ml-explore/mlx-lm#12345", "ml-explore/mlx-lm", 12345),
        ("Owner/repo.name#42", "Owner/repo.name", 42),
    ],
)
def test_parse_short_issue_reference(value: str, repository: str, number: int) -> None:
    reference = parse_issue_reference(value)

    assert reference.repository == repository
    assert reference.number == number
    assert reference.kind is ReferenceKind.ISSUE
    assert reference.display_name == f"{repository}#{number}"


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("https://github.com/openai/example/issues/12", ReferenceKind.ISSUE),
        ("https://github.com/openai/example/pull/44", ReferenceKind.PULL_REQUEST),
        ("https://www.github.com/openai/example/issues/3?notification=1", ReferenceKind.ISSUE),
    ],
)
def test_parse_github_issue_and_pull_urls(value: str, kind: ReferenceKind) -> None:
    reference = parse_github_url(value)

    assert reference.repository == "openai/example"
    assert reference.kind is kind


@pytest.mark.parametrize(
    "value",
    [
        "",
        "owner/repo",
        "owner/repo#0",
        "owner/repo#-1",
        "owner//repo#1",
        "-owner/repo#1",
        "owner--name/repo#1",
        "owner/repo.git#1",
        "owner/repo#1 trailing",
    ],
)
def test_invalid_short_identities_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_issue_reference(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/openai/example/issues/1",
        "https://example.com/openai/example/issues/1",
        "https://user@github.com/openai/example/issues/1",
        "https://github.com/openai/example/issues/0",
        "https://github.com/openai/example/discussions/1",
        "https://github.com/openai/example/issues/not-a-number",
        "https://github.com/openai/example/issues/1/extra",
    ],
)
def test_invalid_github_urls_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_github_url(value)


@pytest.mark.parametrize("value", ["owner/.", "owner/..", "owner/repo.git", "one/two/three"])
def test_invalid_repository_names_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        validate_repository_name(value)


def test_page_metadata_enforces_positive_bounds() -> None:
    page = PageMetadata(page_number=2, item_count=30, max_pages=3, has_next=True)

    assert page.item_count == 30
    with pytest.raises(ValidationError):
        PageMetadata(page_number=0, item_count=0, max_pages=1, has_next=False)
    with pytest.raises(ValidationError, match="cannot exceed"):
        PageMetadata(page_number=2, item_count=0, max_pages=1, has_next=False)


def test_dto_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        RepositoryDTO(
            github_id=1,
            node_id="R_1",
            owner="openai",
            name="example",
            full_name="openai/example",
            url="https://github.com/openai/example",
            default_branch="main",
            stars=0,
            forks=0,
            created_at=datetime(2026, 7, 24),
            updated_at=NOW,
        )


def test_typed_rate_limit_and_authentication_errors_preserve_context() -> None:
    authentication = AuthenticationError("bad token", status_code=401, request_id="request-1")
    rate_limit = RateLimitError(
        "wait",
        reset_at=NOW,
        retry_after_seconds=2.5,
        request_id="request-2",
    )

    assert authentication.status_code == 401
    assert authentication.request_id == "request-1"
    assert rate_limit.status_code == 403
    assert rate_limit.reset_at == NOW
    assert rate_limit.retry_after_seconds == 2.5


def test_domain_package_has_no_http_client_dependency() -> None:
    domain_root = Path("src/radar/domain")
    source = "\n".join(path.read_text(encoding="utf-8") for path in domain_root.glob("*.py"))

    assert "import httpx" not in source
    assert "from httpx" not in source
