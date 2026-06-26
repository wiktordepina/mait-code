---
name: recall
description: Search memory for past facts, decisions, patterns, and preferences. Use when the user asks about something previously discussed or stored.
argument-hint: "<query>"
allowed-tools: Bash(mc-tool-memory *)
---

# /recall

Search persistent memory for relevant past context.

## When invoked with a query

Search results:

!`mc-tool-memory search $ARGUMENTS 2>/dev/null || echo "No query provided or search failed."`

Recent memories:

!`mc-tool-memory list --limit 5 2>/dev/null`

## Instructions

Present the results above clearly. If the search returned no results, suggest broadening the query. If only the recent list has results (no query was given), present those.

Results are scoped to the current project and branch by default. To refine, run any of these via Bash:

- `mc-tool-memory search <query> --mode vector` — semantic search; reach for this when keyword matching misses the intent (default mode is `hybrid`; `fts` is keyword-only)
- `mc-tool-memory search <query> --type <type>` — restrict to one entry type (`fact`, `preference`, `decision`, `insight`, `event`, `task`, `relationship`, `procedure`)
- `mc-tool-memory search <query> --scope all` — search across all projects, not just the current one
- `mc-tool-memory list --since 7d` (e.g. `24h`, `1w`) or `--include-superseded` — recent or historical entries rather than a query
