---
name: board
description: View and drive the project kanban board. Use when the user mentions the board, asks to pick up / refine / move / complete a card, asks what's on the board, or wants to add a card to the board.
allowed-tools: Bash(mc-tool-board *)
---

# /board

View and drive the kanban board for the current project.

## Current board

!`mc-tool-board list 2>/dev/null || echo "No board yet — add a card with: mc-tool-board add \"<title>\""`

## Instructions

The board is a **manually-driven** kanban — *you (Claude) are the worker*. There is no autonomous dispatcher; you act only when the user asks. Drive it through `mc-tool-board` via Bash. Cards flow through fixed columns: **backlog → refined → in_progress → done**, with **blocked** and a hidden **archived** side-state.

Present the board above clearly, then act on what the user asks.

### Picking up work

- **"pick up the next refined card"** (or similar): run `mc-tool-board next --claim --json`. This returns the highest-priority (then oldest) refined card for the current project *and* moves it to `in_progress`. Read its `acceptance_criteria`, then do the work in this session.
- Peek without claiming: `mc-tool-board next --json`.

### Refining

- **"refine card N"**: draft a clear description and acceptance criteria, **show them to the user for approval first**, then run `mc-tool-board refine N --description "..." --acceptance "..."` (moves it to `refined`). Don't refine without confirmation.

### Finishing & parking

- Complete: `mc-tool-board complete N --summary "what was done"` (moves to `done`, records a handoff summary).
- Block: `mc-tool-board block N <reason>` — the reason is recorded as a comment. Unblock: `mc-tool-board unblock N` (returns it to `refined`).
- Archive (hide, don't delete): `mc-tool-board archive N`.
- Arbitrary move: `mc-tool-board move N <backlog|refined|in_progress|blocked|done|archived>`.

### Adding & editing

- Add: `mc-tool-board add "<title>" [--description ...] [--priority low|medium|high] [--project <name>]`. New cards land in `backlog`. Use `--project` for work with no git repo yet (e.g. an app idea).
- Edit: `mc-tool-board edit N [--title ...] [--description ...] [--priority ...] [--acceptance ...]`.
- Comment: `mc-tool-board comment N "<note>" [--author claude]`.
- Show one card with its thread: `mc-tool-board show N`.

### Viewing

- This project: `mc-tool-board list`. All projects: `mc-tool-board list --all`. Include archived: add `--archived`. Machine-readable: add `--json`.

## Proactive behaviour

If you spot work worth tracking during a session, you may **suggest** adding a card — but always ask before adding. When you finish a chunk of work that maps to an in-progress card, offer to complete it with a summary. Never move, complete, or archive cards without the user's say-so.
