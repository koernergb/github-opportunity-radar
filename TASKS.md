# Agent Task Cards

Each card is a focused implementation unit. Before coding, the agent must restate
the acceptance criteria and identify affected modules. Every card adds tests.

## 00 — Bootstrap

Implement package layout, Typer CLI, version command, structured secret-redacting
logging, injected clock, Ruff/mypy/pytest, CI.

Acceptance:
- `uv sync --all-extras`
- `radar --help`
- `radar --version`
- CI lint/type/test
- CLI and redaction tests.

## 01 — Typed configuration

Implement `.env` plus strict YAML settings, repository-name validation, weight and
range checks, canonical config/profile hash, `validate-config`, `repos list`.

Acceptance:
- example loads,
- unknown keys fail,
- missing token allowed for offline validation,
- stable hash,
- precise validation errors.

## 02 — Database and migrations

Implement SQLAlchemy models described in `AGENT_SPEC.md`, SQLite FK enforcement,
PostgreSQL compatibility, transactions, UTC validation, Alembic initial migration,
`init-db`.

Acceptance:
- migrate zero to head,
- round-trip entities,
- uniqueness and rollback tests,
- no naive datetime persistence.

## 03 — Domain DTOs and protocols

Implement GitHub DTOs, gateway protocol, typed errors, page metadata, parsers for
`owner/repo#123` and GitHub issue/PR URLs.

Acceptance:
- optional documented fields tolerated,
- invalid identities rejected,
- domain services have no HTTP dependency.

## 04 — GitHub REST transport

Implement async client, required headers, retry/backoff/jitter, rate-limit parsing,
bounded Link pagination, ETags/304, typed errors, secret-safe logs, repository and
rate-limit endpoints, `doctor --github`.

Acceptance:
- rate-limit 403 differs from permission 403,
- 401 no retry,
- Retry-After wins,
- pagination always bounded,
- exhaustive mocked status tests.

## 05 — Repository/document sync

Implement repository upsert, config association, README/contribution/security/code
documents and templates, base64 decoding, SHA versioning, pipeline run/events,
`repos sync`.

Acceptance:
- idempotent,
- missing optional docs are normal,
- changed status reflected,
- clear run counts.

## 06 — Incremental issues/comments

Implement overlap cursor, open issue fetch/upsert, PR discrimination, labels and
assignees synchronization including removals, changed-issue comments, URL extraction,
soft inaccessible marking, `sync`.

Acceptance:
- repeat run no duplicates,
- edited comments update,
- cursor moves only after complete pages,
- partial comments failure recorded safely.

## 07 — PR history and maintainer evidence

Implement bounded PR history, PR hydration, reviews/comments, maintainer identity,
bot exclusion, external contributor classification, first maintainer response,
issue-link evidence.

Acceptance:
- Contributor remains external,
- response after creation from credible maintainer,
- active/closed/merged links distinguished,
- ambiguous references remain weak.

## 08 — Repository metrics

Implement external merge rate, response/merge distributions, closed-unmerged rate,
activity, maintainers, docs score, confidence, Bayesian shrunk prior, snapshots,
`metrics`.

Acceptance:
- defined windows,
- null unknowns,
- small samples shrink,
- deterministic versioned snapshots.

## 09 — Deterministic filters

Implement composable rules, stable codes/evidence, exclusions/warnings, configured
labels, soft claims with quote/withdrawal/age logic, persisted results, `filter`.

Acceptance:
- exactly one current result per version,
- warnings do not exclude,
- linked PR exclusion requires credible evidence,
- one test per rule.

## 10 — LLM input/schema/cache

Implement strict analysis model, validators, versioned prompt loading, bounded
context builder, priority comment retention, untrusted delimiters, truncation
metadata, canonical content hash, cache.

Acceptance:
- stable semantic hash,
- deterministic ordering,
- caps enforced,
- maintainer and claim comments retained,
- injection-like content inert.

## 11 — Provider and fallback

