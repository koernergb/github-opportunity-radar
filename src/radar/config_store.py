"""Immutable configuration revisions shared by CLI, API, and pipeline callers."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.db.models import ConfigActivation, ConfigRevision
from radar.settings import RadarConfig

CONFIG_REVISION_SCHEMA_VERSION = "config_revision_v1"
ConfigSource = Literal["bootstrap", "manual", "assistant", "imported", "undo"]
_SECRET_KEYS = {"github_token", "openai_api_key", "authorization"}


class ConfigConflictError(RuntimeError):
    """The active revision changed since a caller read it."""


class ConfigNotFoundError(LookupError):
    """A requested configuration revision does not exist."""


class InvalidRevisionError(ValueError):
    """An invalid revision cannot become active."""


class SecretInConfigError(ValueError):
    """Secret-shaped fields are forbidden in revision payloads."""


@dataclass(frozen=True)
class RevisionView:
    """Transport-neutral revision with derived validation state."""

    revision_id: UUID
    valid: bool
    config_hash: str | None
    profile_hash: str | None
    source: str
    summary: str
    created_at: datetime
    activated_at: datetime | None
    supersedes_id: UUID | None
    validation_errors: tuple[dict[str, Any], ...]


class ConfigurationStore(Protocol):
    """Common active-configuration interface for every application surface."""

    def active_config(self) -> RadarConfig | None: ...

    def active_revision(self) -> ConfigRevision | None: ...


class SqlAlchemyConfigurationStore:
    """SQL-backed append-only configuration revision store."""

    def __init__(self, sessions: sessionmaker[Session], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    def create_revision(
        self,
        payload: object,
        *,
        source: ConfigSource,
        summary: str,
        supersedes_id: UUID | None = None,
    ) -> ConfigRevision:
        _reject_secrets(payload)
        config, errors = _validate(payload)
        normalized = (
            config.model_dump(mode="json") if config is not None else _json_payload(payload)
        )
        revision = ConfigRevision(
            schema_version=CONFIG_REVISION_SCHEMA_VERSION,
            payload=normalized,
            yaml_text=_dump_yaml(normalized),
            valid=config is not None,
            validation_errors=errors,
            config_hash=config.config_hash if config is not None else None,
            profile_hash=config.profile_hash if config is not None else None,
            source=source,
            summary=summary,
            supersedes_id=supersedes_id,
            created_at=self._clock.now(),
        )
        with self._sessions.begin() as session:
            session.add(revision)
        return revision

    def import_yaml(
        self, yaml_text: str, *, source: ConfigSource = "imported", summary: str = "Imported YAML"
    ) -> ConfigRevision:
        try:
            payload = yaml.safe_load(yaml_text)
        except yaml.YAMLError as error:
            del error
            payload = {"parse_error": "invalid_yaml"}
            return self.create_revision(payload, source=source, summary=summary)
        return self.create_revision(payload, source=source, summary=summary)

    def bootstrap(self, path: Path) -> ConfigRevision | None:
        if self.active_revision() is not None or not path.exists():
            return None
        revision = self.import_yaml(
            path.read_text(encoding="utf-8"), source="bootstrap", summary=f"Bootstrap from {path}"
        )
        if revision.valid:
            self.activate(revision.id, expected_active_id=None)
        return revision

    def activate(self, revision_id: UUID, *, expected_active_id: UUID | None) -> ConfigActivation:
        with self._sessions.begin() as session:
            current = _active_revision(session)
            current_id = current.id if current is not None else None
            if current_id != expected_active_id:
                raise ConfigConflictError("active configuration changed")
            revision = session.get(ConfigRevision, revision_id)
            if revision is None:
                raise ConfigNotFoundError(str(revision_id))
            if not revision.valid:
                raise InvalidRevisionError("invalid revision cannot be activated")
            activation = ConfigActivation(
                revision_id=revision.id,
                previous_revision_id=current_id,
                created_at=self._clock.now(),
            )
            session.add(activation)
        return activation

    def active_revision(self) -> ConfigRevision | None:
        with self._sessions() as session:
            return _active_revision(session)

    def active_config(self) -> RadarConfig | None:
        revision = self.active_revision()
        return RadarConfig.model_validate(revision.payload) if revision is not None else None

    def export_yaml(self) -> str:
        revision = self.active_revision()
        if revision is None:
            raise ConfigNotFoundError("no active configuration")
        return revision.yaml_text

    def list_revisions(self) -> list[RevisionView]:
        with self._sessions() as session:
            revisions = list(
                session.scalars(select(ConfigRevision).order_by(ConfigRevision.created_at.desc()))
            )
            activations = list(session.scalars(select(ConfigActivation)))
        activated = {item.revision_id: item.created_at for item in activations}
        return [
            RevisionView(
                revision_id=item.id,
                valid=item.valid,
                config_hash=item.config_hash,
                profile_hash=item.profile_hash,
                source=item.source,
                summary=item.summary,
                created_at=item.created_at,
                activated_at=activated.get(item.id),
                supersedes_id=item.supersedes_id,
                validation_errors=tuple(item.validation_errors),
            )
            for item in revisions
        ]


def _active_revision(session: Session) -> ConfigRevision | None:
    activation = session.scalar(
        select(ConfigActivation).order_by(
            ConfigActivation.created_at.desc(), ConfigActivation.id.desc()
        )
    )
    return session.get(ConfigRevision, activation.revision_id) if activation is not None else None


def _validate(payload: object) -> tuple[RadarConfig | None, list[dict[str, Any]]]:
    try:
        return RadarConfig.model_validate(payload), []
    except ValidationError as error:
        return None, [
            {
                "path": ".".join(str(part) for part in detail["loc"]) or "<root>",
                "message": detail["msg"],
            }
            for detail in error.errors(
                include_url=False, include_context=False, include_input=False
            )
        ]


def _json_payload(payload: object) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {"invalid_root": payload}


def _dump_yaml(payload: object) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _reject_secrets(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _SECRET_KEYS:
                raise SecretInConfigError(f"secret field is forbidden: {key}")
            _reject_secrets(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _reject_secrets(child)
