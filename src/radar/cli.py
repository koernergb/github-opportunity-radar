"""Command-line interface for GitHub Opportunity Radar."""

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from radar import __version__
from radar.analysis.analyze import analyze_issue
from radar.clock import SystemClock
from radar.config_store import SqlAlchemyConfigurationStore
from radar.db.models import Issue, IssueFilterResult, IssueScore, Repository
from radar.db.session import (
    create_database_engine,
    create_session_factory,
    migrate_database,
)
from radar.digest.markdown import render_markdown
from radar.digest.models import build_digest
from radar.digest.terminal import render_terminal
from radar.domain.errors import AuthenticationError, GitHubError
from radar.domain.schemas import RateLimitDTO
from radar.feedback.service import (
    FeedbackValidationError,
    record_feedback,
    resolve_issue_reference,
)
from radar.filtering.engine import filter_issues
from radar.github.client import GitHubClient
from radar.github.rest import GitHubRestTransport
from radar.ingestion.issues import IssueSyncSummary, sync_issues
from radar.ingestion.pull_requests import sync_pull_request_history
from radar.ingestion.repositories import RepositorySyncSummary, sync_repositories
from radar.llm.registry import ProviderCredentialError, ProviderRegistry
from radar.llm.secrets import CredentialResolver
from radar.metrics.repository_health import calculate_repository_metrics
from radar.pipeline.orchestrator import PipelineLockedError, PipelineOutcome, run_pipeline
from radar.scoring.engine import SCORE_VERSION, rank_scores
from radar.scoring.explanations import explain_score
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
def web(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Local interface on which the web server listens."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", min=1, max=65535, help="Local web server port."),
    ] = None,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Reload the server when source files change."),
    ] = False,
) -> None:
    """Run the local Radar web application."""
    import uvicorn

    environment = EnvironmentSettings()
    uvicorn.run(
        "radar.api.app:create_default_app",
        factory=True,
        host=host or environment.radar_web_host,
        port=port or environment.radar_web_port,
        reload=reload,
    )


@app.command()
def doctor(
    github: Annotated[
        bool,
        typer.Option("--github", help="Check authenticated GitHub API access."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile to diagnose."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="Database URL to diagnose."),
    ] = None,
) -> None:
    """Check local prerequisites and optional live integrations."""
    environment = EnvironmentSettings()
    configured_path = config or environment.radar_config
    diagnostic_path = configured_path
    if not configured_path.exists() and config is None:
        diagnostic_path = Path("config/profile.example.yaml")
        console.print(
            f"[yellow]Profile missing:[/] {configured_path}; copy config/profile.example.yaml first"
        )
    try:
        loaded = load_config(diagnostic_path)
    except (ConfigLoadError, ValidationError) as error:
        error_console.print(f"[red]Configuration check failed:[/] {error}")
        raise typer.Exit(code=2) from error
    console.print(
        f"[green]Configuration is valid.[/] {diagnostic_path} "
        f"({len(loaded.repositories)} repositories)"
    )
    _diagnose_database(database_url or environment.radar_database_url)
    credentials = CredentialResolver(environment)
    for provider in ("openai", "anthropic", "google", "wafer"):
        state = credentials.resolve(provider).source
        if state:
            console.print(f"[green]{provider.upper()} credentials are configured via {state}.[/]")
    if credentials.resolve(loaded.llm.provider).value is None:
        console.print(
            f"[yellow]{loaded.llm.provider.upper()} credentials are absent; "
            "deterministic fallback will be used.[/]"
        )
    console.print("[green]Local configuration support is available.[/]")
    if not github:
        return

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


def _diagnose_database(database_url: str) -> None:
    """Check local database path safety without creating or changing a database."""
    if database_url.startswith("sqlite:///"):
        database_path = Path(database_url.removeprefix("sqlite:///"))
        parent = database_path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise typer.BadParameter(
                f"database directory is not writable: {parent}", param_hint="--database-url"
            )
        console.print(f"[green]Database path is writable.[/] {database_path}")
        return
    console.print("[yellow]Database connectivity not checked for non-SQLite URL.[/]")


@app.command("digest")
def show_digest(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: terminal or markdown."),
    ] = "terminal",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Write Markdown to this path."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates, capped by digest_size."),
    ] = None,
) -> None:
    """Render the current deterministic opportunity digest."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    factory = create_session_factory(create_database_engine(url))
    with factory() as session:
        digest = build_digest(session, settings, generated_at=SystemClock().now(), limit=limit)
    if output_format == "terminal":
        if output is not None:
            raise typer.BadParameter("--output requires --format markdown", param_hint="--output")
        render_terminal(digest, console)
        return
    if output_format != "markdown":
        raise typer.BadParameter("must be terminal or markdown", param_hint="--format")
    rendered = render_markdown(digest)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"[green]Digest written:[/] {output}")


@app.command("feedback")
def add_feedback(
    issue_reference: Annotated[str, typer.Argument(help="Issue as owner/repository#number.")],
    status: Annotated[str, typer.Argument(help="New feedback status.")],
    note: Annotated[str | None, typer.Option("--note", help="Optional private note.")] = None,
    pr_url: Annotated[
        str | None,
        typer.Option("--pr-url", help="Related GitHub pull request URL."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Append validated user feedback without changing GitHub observations."""
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    factory = create_session_factory(create_database_engine(url))
    try:
        with factory.begin() as session:
            issue = resolve_issue_reference(session, issue_reference)
            feedback = record_feedback(
                session,
                issue_id=issue.id,
                status=status,
                note=note,
                pr_url=pr_url,
                clock=SystemClock(),
            )
    except FeedbackValidationError as error:
        raise typer.BadParameter(str(error)) from error
    console.print(f"[green]Feedback appended:[/] {feedback.status} ({feedback.id})")


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
        f"repositories_failed={summary.repositories_failed} "
        f"pull_requests_synced={summary.pull_requests_synced} "
        f"reviews_stored={summary.reviews_stored} "
        f"pr_comments_stored={summary.pr_comments_stored} "
        f"issue_links_stored={summary.issue_links_stored}"
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
        client = GitHubClient(transport)
        summary = await sync_issues(
            config,
            client,
            sessions,
            SystemClock(),
            repository_filter=repository,
            full=full,
        )
        pr_summary = await sync_pull_request_history(
            config,
            client,
            sessions,
            SystemClock(),
            repository_filter=repository,
        )
        summary.pull_requests_synced = (
            pr_summary.pull_requests_created
            + pr_summary.pull_requests_updated
            + pr_summary.pull_requests_unchanged
        )
        summary.reviews_stored = pr_summary.reviews_stored
        summary.pr_comments_stored = pr_summary.comments_stored
        summary.issue_links_stored = pr_summary.issue_links_stored
        return summary


