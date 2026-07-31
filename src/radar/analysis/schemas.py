"""Strict versioned semantic-analysis output schema."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

UnitFloat = Annotated[float, Field(ge=0, le=1)]
PositiveFloat = Annotated[float, Field(gt=0)]
ANALYSIS_SCHEMA_VERSION = "issue_analysis_v1"


class IssueAnalysisOutput(BaseModel):
    """Bounded semantic features; deliberately excludes a total score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = ANALYSIS_SCHEMA_VERSION
    task_type: str
    short_summary: str
    likely_work: tuple[str, ...]
    required_skills: tuple[str, ...]
    required_domains: tuple[str, ...]
    effort_low_hours: PositiveFloat
    effort_high_hours: PositiveFloat
    effort_confidence: UnitFloat
    ambiguity: UnitFloat
    design_dependency: UnitFloat
    environment_difficulty: UnitFloat
    hardware_required: bool
    hardware_notes: str | None = None
    reproduction_clarity: UnitFloat
    acceptance_criteria_clarity: UnitFloat
    test_plan_clarity: UnitFloat
    technical_depth: UnitFloat
    project_impact: UnitFloat
    learning_value: UnitFloat
    portfolio_explainability: UnitFloat
    visibility: UnitFloat
    interest_fit: UnitFloat
    career_relevance: UnitFloat
    maintainer_intent: UnitFloat
    maintainer_intent_confidence: UnitFloat
    likely_claimed: bool
    claim_confidence: UnitFloat
    questions: tuple[str, ...]
    risks: tuple[str, ...]
    positive_signals: tuple[str, ...]
    suggested_first_move: str
    rationale: str
    investigation_steps: tuple[str, ...]
    overall_confidence: UnitFloat

    @model_validator(mode="after")
    def effort_range_is_ordered(self) -> "IssueAnalysisOutput":
        if self.effort_high_hours < self.effort_low_hours:
            raise ValueError("effort_high_hours must be greater than or equal to effort_low_hours")
        return self
