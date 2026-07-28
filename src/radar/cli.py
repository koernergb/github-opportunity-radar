"""Command-line interface for GitHub Opportunity Radar."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from sqlalchemy.orm import Session, sessionmaker

from radar import __version__
from radar.clock import SystemClock
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
)
from radar.domain.errors import AuthenticationError, GitHubError
from radar.domain.schemas import RateLimitDTO
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport
from radar.ingestion.issues import IssueSyncSummary, sync_issues
from radar.ingestion.repositories import RepositorySyncSummary, sync_repositories
from radar.settings import (
    ConfigLoadError,
    EnvironmentSettings,
    RadarConfig,
    format_validation_error,
    load_config,
)

app = typer.Typer(
    name="radar",
    help="Rank open-source contribution opportunities.",
    no_args_is_help=True,
)
repos_app = typer.Typer(help="Inspect and synchronize configured repositories.")
app.add_typer(repos_app, name="repos")
console = Console()
error_console = Console(stderr=True)


def version_callback(value: bool) -> None:
    """Print the package version and exit."""
    if value:
        typer.echo(f"radar {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """Rank open-source contribution opportunities."""


@app.command()
def validate_config(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
) -> None:
    """Validate configuration without making network calls."""
    settings, path = _load_cli_config(config)
    console.print(f"[green]Valid configuration:[/] {path}")
    console.print(f"Config hash: {settings.config_hash}")
    console.print(f"Profile hash: {settings.profile_hash}")


@app.command("init-db")
def init_db(
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Initialize or upgrade the local database."""
    url = database_url or EnvironmentSettings().radar_database_url
    migrate_database(url)
    console.print("[green]Database is at the latest migration.[/]")


@app.command()
def doctor(
    github: Annotated[
        bool,
        typer.Option("--github", help="Check authenticated GitHub API access."),
    ] = False,
) -> None:
    """Check local prerequisites and optional live integrations."""
    if not github:
        console.print("[green]Local configuration support is available.[/]")
        return

    environment = EnvironmentSettings()
    if not environment.github_token:
        error_console.print("[red]GitHub check failed:[/] GITHUB_TOKEN is not configured")
        raise typer.Exit(code=3)
    try:
        rate_limit = asyncio.run(
            _check_github(
                token=environment.github_token,
                api_version="2022-11-28",
            )
        )
    except AuthenticationError as error:
        error_console.print(f"[red]GitHub authentication failed:[/] {error}")
        raise typer.Exit(code=3) from error
    except GitHubError as error:
        error_console.print(f"[red]GitHub check failed:[/] {error}")
        raise typer.Exit(code=1) from error
    console.print(
        "[green]GitHub API access is healthy.[/] "
        f"Core rate limit: {rate_limit.core.remaining}/{rate_limit.core.limit}"
    )


async def _check_github(*, token: str, api_version: str) -> RateLimitDTO:
    async with GitHubRestTransport(token=token, api_version=api_version) as transport:
        return await GitHubClient(transport).get_rate_limit()


@repos_app.command("list")
def list_repositories(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
) -> None:
    """List configured repositories without making network calls."""
    settings, _ = _load_cli_config(config)
    table = Table("Repository", "Status", "Include labels", "Exclude labels")
    for repository in settings.repositories:
        table.add_row(
            repository.full_name,
            "enabled" if repository.enabled else "disabled",
            ", ".join(repository.include_labels) or "—",
            ", ".join(repository.exclude_labels) or "—",
        )
    console.print(table)


@repos_app.command("sync")
def sync_repository_observations(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Synchronize configured repositories and contribution documents."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    if not environment.github_token:
        error_console.print("[red]Repository sync failed:[/] GITHUB_TOKEN is not configured")
        raise typer.Exit(code=3)
    url = database_url or environment.radar_database_url
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    try:
        summary = asyncio.run(
            _sync_repositories_live(
                settings,
                token=environment.github_token,
                sessions=sessions,
            )
        )
    except AuthenticationError as error:
        error_console.print(f"[red]GitHub authentication failed:[/] {error}")
        raise typer.Exit(code=3) from error
    _print_repository_sync_summary(summary)


async def _sync_repositories_live(
    config: RadarConfig,
    *,
    token: str,
    sessions: sessionmaker[Session],
) -> RepositorySyncSummary:
    async with GitHubRestTransport(
        token=token,
        api_version=config.github.api_version,
    ) as transport:
        return await sync_repositories(
            config,
            GitHubClient(transport),
            sessions,
            SystemClock(),
        )


def _print_repository_sync_summary(summary: RepositorySyncSummary) -> None:
    console.print(
        "[green]Repository sync complete.[/] "
        f"created={summary.repositories_created} "
        f"updated={summary.repositories_updated} "
        f"unchanged={summary.repositories_unchanged} "
        f"failed={summary.repositories_failed} "
        f"skipped={summary.repositories_skipped} "
        f"documents_stored={summary.documents_stored} "
        f"documents_unchanged={summary.documents_unchanged} "
        f"documents_missing={summary.documents_missing} "
        f"documents_failed={summary.documents_failed}"
    )


@app.command("sync")
def sync_issue_observations(
    repository: Annotated[
        str | None,
        typer.Option("--repo", help="Limit synchronization to owner/repository."),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Ignore incremental cursors."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Synchronize open issues and changed-issue comments."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    if not environment.github_token:
        error_console.print("[red]Issue sync failed:[/] GITHUB_TOKEN is not configured")
        raise typer.Exit(code=3)
    url = database_url or environment.radar_database_url
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    try:
        summary = asyncio.run(
            _sync_issues_live(
                settings,
                token=environment.github_token,
                sessions=sessions,
                repository=repository,
                full=full,
            )
        )
    except AuthenticationError as error:
        error_console.print(f"[red]GitHub authentication failed:[/] {error}")
        raise typer.Exit(code=3) from error
    console.print(
        "[green]Issue sync complete.[/] "
        f"created={summary.issues_created} updated={summary.issues_updated} "
        f"unchanged={summary.issues_unchanged} prs_excluded={summary.pull_requests_excluded} "
        f"comments_created={summary.comments_created} "
        f"comments_updated={summary.comments_updated} "
        f"comment_failures={summary.comment_failures} "
        f"repositories_failed={summary.repositories_failed}"
    )


async def _sync_issues_live(
    config: RadarConfig,
    *,
    token: str,
    sessions: sessionmaker[Session],
    repository: str | None,
    full: bool,
) -> IssueSyncSummary:
    async with GitHubRestTransport(
        token=token,
        api_version=config.github.api_version,
    ) as transport:
        return await sync_issues(
            config,
            GitHubClient(transport),
            sessions,
            SystemClock(),
            repository_filter=repository,
            full=full,
        )


def _load_cli_config(config: Path | None) -> tuple[RadarConfig, Path]:
    environment = EnvironmentSettings()
    path = config or environment.radar_config
    try:
        return load_config(path), path
    except ConfigLoadError as error:
        error_console.print(f"[red]Configuration error:[/] {error}")
        raise typer.Exit(code=2) from error
    except ValidationError as error:
        error_console.print("[red]Configuration validation failed:[/]")
        error_console.print(format_validation_error(error))
        raise typer.Exit(code=2) from error


if __name__ == "__main__":
    app()
