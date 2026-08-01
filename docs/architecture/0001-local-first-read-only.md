# ADR 0001: Local-first, read-only v1

Status: accepted (2026-07-31)

V1 reads public GitHub data and writes only to a user-controlled database and requested
artifacts. It does not comment, assign, label, open PRs, or send notifications. This keeps
the trust boundary narrow, makes reruns auditable, and prevents issue text from inducing
external actions. Future write adapters require a separate decision and explicit user
authorization.
