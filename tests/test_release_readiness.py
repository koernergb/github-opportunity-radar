"""Release documentation, fixture, doctor, and fresh-clone walkthrough tests."""

import json
from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_documented_offline_fresh_clone_walkthrough(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'data/radar.sqlite'}"
    common = ["--config", "config/profile.example.yaml"]

    validate = runner.invoke(app, ["validate-config", *common])
    initialize = runner.invoke(app, ["init-db", "--database-url", database_url])
    doctor = runner.invoke(
        app,
        ["doctor", *common, "--database-url", database_url],
    )
    digest = runner.invoke(
        app,
        ["digest", *common, "--database-url", database_url, "--format", "markdown"],
    )

    assert validate.exit_code == initialize.exit_code == doctor.exit_code == digest.exit_code == 0
    assert "Configuration is valid" in doctor.output
    assert "Database path is writable" in doctor.output
    assert "deterministic fallback" in doctor.output
    assert "No eligible scored opportunities" in digest.output


def test_doctor_catches_missing_profile_and_invalid_database_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    missing_result = runner.invoke(app, ["doctor", "--config", str(missing)])
    database_result = runner.invoke(
        app,
        [
            "doctor",
            "--config",
            "config/profile.example.yaml",
            "--database-url",
            "sqlite:////dev/null/radar.sqlite",
        ],
    )

    assert missing_result.exit_code == 2
    assert "Configuration check failed" in missing_result.output
    assert database_result.exit_code == 2
    assert "database directory is not writable" in database_result.output


def test_required_environment_variables_and_heuristic_warning_are_documented() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = (ROOT / "docs/COMMANDS.md").read_text(encoding="utf-8")
    example = (ROOT / "docs/example-digest.md").read_text(encoding="utf-8")
    template = (ROOT / "src/radar/digest/templates/digest.md.j2").read_text(encoding="utf-8")

    for variable in (
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "RADAR_CONFIG",
        "RADAR_DATABASE_URL",
    ):
        assert f"{variable}=" in env_example
        assert variable in readme
    for text in (readme, commands, example, template):
        assert "heuristic" in text.casefold()


def test_command_surface_and_golden_candidate_fixture_are_complete() -> None:
    help_result = runner.invoke(app, ["--help"])
    fixture = json.loads((ROOT / "tests/fixtures/candidates.json").read_text(encoding="utf-8"))

    assert help_result.exit_code == 0
    for command in ("analyze", "rank", "explain", "digest", "feedback", "run"):
        assert command in help_result.output
    assert len(fixture) == 10
    assert {item["expected"] for item in fixture} >= {"high", "excluded", "low-confidence"}
