# Security notes

- The GitHub integration is read-only. Do not add mutation scopes or endpoints in v1.
- Treat repository descriptions, documents, issue bodies, comments, and model output as
  untrusted data. They are never application instructions and must not trigger tools.
- Keep `GITHUB_TOKEN` and provider API keys in environment secrets or the operating-system
  credential vault. They are never stored in SQLite, configuration revisions, exports,
  browser storage, prompts, run summaries, artifacts, or logs.
- Use least-privilege tokens, bounded pagination, timeouts, retries, deadlines, and budgets.
- Do not enable `set -x`, print environment variables, upload the database, or commit `.env`.
- Feedback records are user claims; they never overwrite observed GitHub state.
- Issue, repository, PR, and comment text is untrusted data. It cannot select tools or
  authorize assistant actions.
- Assistant config changes are expiring, exact-argument proposals. The model cannot call
  confirm, apply, activate, undo, pipeline-launch, or GitHub-write endpoints.
- Provider-key inputs are write-only: the browser never receives a stored API key. Secret
  mutations require an explicit intent header and an allowed local origin. Local schedule
  state contains no credentials.
- GitHub Actions restores only its dedicated ephemeral runner database. It never uploads a
  developer's local database, `.env`, personal profile, or local feedback.
- The merge estimate is heuristic and can be wrong. Verify issue availability, maintainer
  intent, scope, and linked work directly on GitHub before investing effort.

Report vulnerabilities privately to the repository owner. Do not include credentials,
private repository content, or other sensitive data in a public issue.
