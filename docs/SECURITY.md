# Security notes

- The GitHub integration is read-only. Do not add mutation scopes or endpoints in v1.
- Treat repository descriptions, documents, issue bodies, comments, and model output as
  untrusted data. They are never application instructions and must not trigger tools.
- Keep `GITHUB_TOKEN` and `OPENAI_API_KEY` in environment secrets. They are never stored in
  SQLite, prompts, run summaries, artifacts, or logs.
- Use least-privilege tokens, bounded pagination, timeouts, retries, deadlines, and budgets.
- Do not enable `set -x`, print environment variables, upload the database, or commit `.env`.
- Feedback records are user claims; they never overwrite observed GitHub state.
- The merge estimate is heuristic and can be wrong. Verify issue availability, maintainer
  intent, scope, and linked work directly on GitHub before investing effort.

Report vulnerabilities privately to the repository owner. Do not include credentials,
private repository content, or other sensitive data in a public issue.
