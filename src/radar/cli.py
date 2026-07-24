"""Command-line interface for GitHub Opportunity Radar."""

from typing import Annotated

import typer

from radar import __version__

app = typer.Typer(
    name="radar",
    help="Rank open-source contribution opportunities.",
    no_args_is_help=True,
)


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
def validate_config() -> None:
    """Validate configuration. Implement in Task Card 01."""
    typer.echo("Not implemented")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
