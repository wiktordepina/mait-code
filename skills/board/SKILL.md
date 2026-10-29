---
name: board
description: View and drive the project kanban board. Use when the user mentions the board, asks to pick up / refine / move / complete a card, asks what's on the board, or wants to add a card to the board.
allowed-tools: Bash(mc-tool-board list:*), Bash(mc-tool-board show:*), Bash(mc-tool-board next:*), Bash(mc-tool-board export:*), Bash(mc-tool-board add:*), Bash(mc-tool-board edit:*), Bash(mc-tool-board move:*), Bash(mc-tool-board refine:*), Bash(mc-tool-board review:*), Bash(mc-tool-board complete:*), Bash(mc-tool-board block:*), Bash(mc-tool-board unblock:*), Bash(mc-tool-board tag:*), Bash(mc-tool-board untag:*), Bash(mc-tool-board ref:*), Bash(mc-tool-board comment:*), Bash(mc-tool-board archive:*), Bash(mc-tool-board bind:*), Bash(mc-tool-board unbind:*), Bash(mc-tool-board link:*), Bash(mc-tool-board unlink:*), Bash(mc-tool-board epic:*), Bash(mc-tool-board run:*), Bash(mait-code identity show testing_strategies:*)
---

# /board

View and drive the kanban board for the current project.

## Current board

!`mc-tool-board list 2>/dev/null || echo "No board yet - add a card with: mc-tool-board add \"<title>\""`

## Instructions

The board is a **manually-driven** kanban - *you (Claude) are the worker*. There is no autonomous dispatcher; you act only when the user asks. Drive it through `mc-tool-board` via Bash. Cards flow through fixed columns: **backlog -> refined -> in_progress -> in_review -> done**, plus a hidden **archived** side-state. **blocked** is a tag carried in place (not a column), so a blocked card keeps its real column.

Present the board above clearly, then act on what the user asks.

### Picking up work

- **"pick up the next refined card"** (or similar): run `mc-tool-board next --claim --json`. This returns the highest-priority (then oldest) *ready* card for the current project - refined, not tagged `blocked`, and not waiting on an unfinished card that blocks it - *and* moves it to `in_progress`. Read its `acceptance_criteria`, then do the work in this session.
- **"what's next?"** / **"what can I pick up?"**: answer with `mc-tool-board next --json` (or `next --epic N --json` for one initiative) - don't assemble the answer by hand from `list`. When nothing is ready, `list --ready` and `show N` explain what each card is waiting on.
- **"pick up the next card on epic N"**: `mc-tool-board next --epic N --claim --json` - the top ready member of that epic, whatever project it sits in.
- **"pick up card N"** / **"continue card N"**: if card N is an **epic** (`kind: "epic"`), don't pick it up - epics are never worked directly; offer `next --epic N` instead. Otherwise, to start building it, `mc-tool-board move N in_progress` (which binds it); if it's already In Progress (started in an earlier or parallel session), or you're only refining or reviewing it, run `mc-tool-board bind N`. Either way this session ends up bound to it. Then read its `acceptance_criteria` and carry on.
- Peek without claiming: `mc-tool-board next --json`.

### Sessions

Several Claude Code sessions can work the same project at once, so each card records **which sessions are working on it**, in any open column. Moving a card into `in_progress` (via `next --claim` or `move`) binds it to the current session automatically; `bind N` binds any card that isn't Done or Archived (a card you're refining, or an In Review card you're addressing PR feedback on); `unbind N` drops this session's binding. Entering In Review or closing a card (complete, archive, epic promotion, any move to done or archived) releases every binding; refining and moves between Backlog, Refined and In Progress keep them. `next` and `list --ready` pass over a card another live session is bound to. A binding stays active only while its session's Claude Code process is alive, and it follows a `/clear` or a resume on its own. Bindings are why "the card I'm on" is `mc-tool-board list --mine`, not the whole In Progress column.

### Refining

