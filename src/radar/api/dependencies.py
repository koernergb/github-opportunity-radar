"""Typed dependencies shared by API routes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session, sessionmaker

from radar.clock import Clock
from radar.llm.secrets import CredentialResolver
from radar.settings import ConfigLoadError, EnvironmentSettings, RadarConfig


@dataclass(frozen=True)
class ApiServices:
    """Process-local services injected into request handlers."""

    environment: EnvironmentSettings
    config: RadarConfig | None
    config_error: ConfigLoadError | None
    sessions: sessionmaker[Session]
    clock: Clock
    credentials: CredentialResolver
    static_dir: Path | None = None


def get_services(request: Request) -> ApiServices:
    """Return application services without relying on module globals."""
    services: ApiServices = request.app.state.services
    return services


Services = Annotated[ApiServices, Depends(get_services)]
