# Multi-provider LLM implementation plan

## Outcome

GitHub Opportunity Radar will support OpenAI, Anthropic, Google Gemini, and Wafer for
bounded semantic issue analysis and the read-only conversational assistant. Users may
select separate providers and models for those workloads and may save provider API keys
from the local Settings screen without placing secrets in configuration revisions,
exports, logs, browser storage, or API responses.

## Invariants

- GitHub remains read-only.
- Issue and repository text remains untrusted evidence and never authorizes tools.
- LLM output remains a bounded semantic input; deterministic code owns final scores.
- Provider, exact model, prompt, schema, usage, and result status remain persisted with
  every derived artifact.
- Existing version-1 profiles using `llm.provider` and `llm.model` remain valid.
- Environment variables remain the credential source for CI and headless operation.
- A credential is write-only through the API. Existing credential material is never
  returned to the browser.

## Configuration

The existing analysis fields remain authoritative and optional assistant fields fall
back to them:

```yaml
llm:
  provider: wafer
  model: DeepSeek-V4-Flash-0731-Fast
  assistant_provider: anthropic
  assistant_model: claude-sonnet-4-5
  max_candidates_per_run: 30
  max_input_characters: 60000
```

Provider identifiers are `openai`, `anthropic`, `google`, and `wafer`. Model identifiers
are explicit strings so provider catalog changes do not require a Radar release.

## Credential boundary

`SecretStore` separates credentials from ordinary configuration. Resolution order is:

1. provider-specific process environment variable;
2. operating-system credential vault;
3. missing.

The operating-system vault is accessed through `keyring`. If no safe vault backend is
available, UI persistence fails closed and environment variables continue to work. The
API reports only provider, source, and configured/invalid/missing status. Secret-changing
requests require an allowed local `Origin` and a custom `X-Radar-Secret-Intent` header.

## Provider contracts

Two provider-neutral contracts remain intentionally separate:

1. analysis: strict `IssueAnalysisOutput` with one bounded repair attempt;
2. assistant: text deltas, validated tool calls, and usage metadata.

OpenAI uses the Responses API. Anthropic uses Messages and JSON-schema tool input. Google
uses Gemini `generateContent`/streaming and response schemas. Wafer uses its OpenAI-style
Chat Completions endpoint. Capability metadata prevents a model that has not demonstrated
tool calling from being selected for the assistant.

## API and UI

The API adds:

- `GET /api/v1/llm/providers`
- `PUT /api/v1/llm/providers/{provider}/credential`
- `DELETE /api/v1/llm/providers/{provider}/credential`
- `POST /api/v1/llm/providers/{provider}/test`

Settings displays one provider card per backend, a write-only key field, credential
source/status, test/remove controls, and analysis/assistant provider and model selectors.
Ordinary provider/model selections create immutable configuration revisions; credentials
never do.

## Delivery cards

### LLM-00 — Configuration and registry

Acceptance:

- all four provider identifiers validate;
- assistant selection falls back to analysis selection;
- old profiles retain identical hashes and semantics until edited;
- provider construction is centralized and no orchestration code hard-codes OpenAI.

### LLM-01 — Credential storage and safe API

Acceptance:

- environment and OS-vault credentials resolve predictably;
- keys are never returned, exported, revised, or logged;
- save/delete/test operations have stable sanitized responses;
- hostile origins and missing intent headers cannot change secrets.

### LLM-02 — Provider adapters

Acceptance:

- OpenAI, Anthropic, Google, and Wafer implement structured issue analysis;
- supported providers implement assistant text and tool events;
- timeouts, authentication errors, malformed output, and usage normalize at the boundary;
- provider/model identity is persisted accurately;
- mocked tests perform no paid network calls.

### LLM-03 — Settings experience

Acceptance:

- users can save, replace, test, and remove each provider key;
- users can select analysis and assistant provider/model independently;
- no key enters browser storage or is repopulated into an input;
- keyboard, loading, success, and sanitized error states are tested.

### LLM-04 — Operations and release readiness

Acceptance:

- CLI, API runs, proposals, and scheduler use the same provider resolution;
- readiness and doctor show all provider states without credential material;
- environment variables and limitations are documented;
- Ruff, formatting, mypy, pytest with 85% coverage, frontend lint, typecheck, unit tests,
  production build, and Playwright pass.

## Wafer compatibility policy

Wafer exposes `https://pass.wafer.ai/v1/chat/completions`, but capabilities can differ by
served model. Radar treats the catalog as dynamic, validates all structured output
locally, retries once with bounded validation feedback, and only advertises assistant tool
support for models that pass contract tests. Zero-data-retention support is surfaced as
model/provider metadata rather than assumed globally.