- **"refine card N"**: draft a clear description and acceptance criteria, **show them to the user for approval first**, then run `mc-tool-board refine N --description "..." --acceptance "..."` (moves it to `refined`). Don't refine without confirmation.
- **Testing strategy**: every refined description ends with this section.
  - **Heading:** a paragraph reading exactly `**Testing strategy**`. Keep it exactly as written: playbooks such as `/work` look for it.
  - **Body:** one bullet per chosen strategy, saying what it will check for this card and why it fits. Ask the user to choose when the choice isn't obvious.
  - **Options:** while drafting (not before), load the user's strategies with `mait-code identity show testing_strategies`. Offer the entries whose `Projects:` line names the card's project, plus those with no `Projects:` line. A strategy outside the file is fine if you say so.
  - **Missing file:** if the command fails, use `unit` (the project's own test suite) and `manual` (a scripted check on a throwaway target), and tell the user to run `mait-code update` to install the file.
- **Splitting a card during refinement**: each piece is a card born from the original - see *Cards born from other cards* below.

### Cards born from other cards

Splits during refinement and follow-ups spotted mid-work are where an initiative loses track of its pieces, so every such card keeps its epic and its origin:

- **Find the origin**: the card being split or refined, the card under discussion, or - for a follow-up raised while working - this session's card (`mc-tool-board list --mine`). If it's ambiguous (several bound cards, or the work is unrelated to any), ask.
- **Add it with `--from`**: `mc-tool-board add "<title>" --from N [...]`. This joins N's epic and records a `from` -> `#N` reference in one step; the origin may sit in another project. Override the epic with `--parent E`, or drop it with `--parent none`, when the new card belongs elsewhere.
- **Say what it inherited** when proposing the card ("under epic #E, from #N") so the user can redirect it before you add it.
- **Ordering is still the user's call**: ask how the new card orders against its origin and siblings before linking any `blocks` - never guess a dependency.

### Epics & dependencies

Cards relate two ways - both cross projects freely:

- **Epics** are umbrella cards for an initiative (e.g. a roadmap spanning several repos). An epic is `kind: "epic"` on the reserved project `@epic`; it never appears on the kanban, in `list` or in `next`. Members name it as their `parent` (one epic per card, one level only).
  - Create: `mc-tool-board add "<title>" --epic [--description ...]`. Turn an existing umbrella card into one: `mc-tool-board epic promote N` (refused while it has a parent or `blocks` links).
  - Membership: `mc-tool-board add "<title>" --parent E`, or `mc-tool-board edit N --parent E` / `--parent none`.
  - Look: `mc-tool-board epic list [--done]` (progress per epic), `mc-tool-board epic show E` (members by column), `mc-tool-board list --epic E`.
  - An epic's status is set by hand. When finishing or archiving its last open member prints *"epic #E has no open members"*, **offer** to complete the epic - never complete it unasked.
- **`blocks` links** record that one card must be done before another can start: `mc-tool-board link A blocks B`, removed with `unlink A blocks B`. A waiting card shows `waiting on #A` in `list`, and `next` / `list --ready` skip it until A is done (or archived - `show` then flags the archived blocker for another look). A link that would close a loop is refused with the loop's path. Epics take no links: link their member cards.
- **`blocked` tag vs links**: link when the blocker is another card; tag `blocked` (below) only when it's something outside the board - an upstream fix, a person, a decision.
- Add `blocks` links only when the user has said how the work orders - ask rather than infer. Epic membership is different: a card born from another inherits its epic via `--from` (above); otherwise ask which epic, if any, a new card belongs to.

### Finishing & parking

- Review: `mc-tool-board review N [--pr <url>]` - moves the card to `in_review` (finished, awaiting review or merge) and, with `--pr`, records the PR as a `PR` reference. Use it once the work is up as a pull request.
- Complete: `mc-tool-board complete N --summary "what was done"` (moves to `done` from any column, records a handoff summary).
- Block: `mc-tool-board block N <reason>` - tags the card `blocked` **in place** (keeps its column); the reason is recorded as a comment. Unblock: `mc-tool-board unblock N` removes the tag. These are thin aliases over the tag system below.
- Tag / untag: `mc-tool-board tag N <tag>` / `mc-tool-board untag N <tag>` - free-form tags that ride alongside a card's status.
- Archive (hide, don't delete): `mc-tool-board archive N`.
- Delete permanently: `mc-tool-board remove N` - destructive and unrecoverable; prefer `archive` to hide a card. Only delete when the user explicitly asks.
- Arbitrary move: `mc-tool-board move N <backlog|refined|in_progress|in_review|done|archived>`.

### Adding & editing

The **description**, **acceptance criteria** and **completion summary** fields render markdown in the card detail view (plain text works too - it's a subset). Write these in markdown when it helps: headings, lists, emphasis, inline and fenced code all display formatted, and single newlines are kept as line breaks. No need to flatten a markdown source into plain prose.

- Add: `mc-tool-board add "<title>" [--description ...] [--priority low|medium|high] [--project <name>] [--parent E] [--from N]`. New cards land in `backlog`. Use `--project` for work with no git repo yet (e.g. an app idea), and `--from` whenever the card comes out of another (see *Cards born from other cards*).
- Edit: `mc-tool-board edit N [--title ...] [--description ...] [--priority ...] [--acceptance ...] [--project ...]`.
- Comment: `mc-tool-board comment N "<note>" [--author claude]`.
- References (label->value links on a card): `mc-tool-board ref add N <label> <value>` - *value* is a URL, a `file://` path, or a bare ID. List them with `mc-tool-board ref list N`, remove one by its 1-based position with `mc-tool-board ref remove N <position>`. Cards carry these as a structured References field.
- Show one card with its comments and references: `mc-tool-board show N`.
- Every mutating subcommand (`add`, `move`, `refine`, `review`, `complete`, `block`/`unblock`, `tag`/`untag`, `ref add`/`ref remove`, `archive`, `bind`/`unbind`, `comment`, `edit`, `remove`, `link`/`unlink`, `epic promote`, `run start`/`run step`/`run end`) accepts `--json`, emitting the affected card after the mutation in the `show --json` shape - e.g. `add ... --json` returns the new card's id without parsing prose. `remove --json` emits the card as it was before deletion.

### Playbook runs

A playbook skill records where a card is in its run; you only drive these when a playbook asks, or the user does.

- `mc-tool-board run start N --playbook <name> --steps "A" "B" ...` writes the steps, all pending. Refused while the card has an open run, unless `--replace` (which ends it first) - check `run show N` before replacing.
- `mc-tool-board run step N <position|name> <pending|in_progress|done|skipped|paused> [--reason ...]`. A skip needs `--reason` and the board adds the card comment itself - don't post another. Only one step can be in progress.
- `mc-tool-board run end N` once the playbook has reported on the run; nothing ends it automatically except completing, archiving or promoting the card.
- `mc-tool-board run show N [--json]` for the open run; `show` includes it too. Add `--all` for every run on the card, ended ones included, newest first - how earlier attempts went.

### Viewing

- This project: `mc-tool-board list`. All projects: `mc-tool-board list --all`. One epic's members (any project): `--epic E`. Only cards ready to pick up: `--ready`. Include archived: add `--archived`. Filter by title: `--search`/`-q <text>` (case-insensitive substring; composes with the others - pair with `--all` to sweep every project). Cards bound to this session: `--mine` (or another session's with `--session <id>`). Machine-readable: add `--json`.

### Exporting

- One card: `mc-tool-board export N [--format markdown|json] [--out FILE]` - a portable, full-fidelity document (meta, description, acceptance criteria, completion summary, references, comments). Markdown is the default; output goes to stdout unless `--out` is given.
- One epic with its members: `mc-tool-board export --epic E [--format ...] [--out FILE]` - use this instead of hand-writing "what's next / what's blocked" documents for an initiative.
- Whole board: `mc-tool-board export [--format ...] [--out FILE]` - one markdown document grouped by column, or a JSON array. Takes the same filters as `list` (`--all`, `--project`, `--status`, `--archived`, `-q`).

## Proactive behaviour

If you spot work worth tracking during a session, you may **suggest** adding a card - but always ask before adding. When it comes out of a card on the board (usually this session's, `list --mine`), propose it with `--from` and name the epic it would inherit. When you open a PR for an in-progress card, offer to move it to review with the PR link; when you finish a chunk of work that maps to a card (or its PR merges), offer to complete it with a summary. Never move, complete, or archive cards without the user's say-so.
