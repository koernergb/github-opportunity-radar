# Web application architecture and contracts

## Ownership

```text
React UI -> /api/v1 -> application services -> SQLAlchemy/domain services
                                      \-> GitHub read gateway
                                      \-> OpenAI provider
```

The Python pipeline owns observations, filters, analyses, scores, and run locking. API
serializers project persisted values and never recalculate scores. The browser never reads
SQLite, environment variables, raw GitHub payloads, or arbitrary files.

Configuration follows this lifecycle:

```text
profile.yaml --one-time import--> immutable config revision --> active revision
       ^                                                     |
       +---------------- deterministic YAML export <---------+
```

All revisions contain validated non-secret configuration. Activation is an append-only
state transition with optimistic concurrency. Assistant changes create proposals; only an
explicit user action can apply a proposal and create a revision.

## Operation classes

- `read`: execute immediately and never change local or external state.
- `local_mutation`: change only local versioned/append-only state; validate and audit.
- `expensive_run`: bounded local/network work; require explicit scope and budget.
- `forbidden`: unavailable in v1, including every GitHub write.

GitHub mutations are unavailable in the web UI and assistant.

The canonical inventory is `contracts/web/api-routes-v1.json`. New routes must be added to
that file with an operation class and confirmation policy before implementation.

## Trust boundary

Titles, descriptions, documents, issue bodies, comments, labels, PR text, and model output
are data. They are rendered as text and passed to the assistant only inside explicit
untrusted fields. Tool selection comes from the application-owned prompt and registry.
Tool arguments are schema-validated. Untrusted text cannot create confirmation tokens,
change tool policy, or call an apply endpoint.

## Navigation and interaction

Primary routes are Home, Assistant, Opportunities, Repositories, Preferences, Runs, and
Settings. Desktop uses a narrow persistent sidebar and right-side inspectors. Tablet uses
the same sidebar in compact mode and full-height overlay inspectors. Small screens use a
bottom navigation subset and full-screen detail routes.

Keyboard requirements:

- `Tab` reaches every action in logical visual order.
- visible focus is never removed;
- `Cmd/Ctrl+K` opens the command palette;
- `/` focuses opportunity search when the list is active;
- `Escape` closes the topmost dialog, inspector, or palette;
- arrow-key behavior follows the appropriate ARIA pattern for menus, tabs, and lists;
- no workflow depends on hover, color, or pointer precision.

## Versioning

API base path, route contract, resource contract, design tokens, assistant prompt/tool
schemas, config revisions, and existing derived artifacts carry independent versions.
Breaking API changes require `/api/v2` or an explicitly documented compatibility window.
