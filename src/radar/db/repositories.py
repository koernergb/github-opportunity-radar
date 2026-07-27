"""Transactional upserts for repository observations and configuration."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.db.models import Repository, RepositoryConfig, RepositoryDocument
from radar.domain.schemas import ContentDTO, RepositoryDTO
from radar.settings import GitHubSettings, RepositorySettings


@dataclass(frozen=True)
class RepositoryUpsert:
    repository: Repository
    created: bool
    changed: bool


def upsert_repository(
    session: Session,
    observation: RepositoryDTO,
    configured: RepositorySettings,
    github_settings: GitHubSettings,
    *,
    synced_at: datetime,
) -> RepositoryUpsert:
    """Upsert mutable observations by immutable GitHub ID."""
    repository = session.scalar(
        select(Repository).where(Repository.github_id == observation.github_id)
    )
    created = repository is None
    if repository is None:
        repository = Repository(
            github_id=observation.github_id,
            node_id=observation.node_id,
            owner=observation.owner,
            name=observation.name,
            full_name=observation.full_name,
            url=observation.url,
            description=observation.description,
            default_branch=observation.default_branch,
            primary_language=observation.primary_language,
            stars=observation.stars,
            forks=observation.forks,
            archived=observation.archived,
            disabled=observation.disabled,
            is_fork=observation.is_fork,
            pushed_at=observation.pushed_at,
            github_created_at=observation.created_at,
            github_updated_at=observation.updated_at,
            last_synced_at=synced_at,
            raw_json=observation.raw_payload,
        )
        session.add(repository)
        session.flush()
        observation_changed = True
    else:
        values = _repository_values(observation)
        observation_changed = any(
            getattr(repository, key) != value for key, value in values.items()
        )
        for key, value in values.items():
            setattr(repository, key, value)
        repository.last_synced_at = synced_at

    repository_config = session.scalar(
        select(RepositoryConfig).where(RepositoryConfig.repository_id == repository.id)
    )
    config_values = _config_values(configured, github_settings)
    if repository_config is None:
        session.add(RepositoryConfig(repository_id=repository.id, **config_values))
        config_changed = True
    else:
        config_changed = any(
            getattr(repository_config, key) != value for key, value in config_values.items()
        )
        for key, value in config_values.items():
            setattr(repository_config, key, value)

    return RepositoryUpsert(
        repository=repository,
        created=created,
        changed=observation_changed or config_changed,
    )


def store_repository_document(
    session: Session,
    repository_id: UUID,
    content: ContentDTO,
    *,
    document_type: str,
    decoded_text: str,
    fetched_at: datetime,
) -> bool:
    """Store a SHA-versioned document, returning false on an exact cache hit."""
    existing = session.scalar(
        select(RepositoryDocument).where(
            RepositoryDocument.repository_id == repository_id,
            RepositoryDocument.document_type == document_type,
            RepositoryDocument.path == content.path,
            RepositoryDocument.sha == content.sha,
        )
    )
    if existing is not None:
        return False
    session.add(
        RepositoryDocument(
            repository_id=repository_id,
            document_type=document_type,
            path=content.path,
            sha=content.sha,
            decoded_text=decoded_text,
            fetched_at=fetched_at,
        )
    )
    return True


def _repository_values(observation: RepositoryDTO) -> dict[str, object]:
    return {
        "node_id": observation.node_id,
        "owner": observation.owner,
        "name": observation.name,
        "full_name": observation.full_name,
        "url": observation.url,
        "description": observation.description,
        "default_branch": observation.default_branch,
        "primary_language": observation.primary_language,
        "stars": observation.stars,
        "forks": observation.forks,
        "archived": observation.archived,
        "disabled": observation.disabled,
        "is_fork": observation.is_fork,
        "pushed_at": observation.pushed_at,
        "github_created_at": observation.created_at,
        "github_updated_at": observation.updated_at,
        "raw_json": observation.raw_payload,
    }


def _config_values(
    configured: RepositorySettings,
    github_settings: GitHubSettings,
) -> dict[str, object]:
    return {
        "enabled": configured.enabled,
        "include_labels": list(configured.include_labels),
        "exclude_labels": list(configured.exclude_labels),
        "min_issue_age_minutes": configured.min_issue_age_minutes,
        "max_issue_age_days": configured.max_issue_age_days,
        "max_estimated_hours": configured.max_estimated_hours,
        "pr_history_limit": github_settings.pr_history_limit,
        "pr_history_days": github_settings.pr_history_days,
        "custom_weights": configured.custom_weights,
    }
