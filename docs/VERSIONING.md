# Versioning guide

Package releases follow semantic versioning. Stored derived conclusions are versioned
independently so old observations remain usable and behavioral changes are auditable.

- Increment `metric_version` when a repository metric definition/window changes.
- Increment `filter_version` when rule behavior, codes, or evidence changes.
- Increment the prompt version and retain its SHA-256 when reviewed prompt text changes.
- Increment the analysis schema version for field or validation changes.
- Increment the context version when canonical input selection/truncation changes.
- Increment the score version when formulas, calibration, coefficients, or bands change.
- Increment the feedback-modifier version when preference effects change.

Never silently reinterpret an existing version. New derivations may reuse immutable
observations, but must write/upsert only their own version key. Database migrations govern
storage shape; artifact versions govern semantic meaning. Document user-visible changes
in `CHANGELOG.md`.
