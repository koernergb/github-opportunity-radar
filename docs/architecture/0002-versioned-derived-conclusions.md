# ADR 0002: Separate observations from versioned conclusions

Status: accepted (2026-07-31)

GitHub entities and raw payloads are observations. Metrics, filters, semantic analyses,
scores, and feedback modifiers are derived conclusions with independent version keys.
Prompts also retain a content hash. This allows formula and model changes without rewriting
history, exposes why a recommendation changed, and prevents user feedback from corrupting
upstream truth.
