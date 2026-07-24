"""Tests for strict typed configuration and canonical hashes."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from radar.settings import (
    ConfigLoadError,
    EnvironmentSettings,
    format_validation_error,
    load_config,
)

EXAMPLE = Path("config/profile.example.yaml")


def _example_data() -> dict[str, Any]:
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_config(tmp_path: Path, data: object) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_example_loads_without_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    config = load_config(EXAMPLE)
    environment = EnvironmentSettings(_env_file=None)

    assert config.version == 1
    assert config.repositories[0].full_name == "ml-explore/mlx"
    assert environment.github_token is None


def test_unknown_keys_fail(tmp_path: Path) -> None:
    data = _example_data()
    data["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_config(_write_config(tmp_path, data))


@pytest.mark.parametrize(
    ("mutate", "path_fragment"),
    [
        (
            lambda data: data["user"]["languages"].update({"python": 1.1}),
            "user.languages.python",
        ),
        (
            lambda data: data["repositories"][0].update({"full_name": "not-a-repository"}),
            "repositories.0.full_name",
        ),
        (
            lambda data: data["scoring"].update({"global_merge_prior": -0.1}),
            "scoring.global_merge_prior",
        ),
    ],
)
def test_precise_range_and_identity_errors(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
    path_fragment: str,
) -> None:
    data = _example_data()
    mutate(data)

    with pytest.raises(ValidationError) as caught:
        load_config(_write_config(tmp_path, data))

    assert path_fragment in format_validation_error(caught.value)


def test_hashes_are_stable_across_mapping_order(tmp_path: Path) -> None:
    first_data = _example_data()
    second_data = dict(reversed(first_data.items()))

    first = load_config(_write_config(tmp_path / "first", first_data))
    second = load_config(_write_config(tmp_path / "second", second_data))

    assert first.config_hash == second.config_hash
    assert first.profile_hash == second.profile_hash
    assert len(first.config_hash) == 64


def test_profile_hash_ignores_non_user_configuration(tmp_path: Path) -> None:
    original = _example_data()
    modified = _example_data()
    modified["scoring"]["digest_size"] = 10

    first = load_config(_write_config(tmp_path / "first", original))
    second = load_config(_write_config(tmp_path / "second", modified))

    assert first.config_hash != second.config_hash
    assert first.profile_hash == second.profile_hash


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigLoadError, match="must be a mapping"):
        load_config(_write_config(tmp_path, ["not", "a", "mapping"]))


def test_unknown_timezone_is_rejected(tmp_path: Path) -> None:
    data = _example_data()
    data["user"]["timezone"] = "Mars/Olympus_Mons"

    with pytest.raises(ValidationError, match="unknown IANA timezone"):
        load_config(_write_config(tmp_path, data))


def test_payoff_weights_must_sum_to_one(tmp_path: Path) -> None:
    data = _example_data()
    data["scoring"]["payoff_weights"] = {
        "career_relevance": 0.5,
        "technical_depth": 0.5,
        "project_impact": 0.5,
    }

    with pytest.raises(ValidationError, match=r"payoff weights must sum to 1.0"):
        load_config(_write_config(tmp_path, data))


def test_repository_names_are_case_insensitively_unique(tmp_path: Path) -> None:
    data = _example_data()
    data["repositories"].append(
        {
            "full_name": "ML-EXPLORE/MLX",
            "enabled": True,
        }
    )

    with pytest.raises(ValidationError, match="must be unique"):
        load_config(_write_config(tmp_path, data))


def test_invalid_yaml_is_reported_as_load_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("user: [unterminated", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="invalid YAML"):
        load_config(path)
