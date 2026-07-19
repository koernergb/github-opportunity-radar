# GitHub Opportunity Radar

This is an agent-ready project pack. Give the repository to Cursor or Codex and
instruct it:

> Read `AGENTS.md` and `docs/AGENT_SPEC.md`, then execute `TASKS.md` one card at
> a time. Do not skip acceptance criteria or tests.

The project ranks selected GitHub issues by likely payoff, effort, personal fit,
maintainer receptiveness, merge likelihood, and risk.

Start with:

```bash
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
uv sync --all-extras
```
