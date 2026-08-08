"""Static safety and structure checks for GitHub Actions workflows."""

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github/workflows"


def _load(name: str) -> dict[str, Any]:
    loaded = yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return loaded


def test_workflow_yaml_is_valid_and_jobs_are_bounded() -> None:
    for name in ("ci.yml", "radar.yml"):
        workflow = _load(name)
        expected = (
            {"contents": "read", "actions": "read"} if name == "radar.yml" else {"contents": "read"}
        )
        assert workflow["permissions"] == expected
        assert workflow["jobs"]
        assert all("timeout-minutes" in job for job in workflow["jobs"].values())


def test_radar_has_utc_schedule_manual_dispatch_concurrency_and_artifact() -> None:
    workflow = _load("radar.yml")
    triggers = workflow["on"]
    assert triggers["schedule"] == [{"cron": "17 12 * * 1,3,5"}]
    assert "workflow_dispatch" in triggers
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    job = workflow["jobs"]["radar"]
    uses = [step.get("uses", "") for step in job["steps"]]
    assert "actions/upload-artifact@v4" in uses
    assert "actions/download-artifact@v4" in uses
    assert "actions/github-script@v7" in uses
    assert job["env"]["RADAR_CONFIG"] == "config/profile.example.yaml"
    text = (WORKFLOWS / "radar.yml").read_text(encoding="utf-8")
    assert "PRAGMA quick_check" in text
    assert "No prior state found; performing a safe full sync" in text


def test_secrets_are_injected_only_as_environment_values_not_shell_text() -> None:
    workflow_text = (WORKFLOWS / "radar.yml").read_text(encoding="utf-8")
    workflow = _load("radar.yml")
    scripts = "\n".join(step.get("run", "") for step in workflow["jobs"]["radar"]["steps"])

    assert "secrets.GITHUB_TOKEN" in workflow_text
    assert "secrets.OPENAI_API_KEY" in workflow_text
    assert "secrets." not in scripts
    assert "set -x" not in scripts
    assert "printenv" not in scripts
