# Command reference

Commands use `RADAR_CONFIG` and `RADAR_DATABASE_URL` unless an explicit option overrides
them. Run `uv run radar COMMAND --help` for the complete option list.

| Command | Purpose | Network/write behavior |
|---|---|---|
| `radar validate-config` | Validate YAML and print stable hashes | Offline; no writes |
| `radar init-db` | Create or migrate the local database | Local database write |
| `radar doctor [--github]` | Diagnose config, database path, keys, and optional GitHub access | Offline unless `--github` |
| `radar repos list` | List configured repositories | Offline; no writes |
| `radar repos sync` | Observe repositories and contribution documents | Read-only GitHub; local writes |
| `radar sync [--repo NAME] [--full]` | Observe issues, comments, and PR history | Read-only GitHub; local writes |
| `radar metrics [--repo NAME]` | Derive versioned repository metrics | Offline; local writes |
| `radar filter [--repo NAME]` | Derive deterministic exclusions/warnings | Offline; local writes |
| `radar analyze [--limit N] [--fallback-only]` | Cache structured or fallback semantic features | OpenAI unless fallback/cached; local writes |
| `radar rank [--top N]` | Display persisted current-profile ranking | Offline; no writes |
| `radar digest [--format terminal\|markdown]` | Render current-profile eligible scores | Offline; optional output file |
| `radar explain OWNER/REPO#N` | Print exact persisted score inputs and contributions | Offline; no writes |
| `radar feedback OWNER/REPO#N STATUS` | Append validated private feedback | Offline; local append only |
| `radar run [--fallback-only]` | Execute the bounded end-to-end pipeline | Read-only GitHub/OpenAI; local writes |

Exit codes are `0` success, `1` general failure, `2` configuration/usage, `3`
authentication, `4` safe partial run, and `5` overlapping-run lock. The pipeline never
writes to GitHub. A score's merge field is always a heuristic estimate, not a calibrated
probability.
