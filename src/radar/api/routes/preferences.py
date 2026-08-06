"""Immutable configuration revision API."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from radar.api.dependencies import Services
from radar.api.errors import ApiError
from radar.config_store import (
    ConfigConflictError,
    ConfigNotFoundError,
    InvalidRevisionError,
    SecretInConfigError,
    SqlAlchemyConfigurationStore,
)

router = APIRouter(prefix="/preferences", tags=["preferences"])


class ValidationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    message: str


class RevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID
    valid: bool
    config_hash: str | None
    profile_hash: str | None
    source: str
    summary: str
    created_at: datetime
    activated_at: datetime | None
    supersedes_id: UUID | None
    validation_errors: list[ValidationDetail]


class PreferencesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: RevisionResponse
    config: dict[str, Any]


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, Any]
    summary: str = Field(min_length=1, max_length=500)
    expected_active_id: UUID | None
    activate: bool = False
    source: Literal["manual", "assistant"] = "manual"


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml_text: str = Field(min_length=1, max_length=1_000_000)
    summary: str = Field(default="Imported YAML", min_length=1, max_length=500)
    expected_active_id: UUID | None
    activate: bool = False


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_active_id: UUID | None


@router.get("", response_model=PreferencesResponse)
def preferences(services: Services) -> PreferencesResponse:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    revision = store.active_revision()
    if revision is None:
        raise ApiError(404, "config_not_found", "No active configuration exists.")
    view = next(item for item in store.list_revisions() if item.revision_id == revision.id)
    return PreferencesResponse(revision=_revision_response(view), config=revision.payload)


@router.get("/revisions", response_model=list[RevisionResponse])
def revisions(services: Services) -> list[RevisionResponse]:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    return [_revision_response(item) for item in store.list_revisions()]


@router.post("/proposals", response_model=RevisionResponse, status_code=201)
def create_proposal(body: ProposalRequest, services: Services) -> RevisionResponse:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    try:
        revision = store.create_revision(
            body.config,
            source=body.source,
            summary=body.summary,
            supersedes_id=body.expected_active_id,
        )
        if body.activate:
            store.activate(revision.id, expected_active_id=body.expected_active_id)
    except SecretInConfigError as error:
        raise ApiError(
            422, "secret_field_forbidden", "Secrets cannot be stored in preferences."
        ) from error
    except ConfigConflictError as error:
        raise ApiError(409, "config_conflict", "The active configuration changed.") from error
    except InvalidRevisionError as error:
        raise ApiError(
            422, "config_invalid", "Invalid configuration cannot be activated."
        ) from error
    view = next(item for item in store.list_revisions() if item.revision_id == revision.id)
    return _revision_response(view)


@router.post("/import", response_model=RevisionResponse, status_code=201)
def import_preferences(body: ImportRequest, services: Services) -> RevisionResponse:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    try:
        revision = store.import_yaml(body.yaml_text, summary=body.summary)
        if body.activate:
            store.activate(revision.id, expected_active_id=body.expected_active_id)
    except SecretInConfigError as error:
        raise ApiError(
            422, "secret_field_forbidden", "Secrets cannot be stored in preferences."
        ) from error
    except ConfigConflictError as error:
        raise ApiError(409, "config_conflict", "The active configuration changed.") from error
    except InvalidRevisionError as error:
        raise ApiError(
            422, "config_invalid", "Invalid configuration cannot be activated."
        ) from error
    view = next(item for item in store.list_revisions() if item.revision_id == revision.id)
    return _revision_response(view)


@router.post("/revisions/{revision_id}/activate", response_model=PreferencesResponse)
def activate_revision(
    revision_id: UUID, body: ActivateRequest, services: Services
) -> PreferencesResponse:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    try:
        store.activate(revision_id, expected_active_id=body.expected_active_id)
    except ConfigConflictError as error:
        raise ApiError(409, "config_conflict", "The active configuration changed.") from error
    except ConfigNotFoundError as error:
        raise ApiError(404, "config_revision_not_found", "The revision does not exist.") from error
    except InvalidRevisionError as error:
        raise ApiError(
            422, "config_invalid", "Invalid configuration cannot be activated."
        ) from error
    revision = store.active_revision()
    assert revision is not None
    view = next(item for item in store.list_revisions() if item.revision_id == revision.id)
    return PreferencesResponse(revision=_revision_response(view), config=revision.payload)


@router.get("/export")
def export_preferences(services: Services) -> Response:
    store = SqlAlchemyConfigurationStore(services.sessions, services.clock)
    try:
        yaml_text = store.export_yaml()
    except ConfigNotFoundError as error:
        raise ApiError(404, "config_not_found", "No active configuration exists.") from error
    return Response(content=yaml_text, media_type="application/yaml")


def _revision_response(view: Any) -> RevisionResponse:
    return RevisionResponse(
        revision_id=view.revision_id,
        valid=view.valid,
        config_hash=view.config_hash,
        profile_hash=view.profile_hash,
        source=view.source,
        summary=view.summary,
        created_at=view.created_at,
        activated_at=view.activated_at,
        supersedes_id=view.supersedes_id,
        validation_errors=[
            ValidationDetail.model_validate(item) for item in view.validation_errors
        ],
    )
