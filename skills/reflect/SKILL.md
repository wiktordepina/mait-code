---
name: reflect
description: Synthesise recent observations into insights and propose MEMORY.md rewrites, merges & retirements. Use when the user asks to reflect, distil or consolidate recent learnings, or refresh what's in MEMORY.md.
allowed-tools: Bash(mc-tool-memory *), Read, Edit
---

# /reflect

Synthesise recent observations into high-level insights, and consolidate
MEMORY.md — not just append to it. Reflection can propose four kinds of
operation: **add**, **rewrite**, **merge**, and **retire**. You apply each one
only after the user approves it.

## Instructions

1. Run `mc-tool-memory reflect --json` via Bash (scoped to current project by
   default). Insights are generated and stored automatically; the JSON payload
   is `{skipped, reason, insights, ops, stored}`.
2. If `skipped` is true, tell the user there isn't enough new data since the
   last reflection and suggest trying again later. Stop here.
3. Present the `insights` list.
4. If `ops` is non-empty, render them as a clear before/after diff so the user
   can see each proposed change:
   - **add** → a new line (`+`)
   - **rewrite** → the old text replaced by the new (`~ old → new`)
   - **merge** → several existing facts folded into one
   - **retire** → a stale/contradicted fact dropped (`-`)
5. **Ask the user to approve or reject each operation** (offer approve-all /
   reject-all / pick as a convenience). Never apply an op the user hasn't
   approved — MEMORY.md stays human-approved.
6. For each **approved** op, apply it in **two places**:
   - **MEMORY.md** (`~/.claude/mait-code-data/memory/MEMORY.md`) via Edit —
     add the new line, replace the rewritten line, fold the merged lines into
     one, or delete the retired line.
   - **The memory database**, when the op carries `entry_ids` (the backing
     stored entries). This stops the raw store from resurfacing what you just
     consolidated in the curated layer. Run the matching verb per op:
     - **retire** → `mc-tool-memory retire <id>` for each id.
     - **merge** → `mc-tool-memory merge <id1> <id2> … --into "<consolidated text>"`.
     - **rewrite** → one backing id: `mc-tool-memory supersede <id> "<new text>"`;
       several ids: `mc-tool-memory merge <ids…> --into "<new text>"`.
     - **add** → no db verb (there's no prior entry to consolidate).
   An op with an empty `entry_ids` list touches MEMORY.md only.
7. Keep MEMORY.md under ~150 lines. If applying an op would push it over, prefer
   merging or retiring older lines over letting it grow.

## Routing: which curated layer?

mait-code's MEMORY.md and Claude Code's native auto memory
(`~/.claude/projects/<munged-path>/memory/`) are kept cleanly separated —
facts about the **project** belong in the native layer; facts about the
**user** belong in mait-code:

- **Cross-project user/identity facts** (preferences, conventions, working
  style, decisions about how the user works) → mait-code MEMORY.md. This is
  what these operations target.
- **Per-project code facts** (architecture, build/test commands, repo
  gotchas) → Claude Code's native auto memory, which it maintains itself.

When a proposed **add** concerns a project/code fact, do **not** add it to
mait-code's MEMORY.md — write it to the native per-project memory instead (or
skip it if the native layer already records it). Putting the same fact in
both layers makes them drift and double-spends context tokens.

Reflection is idempotent — each observation is only reflected on once, tracked by a per-project watermark. Running `/reflect` twice without new observations is a no-op.

If reflection was skipped (not enough new observations), explain that there isn't enough new data since the last reflection and suggest trying again later.

Keep `--json` on every variant below so you get structured `ops` back.

If the user wants to force a reflection with a different time window, run `mc-tool-memory reflect --json --days <N> --min-new 0`.

For large backlogs, use `mc-tool-memory reflect --json --drain` to process all unreflected entries in batches. Use `--batch-size <N>` to control entries per batch (default 50).

For cross-project reflection, run `mc-tool-memory reflect --json --scope all`.