@app.command("metrics")
def calculate_metrics(
    repository: Annotated[
        str | None,
        typer.Option("--repo", help="Limit calculation to owner/repository."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Calculate versioned repository contribution metrics."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    snapshots = calculate_repository_metrics(
        settings,
        sessions,
        SystemClock(),
        repository_filter=repository,
    )
    table = Table("Repository ID", "External PRs", "Merge rate", "Shrunk rate", "Confidence")
    for snapshot in snapshots:
        table.add_row(
            str(snapshot.repository_id),
            str(snapshot.external_pr_count),
            "unknown"
            if snapshot.external_merge_rate is None
            else f"{snapshot.external_merge_rate:.3f}",
            f"{snapshot.shrunk_merge_rate:.3f}",
            f"{snapshot.data_confidence:.3f}",
        )
    console.print(table)
    console.print(f"[green]Calculated {len(snapshots)} repository metric snapshot(s).[/]")


@app.command("filter")
def apply_filters(
    repository: Annotated[
        str | None,
        typer.Option("--repo", help="Limit filtering to owner/repository."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Apply and persist deterministic issue filters."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    counts = filter_issues(
        settings,
        sessions,
        SystemClock(),
        repository_filter=repository,
    )
    console.print(
        "[green]Filtering complete.[/] "
        f"eligible={counts['eligible']} warning={counts['warning']} "
        f"excluded={counts['excluded']}"
    )


@app.command("analyze")
def analyze_candidates(
    repository: Annotated[
        str | None,
        typer.Option("--repo", help="Limit analysis to owner/repository."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates for this invocation."),
    ] = None,
    fallback_only: Annotated[
        bool,
        typer.Option("--fallback-only", help="Skip OpenAI and use deterministic fallback."),
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
    """Analyze eligible issues using cached structured or fallback features."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    factory = create_session_factory(create_database_engine(url))
    maximum = min(limit or settings.llm.max_candidates_per_run, settings.llm.max_candidates_per_run)
    with factory() as session:
        statement = (
            select(Issue.id)
            .join(Repository)
            .join(IssueFilterResult, IssueFilterResult.issue_id == Issue.id)
            .where(IssueFilterResult.status.in_({"eligible", "warning"}))
            .order_by(Repository.full_name, Issue.number)
        )
        if repository is not None:
            statement = statement.where(Repository.full_name == repository)
        issue_ids = list(session.scalars(statement).all())[:maximum]
    statuses: dict[str, int] = {"success": 0, "fallback": 0}
    provider = None
    if not fallback_only:
        try:
            provider = ProviderRegistry(CredentialResolver(environment)).analysis(
                settings.llm.provider, settings.llm.model
            )
        except ProviderCredentialError:
            provider = None
    for issue_id in issue_ids:
        with factory.begin() as session:
            analysis = analyze_issue(
                session,
                issue_id=issue_id,
                config=settings,
                clock=SystemClock(),
                provider=provider,
                fallback_only=fallback_only,
            )
            statuses[analysis.status] = statuses.get(analysis.status, 0) + 1
    console.print(
        "[green]Analysis complete.[/] "
        f"candidates={len(issue_ids)} success={statuses['success']} fallback={statuses['fallback']}"
    )


@app.command("rank")
def show_ranked(
    top: Annotated[int, typer.Option("--top", min=1, help="Maximum rows to display.")] = 10,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Show current-profile eligible scores in deterministic order."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    factory = create_session_factory(create_database_engine(url))
    table = Table("Rank", "Score", "Confidence", "Opportunity", "Merge")
    with factory() as session:
        scores = rank_scores(
            session,
            limit=top,
            score_version=SCORE_VERSION,
            profile_hash=settings.profile_hash,
        )
        for rank, score in enumerate(scores, start=1):
            issue = session.get(Issue, score.issue_id)
            assert issue is not None
            repository = session.get(Repository, issue.repository_id)
            assert repository is not None
            table.add_row(
                str(rank),
                f"{score.total:.1f}",
                f"{score.confidence:.0%}",
                f"{repository.full_name}#{issue.number} — {issue.title}",
                f"{score.merge_band} ({score.merge_estimate:.0%}) heuristic",
            )
    console.print(table)


@app.command("explain")
def explain_candidate(
    issue_reference: Annotated[str, typer.Argument(help="Issue as owner/repository#number.")],
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
) -> None:
    """Print the persisted versioned score explanation for one issue."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    url = database_url or environment.radar_database_url
    migrate_database(url)
    factory = create_session_factory(create_database_engine(url))
    with factory() as session:
        try:
            issue = resolve_issue_reference(session, issue_reference)
        except FeedbackValidationError as error:
            raise typer.BadParameter(str(error)) from error
        score = session.scalar(
            select(IssueScore).where(
                IssueScore.issue_id == issue.id,
                IssueScore.score_version == SCORE_VERSION,
                IssueScore.profile_hash == settings.profile_hash,
            )
        )
        if score is None:
            raise typer.BadParameter("no current score; run analyze and score via radar run")
        typer.echo(json.dumps(explain_score(score), indent=2, sort_keys=True))


@app.command("run")
def run_all(
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to the YAML profile."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="SQLAlchemy database URL."),
    ] = None,
    fallback_only: Annotated[
        bool,
        typer.Option("--fallback-only", help="Skip OpenAI and use deterministic fallback."),
    ] = False,
    deadline_seconds: Annotated[
        int,
        typer.Option("--deadline-seconds", min=1, help="Bound total pipeline runtime."),
    ] = 600,
) -> None:
    """Run sync, metrics, filter, analysis, scoring, and digest."""
    settings, _ = _load_cli_config(config)
    environment = EnvironmentSettings()
    if not environment.github_token:
        error_console.print("[red]Pipeline failed:[/] GITHUB_TOKEN is not configured")
        raise typer.Exit(code=3)
    url = database_url or environment.radar_database_url
    migrate_database(url)
    sessions = create_session_factory(create_database_engine(url))
    provider = None
    if not fallback_only:
        try:
            provider = ProviderRegistry(CredentialResolver(environment)).analysis(
                settings.llm.provider, settings.llm.model
            )
        except ProviderCredentialError:
            provider = None

    async def execute() -> PipelineOutcome:
        async with GitHubRestTransport(
            token=environment.github_token,
            api_version=settings.github.api_version,
        ) as transport:
            return await run_pipeline(
                settings,
                GitHubClient(transport),
                sessions,
                SystemClock(),
                provider=provider,
                fallback_only=fallback_only,
                deadline_seconds=deadline_seconds,
            )

    try:
        outcome = asyncio.run(execute())
    except PipelineLockedError as error:
        error_console.print(f"[yellow]Pipeline already running:[/] {error}")
        raise typer.Exit(code=5) from error
    except AuthenticationError as error:
        error_console.print(f"[red]GitHub authentication failed:[/] {error}")
        raise typer.Exit(code=3) from error
    typer.echo(outcome.markdown, nl=False)
    if outcome.exit_code:
        raise typer.Exit(code=outcome.exit_code)


def _load_cli_config(config: Path | None) -> tuple[RadarConfig, Path]:
    environment = EnvironmentSettings()
    path = config or environment.radar_config
    try:
        if config is None:
            sessions = create_session_factory(
                create_database_engine(environment.radar_database_url)
            )
            try:
                active = SqlAlchemyConfigurationStore(sessions, SystemClock()).active_config()
            except SQLAlchemyError:
                active = None
            if active is not None:
                return active, path
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
