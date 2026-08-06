# ADR 0003: Local single-user React and FastAPI web application

Status: accepted (2026-08-05)

## Decision

The first web release is a local, single-user application in this monorepo. FastAPI exposes
versioned HTTP resources over the existing Python services and database. A React and
TypeScript application lives in `web/` and consumes only those resources. The CLI and web
application call the same domain services; neither reimplements scoring, filtering, or
GitHub synchronization.

The web application uses immutable database configuration revisions. On first startup it
may import `config/profile.yaml`; afterward the active revision is authoritative for web,
assistant, scheduler, and pipeline execution. Deterministic YAML import/export preserves
CLI portability. Secrets remain environment-only.

Assistant reads may execute immediately. Repository/preference mutations and expensive
runs create exact, expiring proposals requiring a separate user confirmation. GitHub
mutations are unavailable. Repository and issue text is always untrusted evidence and can
neither choose nor authorize tools.

## Consequences

- `src/radar/api/` owns HTTP concerns; `web/` owns presentation.
- SQLite remains the local default and PostgreSQL compatibility is retained.
- Local access has no account system in the first release; remote hosting requires a new
  authentication and authorization ADR.
- Server-Sent Events carry run and assistant progress because traffic is primarily
  server-to-browser.
- The UI must label merge likelihood as heuristic and show missing evidence/confidence.