Implement provider protocol, OpenAI structured-output adapter, timeout/retries,
single repair retry, usage metadata, deterministic fallback, persisted statuses,
`analyze`.

Acceptance:
- success, repair, fallback, cache hit, and no-key paths tested,
- no final score requested from LLM.

## 12 — Scoring

Implement feature extraction, formulas, Bayesian prior, merge logits, fit,
completion, effort, risk, confidence, calibration scale, bands, persistence,
`rank`, `explain`.

Acceptance:
- score `[0,100]`,
- missing data lowers confidence,
- active linked PR never ranks,
- deterministic and fully explainable,
- monotonicity tests and golden ordering.

## 13 — Digest

Implement Rich table/detail views, Markdown Jinja renderer, top-N/confidence/freshness,
empty state, `digest`.

Acceptance:
- excluded absent,
- low confidence explicit,
- deterministic tie breaks,
- golden Markdown snapshots.

## 14 — Feedback

Implement append-only feedback, transition validation, PR URL validation, rejection
filter integration, transparent preference modifiers, outcome report.

Acceptance:
- no overwrites,
- latest state shown,
- modifier visible,
- observed GitHub truth not corrupted.

## 15 — Orchestrator

Implement `run`: sync -> metrics -> filter -> analyze -> score -> digest, repository
isolation, run deadline, budget, lock, partial-success semantics and exit codes.

Acceptance:
- fixture end-to-end,
- one repo failure does not block others,
- auth stops run,
- concurrency lock,
- rerun idempotent.

## 16 — Scheduled workflow

Implement CI and scheduled/manual radar Actions workflows, UTC documentation,
minimal permissions, secrets, concurrency, timeout, artifact output.

Acceptance:
- syntax valid,
- no secrets printed,
- schedule and public inactivity caveat documented.

## 17 — Release readiness

Complete setup, command reference, troubleshooting, versioning guide, extension
guides, example digest, fixture set, changelog, security notes, architecture decisions.

Acceptance:
- fresh-clone walkthrough succeeds,
- all required environment variables documented,
- merge estimate clearly called heuristic,
- `doctor` catches common failures.

## Web UI Phase

Build a local-first, single-user web application in this monorepo. Keep the existing
Python pipeline and deterministic scoring engine authoritative. Add a React/TypeScript
frontend under `web/` and a FastAPI layer under `src/radar/api/`.

Web configuration uses immutable database revisions as its active source of truth, with
validated YAML import/export for CLI compatibility. Assistant-driven repository or
preference changes always require explicit confirmation. GitHub remains read-only.
Repository, issue, comment, and document text remains untrusted data and can never invoke
assistant tools.

