"""Command-line interface for GitHub Opportunity Radar."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from radar import __version__
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
