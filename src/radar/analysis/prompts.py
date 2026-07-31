"""Versioned prompt artifact loading."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

PROMPT_VERSION = "issue_analysis_system_v1"


@dataclass(frozen=True)
class PromptArtifact:
    version: str
    sha256: str
    text: str


def load_system_prompt(path: Path | None = None) -> PromptArtifact:
    """Load the reviewed system prompt with a content fingerprint."""
    prompt_path = path or Path(__file__).resolve().parents[3] / "prompts/issue_analysis_system.md"
    text = prompt_path.read_text(encoding="utf-8")
    return PromptArtifact(
        version=PROMPT_VERSION,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        text=text,
    )
