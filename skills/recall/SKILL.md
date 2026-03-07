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

If the user wants to refine, run `mc-tool-memory search <new query>` via Bash.
