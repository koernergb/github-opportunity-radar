import typer
from radar import __version__

app = typer.Typer(no_args_is_help=True)

def version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()

@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True
    ),
) -> None:
    """Rank open-source contribution opportunities."""

@app.command()
def validate_config() -> None:
    """Validate configuration. Implement in Task Card 01."""
    typer.echo("Not implemented")
    raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
