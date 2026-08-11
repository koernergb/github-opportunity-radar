# Web operations and release readiness

## Development and production

Use `uv run radar web` for the API. Use `pnpm dev` from `web/` during React development.
For the production shape, run `pnpm build` first and open `http://127.0.0.1:8000`; FastAPI
serves `web/dist`, including Home and every client-side deep link.

The database and immutable active configuration are shared by CLI, web, assistant, and
scheduler. The local scheduler persists its enabled state, interval, timezone, next due
time, and last outcome in SQLite. It checks every 30 seconds and uses the same durable run
reservation as manual, assistant-confirmed, and CLI runs, so overlaps are skipped visibly.
Times are stored in UTC and displayed in the configured IANA timezone.

## Recovery and troubleshooting

- `Radar is offline`: run `uv run radar doctor`, then inspect `/api/v1/readiness`.
- Assistant unavailable: configure the selected OpenAI, Anthropic, Google, or Wafer key in
  Settings or its environment variable; ranking and all non-chat pages still work.
- GitHub unavailable: set a read-only `GITHUB_TOKEN`. Radar never writes to GitHub.
- Schedule says `credentials_unavailable`: configure GitHub credentials and wait for the
  next due time, or run manually.
- Schedule says `skipped_locked`: another API, CLI, or scheduled run owned the lock. The
  following interval retries without overlapping it.
- Broken frontend asset or deep link: rebuild with `pnpm build` and restart `radar web`.
- Database recovery: back up `data/radar.sqlite`, run `radar init-db`, and retain the old
  copy for audit. Do not delete a database to conceal a failed migration.

The unattended GitHub workflow downloads the newest non-expired state artifact. Missing or
expired state triggers a safe full sync. SQLite `PRAGMA quick_check` guards restore; corrupt
state is renamed and the run starts clean. The artifact is created on an ephemeral runner
from the checked-in example profile, so personal local config/feedback and secrets cannot
enter it. Secrets exist only in the job environment.

## Assistant limitations

Assistant answers are grounded in stored Radar evidence and can still be incomplete or
wrong. Merge likelihood is a versioned heuristic, not a calibrated probability. Repository
content is untrusted data. The assistant can create preview-only proposals, but only the UI
can confirm an exact single-use proposal. GitHub writes are unavailable. Pipeline proposals
require a separate scope/deadline confirmation. Failed or interrupted turns remain auditable
and never silently apply changes.

## Release checklist

Run Ruff, formatting, mypy, pytest with 85% coverage, TypeScript, ESLint, Vitest, production
Vite build, and Playwright. Check keyboard focus, labels, contrast in both themes, reduced
motion, narrow layouts, empty/error/loading states, proposal replay/undo, schedule restart,
and production deep links. The representative UI is documented in
[`SCREENSHOTS.md`](SCREENSHOTS.md).