Required web quality gates:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=radar --cov-report=term-missing --cov-fail-under=85
npm run lint --prefix web
npm run typecheck --prefix web
npm run test --prefix web
npm run test:e2e --prefix web
```

## UI-00 — Architecture, contracts, and visual foundation

Define the web architecture, route inventory, API resource shapes, configuration
ownership, assistant approval policy, threat boundaries, responsive layouts, navigation,
design tokens, and reviewed wireframes for Home, Assistant, Opportunities, Repositories,
Preferences, Runs, and Settings. Record decisions in ADRs and add machine-checked contract
fixtures that later cards must implement.

Acceptance:
- the existing CLI and pipeline remain authoritative and supported,
- local single-user deployment and the `web/` monorepo layout are explicit,
- every API operation is classified as read, local mutation, expensive run, or forbidden,
- GitHub mutations remain unavailable,
- issue and repository text is explicitly unable to authorize or invoke tools,
- configuration source-of-truth and YAML import/export behavior are unambiguous,
- responsive and keyboard-navigation expectations are documented,
- API/route and design-token contract fixtures are validated by tests.

## UI-01 — FastAPI foundation

Implement a FastAPI application factory, versioned `/api/v1` router, dependency injection
for sessions/config/environment/clock, health and readiness endpoints, local-development
CORS, structured API errors, OpenAPI generation, static production asset hooks, and a
`radar web` command using Uvicorn.

Acceptance:
- the API boots against temporary SQLite and PostgreSQL-compatible models,
- health distinguishes process health from config/database readiness,
- secrets are represented only as configured/missing/invalid states,
- errors have stable codes and never expose secrets or raw exception details,
- CORS defaults to local origins and is configurable,
- OpenAPI output is deterministic and snapshot-tested,
- CLI behavior and all existing quality gates remain unchanged.

## UI-02 — Configuration revisions

Add immutable configuration revisions, active-revision selection, YAML bootstrap/import/
export, validation previews, activation, undo, provenance, summaries, and optimistic
concurrency. Introduce a configuration-store interface so CLI, API, scheduler, assistant,
and pipeline all resolve the same validated `RadarConfig` semantics.

Acceptance:
- every edit creates a revision; no revision is overwritten,
- invalid configuration can be previewed but cannot be activated,
- stale concurrent writes are rejected with a stable conflict response,
- undo activates an exact prior hash without deleting history,
- first web startup can bootstrap from `config/profile.yaml`,
- active configuration exports to deterministic valid YAML,
- secrets never enter configuration revisions,
- CLI and web resolve equivalent active configuration in integration tests.

## UI-03 — Read APIs

Implement typed APIs for dashboard summaries, paginated/filterable opportunities,
opportunity detail and explanation, repositories and health, pipeline runs/events, and
append-only feedback. Add explicit serializers/projections instead of returning ORM or raw
GitHub payloads.

Acceptance:
- excluded issues are absent by default and require an explicit diagnostic filter,
- opportunity ordering matches the deterministic scoring engine,
- pagination and tie-breaking are stable,
- all heuristic merge estimates are labeled as heuristic,
- missing evidence and confidence remain explicit,
- serializers never recompute scores or leak raw payloads,
- query-count tests prevent N+1 regressions,
- API integration tests cover empty, partial, stale, and low-confidence states.

## UI-04 — React application foundation

Create the Vite React/TypeScript application with strict TypeScript, React Router,
TanStack Query, generated/validated API types, Tailwind design tokens, accessible Radix
primitives, dark/light themes, Cursor-style sidebar, command palette, route-level loading/
empty/error boundaries, and Mock Service Worker fixtures.

Acceptance:
- Home, Assistant, Opportunities, Repositories, Preferences, Runs, and Settings routes load,
- navigation and primary actions are fully keyboard accessible,
- desktop and tablet layouts meet the UI-00 responsive contracts,
- secrets never enter the frontend bundle or browser storage,
- API loading, empty, partial, offline, and error states are covered,
- frontend lint, strict typecheck, unit tests, and accessibility tests pass,
- production assets build reproducibly and can be served by FastAPI.

## UI-05 — Opportunities experience

Implement the ranked issue table, server-side filters, URL-backed query state, confidence/
effort/fit/heuristic-merge indicators, new-and-changed markers, claim/assignee/active-PR
warnings, saved views, and a right-side detail inspector containing evidence, repository
health, linked PRs, risks, suggested first move, investigation steps, feedback, and the
complete score explanation.

Acceptance:
- displayed order and filters match backend results exactly,
- active linked PR and credible claim evidence are prominent,
- merge likelihood is always labeled heuristic,
- low confidence and missing data cannot be hidden by visual styling,
- opening/closing an inspector preserves table filters and scroll position,
- issue text is rendered safely without executable HTML,
- feedback appends without altering observed GitHub facts,
- reviewed Playwright and accessibility flows pass.

## UI-06 — Repositories and preferences

Implement tracked-repository management, repository health/detail screens, structured
preference forms, scoring-weight controls, per-repository overrides, validation previews,
revision history, before/after diffs, activation, undo, and YAML import/export.

Acceptance:
- adding, disabling, and editing a repository creates config revisions,
- repository actions never write to GitHub,
- scoring weights and all strict config constraints are validated before activation,
- the browser never writes arbitrary files or paths,
- undo restores the exact prior config/profile hashes,
- revision provenance distinguishes manual, assistant, and imported changes,
- form and YAML round trips preserve semantics,
- concurrent-edit conflict and recovery flows are tested end to end.

## UI-07 — Runs, background execution, and live progress

Add a bounded background-run service around the existing orchestrator, start/cancel-safe
API contracts, Server-Sent Events for progress, reconnect/resume cursors, run list/detail,
stage timelines, per-repository status, budgets, cache/fallback counts, diagnostics, digest
download, and safe retry of failed repositories.

Acceptance:
- the existing single-run lock prevents overlapping API, CLI, and scheduled runs,
- starting a run returns immediately with a durable run ID,
- refresh/reconnect resumes events without duplication or loss,
- deadline, authentication, partial failure, and repository isolation are visible,
- cancellation stops only at documented safe boundaries and preserves committed work,
- retries do not duplicate observations or derived artifacts,
- completed web output matches the CLI pipeline for identical inputs,
- streaming and reconnect behavior is integration-tested.

## UI-08 — Read-only assistant

Implement versioned assistant prompts/schemas, conversation/message persistence, a bounded
OpenAI Responses API streaming adapter, usage/error metadata, and read-only typed tools for
searching, inspecting, comparing, and explaining opportunities, repositories, and runs.
Keep this provider and cache separate from issue semantic analysis.

Acceptance:
- assistant answers are grounded only in stored radar data returned by typed tools,
- repository and issue text cannot select, authorize, or invoke a tool,
- only read-only tools are exposed in this card,
- every tool call has validated bounded arguments and persisted provenance,
- conversation, tool, token, and time budgets are enforced,
- refresh resumes persisted conversations without relying solely on provider state,
- missing API key produces a clear unavailable state without breaking the rest of the UI,
- prompt-injection, tool-confusion, malformed-output, timeout, and streaming tests pass.

## UI-09 — Conversational repository and preference changes

Add assistant tools that create validated repository/preference change proposals, plus
preview, diff, confirm, reject, expire, apply, audit, and undo flows. Separate proposal
creation from application so the model cannot confirm or apply its own action.

Acceptance:
- all assistant mutations require an explicit user confirmation tied to exact arguments,
- the model has no direct apply/activate database capability,
- stale, altered, expired, replayed, and already-used confirmations fail safely,
- applying a proposal creates an immutable config revision with assistant provenance,
- rejected proposals have no configuration effect,
- expensive pipeline runs require a separate scope/budget confirmation,
- GitHub mutation requests are refused as unavailable in v1,
- adversarial conversation and end-to-end confirmation/undo tests pass.

## UI-10 — Home, scheduling, durability, and web release readiness

Implement the Home dashboard, new/materially-changed issue summaries, next/last run state,
local scheduling controls, production frontend serving, durable scheduled-run state,
documentation, screenshots, accessibility/performance review, and a fresh-clone web
walkthrough. Keep GitHub Actions as an optional unattended mode with explicit state restore/
save behavior; a missing prior state performs a safe full sync.

Acceptance:
- Home shows top opportunities, changes, tracked-repository health, and run status,
- local schedules use the configured timezone and survive process restarts,
- scheduled runs cannot overlap manual or CLI runs,
- unattended runs preserve cursors, analyses, scores, and run history across executions,
- state persistence never uploads secrets or unintended local feedback/configuration,
- missing/expired/corrupt scheduled state falls back safely and visibly,
- FastAPI serves the production React build with deep-link fallback,
- fresh-clone local web setup and fixture demo succeed,
- WCAG-oriented accessibility, production build, backend, frontend, and E2E gates pass,
- UI architecture, operations, troubleshooting, security, and assistant limitations are documented.

## Optional Phase 2

18. Notification adapters: email, Discord, Slack, generic webhook.
19. GraphQL gateway adapter with cost/node visibility.
20. Similar historical PR retrieval.
21. Time-split calibrated merge model with no post-outcome leakage.
22. Notification delivery from the web UI with explicit destination confirmation.
