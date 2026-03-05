---
name: recall
description: Search memory for past facts, decisions, patterns, and preferences
argument-hint: "<query>"
user-invocable: true
allowed-tools:
  - mcp__mait-memory__search_memory
  - mcp__mait-memory__list_recent_memories
---

# /recall

Search memory for relevant past context using the `mait-memory` MCP server.

## Instructions

When the user invokes `/recall <query>`:

1. Use the `search_memory` tool from the `mait-memory` MCP server with the user's query
2. If no results are found, tell the user and suggest broadening the query
3. If results are found, present them clearly with:
   - The memory content
   - When it was stored (date)
   - Its type and importance
4. Offer to search again with a different query if the results aren't helpful

If the user provides no query, use `list_recent_memories` to show the latest entries.

## Examples

- `/recall database preferences` — Search for past decisions about databases
- `/recall testing patterns` — Find remembered testing approaches
- `/recall kubernetes` — Look up stored knowledge about Kubernetes
- `/recall` — Show recent memories (no query)
