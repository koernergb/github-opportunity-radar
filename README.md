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

`OPENAI_API_KEY` is optional. Without it, analysis uses conservative, deterministic
fallback features with low confidence. The full quality gate is:

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
- `OPENAI_API_KEY`: optional for structured semantic analysis; never stored in SQLite.
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
digest as a 14-day artifact. Never print environment variables or enable shell tracing.

GitHub automatically disables scheduled workflows in a public repository after 60 days
without repository activity. A maintainer must re-enable the workflow when that happens;
manual dispatch remains available for validation and recovery.
