"""Strict, hashable application configuration loaded from YAML and environment."""

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

UnitFloat = Annotated[float, Field(ge=0, le=1)]
PositiveFloat = Annotated[float, Field(gt=0)]
PositiveInt = Annotated[int, Field(gt=0)]
_OWNER_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
_REPOSITORY_PATTERN = r"[A-Za-z0-9_.-]{1,100}"
_FULL_NAME_RE = re.compile(rf"^(?P<owner>{_OWNER_PATTERN})/(?P<repo>{_REPOSITORY_PATTERN})$")


class ConfigLoadError(ValueError):
    """Configuration could not be read or parsed."""


class StrictModel(BaseModel):
    """Base for immutable configuration sections with unknown-key rejection."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class UserSettings(StrictModel):
    """User preferences used to calculate personal fit."""

    timezone: str
    max_estimated_hours: PositiveFloat
    available_hardware: tuple[str, ...] = ()
    languages: dict[str, UnitFloat] = Field(default_factory=dict)
    interests: tuple[str, ...] = ()
    career_targets: tuple[str, ...] = ()
    preferred_task_types: dict[str, UnitFloat] = Field(default_factory=dict)
    avoid: tuple[str, ...] = ()

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA timezone: {value}") from error
        return value


class PayoffWeights(StrictModel):
    """Version-one payoff component weights."""

    career_relevance: UnitFloat = 0.22
    technical_depth: UnitFloat = 0.18
    project_impact: UnitFloat = 0.17
    portfolio_explainability: UnitFloat = 0.15
    learning_value: UnitFloat = 0.12
    visibility: UnitFloat = 0.08
    timeliness: UnitFloat = 0.08

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> "PayoffWeights":
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"payoff weights must sum to 1.0; got {total:.6g}")
        return self


class ScoringSettings(StrictModel):
    """Deterministic scoring controls."""

    digest_size: Annotated[int, Field(ge=1, le=100)] = 5
    global_merge_prior: UnitFloat = 0.45
    prior_strength: PositiveFloat = 20
    minimum_confidence_to_surface: UnitFloat = 0.30
    payoff_weights: PayoffWeights = Field(default_factory=PayoffWeights)


class GitHubSettings(StrictModel):
    """Bounded GitHub synchronization controls."""

    api_version: str = "2022-11-28"
    overlap_minutes: Annotated[int, Field(ge=0, le=1440)] = 10
    max_open_issue_pages: Annotated[int, Field(ge=1, le=100)] = 20
    comment_max_pages: Annotated[int, Field(ge=1, le=100)] = 5
    pr_history_limit: Annotated[int, Field(ge=1, le=5000)] = 300
    pr_history_days: Annotated[int, Field(ge=1, le=3650)] = 365
    timeline_enabled: bool = True
    etag_cache_enabled: bool = True


class LLMSettings(StrictModel):
    """Bounded semantic-analysis provider controls."""

    provider: Literal["openai"] = "openai"
    model: str
    max_candidates_per_run: PositiveInt = 30
    max_input_characters: Annotated[int, Field(ge=1000, le=1_000_000)] = 60_000


class RepositorySettings(StrictModel):
    """Per-repository selection and override settings."""

    full_name: str
    enabled: bool = True
    include_labels: tuple[str, ...] = ()
    exclude_labels: tuple[str, ...] = ()
    min_issue_age_minutes: Annotated[int, Field(ge=0)] = 30
    max_issue_age_days: PositiveInt = 730
    max_estimated_hours: PositiveFloat | None = None
    custom_weights: dict[str, UnitFloat] = Field(default_factory=dict)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        match = _FULL_NAME_RE.fullmatch(value)
        if match is None or match.group("repo").endswith(".git"):
            raise ValueError("must be a GitHub repository name in 'owner/repo' form")
        return value

    @field_validator("include_labels", "exclude_labels")
    @classmethod
    def labels_must_not_be_blank(cls, labels: tuple[str, ...]) -> tuple[str, ...]:
        if any(not label.strip() for label in labels):
            raise ValueError("labels must not be blank")
        return labels


class RadarConfig(StrictModel):
    """Complete versioned YAML configuration."""

    version: Literal[1]
    user: UserSettings
    scoring: ScoringSettings
    github: GitHubSettings
    llm: LLMSettings
    repositories: tuple[RepositorySettings, ...]

    @model_validator(mode="after")
    def repositories_must_be_unique(self) -> "RadarConfig":
        names = [repository.full_name.casefold() for repository in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("repository full_name values must be unique (case-insensitive)")
        return self

    @property
    def config_hash(self) -> str:
        """Stable SHA-256 of the full validated configuration."""
        return canonical_hash(self.model_dump(mode="json"))

    @property
    def profile_hash(self) -> str:
        """Stable SHA-256 of user-specific preferences."""
        return canonical_hash(self.user.model_dump(mode="json"))


class EnvironmentSettings(BaseSettings):
    """Secrets and local paths sourced from process environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: str | None = None
    openai_api_key: str | None = None
    radar_config: Path = Path("config/profile.yaml")
    radar_database_url: str = "sqlite:///data/radar.sqlite"


def canonical_hash(value: Any) -> str:
    """Hash canonical UTF-8 JSON with deterministic key ordering."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_config(path: Path) -> RadarConfig:
    """Load and strictly validate a YAML profile."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigLoadError(f"configuration file not found: {path}") from error
    except OSError as error:
        raise ConfigLoadError(f"could not read configuration file {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigLoadError(f"invalid YAML in {path}: {error}") from error

    if not isinstance(raw, dict):
        raise ConfigLoadError(f"configuration root in {path} must be a mapping")
    return RadarConfig.model_validate(raw)


def format_validation_error(error: ValidationError) -> str:
    """Render concise field paths and messages for CLI users."""
    lines = []
    for detail in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in detail["loc"]) or "<root>"
        lines.append(f"{location}: {detail['msg']}")
    return "\n".join(lines)
