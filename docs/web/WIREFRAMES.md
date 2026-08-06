# Web UI wireframes

These wireframes define information hierarchy, not final pixel styling.

## Shared desktop shell

```text
┌──────────┬──────────────────────────────────────────────────────┐
│ Radar  ⌘K│ Page title                            Run radar      │
│          ├──────────────────────────────────────────────────────┤
│ Home     │                                                      │
│ Assistant│                 route content                        │
│ Issues   │                                                      │
│ Repos    │                                                      │
│ Prefs    │                                                      │
│ Runs     │                                                      │
│ Settings │                                                      │
└──────────┴──────────────────────────────────────────────────────┘
```

## Home

```text
┌─ Radar status ──────────────────────────────────────────────────┐
│ Last run 12m ago · healthy     Next run tomorrow 09:00         │
├─ Top opportunities ────────────┬─ Changes since last run ──────┤
│ 82  owner/repo#42              │ 3 new · 2 claimed · 1 blocked │
│ 76  owner/other#18             │                                │
├────────────────────────────────┴────────────────────────────────┤
│ Repository health and recent run activity                       │
└─────────────────────────────────────────────────────────────────┘
```

## Assistant

```text
┌─ Conversations ─┬───────────────────────────────────────────────┐
│ Today            │ You: Best issues under eight hours?          │
│ Repo comparison  │ Radar: …grounded answer and issue links…     │
│                  │ ┌─ Proposed preference change ─────────────┐ │
│                  │ │ exact diff       Reject       Apply      │ │
│                  │ └───────────────────────────────────────────┘ │
│                  │ Ask about tracked repositories…               │
└──────────────────┴───────────────────────────────────────────────┘
```

## Opportunities

```text
┌─ Filters ────────────────────────────────────────────────────────┐
│ Repo  Effort  Confidence  Task type  Claim state  Search        │
├─────────────────────────────────────┬────────────────────────────┤
│ 82  owner/repo#42  4–8h  High       │ Issue inspector            │
│ 76  owner/other#18 6–12h Moderate   │ evidence, risks, scoring,  │
│ 61  owner/repo#51  2–4h  LOW CONF  │ linked PRs, first move     │
└─────────────────────────────────────┴────────────────────────────┘
```

## Repositories

```text
┌─ Tracked repositories ───────────────────────────────────────────┐
│ Add repository                                                   │
│ owner/repo     enabled   14 candidates   synced 12m ago          │
│ owner/other    warning    3 candidates   partial sync            │
└──────────────────────────────────────────────────────────────────┘
```

## Preferences

```text
┌─ Profile editor ───────────────────┬─ Revision history ──────────┐
│ Languages · interests · effort     │ current  abc123  manual     │
│ task types · avoid · hardware      │ prior    def456  assistant  │
│ scoring weights                    │ View diff · Undo · Export   │
│ Validate changes        Save       │                             │
└────────────────────────────────────┴─────────────────────────────┘
```

## Runs

```text
┌─ Runs ───────────┬─ Run detail ──────────────────────────────────┐
│ running  now     │ sync ✓  metrics ✓  analyze 12/30  digest …   │
│ success  1d ago  │ repository events, budgets, cache/fallbacks  │
│ partial  3d ago  │ structured errors and digest download        │
└──────────────────┴───────────────────────────────────────────────┘
```

## Settings

```text
┌─ Connections ────────────────────────────────────────────────────┐
│ GitHub configured · OpenAI missing · SQLite ready               │
├─ Appearance and diagnostics ─────────────────────────────────────┤
│ Theme · API status · application versions                       │
└──────────────────────────────────────────────────────────────────┘
```
