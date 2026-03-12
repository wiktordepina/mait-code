---
name: reflect
description: Synthesise recent observations into insights and propose MEMORY.md updates
allowed-tools: Bash(mc-tool-memory *), Read, Edit
---

# /reflect

Synthesise recent observations into high-level insights.

## Instructions

1. Run `mc-tool-memory reflect` via Bash to generate insights (scoped to current project by default).
2. Present the generated insights to the user. If the output includes proposed MEMORY.md updates:

1. Show the proposed changes clearly
2. Ask the user if they want to apply the changes
3. If approved, edit `~/.claude/mait-code-data/memory/MEMORY.md` to incorporate the updates
4. Keep MEMORY.md under ~150 lines

Reflection is idempotent — each observation is only reflected on once, tracked by a per-project watermark. Running `/reflect` twice without new observations is a no-op.

If reflection was skipped (not enough new observations), explain that there isn't enough new data since the last reflection and suggest trying again later.

If the user wants to force a reflection with a different time window, run `mc-tool-memory reflect --days <N> --min-new 0`.

For large backlogs, use `mc-tool-memory reflect --drain` to process all unreflected entries in batches. Use `--batch-size <N>` to control entries per batch (default 50).

For cross-project reflection, run `mc-tool-memory reflect --scope all`.
