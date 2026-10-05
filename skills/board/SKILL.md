---
name: board
description: View and drive the project kanban board. Use when the user mentions the board, asks to pick up / refine / move / complete a card, asks what's on the board, or wants to add a card to the board.
allowed-tools: Bash(mc-tool-board list:*), Bash(mc-tool-board show:*), Bash(mc-tool-board next:*), Bash(mc-tool-board export:*), Bash(mc-tool-board add:*), Bash(mc-tool-board edit:*), Bash(mc-tool-board move:*), Bash(mc-tool-board refine:*), Bash(mc-tool-board review:*), Bash(mc-tool-board complete:*), Bash(mc-tool-board block:*), Bash(mc-tool-board unblock:*), Bash(mc-tool-board tag:*), Bash(mc-tool-board untag:*), Bash(mc-tool-board ref:*), Bash(mc-tool-board comment:*), Bash(mc-tool-board archive:*), Bash(mc-tool-board bind:*), Bash(mc-tool-board unbind:*)
---

# /board

View and drive the kanban board for the current project.

## Current board

!`mc-tool-board list 2>/dev/null || echo "No board yet — add a card with: mc-tool-board add \"<title>\""`

## Instructions

The board is a **manually-driven** kanban — *you (Claude) are the worker*. There is no autonomous dispatcher; you act only when the user asks. Drive it through `mc-tool-board` via Bash. Cards flow through fixed columns: **backlog → refined → in_progress → in_review → done**, plus a hidden **archived** side-state. **blocked** is a tag carried in place (not a column), so a blocked card keeps its real column.

Present the board above clearly, then act on what the user asks.

### Picking up work

- **"pick up the next refined card"** (or similar): run `mc-tool-board next --claim --json`. This returns the highest-priority (then oldest) refined card for the current project *and* moves it to `in_progress`. Read its `acceptance_criteria`, then do the work in this session.
- **"pick up card N"** / **"continue card N"**: if the card isn't In Progress yet, `mc-tool-board move N in_progress`; if it already is (started in an earlier or parallel session), run `mc-tool-board bind N`. Either way this session ends up bound to it. Then read its `acceptance_criteria` and carry on.
- Peek without claiming: `mc-tool-board next --json`.

### Sessions

Several Claude Code sessions can work the same project at once, so each In Progress card records **which sessions are working on it**. Moving a card into `in_progress` (via `next --claim` or `move`) binds it to the current session automatically; `bind N` binds an already-started card; `unbind N` drops this session's binding. A card leaving In Progress (review, complete, archive, any move out) releases every binding. A binding stays active only while its session's Claude Code process is alive, and it follows a `/clear` or a resume on its own. Bindings are why "the card I'm on" is `mc-tool-board list --mine`, not the whole In Progress column.

### Refining

- **"refine card N"**: draft a clear description and acceptance criteria, **show them to the user for approval first**, then run `mc-tool-board refine N --description "..." --acceptance "..."` (moves it to `refined`). Don't refine without confirmation.

### Finishing & parking

- Review: `mc-tool-board review N [--pr <url>]` — moves the card to `in_review` (finished, awaiting review or merge) and, with `--pr`, records the PR as a `PR` reference. Use it once the work is up as a pull request.
- Complete: `mc-tool-board complete N --summary "what was done"` (moves to `done` from any column, records a handoff summary).
- Block: `mc-tool-board block N <reason>` — tags the card `blocked` **in place** (keeps its column); the reason is recorded as a comment. Unblock: `mc-tool-board unblock N` removes the tag. These are thin aliases over the tag system below.
- Tag / untag: `mc-tool-board tag N <tag>` / `mc-tool-board untag N <tag>` — free-form tags that ride alongside a card's status.
- Archive (hide, don't delete): `mc-tool-board archive N`.
- Delete permanently: `mc-tool-board remove N` — destructive and unrecoverable; prefer `archive` to hide a card. Only delete when the user explicitly asks.
- Arbitrary move: `mc-tool-board move N <backlog|refined|in_progress|in_review|done|archived>`.

### Adding & editing

The **description**, **acceptance criteria** and **completion summary** fields render markdown in the card detail view (plain text works too — it's a subset). Write these in markdown when it helps: headings, lists, emphasis, inline and fenced code all display formatted, and single newlines are kept as line breaks. No need to flatten a markdown source into plain prose.

- Add: `mc-tool-board add "<title>" [--description ...] [--priority low|medium|high] [--project <name>]`. New cards land in `backlog`. Use `--project` for work with no git repo yet (e.g. an app idea).
- Edit: `mc-tool-board edit N [--title ...] [--description ...] [--priority ...] [--acceptance ...] [--project ...]`.
- Comment: `mc-tool-board comment N "<note>" [--author claude]`.
- References (label→value links on a card): `mc-tool-board ref add N <label> <value>` — *value* is a URL, a `file://` path, or a bare ID. List them with `mc-tool-board ref list N`, remove one by its 1-based position with `mc-tool-board ref remove N <position>`. Cards carry these as a structured References field.
- Show one card with its comments and references: `mc-tool-board show N`.
- Every mutating subcommand (`add`, `move`, `refine`, `review`, `complete`, `block`/`unblock`, `tag`/`untag`, `ref add`/`ref remove`, `archive`, `bind`/`unbind`, `comment`, `edit`, `remove`) accepts `--json`, emitting the affected card after the mutation in the `show --json` shape — e.g. `add ... --json` returns the new card's id without parsing prose. `remove --json` emits the card as it was before deletion.

### Viewing

- This project: `mc-tool-board list`. All projects: `mc-tool-board list --all`. Include archived: add `--archived`. Filter by title: `--search`/`-q <text>` (case-insensitive substring; composes with the others — pair with `--all` to sweep every project). Cards bound to this session: `--mine` (or another session's with `--session <id>`). Machine-readable: add `--json`.

### Exporting

- One card: `mc-tool-board export N [--format markdown|json] [--out FILE]` — a portable, full-fidelity document (meta, description, acceptance criteria, completion summary, references, comments). Markdown is the default; output goes to stdout unless `--out` is given.
- Whole board: `mc-tool-board export [--format ...] [--out FILE]` — one markdown document grouped by column, or a JSON array. Takes the same filters as `list` (`--all`, `--project`, `--status`, `--archived`, `-q`).

## Proactive behaviour

If you spot work worth tracking during a session, you may **suggest** adding a card — but always ask before adding. When you open a PR for an in-progress card, offer to move it to review with the PR link; when you finish a chunk of work that maps to a card (or its PR merges), offer to complete it with a summary. Never move, complete, or archive cards without the user's say-so.
