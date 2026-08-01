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

## Scheduled radar

The `Opportunity radar` GitHub Actions workflow runs at `12:17 UTC` every Monday,
Wednesday, and Friday, and can also be started with `workflow_dispatch`. GitHub cron
schedules always use UTC; they do not follow the profile timezone or daylight-saving
changes. Scheduled jobs can start later than their nominal time during periods of high
Actions load.

The workflow has read-only repository permissions, injects tokens only through the job
environment, bounds execution to 30 minutes, prevents overlapping radar runs, and uploads
the Markdown digest as a 14-day artifact. `OPENAI_API_KEY` is optional; without it the
pipeline uses its deterministic fallback analysis. Do not print environment variables or
enable shell tracing in this workflow.

GitHub automatically disables scheduled workflows in a public repository after 60 days
without repository activity. A repository maintainer must re-enable the workflow when
that happens. Manual `workflow_dispatch` runs remain useful for validation and recovery.
