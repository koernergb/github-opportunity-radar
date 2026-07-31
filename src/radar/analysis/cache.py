"""Version-aware persisted analysis cache lookup."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import IssueAnalysis


def find_cached_analysis(
    session: Session,
    *,
    issue_id: UUID,
    content_hash: str,
    schema_version: str,
    prompt_version: str,
    provider: str,
    model_version: str,
) -> IssueAnalysis | None:
    """Return a reusable successful or deterministic-fallback analysis."""
    return session.scalar(
        select(IssueAnalysis).where(
            IssueAnalysis.issue_id == issue_id,
            IssueAnalysis.content_hash == content_hash,
            IssueAnalysis.schema_version == schema_version,
            IssueAnalysis.prompt_version == prompt_version,
            IssueAnalysis.provider == provider,
            IssueAnalysis.model_version == model_version,
            IssueAnalysis.status.in_({"success", "fallback"}),
        )
    )
