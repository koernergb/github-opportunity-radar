"""Stable domain enumerations for GitHub observations."""

from enum import StrEnum


class AuthorAssociation(StrEnum):
    """GitHub's relationship between an author and a repository."""

    COLLABORATOR = "COLLABORATOR"
    CONTRIBUTOR = "CONTRIBUTOR"
    FIRST_TIMER = "FIRST_TIMER"
    FIRST_TIME_CONTRIBUTOR = "FIRST_TIME_CONTRIBUTOR"
    MANNEQUIN = "MANNEQUIN"
    MEMBER = "MEMBER"
    NONE = "NONE"
    OWNER = "OWNER"


class IssueState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ReferenceKind(StrEnum):
    ISSUE = "issue"
    PULL_REQUEST = "pull_request"
