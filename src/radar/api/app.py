"""FastAPI application factory and local production defaults."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from radar import __version__
from radar.api.dependencies import ApiServices
from radar.api.errors import install_error_handlers
from radar.api.routes.assistant import router as assistant_router
from radar.api.routes.health import router as health_router
from radar.api.routes.preferences import router as preferences_router
from radar.api.routes.proposals import router as proposals_router
from radar.api.routes.read import router as read_router
from radar.api.routes.runs import router as runs_router
from radar.api.routes.schedule import router as schedule_router
from radar.clock import Clock, SystemClock
from radar.config_store import SqlAlchemyConfigurationStore
from radar.db.session import create_database_engine, create_session_factory, migrate_database
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport
from radar.pipeline.background import BackgroundRunConflictError, BackgroundRunCoordinator
from radar.pipeline.orchestrator import run_pipeline
from radar.scheduling import claim_due, record_schedule_status
from radar.settings import ConfigLoadError, EnvironmentSettings, RadarConfig, load_config

API_PREFIX = "/api/v1"


def create_app(
    *,
    environment: EnvironmentSettings,
    sessions: sessionmaker[Session],
    config: RadarConfig | None,
    config_error: ConfigLoadError | None = None,
    clock: Clock | None = None,
    allowed_origins: Sequence[str] = (),
    static_dir: Path | None = None,
) -> FastAPI:
    """Build an application entirely from explicitly injected services."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(_schedule_loop(application))
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(
        title="GitHub Opportunity Radar API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.services = ApiServices(
        environment=environment,
        config=config,
        config_error=config_error,
        sessions=sessions,
        clock=clock or SystemClock(),
        static_dir=static_dir,
    )
    app.state.run_coordinator = BackgroundRunCoordinator(sessions, app.state.services.clock)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health_router)
    api.include_router(assistant_router)
    api.include_router(preferences_router)
    api.include_router(proposals_router)
    api.include_router(read_router)
    api.include_router(runs_router)
    api.include_router(schedule_router)
    app.include_router(api)
    install_error_handlers(app)

    assets = static_dir / "assets" if static_dir is not None else None
    if assets is not None and assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    index = static_dir / "index.html" if static_dir is not None else None
    if index is not None and index.is_file():

        @app.get("/{full_path:path}", include_in_schema=False)
        def web_application(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            return FileResponse(index)

    return app


async def _schedule_loop(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(30)
        services: ApiServices = app.state.services
        due = claim_due(services.sessions, services.clock)
        if due is None:
            continue
        config = (
            SqlAlchemyConfigurationStore(services.sessions, services.clock).active_config()
            or services.config
        )
        if config is None or not services.environment.github_token:
            record_schedule_status(services.sessions, services.clock, "credentials_unavailable")
            continue
        coordinator: BackgroundRunCoordinator = app.state.run_coordinator
        try:
            run_id = coordinator.reserve(
                config.config_hash,
                {
                    "scope": "all",
                    "deadline_seconds": 600,
                    "fallback_only": False,
                    "source": "local_schedule",
                },
            )
        except BackgroundRunConflictError:
            record_schedule_status(services.sessions, services.clock, "skipped_locked")
            continue

        async def work(
            active_services: ApiServices = services,
            active_config: RadarConfig = config,
            active_run_id: UUID = run_id,
            active_coordinator: BackgroundRunCoordinator = coordinator,
        ) -> None:
            assert active_services.environment.github_token is not None
            async with GitHubRestTransport(
                token=active_services.environment.github_token,
                api_version=active_config.github.api_version,
            ) as transport:
                await run_pipeline(
                    active_config,
                    GitHubClient(transport),
                    active_services.sessions,
                    active_services.clock,
                    api_key=active_services.environment.openai_api_key,
                    fallback_only=False,
                    deadline_seconds=600,
                    reserved_run_id=active_run_id,
                    should_cancel=lambda: active_coordinator.should_cancel(active_run_id),
                )

        coordinator.launch(run_id, work)
        record_schedule_status(services.sessions, services.clock, "queued")


def create_default_app() -> FastAPI:
    """Create the local application from environment and on-disk configuration."""
    environment = EnvironmentSettings()
    migrate_database(environment.radar_database_url)
    sessions = create_session_factory(create_database_engine(environment.radar_database_url))
    store = SqlAlchemyConfigurationStore(sessions, SystemClock())
    store.bootstrap(environment.radar_config)
    config: RadarConfig | None = None
    config_error: ConfigLoadError | None = None
    try:
        config = store.active_config() or load_config(environment.radar_config)
    except ConfigLoadError as error:
        config_error = error
    return create_app(
        environment=environment,
        sessions=sessions,
        config=config,
        config_error=config_error,
        allowed_origins=environment.web_origins,
        static_dir=Path(__file__).resolve().parents[1] / "web" / "dist",
    )
