---
name: triage
description: Triage the quick-capture inbox — route each captured item to the board or memory. Use when the user mentions triage, the inbox, processing/sorting captured items, or asks to clear the inbox.
allowed-tools: Bash(mc-tool-inbox *), Bash(mc-tool-board *), Bash(mc-tool-memory *)
---

# /triage

Drain the quick-capture inbox by routing each item to where it belongs.

## Current inbox

!`mc-tool-inbox list 2>/dev/null || echo "Inbox is empty."`

## Instructions

The inbox is a "capture now, sort later" holding pen. Your job is to help route
each item out — **suggestion-based, the user decides**. Never route or remove an
item without confirmation.

Work through the items above one at a time. For each, propose the best
destination, and on the user's say-so create it in the target store, then
**remove the item from the inbox** so it stays near-empty:

- **Board card** — actionable project work (a one-line title lands straight in
  the backlog; no description or refinement needed for a quick to-do):
  `mc-tool-board add "<title>" [--description ...] [--priority low|medium|high] [--project <name>]`
- **Memory** — a durable fact about the user, a project, or a preference:
  use the `/remember` skill (or `mc-tool-memory` directly)

After the item lands in its destination, drain it: `mc-tool-inbox remove <id>`.

If an item turns out to be noise or no longer relevant, offer to drop it
(`mc-tool-inbox remove <id>`) without routing.

The goal is an empty (or near-empty) inbox. When you're done, summarise what was
routed where.
