"""Transport-independent domain types and protocols."""

from radar.domain.protocols import GitHubGateway
from radar.domain.schemas import GitHubReference, parse_github_url, parse_issue_reference

__all__ = ["GitHubGateway", "GitHubReference", "parse_github_url", "parse_issue_reference"]
