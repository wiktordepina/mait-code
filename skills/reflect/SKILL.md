---
name: reflect
description: Synthesise recent observations into insights and propose MEMORY.md updates. Use when the user asks to reflect, distil or consolidate recent learnings, or refresh what's in MEMORY.md.
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

## Routing: which curated layer?

mait-code's MEMORY.md and Claude Code's native auto memory
(`~/.claude/projects/<munged-path>/memory/`) are kept cleanly separated —
facts about the **project** belong in the native layer; facts about the
**user** belong in mait-code:

- **Cross-project user/identity facts** (preferences, conventions, working
  style, decisions about how the user works) → mait-code MEMORY.md. This is
  what the proposals above are for.
- **Per-project code facts** (architecture, build/test commands, repo
  gotchas) → Claude Code's native auto memory, which it maintains itself.

When a proposed MEMORY.md update is a project/code fact, do **not** add it to
mait-code's MEMORY.md — write it to the native per-project memory instead (or
skip it if the native layer already records it). Putting the same fact in
both layers makes them drift and double-spends context tokens.

Reflection is idempotent — each observation is only reflected on once, tracked by a per-project watermark. Running `/reflect` twice without new observations is a no-op.

If reflection was skipped (not enough new observations), explain that there isn't enough new data since the last reflection and suggest trying again later.

If the user wants to force a reflection with a different time window, run `mc-tool-memory reflect --days <N> --min-new 0`.

For large backlogs, use `mc-tool-memory reflect --drain` to process all unreflected entries in batches. Use `--batch-size <N>` to control entries per batch (default 50).

For cross-project reflection, run `mc-tool-memory reflect --scope all`.
