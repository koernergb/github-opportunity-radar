"""Tests for the command-line interface."""

from pathlib import Path

from typer.testing import CliRunner

from radar import __version__
from radar.cli import app

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
