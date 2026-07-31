"""Provider orchestration, repair, fallback, and cache behavior tests."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from radar.analysis.analyze import analyze_issue
from radar.analysis.fallback import deterministic_fallback
from radar.analysis.openai_provider import OpenAIAnalysisProvider
from radar.analysis.provider import ProviderResult
from radar.analysis.schemas import IssueAnalysisOutput
from radar.db.models import Base, Issue, Repository
from radar.settings import RadarConfig, load_config

NOW = datetime(2026, 7, 31, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeProvider:
    provider_name = "openai"
    model_version = "test-model"

    def __init__(self, outcomes: list[ProviderResult | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, str | None]] = []

    def analyze(
        self,
        *,
        context_json: str,
        system_prompt: str,
        repair_feedback: str | None = None,
    ) -> ProviderResult:
        self.calls.append(
            {
                "context_json": context_json,
                "system_prompt": system_prompt,
                "repair_feedback": repair_feedback,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _config() -> RadarConfig:
    path = Path(__file__).resolve().parents[2] / "config/profile.example.yaml"
    config = load_config(path)
    llm = config.llm.model_copy(update={"model": "test-model", "max_input_characters": 10_000})
    return config.model_copy(update={"llm": llm})


@pytest.fixture
def seeded() -> tuple[Session, Issue, RadarConfig]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = Repository(
        github_id=1,
        node_id="R_1",
        owner="owner",
        name="repo",
        full_name="owner/repo",
        url="https://github.com/owner/repo",
        description="Repository",
        default_branch="main",
        primary_language="Python",
        stars=1,
        forks=0,
        archived=False,
        disabled=False,
        is_fork=False,
        pushed_at=NOW,
        github_created_at=NOW,
        github_updated_at=NOW,
        last_synced_at=NOW,
        raw_json={},
    )
    session.add(repository)
    session.flush()
    issue = Issue(
        repository_id=repository.id,
        github_id=2,
        node_id="I_2",
        number=2,
        title="Fix the parser",
        body="The parser fails on a bounded reproducible input.",
        state="open",
        state_reason=None,
        url="https://github.com/owner/repo/issues/2",
        author_login="author",
        author_association="CONTRIBUTOR",
        locked=False,
        comment_count=0,
        github_created_at=NOW,
        github_updated_at=NOW,
        github_closed_at=None,
        last_seen_at=NOW,
        inaccessible_at=None,
        is_pull_request=False,
        raw_json={},
    )
    session.add(issue)
    session.commit()
    yield session, issue, _config()
    session.close()


def _result(config: RadarConfig) -> ProviderResult:
    analysis = deterministic_fallback({}, config).model_copy(
        update={
            "short_summary": "Validated provider analysis.",
            "overall_confidence": 0.8,
        }
    )
    return ProviderResult(
        analysis=analysis,
        model_version="test-model",
        raw_response='{"short_summary":"Validated provider analysis."}',
        usage={"input_tokens": 10, "output_tokens": 20},
    )


def test_success_is_persisted_and_exact_cache_hit_skips_provider(
    seeded: tuple[Session, Issue, RadarConfig],
) -> None:
    session, issue, config = seeded
    provider = FakeProvider([_result(config)])

    first = analyze_issue(
        session,
        issue_id=issue.id,
        config=config,
        clock=FixedClock(),
        provider=provider,
    )
    second = analyze_issue(
        session,
        issue_id=issue.id,
        config=config,
        clock=FixedClock(),
        provider=provider,
    )

    assert first is second
    assert first.status == "success"
    assert first.confidence == 0.8
    assert first.usage_json["provider_attempts"] == 1
    assert len(provider.calls) == 1
    assert "score" in provider.calls[0]["system_prompt"].casefold()
    assert "final_score" not in IssueAnalysisOutput.model_json_schema()["properties"]


def test_one_validation_failure_gets_one_repair_attempt(
    seeded: tuple[Session, Issue, RadarConfig],
) -> None:
    session, issue, config = seeded
    provider = FakeProvider([ValueError("ambiguity must be at most 1"), _result(config)])

    persisted = analyze_issue(
        session,
        issue_id=issue.id,
        config=config,
        clock=FixedClock(),
        provider=provider,
    )

    assert persisted.status == "success"
    assert len(provider.calls) == 2
    assert provider.calls[0]["repair_feedback"] is None
    assert provider.calls[1]["repair_feedback"] == "ValueError: ambiguity must be at most 1"
    assert persisted.usage_json["provider_attempts"] == 2


def test_two_failures_persist_deterministic_fallback(
    seeded: tuple[Session, Issue, RadarConfig],
) -> None:
    session, issue, config = seeded
    provider = FakeProvider([TimeoutError("slow"), ValueError("still invalid")])

    persisted = analyze_issue(
        session,
        issue_id=issue.id,
        config=config,
        clock=FixedClock(),
        provider=provider,
    )

    assert persisted.status == "fallback"
    assert persisted.confidence == 0.1
    assert persisted.analysis_json == deterministic_fallback({}, config).model_dump(mode="json")
    assert persisted.usage_json["provider_attempts"] == 2


@pytest.mark.parametrize("fallback_only", [False, True])
def test_no_key_or_explicit_fallback_only_never_calls_openai(
    seeded: tuple[Session, Issue, RadarConfig], fallback_only: bool
) -> None:
    session, issue, config = seeded

    persisted = analyze_issue(
        session,
        issue_id=issue.id,
        config=config,
        clock=FixedClock(),
        api_key=None,
        fallback_only=fallback_only,
    )

    assert persisted.status == "fallback"
    assert persisted.usage_json["provider_attempts"] == 0


def test_openai_adapter_uses_responses_structured_output_without_score_request(
    seeded: tuple[Session, Issue, RadarConfig],
) -> None:
    _, _, config = seeded
    response = SimpleNamespace(
        output_parsed=_result(config).analysis,
        usage=None,
        model="test-model-snapshot",
        output_text="structured result",
    )
    client = SimpleNamespace(responses=SimpleNamespace(parse=lambda **_kwargs: response))
    captured: dict[str, Any] = {}

    def parse(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return response

    client.responses.parse = parse
    provider = OpenAIAnalysisProvider(
        api_key="unused",
        model="test-model",
        client=client,
    )

    result = provider.analyze(context_json="{}", system_prompt="No final score.")

    assert result.model_version == "test-model"
    assert captured["text_format"] is IssueAnalysisOutput
    assert captured["store"] is False
    assert "final score" in captured["input"].casefold()
    assert "final_score" not in captured["input"]
