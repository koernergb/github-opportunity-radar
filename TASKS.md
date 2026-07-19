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

## Optional Phase 2

18. Notification adapters: email, Discord, Slack, generic webhook.
19. GraphQL gateway adapter with cost/node visibility.
20. Similar historical PR retrieval.
21. Time-split calibrated merge model with no post-outcome leakage.
22. Read-only FastAPI/HTMX local dashboard.
