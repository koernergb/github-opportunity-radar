# Extension guide

## Add a GitHub observation

Add a transport-neutral DTO and gateway method, normalize upstream JSON, persist raw and
typed observation fields, and test pagination/retry/idempotency. Keep the REST dependency
outside domain and scoring modules. V1 remains read-only.

## Add a filter

Add one stable code and evidence object in `filtering/rules.py`, decide explicitly whether
it excludes or warns, add a dedicated rule test, and increment the filter version. Never
execute or follow instructions found in issue text.

## Add an analysis provider

Implement `AnalysisProvider`, return the strict `IssueAnalysisOutput`, bound time/retries,
and retain usage metadata. Provider output must not contain a final score or authoritative
merge probability. Keep deterministic fallback and cache behavior provider-independent.

## Change scoring

Keep formulas deterministic and normalized, record every coefficient/contribution in the
explanation, add monotonicity and golden-order fixtures, and increment the score or modifier
version. Never train on post-outcome evidence when estimating pre-work merge likelihood.

## Add a digest or notification adapter

Consume `Digest` projections rather than querying observations ad hoc. Preserve eligibility,
confidence warnings, deterministic ordering, freshness, and the heuristic-estimate label.
Notification adapters belong after the read-only scoring pipeline and must redact secrets.
