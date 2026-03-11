---
name: remember
description: Store a new memory observation manually
argument-hint: "<content>"
disable-model-invocation: true
allowed-tools: Bash(mc-tool-memory store *)
---

# /remember

Store a memory explicitly.

## Instructions

When the user invokes `/remember <content>`:

1. Determine the best entry type for the content:
   - `fact` — objective information (default)
   - `preference` — user likes/dislikes
   - `event` — something that happened
   - `insight` — a conclusion or pattern
   - `task` — a to-do or action item
   - `relationship` — connection between entities

2. Estimate importance (1-10):
   - 1-3: minor, transient
   - 4-6: normal (default 5)
   - 7-9: important, referenced often
   - 10: critical, must not forget

3. Determine scope:
   - Cross-project facts (e.g., "always use tabs for Go code") → `--scope global`
   - Project-specific facts (e.g., "this repo uses 4-space indent") → auto-detected (default)
   - Branch-specific notes → auto-detected (default)

4. Store using: `mc-tool-memory store "<content>" --type <type> --importance <N>` (add `--scope global` if applicable)

5. Confirm what was stored.

## Examples

- `/remember always use tabs for Go code` — preference, importance 7
- `/remember deployed v2.3 to production today` — event, importance 6
- `/remember the auth service uses JWT with RS256` — fact, importance 7
