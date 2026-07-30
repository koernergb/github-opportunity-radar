"""Tests for the command-line interface."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import radar.cli as cli_module
from radar import __version__
from radar.cli import app
from radar.domain.errors import AuthenticationError
from radar.domain.schemas import RateLimitDTO, RateLimitWindowDTO
from radar.ingestion.issues import IssueSyncSummary
from radar.ingestion.repositories import RepositorySyncSummary

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Rank open-source contribution opportunities" in result.output
    assert "--version" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"radar {__version__}"


def test_validate_config_reports_hashes() -> None:
    result = runner.invoke(
        app,
        ["validate-config", "--config", "config/profile.example.yaml"],
    )

    assert result.exit_code == 0
    assert "Valid configuration" in result.output
    assert "Config hash:" in result.output
    assert "Profile hash:" in result.output


def test_repos_list_shows_enabled_repositories() -> None:
    result = runner.invoke(
        app,
        ["repos", "list", "--config", "config/profile.example.yaml"],
    )

    assert result.exit_code == 0
    assert "ml-explore/mlx" in result.output
    assert "ml-explore/mlx-lm" in result.output
    assert "enabled" in result.output


def test_validate_config_reports_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    result = runner.invoke(app, ["validate-config", "--config", str(missing)])

    assert result.exit_code == 2
    assert "Configuration error" in result.output
    assert "missing.yaml" in result.output


def test_validate_config_reports_precise_validation_error(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        Path("config/profile.example.yaml")
        .read_text(encoding="utf-8")
        .replace("global_merge_prior: 0.45", "global_merge_prior: 2"),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["validate-config", "--config", str(invalid)])

    assert result.exit_code == 2
    assert "Configuration validation failed" in result.output
    assert "scoring.global_merge_prior" in result.output


def test_init_db_migrates_database_to_head(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'radar.sqlite'}"

    result = runner.invoke(app, ["init-db", "--database-url", database_url])

    assert result.exit_code == 0
    assert "latest migration" in result.output
    assert (tmp_path / "radar.sqlite").exists()


def test_doctor_without_live_check_is_offline() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Local configuration support is available" in result.output


def test_doctor_github_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")

    result = runner.invoke(app, ["doctor", "--github"])

    assert result.exit_code == 3
    assert "GITHUB_TOKEN is not configured" in result.output


def test_doctor_github_reports_live_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)

    async def healthy_check(*, token: str, api_version: str) -> RateLimitDTO:
        assert token == "test-token"
        assert api_version == "2022-11-28"
        return RateLimitDTO(
            core=RateLimitWindowDTO(limit=5000, remaining=4999, reset_at=now),
            observed_at=now,
        )

    monkeypatch.setattr(cli_module, "_check_github", healthy_check)

    result = runner.invoke(app, ["doctor", "--github"])

    assert result.exit_code == 0
    assert "GitHub API access is healthy" in result.output
    assert "4999/5000" in result.output


def test_doctor_github_maps_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "bad-token")

    async def failing_check(*, token: str, api_version: str) -> RateLimitDTO:
        raise AuthenticationError("Bad credentials", status_code=401)

    monkeypatch.setattr(cli_module, "_check_github", failing_check)

    result = runner.invoke(app, ["doctor", "--github"])

    assert result.exit_code == 3
    assert "authentication failed" in result.output


def test_repos_sync_requires_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")

    result = runner.invoke(
        app,
        ["repos", "sync", "--config", "config/profile.example.yaml"],
    )

    assert result.exit_code == 3
    assert "GITHUB_TOKEN is not configured" in result.output


def test_repos_sync_prints_clear_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    async def fake_sync(*args: object, **kwargs: object) -> RepositorySyncSummary:
        return RepositorySyncSummary(
            repositories_created=2,
            repositories_unchanged=1,
            documents_stored=3,
            documents_missing=4,
        )

    monkeypatch.setattr(cli_module, "_sync_repositories_live", fake_sync)
    database_url = f"sqlite:///{tmp_path / 'radar.sqlite'}"

    result = runner.invoke(
        app,
        [
            "repos",
            "sync",
            "--config",
            "config/profile.example.yaml",
            "--database-url",
            database_url,
        ],
    )

    assert result.exit_code == 0
    assert "Repository sync complete" in result.output
    assert "created=2" in result.output
    assert "unchanged=1" in result.output
    assert "documents_stored=3" in result.output
    assert "documents_missing=4" in result.output


def test_issue_sync_prints_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    async def fake_sync(*args: object, **kwargs: object) -> IssueSyncSummary:
        assert kwargs["repository"] == "ml-explore/mlx"
        assert kwargs["full"] is True
        return IssueSyncSummary(
            issues_created=2,
            comments_updated=1,
            pull_requests_excluded=3,
        )

    monkeypatch.setattr(cli_module, "_sync_issues_live", fake_sync)
    database_url = f"sqlite:///{tmp_path / 'radar.sqlite'}"

    result = runner.invoke(
        app,
        [
            "sync",
            "--repo",
            "ml-explore/mlx",
            "--full",
            "--config",
            "config/profile.example.yaml",
            "--database-url",
            database_url,
        ],
    )

    assert result.exit_code == 0
    assert "Issue sync complete" in result.output
    assert "created=2" in result.output
    assert "comments_updated=1" in result.output
    assert "prs_excluded=3" in result.output


def test_metrics_command_handles_empty_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'radar.sqlite'}"

    result = runner.invoke(
        app,
        [
            "metrics",
            "--config",
            "config/profile.example.yaml",
            "--database-url",
            database_url,
        ],
    )

    assert result.exit_code == 0
    assert "Calculated 0 repository metric snapshot(s)" in result.output


def test_filter_command_handles_empty_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'radar.sqlite'}"

    result = runner.invoke(
        app,
        [
            "filter",
            "--config",
            "config/profile.example.yaml",
            "--database-url",
            database_url,
        ],
    )

    assert result.exit_code == 0
    assert "eligible=0 warning=0 excluded=0" in result.output
