# GitHub Opportunity Radar

GitHub Opportunity Radar is a local-first, read-only pipeline that finds promising
open-source issues, records GitHub observations separately from derived conclusions,
and produces a deterministic ranked digest. It never comments, assigns issues, opens
pull requests, or otherwise writes to GitHub.

Merge likelihood is a **versioned heuristic estimate, not a calibrated or proven
probability**. Use each recommendation as a prioritized investigation lead, not as a
promise that work will be accepted or merged.

## Fresh-clone setup

Requirements: Git, [uv](https://docs.astral.sh/uv/), Python 3.12 (installed by uv),
and a GitHub token for live synchronization.

```bash
git clone https://github.com/koernergb/github-opportunity-radar.git
cd github-opportunity-radar
cp .env.example .env
cp config/profile.example.yaml config/profile.yaml
uv sync --all-extras --locked
uv run radar validate-config
uv run radar init-db
uv run radar doctor
uv run radar digest --format markdown
```

Edit `config/profile.yaml` before a live run. Set `GITHUB_TOKEN` in `.env`, then:

```bash
uv run radar doctor --github
uv run radar run > digest.md
```

## Local web application

Install the frontend once, build it, and start the single local FastAPI process:

```bash
cd web
pnpm install --frozen-lockfile
pnpm build
cd ..
uv run radar web
```

Open `http://127.0.0.1:8000`. Deep links are served by the production build. For a
two-process development session, run `pnpm dev` in `web/` and `uv run radar web` at the
repository root. The empty-database walkthrough is a safe fixture demo: it exercises Home,
Settings, configuration, and run-history empty states without contacting GitHub. Live sync
requires `GITHUB_TOKEN`; assistant chat requires a key for its selected provider.

See [web operations](docs/web/OPERATIONS.md) for scheduling, state recovery,
troubleshooting, and the release checklist.

Provider API keys are optional. OpenAI, Anthropic, Google Gemini, and Wafer are supported.
Keys may be supplied through environment variables or saved from local Settings into the
operating-system credential vault. Without the selected analysis provider's key, analysis
uses conservative, deterministic fallback features with low confidence. See the
[multi-provider plan](docs/LLM_PROVIDERS_PLAN.md). The full quality gate is:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=radar --cov-report=term-missing --cov-fail-under=85
```

## Configuration and data

All environment variables are listed in [.env.example](.env.example):

- `GITHUB_TOKEN`: required only for live GitHub commands (`doctor --github`, `sync`,
  `repos sync`, and `run`). Grant only the access needed to read selected repositories.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `WAFER_API_KEY`: optional
  credentials for the selected analysis/assistant providers; never stored in SQLite.
- `RADAR_CONFIG`: YAML profile path; defaults to `config/profile.yaml`.
- `RADAR_DATABASE_URL`: SQLAlchemy database URL; defaults to local SQLite at
  `data/radar.sqlite`.

The database stores upstream observations (issues, comments, PRs, documents) separately
from versioned filters, metrics, analyses, scores, and append-only user feedback. Issue
text is untrusted quoted data, never an instruction to the application or model.

## Commands and documentation

See [Command reference](docs/COMMANDS.md), [Security](docs/SECURITY.md),
[Versioning](docs/VERSIONING.md), [Extension guide](docs/EXTENDING.md), and the
[example digest](docs/example-digest.md). Architecture decisions live in
[`docs/architecture`](docs/architecture), and release history is in
[CHANGELOG.md](CHANGELOG.md).

## Scheduled radar

The `Opportunity radar` GitHub Actions workflow runs at `12:17 UTC` every Monday,
Wednesday, and Friday, and supports `workflow_dispatch`. GitHub cron schedules always
use UTC; they do not follow the profile timezone or daylight-saving changes. Scheduled
jobs can start later than their nominal time during high Actions load.

The workflow has read-only repository permissions, injects tokens only through the job
environment, bounds execution to 30 minutes, prevents overlaps, and uploads the Markdown
digest plus a dedicated 14-day unattended-state artifact. That ephemeral runner database
contains cursors, GitHub observations, analyses, scores, and run history. It uses only the
checked-in example profile and never receives a user's local feedback or personal config.
Missing state performs a safe full sync; corrupt state is quarantined visibly. Never print
environment variables or enable shell tracing.

GitHub automatically disables scheduled workflows in a public repository after 60 days
without repository activity. A maintainer must re-enable the workflow when that happens;
manual dispatch remains available for validation and recovery.
