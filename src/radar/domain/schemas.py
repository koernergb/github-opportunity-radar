"""Transport-neutral DTOs and validated GitHub entity references."""

import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.domain.enums import AuthorAssociation, IssueState, PullRequestState, ReferenceKind

JsonObject = dict[str, Any]
_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
_REPOSITORY = r"[A-Za-z0-9_.-]{1,100}"
_FULL_NAME_RE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repository>{_REPOSITORY})$")
_SHORT_REFERENCE_RE = re.compile(
    rf"^(?P<full_name>{_OWNER}/{_REPOSITORY})#(?P<number>[1-9][0-9]*)$"
)


class DTO(BaseModel):
    """Immutable DTO base that tolerates new, undocumented upstream keys."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class UserDTO(DTO):
    login: str
    github_id: int | None = None
    node_id: str | None = None
    user_type: str | None = None


class LabelDTO(DTO):
    name: str
    color: str | None = None
    description: str | None = None


class RepositoryDTO(DTO):
    github_id: int
    node_id: str
    owner: str
    name: str
    full_name: str
    url: str
    description: str | None = None
    default_branch: str
    primary_language: str | None = None
    stars: int = Field(ge=0)
    forks: int = Field(ge=0)
    archived: bool = False
    disabled: bool = False
    is_fork: bool = False
    pushed_at: AwareDatetime | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    raw_payload: JsonObject = Field(default_factory=dict)

    @field_validator("full_name")
    @classmethod
    def full_name_must_be_valid(cls, value: str) -> str:
        validate_repository_name(value)
        return value


class IssueDTO(DTO):
    github_id: int
    node_id: str
    repository: str
    number: int = Field(gt=0)
    title: str
    body: str | None = None
    state: IssueState
    state_reason: str | None = None
    url: str
    author: UserDTO | None = None
    author_association: AuthorAssociation | None = None
    locked: bool = False
    comment_count: int = Field(default=0, ge=0)
    labels: tuple[LabelDTO, ...] = ()
    assignees: tuple[UserDTO, ...] = ()
    created_at: AwareDatetime
    updated_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    is_pull_request: bool = False
    raw_payload: JsonObject = Field(default_factory=dict)

    @field_validator("repository")
    @classmethod
    def repository_must_be_valid(cls, value: str) -> str:
        validate_repository_name(value)
        return value


class IssueCommentDTO(DTO):
    github_id: int
    node_id: str
    issue_number: int = Field(gt=0)
    body: str
    url: str
    author: UserDTO | None = None
    author_association: AuthorAssociation | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    raw_payload: JsonObject = Field(default_factory=dict)


class TimelineEventDTO(DTO):
    event_id: str
    event_type: str
    created_at: AwareDatetime | None = None
    actor: UserDTO | None = None
    source_repository: str | None = None
    source_number: int | None = Field(default=None, gt=0)
    source_type: str | None = None
    state: str | None = None
    merged: bool | None = None
    url: str | None = None
    raw_payload: JsonObject = Field(default_factory=dict)


class PullRequestDTO(DTO):
    github_id: int
    node_id: str
    repository: str
    number: int = Field(gt=0)
    title: str
    body: str | None = None
    url: str
    author: UserDTO | None = None
    author_association: AuthorAssociation | None = None
    state: PullRequestState
    draft: bool = False
    merged: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    merged_at: AwareDatetime | None = None
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    changed_files: int | None = Field(default=None, ge=0)
    commit_count: int | None = Field(default=None, ge=0)
    comment_count: int | None = Field(default=None, ge=0)
    review_comment_count: int | None = Field(default=None, ge=0)
    raw_payload: JsonObject = Field(default_factory=dict)

    @field_validator("repository")
    @classmethod
    def repository_must_be_valid(cls, value: str) -> str:
        validate_repository_name(value)
        return value


class ReviewDTO(DTO):
    github_id: int
    node_id: str
    pull_request_number: int = Field(gt=0)
    author: UserDTO | None = None
    author_association: AuthorAssociation | None = None
    state: str
    body: str | None = None
    submitted_at: AwareDatetime | None = None
    raw_payload: JsonObject = Field(default_factory=dict)


class ContentDTO(DTO):
    path: str
    sha: str
    content: str | None = None
    encoding: str | None = None
    size: int = Field(ge=0)
    download_url: str | None = None
    content_type: str = "file"
    raw_payload: JsonObject = Field(default_factory=dict)


class RateLimitWindowDTO(DTO):
    limit: int = Field(ge=0)
    remaining: int = Field(ge=0)
    used: int | None = Field(default=None, ge=0)
    reset_at: AwareDatetime


class RateLimitDTO(DTO):
    core: RateLimitWindowDTO
    search: RateLimitWindowDTO | None = None
    graphql: RateLimitWindowDTO | None = None
    observed_at: AwareDatetime
    raw_payload: JsonObject = Field(default_factory=dict)


class PageMetadata(DTO):
    """Observable bounds and continuation state for a traversed page."""

    page_number: int = Field(ge=1)
    item_count: int = Field(ge=0)
    max_pages: int = Field(ge=1)
    has_next: bool
    next_url: str | None = None
    etag: str | None = None

    @model_validator(mode="after")
    def page_must_fit_bound(self) -> "PageMetadata":
        if self.page_number > self.max_pages:
            raise ValueError("page_number cannot exceed max_pages")
        return self


class GitHubReference(DTO):
    """Canonical issue or pull-request identity."""

    repository: str
    number: int = Field(gt=0)
    kind: ReferenceKind

    @field_validator("repository")
    @classmethod
    def repository_must_be_valid(cls, value: str) -> str:
        validate_repository_name(value)
        return value

    @property
    def display_name(self) -> str:
        return f"{self.repository}#{self.number}"


def validate_repository_name(value: str) -> str:
    """Validate a canonical GitHub `owner/repository` name."""
    match = _FULL_NAME_RE.fullmatch(value)
    if (
        match is None
        or "--" in match.group("owner")
        or match.group("repository") in {".", ".."}
        or match.group("repository").casefold().endswith(".git")
    ):
        raise ValueError("must be a GitHub repository name in 'owner/repo' form")
    return value


def parse_issue_reference(value: str) -> GitHubReference:
    """Parse `owner/repo#123` as an issue reference."""
    match = _SHORT_REFERENCE_RE.fullmatch(value)
    if match is None:
        raise ValueError("must be an issue reference in 'owner/repo#123' form")
    repository = validate_repository_name(match.group("full_name"))
    return GitHubReference(
        repository=repository,
        number=int(match.group("number")),
        kind=ReferenceKind.ISSUE,
    )


def parse_github_url(value: str) -> GitHubReference:
    """Parse an official GitHub issue or pull-request URL."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "www.github.com"}
        or parsed.username is not None
        or parsed.port is not None
    ):
        raise ValueError("must be an HTTPS github.com issue or pull-request URL")

    parts = parsed.path.strip("/").split("/")
    if len(parts) != 4 or parts[2] not in {"issues", "pull"}:
        raise ValueError("must be a GitHub issue or pull-request URL")
    repository = validate_repository_name(f"{parts[0]}/{parts[1]}")
    if not parts[3].isdigit() or int(parts[3]) <= 0:
        raise ValueError("GitHub issue or pull-request number must be positive")
    kind = ReferenceKind.ISSUE if parts[2] == "issues" else ReferenceKind.PULL_REQUEST
    return GitHubReference(repository=repository, number=int(parts[3]), kind=kind)
