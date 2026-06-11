# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the project is pre-1.0, minor version bumps track meaningful additions
of functionality; patch bumps cover docs, internal tidy-ups, and fixes that
don't change the public surface. Everything is still in flux.

## [Unreleased]

### Added

- **`--json` on mutating board subcommands** — `add`, `move`, `refine`,
  `complete`, `block`/`unblock`, `tag`/`untag`, `ref add`/`ref remove`,
  `archive`, `comment`, `edit` and `remove` now accept `--json`, emitting the
  affected card after the mutation in the `show --json` shape (tags,
  references and comments included). Scripted callers get e.g. the new
  card's id from `add --json` instead of parsing it out of prose;
  `remove --json` emits the card as it was before deletion. The read side
  (`list`, `show`, `next`, `ref list`, `summary`) already spoke JSON.

## [0.58.0] — 2026-06-11

### Added

- **Knowledge-graph explorer (`mait-code graph`)** — an ego-centric,
  read-only TUI over the entity graph the observe hook accumulates: a
  mention-ranked entity list, the selected entity's 1-hop neighbourhood, and
  a detail pane surfacing each relationship's free-text context (previously
  collected but never displayed). The centre pane renders two ways — a
  [netext](https://github.com/mahrz24/netext) node-link diagram or a flat,
  glyph-annotated relationship table — and `t` swaps them. The explorer
  follows the list: highlights preview instantly, and the neighbourhood
  re-centres when the cursor rests. Entity-type glyphs and colours follow
  the active theme; single-mention and orphan entities hide behind a
  toggleable noise filter (`a`). Off-TTY the command prints the graph's
  hubs as text. Launchable from the home hub's Memory section.
- **Graph query layer** — `list_graph_entities` (degree-annotated entity
  listing with noise filters) and `get_ego_graph` (deterministic 1-hop
  neighbourhood) join the public `tools.memory` surface.
- **netext (≥0.5.0)** joins the runtime dependencies — the terminal
  graph-rendering library behind the node-link view.


## [0.57.0] — 2026-06-11

### Added

- **Canonical entity types in the knowledge graph** — entity types now mirror
  the relationship-type pattern: a canonical vocabulary (`person`, `project`,
  `tool`, `service`, `concept`, `org`) defined once in
  `tools/memory/entities.py`, fed into the extraction prompt enum, and
  enforced at write time — types the extraction model invents coerce to
  `unknown` instead of accumulating in the table.
- **`mc-tool-memory entities merge <source> <target>`** — folds alias
  duplicates into one entity: relationships are repointed (deduplicating
  where the target already holds the edge), mention counts summed, the
  first/last-seen window widened to span both, would-be self-loops dropped,
  and the source deleted. Quote multi-word names.

### Changed

- **Migration 12 cleans the legacy graph** — relationship rows written before
  write-time coercion landed are remapped to the canonical six via a
  conservative static lookup (one that never flips edge direction), merging
  rows that collide on the `(source, target, type)` uniqueness index; legacy
  entity types are remapped likewise. The stored graph ends fully canonical.
- **Extraction prompt guards against ephemera** — the model is now told not
  to extract version strings, commit hashes, PR/card/issue numbers, or branch
  names as entities, and to reuse canonical entity names (the user's actual
  name, the name an entity was introduced with) rather than coining variants.

## [0.56.0] — 2026-06-11

### Added

- **The log viewer** — a sixth TUI surface: `mait-code logs` (or **System ▸
  ↗ Open logs** in the home hub) browses the structured JSON Lines logs
  interactively instead of via `jq`. A master–detail tree groups lines by day
  (the active file plus its rotated siblings), newest day expanded, each day
  badged with its line/warning/error tallies; the detail pane renders the
  selected line's full record — message, schema fields, invocation arguments,
  and the stack trace when one was captured. Four composable filters: free-text
  search over messages (`/`), a cycling severity floor (`l`), and tool / day
  pickers (`t` / `d`) — the masthead subtitle always carries the active
  narrowing. Read-only and forgiving: malformed lines are skipped, oversized
  files are read from their tail, and off a TTY the command prints a
  day-grouped summary instead. Documented with screenshots in the new
  [log viewer guide](docs/logs.md).
- **`mait_code.logging.log_file_path()`** — the active log file's resolution
  (the `log-file` setting, else `<state-dir>/mait-code.jsonl`) is now public,
  shared by the writing side and the viewer.

### Fixed

- **`MAIT_CODE_LOG_FILE` with a `~` path** — the configured log-file path is
  now tilde-expanded instead of creating a literal `~` directory (the
  recurring tilde-expansion bug class).

## [0.55.0] — 2026-06-11

### Changed

- **Structured JSON Lines logging** — the shared logging layer now emits one
  JSON object per line with a deterministic, ECS-inspired schema instead of
  plain text. Every line carries `ts` (epoch seconds as a float — cast to a
  timezone at the presentation layer), `level`, `logger`, `msg`, `tool` (the
  entry-point name, on every line, not just invocation events) and `pid`.
  `@log_invocation` events gain structured `event`
  (`invoked`/`completed`/`failed`/`exited`), `duration_ms` and `args` fields
  (sensitive-value truncation unchanged), exceptions serialise to
  `error_type`/`error_message`/`stack` on a single line, and call sites can
  merge their own fields with `extra={...}` (core fields win on collision).
  Logs write to `mait-code.jsonl`; the old `mait-code.log` is no longer
  written and its rotated history ages out on the usual schedule. Daily
  rotation and the `log-level`/`log-file`/`log-backup-count` settings behave
  exactly as before. This is the enabler for the log viewer.

## [0.54.0] — 2026-06-11

### Added

- **Custom environment variables — the `[env]` table** — settings.toml gains
  an `[env]` table of user-defined environment variables, injected into the
  process environment whenever any mait-code entry point starts: the
  `mait-code` CLI and TUIs, every `mc-tool-*` tool and `mc-hook-*` hook. The
  headline use is `AWS_PROFILE` for Bedrock embeddings — `mait-code doctor
  --fix` and `mc-tool-memory reindex` now authenticate outside Claude Code
  sessions without a manual env prefix. The real environment always wins (a
  one-off `AWS_PROFILE=other mc-tool-…` override keeps working, and startup
  injection never masquerades as a shell export in provenance views), the
  table survives every settings-file rewrite, `MAIT_CODE_*` keys are rejected
  and flagged by `doctor`, and secret-looking values are masked in display.
- **Manage `[env]` from the CLI and the editor** — `settings set env.NAME
  value` adds or updates, `settings unset env.NAME` removes, `settings get
  env.NAME` resolves with provenance, and `settings list` shows `env.<NAME>`
  rows. The interactive editor grows an always-present *Custom env* group:
  each variable is editable in place with Apply/Remove (removal confirms),
  and a *+ add variable…* row opens an inline name + value form with live
  name validation. Both surfaces funnel through one shared write path, which
  also applies the change to the running process.

### Changed

- **Memory-browser guide caught up with the browser** — the native view
  (`n`, Claude Code's per-project auto-memory files) and the `p` project
  filter are now documented, with a new screenshot of the native view; both
  existed in the TUI but were missing from the guide. The settings guide
  gains the *Custom environment variables* section with a screenshot of the
  env editor pane, and long help copy in the settings editor's detail pane
  now wraps instead of clipping.

## [0.53.0] — 2026-06-10

### Added

- **Procedural memory class** — the memory system now knows *how things are
  done*, not just what happened and what's true. A new `procedure` entry
  type carries its own `procedural` class with the slowest decay of the
  three (180-day half-life, tunable via `half-life-procedural`) — workflows
  go stale when superseded, not with time. The observe hook extracts a
  `procedures` category with crisp boundary guidance (a procedure answers
  *"how do I do X next time?"*; a decision answers *"what did we pick?"*; a
  preference answers *"what does the user like?"*), defaulting to project
  scope. The new type flows through `mc-tool-memory store`/`search
  --type procedure`, gets its own group in the memory browser, and shows up
  in the observations browser and the settings editor.

## [0.52.0] — 2026-06-10

### Changed

- **Multi-colour wordmark** — the brand wordmark across every TUI now wears
  a horizon gradient with a depth shadow: a per-column sweep from the active
  theme's primary through secondary to accent across the glyph fills, with
  the box-drawing drop shadow blended toward the background so it sits
  *behind* the letters instead of competing with them. Same art, same banner
  height (full and compact), and the plain-text fallback for narrow
  terminals carries the same gradient. Switching theme re-paints the
  wordmark in that theme's colours; themes whose colour slots aren't hex
  (the `ansi` family) fall back to the house palette per slot.

## [0.51.0] — 2026-06-10

### Added

- **Reindex from the home hub** — `e` (or **Reindex memory** in the `Ctrl+P`
  palette) embeds the memory entries missing a vector. The confirm names the
  live missing count, the hub suspends to the terminal so the embed prints
  its normal progress, then home reloads with fresh badges and health. When
  nothing is missing it says so and skips the confirm entirely.
- **`mait-code doctor --fix` fills embedding gaps** — the `memory-embeddings`
  check now embeds the missing entries itself instead of just pointing at
  `mc-tool-memory reindex`. Progress goes to stderr, so `--fix --json` keeps
  a parseable stdout; when the embedding provider can't run, the warning
  stands and reports why.
- **`run_reindex(missing_only=True)`** — the programmatic reindex can now
  embed only the entries lacking a vector. A full reindex is unchanged
  (and is still what the bare `mc-tool-memory reindex` and the settings
  provider-switch follow-up do); a dimension mismatch recreates the vec
  table first, so missing-only degrades to a full re-embed exactly when
  it must.

### Changed

- **`ConfirmScreen` is shared TUI furniture** — the yes/no modal moved from
  the settings editor into `tui.confirm`, so the home hub and settings stay
  pixel-consistent instead of each carrying a copy.

### Fixed

- **Long confirm questions wrap inside modals** — `.modal-title` now takes
  the dialog's width; an auto-width label never wraps, so an over-long
  question clipped at the border (the settings re-embed confirm was
  affected).
- **A failed embedding batch no longer kills the calling app** — mid-run
  embedding failure in a reindex now raises `ReindexError` instead of
  exiting the process, so the home hub, settings editor, and doctor survive
  it; the CLI still exits `1`.

## [0.50.0] — 2026-06-10

### Added

- **Native auto-memory view in the memory browser** — `mait-code memory` now
  surfaces Claude Code's native per-project auto memory alongside the
  mait-code store. `n` switches to a read-only view over every project's
  `~/.claude/projects/<slug>/memory/` files — all projects, regardless of
  where the browser was launched — grouped by project with best-effort
  de-munged labels, `MEMORY.md` first, and each file's markdown rendered in
  the detail pane. Backed by the new `tools.memory.native` reader
  (`list_native_memories`, `native_projects_dir`, `resolve_slug`).
- **Project filter in the memory browser** — `p` opens the same project
  `Select` the observations browser uses, in both views: the store view
  narrows to one project's entries (plus globals, via the new
  `search.list_projects`), the native view to one project's files. The
  modal now lives in `tui.filters` as `ProjectFilterScreen`, shared by both
  browsers.

### Changed

- **The two curated memory layers are now formally separated** — Claude
  Code's native auto memory carries per-project *code* facts; mait-code
  memory carries cross-project *user/identity* facts. `docs/memory.md`
  documents the split and the routing rule, and the `/reflect` and
  `memory-store` skills apply it, so project knowledge no longer accretes
  into mait-code's MEMORY.md.

## [0.49.0] — 2026-06-10

### Added

- **Memory-health checks in `mait-code doctor`** — three new checks surface
  silent memory degradation: `memory-embeddings` counts live entries with no
  vector (invisible to semantic search) and points at `mc-tool-memory reindex`;
  `vector-search` verifies the sqlite-vec extension loads and the vector table
  is queryable, naming the configured embedding provider and model on failure;
  `observe-pipeline` warns when the observe hook hasn't recorded a capture in
  over a week, or has never captured despite an existing memory database. The
  checks open the database raw — a diagnostic run never creates or migrates it.

### Changed

- **Memory-pipeline failures now log at warning, not debug** — embedding
  storage failures (the entry is kept, but stored without a vector), vector
  dedup fallbacks, and vector searches degrading to keyword-only were
  previously swallowed at debug level; each now logs an actionable warning.
  Graceful degradation behaviour is unchanged.

## [0.48.0] — 2026-06-09

### Added

- **Export cards to markdown and JSON.** `mc-tool-board export N` renders one
  card as a portable, full-fidelity document — meta, description, acceptance
  criteria, completion summary, references and comments; stored markdown
  round-trips verbatim. The board-wide form (`mc-tool-board export`) produces
  one markdown document grouped by column, or a JSON array, and takes the same
  filters as `list` (`--all`, `--project`, `--status`, `--archived`, `-q`).
  Output goes to stdout, or to a file with `--out`. In the board TUI,
  <kbd>x</kbd> on the card screen prompts for a destination — pre-filled with
  `card-N.md` in the current directory — and writes the markdown there. The
  rendering layer lives in `tools/board/export.py`, shared by CLI and TUI.

## [0.47.0] — 2026-06-09

### Added

- **The observations browser — the raw extraction tier, finally visible.**
  `mait-code observations` is the fifth TUI surface: a read-only master–detail
  browser over everything the observe hook has extracted, grouped by capture
  day, each entry flagged **pending** or **reflected** against the reflection
  watermark — so what reads pending is precisely what the next `/reflect` run
  will consider. Highlighting a day shows its capture sessions (trigger,
  project, per-category counts) from the daily JSONL logs; `/` filters live by
  content, and `p` narrows to one project, judged against that project's own
  watermark. Piped or redirected, the command prints a day-grouped summary
  instead. The query layer lives in `tools/memory/observations.py`
  (`list_observations`, `observation_projects`, `daily_batches`).
- **Home knows the way there.** The hub's Memory section gains an
  "↗ Open observations" launch leaf beneath Reflection status — the
  "awaiting N observation(s)" count now has a drill-down instead of being a
  dead end — and the hand-off also rides the `Ctrl+P` palette.
- **A full guide, screenshots included.** `docs/observations.md` joins the
  other TUI guides — main view, live filter, and a day's capture sessions —
  with the shots rendered from the snapshot baselines like the rest.

### Changed

- **The Rich colour normaliser moved to the shared palette.** The home hub's
  theme-colour helper now lives in `mait_code.tui.palette` as `rich_colour`,
  where any surface that paints Rich text from the active theme can reach it.

## [0.46.1] — 2026-06-09

### Added

- **Guides for the settings editor and the memory browser.** `mait-code
  settings` and `mait-code memory` now have their own documentation pages, with
  screenshots, alongside the home hub and board guides — covering the adaptive
  settings editor (and where settings live) and the read-only memory browser.

### Changed

- **The board wears the brand banner again.** It had kept its stock header
  because the full six-row wordmark crowded the columns; the banner is now
  height-responsive, dropping to a half-height wordmark on terminals of 30 rows
  or fewer, so the board (and every other surface) gets the brand without losing
  the room. This supersedes the 0.45.1 note that the board drops the banner.
- **The documentation screenshots are rendered uniformly through the PNG path.**
  Now that every surface carries the wordmark, the board guide's images move off
  the SVG export (which seams across the block art) onto the same headless-Chrome
  rasterisation the home hub already used.

## [0.46.0] — 2026-06-09

### Added

- **Evolving memory — supersede, don't duplicate.** When a fact genuinely
  changes ("uses X" → "now uses Y"), memory no longer leaves two contradictory
  entries coexisting. A new `mc-tool-memory supersede <old_id> "<new content>"`
  replaces an entry with its current version: the new fact inherits the old
  one's type and scope, and the old row is kept for audit but hidden from recall,
  search, listing, and deduplication. See it with `list --include-superseded`,
  and `stats` now reports the superseded count.
- **Contradiction surfacing at write time.** Storing a related-but-different
  fact (cosine similarity in the new `[0.60, 0.92)` band) now stores the new
  entry _and_ flags the near-neighbours it may contradict — `mc-tool-memory
  store` prints a `⚠ This may contradict …` notice with a supersede hint, so a
  stale fact can be retired rather than silently shadowed. The lower edge is a
  new advanced knob, `dedup-conflict-threshold`. Manually-driven throughout: it
  suggests, you decide.

### Changed

- **The home hub's memory pane notes superseded entries,** and the memory-store
  skill now guides superseding a stale fact when a write surfaces a conflict.

## [0.45.1] — 2026-06-09

### Added

- **A view name on the brand banner.** The masthead now carries the name of the
  surface — _Home Hub_, _Settings_, _Memory_ — on the middle-right, over the
  tagline and version. The memory browser folds its live match count into it.
- **A token estimate for the system prompt.** Identity → System prompt now tags
  each block of the identity stack, and the live session context, with a rough
  `~N tokens` badge and a budget total — so you can gauge what the context
  window spends before a session even starts. An offline ~4-characters-per-token
  heuristic; no tokenizer, no network.
- **A home hub guide.** The home hub gets its own documentation page with
  screenshots, and the `mait-code home` command (and bare `mait-code`) is now
  documented in the CLI reference.

### Changed

- **The brand banner leads the settings editor and the memory browser too,** in
  place of their stock headers — one identity across the surfaces. The board
  keeps its header and drops the banner: the wordmark was crowding the columns.
- **Opening a TUI from the home tree is now a dedicated `↗ Open …` leaf.** Board,
  Memory and System are ordinary expand/collapse categories again; the
  accent-coloured launch leaf hands off to the dedicated app, so a category no
  longer has to choose between expanding and launching.

### Fixed

- **The home hub no longer crashes under the ansi themes.** Their colour names
  (`ansi_yellow`…) aren't valid Rich styles, so the health line raised
  `MissingStyle` on launch. Theme colours are normalised to Rich-parseable
  values now, matching the guard the board already had.

## [0.45.0] — 2026-06-08

### Added

- **`mait-code home` — the companion's home hub.** A fourth Textual surface
  and the front door to everything mait-code: a slim tree sidebar of sections
  — Board, Memory, Reminders, Inbox, Identity, System — each node carrying a
  live status badge (active cards, memory total, overdue reminders in alarm
  colour, inbox count), beside a detail pane that renders the highlighted
  section in full. Pressing Enter on the Board, Memory or Settings node opens
  that dedicated TUI and returns to a freshly-read home when it quits. The
  Identity → System prompt view shows exactly what the companion is presented
  with at session start, built live by the session-start context builder. Bare
  `mait-code` on a terminal opens the hub; off a TTY the command prints a
  compact text summary.
- **A bold block-shadow brand wordmark.** The home header debuts a filled
  block-shadow `mait-code` wordmark — with a plain-text fallback for narrow
  terminals — set off by a separator rule, the signature glyph and the tagline.

### Changed

- **Escape now exits every TUI.** Home and the board quit on Escape; the
  memory and settings master–detail browsers step back to the list first, then
  quit from the list — so Escape always eventually leaves, like `q`.
- **Companion-voice empty states across the board.** Empty board columns and
  every home detail pane speak in the companion's voice rather than rendering
  as a bare void.
- **Home detail panes align key→value rows into columns** (overview, memory,
  doctor, settings, version & paths) for a clean, tabular read.

## [0.44.0] — 2026-06-07

### Added

- **`mait-code memory` — a read-only memory browser TUI.** A third Textual
  surface alongside the board and the settings editor: a master–detail browser
  over the memory store, with memories grouped by entry type (counts per
  group, newest first), the selected memory's body rendered as markdown with
  its metadata, and a live substring filter (`/`). It browses everything —
  across projects and scopes — and performs no mutations. Off a TTY the
  command falls back to a read-only grouped summary. The shared body-markdown
  parser (single newlines kept as line breaks) moved from the board into
  `mait_code.tui.markdown`, where both surfaces now use it.

## [0.43.0] — 2026-06-04

### Removed

- **Seven unused skills and the decisions subsystem are gone.** The workflow
  skills `/prs`, `/standup`, `/today`, `/work-history`, and `/status`, along with
  the `/decision` and `/decisions` skills and their backing `mc-tool-decisions`
  tool (and its `decisions.db` store), have been removed. They saw effectively no
  use, and the kanban board plus quick-capture inbox cover the same ground. Inbox
  triage no longer offers a "decision" destination — items route to the board or
  memory. The `mait-code status` CLI command is unaffected; only the `/status`
  skill was removed.

- **The tasks subsystem is gone.** The `/task` and `/tasks` skills, the
  `mc-tool-tasks` CLI tool, and its `tasks.db` store have been removed. The board
  is a strict superset of what tasks tracked, and the quick-capture inbox owns
  frictionless capture — a one-line `mc-tool-board add "<title>"` lands straight
  in the backlog, so tasks was left with no exclusive job. Inbox triage now routes
  to the board or memory only, and the session-start brief surfaces open work
  through its existing board summary rather than a separate "Project Tasks" block.

## [0.42.0] — 2026-06-01

### Added

- **The board now refreshes itself when something changes underneath it.** If
  you keep the board open while editing cards from the CLI or a skill in another
  window, those changes now appear on their own — no manual reload (`r`) needed.
  The board polls about once a second and only reloads when an outside change
  has actually landed, so its own edits don't cause needless churn. Your
  selected card and column are kept across a refresh, and an open card-detail
  view updates in place rather than going stale (so, for example, completing a
  card elsewhere is reflected without closing and reopening it). A refresh never
  interrupts an in-progress edit or steals focus from an open dialog.

## [0.41.0] — 2026-06-01

### Added

- **Card descriptions and acceptance criteria now render markdown.** In the
  board's card detail view, the Description, Acceptance criteria and Completion
  summary fields display formatted markdown — headings, bullet and ordered lists
  (including nested), emphasis, blockquotes, tables, inline code and
  syntax-highlighted fenced code blocks — instead of showing raw `#`, `**` and
  `-`. Plain text and markdown share the same field with no format to choose:
  plain text is valid markdown, and a single newline is kept as a line break, so
  existing plain descriptions lay out exactly as before. Links in the body
  render as styled text but aren't clickable — the References field stays the
  place for links you can follow. Editing is unchanged; you type raw text either
  way, and storage is untouched (no migration).

## [0.40.1] — 2026-05-31

### Changed

- **Docs caught up with the recent shipping wave.** The hand-written guides had
  drifted behind the board overhaul, the multi-theme system and the settings
  tree. The architecture diagram now lists all the skills and shows the board's
  `service` layer; the development guide's theming section covers the five house
  themes and notes that a chosen theme persists across sessions; the board guide
  documents the `/` title-search key; the settings reference table gains
  `MAIT_CODE_THEME`; the skills tree includes `/triage`; and the stale test
  counts are gone.

## [0.40.0] — 2026-05-31

### Changed

- **The `mait-code settings` editor now groups its settings into a collapsible
  tree.** The flat table is gone: settings are filed under expandable categories
  — General, Logging, Embeddings, Models, Scoring & dedup, and Paths (derived).
  Common groups open on launch while advanced and derived ones start collapsed,
  so the list opens short instead of as one long scroll. Each row shows its key
  with the current value inline (defaults dimmed, the re-embed ⚠ marker kept);
  the separate Source column folds away since the detail pane already reports it.
  Editing is unchanged — highlight a setting to edit it, Enter to focus the
  editor, Ctrl+S to apply.

## [0.39.0] — 2026-05-31

### Changed

- **The card's title and badge line now stay pinned as you scroll.** In a card's
  detail view, the title and the meta line beneath it (project · status ·
  priority · tags) are lifted out of the scroll region into a fixed header, so a
  long description, acceptance criteria and comment thread scroll underneath them
  — you keep a constant reference to which card you're reading. The title's
  underline now doubles as the divider between the pinned header and the scrolling
  body. Edit mode is unchanged.

## [0.38.0] — 2026-05-31

### Added

- **The card edit form is now the single place to change a card.** Open a card
  and press `e`: alongside title, priority, description and acceptance criteria,
  the form now carries a **status** selector (backlog → refined → in_progress →
  done, plus archived), a **tag** editor (type to add, `✕` a chip to remove) and
  a **references** editor (label + value rows, each removable). Tags, references
  and status are a working copy — **Save** applies them all at once, and cancel
  (`Esc`) discards every pending change, so editing a card is one cohesive form
  rather than a form plus a scatter of modals.
- **`set_tags` / `set_references` on the board service** — set-replace operations
  that rewrite a card's whole tag or reference set in one transaction, backing
  the form's working-copy save.

### Changed

- **A status change from the form maintains the done-invariant.** Moving a card
  to (or out of) `done` via the new selector routes through the same path as the
  move keys, so `completed_at` is stamped and cleared correctly; an unchanged
  status is left alone.

### Removed

- **The card screen's `t` (tag), `r` (references) and `<` / `>` (move) gestures**
  and the standalone reference modal — that editing now lives in the card's edit
  form. Block / unblock (`b` / `u`) stay as in-place gestures (they carry a reason
  comment a plain tag can't), and the board-level tag and move keys are unchanged.

## [0.37.1] — 2026-05-31

### Fixed

- **`mait-code update` no longer wedges itself on a dirty source clone.** The
  bootstrap clone sits in detached HEAD and its skills are symlinked into
  `~/.claude`, so editing a skill in place writes back through the symlink and
  leaves a tracked file modified. The tag checkout then aborted with "local
  changes would be overwritten", and the error surfaced as a raw traceback that
  broke every subsequent update. The detached-HEAD checkout is now forced — the
  clone is tool-managed and the committed release is authoritative, so
  write-through edits are discarded — and a failing git/uv subprocess prints a
  clean error line instead of a traceback.

## [0.37.0] — 2026-05-31

### Changed

- **The board's project filter is now a dropdown picker.** Pressing `p` opens a
  `Select` listing every project plus "All projects", pre-set to the active
  filter; choosing an entry applies it straight away. This replaces the
  round-robin cycling, which grew unwieldy once more than a handful of projects
  were in play — "All projects" clears the filter, and escape leaves it
  untouched.

## [0.36.0] — 2026-05-31

### Added

- **Search the board by title.** Both surfaces gained a case-insensitive
  title-substring filter sharing one query path. On the CLI, `mc-tool-board
  list --search`/`-q <text>` filters the listing and composes with the existing
  `--all`, `--status`, `--archived`, and `--json` flags — pair it with `--all`
  to sweep every project's board at once. In the TUI, `/` opens a search box;
  the active query rides in the subtitle and clears on an empty submit (escape
  leaves it untouched). Literal `%` and `_` in a query match as themselves
  rather than acting as wildcards.

### Changed

- **The card detail title now reads as a heading.** It carries a heavy
  underline in the theme's primary hue — its own separator above the meta line,
  distinct from the thinner accent rules under each section — so it stands out
  rather than blurring into the surrounding bold text.
- **The `/board` skill guide is back in sync with the tool.** It now documents
  the card references subcommands (`ref add`/`remove`/`list`) and References
  field, the new title-search flag, and `remove` (a permanent delete, distinct
  from archiving).

## [0.35.0] — 2026-05-31

### Added

- **A quick-capture inbox — capture now, sort later.** A new `mc-tool-inbox`
  gives you one frictionless verb to dump a thought without deciding upfront
  whether it's a task, a card, a decision, or a memory: `add` captures it,
  `list` shows the inbox oldest-first, and `remove` drains an item out. The
  inbox is global rather than project-scoped — capture shouldn't make you stop
  and classify. The session-start brief now surfaces the waiting count, so an
  unsorted pile stays visible rather than forgotten.
- **A `/triage` skill to drain the inbox.** It walks the captured items and
  proposes a destination for each — board card, task, decision, or memory —
  creating it on your say-so and then removing the item, so the inbox stays
  near-empty rather than becoming a second backlog. Suggestion-based throughout:
  the companion proposes, you decide; nothing is routed or removed without
  confirmation.

## [0.34.1] — 2026-05-31

### Added

- **A dedicated guide for the kanban board.** The board now has its own page in
  the documentation, rather than being scattered across command mentions: the
  working model (manually driven, with Claude as the worker), the card lifecycle,
  the collapsed-for-work versus expanded-for-review layouts, card anatomy, and
  full TUI and CLI references — illustrated with screenshots of a busy
  multi-project board and a fully-populated card.

## [0.34.0] — 2026-05-31

### Added

- **References on cards — a structured list of label→value links.** Point a card
  at the things it relates to (a PR URL, a `file://` plan, a bare JIRA key)
  instead of burying them in the description. Manage them from the CLI with
  `mait-code board ref add/remove/list`, or in the board TUI's card screen with
  `r`; the card screen shows a References section where URL and `file://` values
  are clickable. References are kept in order and identified by position.
- **Toasts now carry the house look.** Notifications get a rounded, severity-keyed
  border and a leading glyph (`ℹ`/`⚠`/`✘`) keyed to their colour — information in
  the primary hue, warnings amber, errors red — so they read as part of the same
  family as the chips and recolour with the active theme.
- **The TUI theme now sticks.** Pick a theme with `Ctrl+P` and it's remembered
  across sessions (a new `theme` setting). Any registered theme persists — the
  house themes or a Textual built-in — and an unknown saved name falls back to
  `mait-dark`. The `mait-code settings` editor offers it as a theme picker too.

## [0.33.0] — 2026-05-31

### Added

- **Four new board themes, and the board now recolours fully when you switch.**
  Press `Ctrl+P` to pick a theme: **mait-bubblegum** (a vivid neon palette — hot
  pink, purple and mint on a deep aubergine base), **mait-aurora** (a calmer
  spread of teal, periwinkle and violet), **mait-ember** (warm amber and gold on
  a roasted-brown base), or **mait-syntax** (a vivid code-editor palette — teal,
  gold, violet, green and pink). `mait-dark` stays the default. A switch now
  repaints the whole screen — including the priority and tag chips, which
  previously stayed on the old palette.

### Changed

- **The card screen reads in distinct colours instead of one hue.** The title is
  a strong neutral, section headers take the accent colour, tags and the comment
  bar take the secondary — so the frame, headings, tags and body no longer blur
  together. Every theme inherits the separation.
- **Low-priority cards read as the quiet end of the scale.** The `low` chip now
  recedes to a muted grey rather than a saturated blue, so it stays clearly
  distinct from a card's tags.
- **The card-detail meta line has a consistent rhythm.** Project, status,
  priority and tags are now set off by the same separator
  (`project · status · priority · #tag`), rather than the priority and tags
  trailing off space-separated.

## [0.32.0] — 2026-05-31

### Added

- **You can now act on a board card without leaving its screen.** Comment (`c`),
  tag (`t`), move (`<` / `>`), block / unblock (`b` / `u`) and complete (`C`) all
  work from inside the card screen, refreshing the open card in place rather than
  bouncing back to the board and losing your reading position. Completing a card
  keeps the screen open and re-renders it as Done with its summary.

### Changed

- **The card screen's hint bar is now contextual.** The footer advertises only
  the actions that apply right now — the view actions while reading, Save
  (`Ctrl+S`) while editing, and whichever of block / unblock matches the card —
  so it stays an accurate map of what each key does.
- **The card screen content has room to breathe.** Running text no longer fuses
  against the scrollbar or the hint bar: the content keeps symmetric side padding
  and lifts off the footer, and stays visually centred whether or not a scrollbar
  is present.

## [0.31.0] — 2026-05-31

### Added

- **The board TUI's card view is now near-fullscreen, and you can edit in
  place.** Pressing `Enter` opens a card on a roomy screen; `e` flips it from
  reading to an edit form without leaving — and saving lands the change and
  drops you back into the view, rather than bouncing to the board. `Esc` backs
  an edit out to the view first, then closes. The two modes share one screen, so
  there's no longer a separate read-only modal and edit modal to juggle.

### Changed

- **The card screen's width hugs its text.** The frame is tall for room but caps
  its width to the readable content column instead of sprawling across wide
  terminals, so the card stays a comfortable measure and centres rather than
  leaving large empty gutters.

## [0.30.0] — 2026-05-30

### Added

- **Tag removal is now discoverable in the board TUI.** The tag modal lists a
  card's current tags as `✕ tag` chips — select one to remove it — rather than
  making you retype the exact tag name to toggle it off.

### Changed

- **The board columns now show cards as boxed widgets.** Each column is an
  `OptionList` of bordered card boxes: `#id` top-left, project top-right, the
  full title wrapped to the column width (so it no longer clips, and the
  mouse-only horizontal scrollbar is gone), and tags bottom-right. Blocked cards
  carry a red border alongside the `⊘` marker and `#blocked` badge.
- **The Done column is hidden by default**, behind a `d` toggle (mirroring the
  `a` archived toggle), to widen the active flow (backlog / refined / in
  progress). Moving or completing a card into a hidden Done leaves it hidden and
  confirms with a toast.

### Fixed

- **The selected card stays legible.** The highlighted card's background was a
  solid cyan fill — the same hue as its `#id` and tags, which made them vanish
  on selection; it now uses a tint so every glyph stays readable.

## [0.29.1] — 2026-05-30

### Changed

- **The board TUI's card-detail view is now readable with real content.** The
  title wraps instead of clipping; project/status show with priority and tags as
  chips; each section (Description / Acceptance / Completion / Comments) has a
  clear header set off by a rule; and comments render as distinct blocks with an
  author + timestamp, rather than running together.

## [0.29.0] — 2026-05-30

### Added

- **Interaction polish across the board and settings TUIs.** A `Ctrl+P` command
  palette exposes each app's actions; `?` opens a context help screen built from
  the live key-bindings; number keys jump straight to a column (board) or
  between the list and editor (settings); and actions raise toasts.

### Changed

- **Priority and tags render as domain-coloured chips** on the board card rows
  (a heat scale for priority, the blocked tag bold in the error colour),
  replacing the previous plain text. The leading `⊘` marker remains the
  truncation-proof blocked signal.

## [0.28.0] — 2026-05-30

### Added

- **In-place card mutation in the board TUI.** Create (`n`), edit (`e`) and
  complete-with-summary (`C`) without leaving the board — each a modal over the
  shared service layer, with a toast on success. The complete gesture captures a
  handoff summary (distinct from a bare move into done), so done cards are never
  summary-less.

## [0.27.0] — 2026-05-30

### Added

- **A shared design system for the Textual TUIs.** A new house theme
  (`mait-dark`) and a single colour palette now back both the board and the
  settings editor, and the same palette colours the plain CLI output — so the
  TUIs and command output read as one product. Press `Ctrl+P` to switch themes
  (the house theme alongside Textual's built-ins).

### Changed

- **The board and settings TUIs are restyled onto the shared theme.** Titled
  rounded panels with a clear focus colour, a consistent type hierarchy, and
  shared modal styling replace the old per-app inline CSS. Behaviour is
  unchanged.
- **Raised the Textual floor to `>=0.86`** (the Theme-system baseline; the
  installed version already satisfied it).

## [0.26.0] — 2026-05-30

### Added

- **A general card-tagging system for the board.** Cards now carry free-form
  tags: `mc-tool-board tag N <tag>` adds one and `untag N <tag>` removes it,
  `list` and `show` render a card's tags, and `list_cards` gained a single-tag
  filter. In the board TUI, `t` toggles a tag on the selected card (present →
  removed, absent → added) and tags paint on the card rows.

### Changed

- **`blocked` is now a tag, not a column.** Blocking a card tags it `blocked`
  *in place* instead of moving it, so the card keeps its real flow position
  (`backlog` / `refined` / `in_progress` / `done`). `block` / `unblock` (and the
  TUI `b` / `u` keys) survive as thin aliases over the `blocked` tag, and a
  blocked card now moves along the flow normally. The board drops from six panes
  to five.

### Migration

- Existing `blocked` cards are migrated automatically on first board open
  (schema migration #2): each is moved to `refined` and gains a `blocked` tag.
  The pre-block column was never stored, so `refined` matches the previous
  unblock behaviour.

### Removed

- The `mait_code.tools.board` package no longer exports the `BLOCKED` status
  constant (replaced by `BLOCKED_TAG`), and `blocked` is no longer a valid
  `move` / `list --status` target.

## [0.25.4] — 2026-05-30

### Fixed

- **The test suite wrote into the developer's real log.** Tests that drive a
  `@log_invocation`-decorated entry point ran `setup_logging()`, which writes to
  `$XDG_STATE_HOME/mait-code/mait-code.log` — the dev's *real* log — recording
  pytest's argv as the command and inflating ERROR counts with test fixtures.
  The root autouse fixture now isolates `XDG_STATE_HOME` (and, belt-and-braces,
  `MAIT_CODE_DATA_DIR`) to a temp dir per test and re-initialises logging there,
  so a full run leaves the real log untouched.
- **The observe hook logged a vanished transcript as an ERROR.** When the
  stdin event named a transcript that no longer existed on disk (a brand-new or
  already-cleaned session), `open()` raised and surfaced as a generic
  `observe: [Errno 2] ...` ERROR. That window has nothing to observe — the hook
  now detects the missing file up front and skips with a WARNING, leaving the
  cursor untouched.

### Changed

- **Expected user-input and empty-state conditions log at WARNING, not ERROR.**
  The task/reminder/board/decision/memory tools logged routine outcomes — "#N
  not found", "title cannot be empty", "invalid type", "no observation logs
  found" — at ERROR, even though the user already sees the message on stderr.
  These are now WARNING; genuine faults (embedding failure, fetch failure) stay
  ERROR.

### Internal

- **Regression test for the local-embedding cache path.** Pins that
  `LocalProvider` hands fastembed an expanded model-cache path — guarding the
  consumer that broke when `MAIT_CODE_DATA_DIR` held a literal `~` (a load
  failure that silently degraded semantic search until the 0.25.1/0.25.2 tilde
  fixes).

## [0.25.3] — 2026-05-30

### Fixed

- **Session-start hook produced no companion context and logged a validation
  error.** The `SessionStart` hook emitted `hookSpecificOutput` with a `context`
  key and no `hookEventName`, so Claude Code rejected the payload
  (`hookSpecificOutput is missing required field "hookEventName"`) and the
  reminders / tasks / board summary never reached the session. The hook now
  emits the correct schema (`hookEventName: "SessionStart"` and
  `additionalContext`). The regression slipped through because the test asserted
  the same wrong key; it now checks the correct contract.

### Internal

- **Shared hook-output schema test.** Added a single validator for the Claude
  Code `hookSpecificOutput` contract that every hook's actual stdout is checked
  against, replacing per-hook ad-hoc shape assertions. Catches missing
  `hookEventName`, mislabelled context keys, and unknown events for any current
  or future hook.

## [0.25.2] — 2026-05-29

### Fixed

- **`XDG_DATA_HOME` / `XDG_CONFIG_HOME` / `XDG_STATE_HOME` with a leading `~`
  resolved to the wrong place.** Same bug class as the 0.25.1 `data-dir` fix:
  an override with a literal, unexpanded tilde was used as a relative path, so
  the install record, settings file, and logs could land in a stray `~`
  directory under the working directory. The three XDG resolvers now expand a
  leading `~`.

## [0.25.1] — 2026-05-29

### Fixed

- **Board TUI showed no cards.** The status panes were laid out with no height,
  so every column collapsed to zero rows and `mait-code board` rendered empty
  even when cards existed. The panes now fill the body and the card lists flex
  to fill each pane. Added layout regression tests that assert non-zero pane
  height and that card text actually paints (the earlier tests only checked the
  data model, not the render).
- **Card detail modal dropped bracketed text.** A comment author (`[claude]`)
  or any field containing `[...]` was parsed as Rich console markup and
  silently removed. Dynamic fields are now escaped, so the text renders
  literally.
- **`data-dir` with a leading `~` resolved to the wrong place.** A
  `MAIT_CODE_DATA_DIR` value like `~/.claude/mait-code-data` (a literal,
  unexpanded tilde) was used as a relative path, scattering databases into a
  stray `~` directory under the working directory — so the board, tasks, and
  memory read empty stores. `data_dir()` now expands a leading `~`.

## [0.25.0] — 2026-05-29

### Added

- **`mait-code board`** — an on-demand, full-screen kanban TUI. View every
  project's cards in side-by-side status columns, filter by project (`p`),
  navigate with the arrow keys, and move a card along the flow with `<`/`>`
  (`backlog → refined → in_progress → done`; `blocked` is reached via `b`/`u`).
  Open a card's detail and comment thread with `Enter`, add a comment with `c`,
  toggle archived with `a`, and quit with `q`. Launched explicitly and run in
  the foreground — no background process. Piped or redirected, it falls back to
  a read-only grouped render. This completes the board: data + CLI (0.23.0),
  skill + session summary (0.24.0), and now the visual board.

### Changed

- **Board internals** — the card queries and mutations (including the
  done-invariant) now live in a shared `board/service.py`, so the CLI and the
  TUI sit on one source of truth. No change to the `mc-tool-board` interface.

## [0.24.0] — 2026-05-29

### Added

- **`/board` skill** — view and drive the kanban board conversationally. Shows
  the current project's board, and teaches Claude the verb vocabulary so "pick
  up the next refined card", "refine card N", and complete/block/move/add map to
  `mc-tool-board` calls. Claude acts as the worker; nothing moves without your
  say-so.
- **Session-start board summary** — the `session_start` hook now surfaces a
  one-line summary of the current project's live (non-done) columns alongside
  reminders and tasks (e.g. `3 refined · 1 in progress`), and stays silent when
  there's nothing actionable.

## [0.23.0] — 2026-05-29

### Added

- **A manually-driven kanban board (`mc-tool-board`).** A single cross-project
  board in `board.db`: cards carry a `project` field and move through a fixed
  workflow — backlog → refined → in_progress → done, with `blocked` and hidden
  `archived` side-states. Create and refine cards (description + acceptance
  criteria), pick up the next refined card for the current project
  (`next --claim`), comment, and complete with a handoff summary. Claude in the
  live session is the worker — there's no background dispatcher. CLI-only in
  this release; an on-demand TUI and a `/board` skill follow.

## [0.22.1] — 2026-05-29

### Changed

- **The interactive `mait-code settings` list is now an aligned table** —
  `Setting` / `Value` / `Source` columns under a header, replacing the ragged
  single-line rows whose source column drifted out of line on long values.
  Values are truncated with an ellipsis (the full value stays editable in the
  detail pane); derived/default rows read as muted. The list and detail panes
  split the screen evenly, the `Value` column flexes to fill the list pane
  while `Source` stays compact, the migration `⚠` marker now sits on the
  setting name (with an inline explanation in the detail pane that changing it
  re-embeds stored memories), `Enter` on a row jumps focus to the editor,
  `Escape` returns focus to the list, and a single `Tab` moves between the list
  and the editor.

## [0.22.0] — 2026-05-29

**The interactive `mait-code settings` editor is now a proper full-screen
TUI.** The questionary prompt sequence shipped in 0.21.0 is replaced by a
[Textual](https://textual.textualize.io/) app — a master–detail layout with
live, in-context validation.

### Changed

- **Bare `mait-code settings` (on a TTY) opens a full-screen editor**: the
  settings list on the left, an inline edit form on the right that adapts to
  the highlighted setting — a radio set for enums, a validated text input
  otherwise, read-only for derived values. The grouped scoring-weight editor
  enforces the sum of `1.0` before a single combined write; migration and
  `data-dir` follow-ups are confirmed in a modal (a re-embed drops out to the
  terminal for its normal progress output). The non-TTY fallback, and the
  `list`/`get`/`set` subcommands, are unchanged.

### Dependencies

- Replaced `questionary` with `textual` for the interactive editor. Textual
  builds on `rich` (already shipped) and `markdown-it-py` (already in the
  lock), so the net footprint is small; `prompt_toolkit` and `wcwidth` are
  dropped with questionary. Imported lazily, so hooks and CLI tools never
  load it.

## [0.21.0] — 2026-05-29

**`mait-code settings` is now editable: a non-interactive `set`, an
interactive editor, and `get`/`list` subcommands — every change validated,
kept clear of stale env shadows, and with destructive follow-ups carried
out rather than left implied.**

### Added

- **`mait-code settings set <key> <value>`** validates against the same
  rules `doctor` runs, persists to `settings.toml`, and runs the required
  follow-up. Migration keys (`embedding-provider`, `embedding-model`,
  `bedrock-model-id`) require an explicit `--reindex`/`--no-reindex`;
  `data-dir` requires `--move-data`/`--no-move-data`. The three scoring
  weights are rejected (they can't change one at a time without a transient
  invalid sum) with a pointer to the editor.
- **Interactive editor on bare `mait-code settings`** (when attached to a
  terminal): an arrow-key picker with live, per-value validation, enum
  pickers for `embedding-provider` and `log-level`, a grouped editor that
  retunes all three scoring weights and enforces their sum before a single
  write, and inline confirmation of re-embed / data-dir-move follow-ups.
  Piped or redirected, the bare command still prints the read-only view, so
  scripts are unaffected.
- **`mait-code settings list [--json]`** is the read-only, provenance-aware
  view that was previously the bare command; **`mait-code settings get <key>
  [--json]`** prints one resolved value and its source for scripting.
- **Enum `choices` on `Setting`** for `embedding-provider` and `log-level`,
  driving both the editor's picker and `set`/`doctor` validation from one
  source.

### Changed

- **Bare `mait-code settings` opens the editor on a TTY** instead of printing
  the view; the `--json` flag moved to `settings list`. Non-interactive use
  (pipes, redirects) is unchanged.
- **`set` keeps an already-mirrored `MAIT_CODE_*` key in
  `~/.claude/settings.json` in step** with `settings.toml` (so a stale mirror
  can't silently shadow the change) and warns precisely when a shell export
  still overrides the new value. It never adds keys to `settings.json`.
- Advanced settings are now written **active** in `settings.toml` when an
  explicit value is set (e.g. via `settings set`), instead of always
  commented-out; install/update still emit them commented, so generated files
  are unchanged.
- `run_reindex()` is extracted from the memory CLI so the settings follow-up
  can re-embed in-process.

### Dependencies

- Added `questionary` (pulls `prompt_toolkit`, pure-Python) for the
  interactive editor.

## [0.20.0] — 2026-05-29

**`mait-code settings` now exposes the configuration surface that was
previously hardcoded — derived values, operational knobs, and scoring
tuning — without changing any default.**

### Added

- **Derived, read-only values in `mait-code settings`.** The view now reports
  computed values with source `derived`: `embedding-dim`, the four database
  paths (`memory-db-path`, `tasks-db-path`, `decisions-db-path`,
  `reminders-db-path`), `model-cache-dir`, `observations-dir` and
  `project-aliases-path`. They answer "where does my data live?" and "why does
  a provider switch force a reindex?". They cannot be set.
- **Advanced operational settings**, written commented-out in `settings.toml`
  so the built-in default stays authoritative until you opt in:
  `log-backup-count`, `extraction-model`, `reflection-model`, `llm-timeout`,
  `reflection-batch-size`, `reflection-novelty-gate` and `git-timeout`.
- **Advanced scoring & dedup tuning**, all validated: `score-weight-recency`,
  `score-weight-importance`, `score-weight-relevance`, `half-life-episodic`,
  `half-life-semantic`, `dedup-string-threshold`, `dedup-vector-threshold`,
  `scope-boost-global` and `scope-boost-cross-project`.
- **`mait-code doctor` validates setting values** via a new `settings-values`
  check: it flags out-of-range values and scoring weights that don't sum to
  1.0. Bad values fall back to defaults at runtime, so retrieval is never
  silently skewed between doctor runs.

### Changed

- The `Setting` registry gained typed accessors (`get_int`, `get_float`),
  derived (display-only) and advanced (opt-in, commented-out) settings, and a
  per-value/cross-field validation hook. Existing settings are unchanged.
- `llm-timeout` reconciles the previous split (60s general / 90s extraction)
  onto a single knob defaulting to 90s.

## [0.19.1] — 2026-05-29

**`mait-code update` is now a cheap no-op when nothing changed.**

### Fixed

- **`mait-code update` no longer rebuilds every package on each run.** The
  reinstall is now skipped when the source `HEAD` did not move during the
  advance step, so a repeated update with nothing new upstream is a fast
  no-op instead of a full `uv tool install --force --reinstall` of all
  dependencies. When a reinstall *is* needed, it uses
  `--reinstall-package mait-code` to rebuild only the local source package —
  whose version does not bump between commits — leaving unchanged
  third-party dependencies in place.

### Added

- **`mait-code update --force`** reinstalls even when the source `HEAD` is
  unchanged, for rebuilding uncommitted working-tree edits on a dev
  checkout.

## [0.19.0] — 2026-05-28

**Centralised settings file and XDG-compliant directory layout.**

### Added

- **Centralised settings file at `$XDG_CONFIG_HOME/mait-code/settings.toml`.**
  All `MAIT_CODE_*` configuration knobs now resolve through a three-tier
  chain: environment variable → settings file → hardcoded default. TOML
  format with comments for human readability; all values written (including
  defaults) for full transparency. Written by `mait-code install` and
  `mait-code update`; values propagated into `~/.claude/settings.json` for
  Claude Code session compatibility.

- **`config.get(key)` convenience function.** Returns the resolved value
  for a setting by its kebab-case key, without exposing provenance.

- **XDG path helpers:** `xdg_config_home()`, `xdg_state_home()`,
  `mait_code_config_dir()`, `mait_code_log_dir()`, `settings_path()`.

### Changed

- **Logs default to `$XDG_STATE_HOME/mait-code/`** (typically
  `~/.local/state/mait-code/`) instead of `~/.claude/mait-code-data/logs/`.
  The `MAIT_CODE_LOG_FILE` override still works. Old logs are left in place.

- **`mait-code settings` output** now shows a `"settings"` source column
  for values from the settings file, and displays the settings file path.
  Drift detection compares the env var against the settings file (the install
  record is no longer involved).

- **`merge_settings()` propagates all settings**, not just
  `embedding_provider`. Its signature changes from
  `embedding_provider: str` to `user_settings: dict[str, str]`.

- **`unmerge_settings()` strips all `MAIT_CODE_*` env vars**, not just
  the embedding provider.

- **Runtime consumers** (`logging.py`, `embeddings.py`) use
  `config.get()` / `config.resolve()` instead of direct `os.environ` reads,
  so they benefit from the settings file in all contexts.

### Removed

- **`embedding_provider` and `version` fields from the install record.**
  Configuration now lives in the settings file; the installed package
  version (`mait_code.__version__`) is the canonical version source.
  Old records with these fields still parse correctly; `mait-code update`
  migrates the embedding provider value on first run.

### Fixed

- **`mait-code settings` reported `local` instead of `bedrock` outside
  Claude Code sessions.** The settings file provides the correct value
  regardless of whether Claude Code's env injection is active.

## [0.18.0] — 2026-05-27

**Coloured `status` and `doctor`, and a new read-only `settings` command.**

### Added

- **`mait-code settings` — a read-only view of the active configuration.**
  Modelled on `aws configure list`: one row per `MAIT_CODE_*` knob showing its
  value and *source* (`env` vs `default`), so "why is it this value?" is
  answerable at a glance. Migration-sensitive knobs (the embedding
  provider/model) are flagged, and the command detects drift — when the active
  embedding provider differs from the one recorded at install time it warns
  that stored memories need re-embedding. Read-only by design; to change an
  embedding knob, set its env var and run `mc-tool-memory reindex` to re-embed
  — an in-place setter isn't built yet. Supports `--json`.
- **A global `--no-color` flag.** Disables coloured output explicitly; colour
  is also dropped automatically when output is not a terminal and under
  `NO_COLOR` / `TERM=dumb`.

### Changed

- **`status` output is grouped and coloured.** It now reads as Install /
  Identity / Components / Memory sections under a top-line health badge
  (healthy / degraded / not installed), with humanised sizes, `~`-abbreviated
  paths, the install date without the timestamp, and git-style hints for
  fixable oddities such as a `CLAUDE.md` that isn't linked. The `--json` shape
  is unchanged.
- **`doctor` gains colour, per-finding fix hints, and a verdict line.** Each
  finding now carries the exact command or URL to resolve it, the run ends with
  a one-line pass/fail summary, and dangling skill/agent symlinks are reported
  as a warning rather than a failure — they are auto-fixable, so they no longer
  make `doctor` exit non-zero on their own. The `--json` output gains an
  additive `fix_hint` field per check.

### Fixed

- **`MAIT_CODE_DATA_DIR` handling is now consistent.** An empty or
  whitespace-only value previously resolved to the current directory in the
  memory / tasks / decisions / reminders / logging code paths (only the install
  CLI handled it safely); every path now falls back to the default data
  directory. Configuration knobs are read through a single registry, so their
  defaults are defined exactly once.

## [0.17.0] — 2026-05-27

**Project-alias map.**

### Added

- **Project-alias map for unified project identity.** Renaming a working
  directory changes its slug, which used to split a project's memories across
  two names. A new `project-aliases.json` in the data directory maps old slugs
  to canonical ones; slugs are now canonicalised on both read and write, and a
  new `mc-tool-memory canonicalize-projects` command rewrites existing rows
  under an old slug to the canonical one. Config-driven, so it generalises to
  any rename.

## [0.16.0] — 2026-05-27

**First-class `decision` entry type.**

### Changed

- **Extracted decisions get their own `decision` entry type.** The observe
  hook stored architectural decisions under `entry_type='insight'`, colliding
  with reflection output (which also uses `insight`). Decisions are now a
  first-class `decision` type, so reflection's synthesised insights stay
  distinct from extracted ones — and decisions are now correctly included in
  the reflection corpus instead of being excluded as if they were insights. A
  schema migration relabels historical `insight` rows to `decision`, but only
  on databases where reflection has never run (where the two are otherwise
  indistinguishable), leaving reflective insights untouched.

## [0.15.5] — 2026-05-27

**Daily log rotation.**

### Changed

- **Logs now rotate daily instead of by size.** The file handler switched from
  a 5 MB size-based rotation — which, at the actual log volume, effectively
  never rotated — to a daily `TimedRotatingFileHandler` at midnight, keeping 14
  days of date-stamped backups.

## [0.15.4] — 2026-05-27

**Extraction reliability fix.**

### Fixed

- **Failed extractions no longer silently lose their transcript window.** When
  the extraction LLM call timed out or errored, the observe hook still advanced
  its read cursor, so that slice of conversation was skipped permanently. It
  now leaves the cursor in place and re-attempts the window on the next
  session, giving up only after three consecutive failures so a single
  un-extractable transcript can't stall extraction forever. The extraction
  timeout is also raised from 45s to 90s to accommodate longer transcripts.

## [0.15.3] — 2026-05-27

**Memory extraction data-quality fixes.**

### Fixed

- **Project- and branch-scoped preferences are no longer flattened to
  global.** The observe hook hard-coded every extracted preference to
  `scope=global`, discarding the scope the model classified. It now honours a
  valid project/branch classification and only falls back to global when none
  is given, so a preference learned in one project no longer leaks into
  others.
- **Extracted relationship types are constrained to a fixed vocabulary.**
  Relationships are coerced on write to the canonical set (`uses`, `owns`,
  `contributes_to`, `depends_on`, `manages`, `related_to`), and the extraction
  prompt is generated from that same set so the two cannot drift. This stops
  the long tail of one-off relationship labels; the edge is preserved, only an
  out-of-set label is normalised to `related_to`.

## [0.15.2] — 2026-05-27

**Fix `mait-code update` on tag-pinned installs.**

### Fixed

- **`mait-code update` no longer fails on a tag-pinned install.** The
  bootstrap installer checks out a release tag, leaving the source in
  detached HEAD; `update` then ran `git pull` unconditionally, which
  aborts with "You are not currently on a branch". `update` now fetches
  and advances based on the source state: `--ref` checks out that ref,
  a branch fast-forwards (`git merge --ff-only`), and a detached HEAD
  moves to the latest `v*` tag. `--no-pull` reinstalls from the current
  checkout without touching git.

## [0.15.1] — 2026-05-27

**One-liner installer.** Adds `curl … | bash` as the primary install
path. Closes the master release-infra checklist — every brick (A
through F) has now shipped.

### Added

- **One-liner installer** (`scripts/bootstrap.sh`). Detects or installs
  `uv`, clones the repo to `~/.local/share/mait-code/source/`, runs
  `uv tool install`, and execs `mait-code install` to wire up symlinks,
  settings, and data directories. Idempotent. Served from
  `raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh`:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
  ```

  Flags: `--embedding-provider`, `--ref` (default: latest `v*` tag),
  `--dir`, `--no-uv`, `--help`. Pass via `bash -s --` when curl-piping.
- **`scripts/test-bootstrap.sh`** — Docker-based smoke test against
  `ubuntu:24.04`. Invoke locally before merging changes to
  `bootstrap.sh`. Not run by CI in v1.

### Changed

- **README, `docs/setup.md`, and the docs Home page** now lead with
  the one-liner. The from-source path stays as a secondary
  alternative for contributors.

## [0.15.0] — 2026-05-27

**`mait-code` install-lifecycle CLI.** A new top-level binary replaces
the ad-hoc bash install/uninstall scripts with a Python CLI that owns
the full lifecycle: install, update, uninstall, status, doctor,
version. The bash shims shrink to ~10–40 lines each, handling only the
chicken-and-egg bootstrap before delegating to the CLI.

### Added

- **`mait-code` CLI binary** (`uv tool install` entry point) that owns the
  install lifecycle. Six subcommands:
  - `mait-code install --from <path>` — set up data directories, symlinks
    (`CLAUDE.md`, `skills/*`, `agents/*`), merge `settings.json`, and write
    an install record at `~/.local/share/mait-code/install.json`. Non-
    interactive by default.
  - `mait-code update` — read the install record, `git pull` (or
    `--no-pull`, plus optional `--ref <tag|branch|sha>`),
    `uv tool install --force --reinstall`, refresh symlinks and settings,
    bump the install record.
  - `mait-code uninstall` — reverse the install footprint. Default
    preserves the data directory (memories, personalised identity files);
    `--purge-data` removes it. `--keep-uv-tool` skips
    `uv tool uninstall`.
  - `mait-code status` — read-only summary with `--json` for
    machine-readable output.
  - `mait-code doctor` — diagnostic checks (install record, source dir,
    settings parses, hook commands on PATH, no dangling symlinks, data
    dir writable, uv on PATH). `--fix` applies safe fixes (removes
    dangling symlinks, recreates a missing data dir).
  - `mait-code version` — prints the installed version.
- **Install record schema** (`schema_version: 1`) with versioned format
  for forward-compatible evolution.

### Changed

- **`scripts/install.sh`** shrunk to a ~40-line shim: prompts for the
  embedding provider (or honours `$MAIT_CODE_EMBEDDING_PROVIDER` and
  non-TTY environments), `uv tool install`s from the local source, then
  `exec`s `mait-code install`.
- **`scripts/uninstall.sh`** shrunk to a 10-line shim that forwards all
  arguments to `mait-code uninstall`.
- **`docs/setup.md`** documents the new CLI lifecycle commands alongside
  the bash shims, with a link to the full reference.
- **`docs/reference/mait-code.md`** — comprehensive per-subcommand
  reference (synopsis, flags, behaviour, examples, exit codes) under
  Reference / CLI. Sits alongside the existing Skills catalogue.

## [0.14.1] — 2026-05-26

**Documentation site, release pipeline, and type-checking infrastructure.**
No runtime behaviour changes — this patch release ships the project's first
hosted documentation site at <https://wiktordepina.github.io/mait-code/>,
encodes the release process in CI, and adopts pyright type-checking up to
standard mode.

### Added

- **Docs site.** `mkdocs-material` + `mkdocstrings` with auto-generated Python
  API reference driven by each surface module's `__all__`. Twelve modules
  surface — four core (`context`, `llm`, `logging`, `ssl`), five tool
  packages, three hook packages. Nested layout under `Tools/` and `Hooks/`
  mirrors the dotted module hierarchy. Hand-authored `docs/reference/skills.md`
  catalogues every slash command.
- **GitHub Pages deploy.** `docs.yml` workflow with cairn's deploy pattern —
  `dev` alias from `main`, version pin + `latest` alias from tags, managed by
  `mike`.
- **`docs/contributing-docs.md`.** Convention note covering the `__all__`
  contract, Google docstring style, the regeneration workflow, and the
  seven-tab nav layout.
- **Release pipeline.** `ci.yml` (lint, test, audit, typecheck) and
  `release.yml` (version-bump-triggered, dispatches `docs.yml` on tag).
  `tests/test_imports.py` is a parametrised smoke test asserting every
  surface module declares a non-empty `__all__`.
- **Pyright type-checking** in standard mode over `src/`. Added as a fourth
  job in `ci.yml` alongside lint / test / audit. Configured via
  `[tool.pyright]` in `pyproject.toml`.
- **CI and Docs badges plus a hosted-docs link** in root `README.md`.

### Changed

- **Codebase-wide docstrings** migrated to Google style for consistent
  rendering by `mkdocstrings`. Surface modules declare `__all__` with
  `# Section` comments grouping symbols by topic.
- **Docs nav** organised into seven tabs (Home, Guide, Concepts, Architecture,
  Reference, Decisions, Contributing). Home page rewritten as a proper landing
  experience rather than a link list.
- **`Optional` narrowing tightened** across ten sites in
  `tools/memory/cli.py`, `hooks/observe/extractor.py`,
  `tools/memory/scoring.py`, `tools/memory/writer.py`, and
  `tools/web_fetch/fetch.py`. Drive-by return / parameter annotations on
  `log_invocation` and `check_dimension_match` surfaced by
  `mkdocs build --strict`.
- **CHANGELOG** reformatted to
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions while
  preserving all prior history.

### Removed

- **`run_pytest.yaml` workflow.** Superseded by the broader `ci.yml`.

## [0.14.0] — 2026-04-07

**Web fetch tool and embedding test fixes.**
Local web fetch tool that bypasses the claude.ai proxy, working behind corporate firewalls and proxies. Also fixes embedding tests to work with both local and Bedrock providers.

### Web fetch tool
- **`mc-tool-web-fetch` CLI tool:** Fetches a URL and returns content as markdown (HTML) or formatted text (JSON, plain text). Uses stdlib `urllib.request` with `truststore` for corporate proxy compatibility.
- **HTML-to-markdown conversion:** Strips noise tags (`<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`) then converts via `markdownify`. Collapses excessive blank lines.
- **Content-type routing:** HTML→markdown, JSON→pretty-printed, text→passthrough, binary→descriptive message.
- **SSRF protection:** Resolves hostnames and blocks private/loopback/link-local/reserved IPs by default. Overridable with `--allow-private`.
- **HTTPS upgrade:** Automatically upgrades `http://` to `https://`, adds scheme to bare domains.
- **Size and length limits:** `--max-size` (default 512KB response body), `--max-chars` (default 100K output characters, ~25K tokens).
- **`/web-fetch` skill:** Slash command wrapping the CLI tool with preprocessing for convenient invocation.
- **New dependency:** `markdownify>=0.14` (brings `beautifulsoup4`).

### Embedding test fixes
- **Provider-aware constant tests:** `test_default_model_name` and `test_default_dimension` now accept both local (nomic/768) and Bedrock (Titan/1024) values depending on environment configuration.
- **Provider-aware graceful degradation:** `test_embed_text_returns_none_when_unavailable` now blocks the correct dependency (`fastembed` or `boto3`) based on the active provider.
- **Provider-pinned dimension checks:** All `TestDimensionCheck` tests explicitly pin the provider via `patch.dict` so they pass regardless of environment. Added bedrock-specific matching tests.
- **New tests:** `test_local_default_dimension`, `test_local_model_name`, `test_empty_table_matching_declaration_bedrock`, `test_matching_dimension_bedrock`.

### Test coverage
- 35 tests for web fetch (URL validation, SSRF protection, HTTP errors, timeouts, HTML conversion, JSON formatting, charset handling, truncation, binary content).
- 27 tests for embeddings (up from 23), all passing with both local and Bedrock providers.

## [0.13.0] — 2026-03-24

**Configurable embedding providers.**
Support for multiple embedding providers — local (fastembed/HuggingFace) and AWS Bedrock — configurable via environment variables. Designed for corporate environments where HuggingFace may be blocked.

### Embedding provider abstraction
- **Provider abstraction:** New `EmbeddingProvider` ABC with `LocalProvider` (fastembed) and `BedrockProvider` (AWS Bedrock) implementations. Public API (`embed_text`, `embed_texts`, `is_available`, `serialize_f32`) unchanged.
- **`LocalProvider`:** Wraps fastembed with nomic-embed-text-v1.5 (768d). Reads `MAIT_CODE_EMBEDDING_MODEL` env var. Prefixes text with task type (`search_document:` / `search_query:`).
- **`BedrockProvider`:** Calls AWS Bedrock `invoke_model` API. Supports Titan and Cohere model families. Reads `MAIT_CODE_BEDROCK_MODEL_ID` and `MAIT_CODE_BEDROCK_REGION` env vars. Calls `setup_ssl()` for corporate proxy compatibility.
- **Configuration:** `MAIT_CODE_EMBEDDING_PROVIDER` env var (`local` or `bedrock`). Deployment-time decision — pick a provider and stick with it.
- **Dimension handling:** `EMBEDDING_DIM` and `EMBEDDING_MODEL` computed from env vars at import time. `check_dimension_match()` detects vec table dimension mismatches.
- **`cmd_reindex` migration:** Automatically detects dimension mismatch when switching providers, drops and recreates the vec table with the correct dimension before reindexing.
- **`cmd_stats` enhanced:** Now shows embedding provider, model name, and dimension alongside existing statistics.
- **Provider-specific error messages:** `cmd_reindex` hints at the correct dependency (`fastembed` or `boto3`) based on the configured provider.
- **Optional dependency:** `pip install mait-code[bedrock]` installs `boto3>=1.34`.
- **Graceful degradation:** Both providers fail silently if their dependency is missing — memory storage and keyword search continue to work.

### Documentation
- Updated `docs/memory.md` with provider configuration, corporate setup guide, and env var table.
- Updated `docs/architecture.md` with provider env vars, key decision, and vec table description.
- Updated `docs/development.md` with revised embeddings module description.

### Test coverage
- Rewrote `test_embeddings.py` for provider abstraction: mock provider tests for prefix handling (local vs bedrock), bedrock dimension config, bedrock invoke_model mock, dimension check (empty, matching, mismatch, error), graceful degradation.

## [0.12.1] — 2026-03-24

**macOS compatibility fixes.**
Workarounds for macOS-specific issues: async hook stdin bug and corporate proxy SSL.

### Async hook stdin fix
- **Resilient stdin parsing:** `_read_event()` returns an empty dict on empty or invalid stdin instead of crashing with `JSONDecodeError`.
- **Transcript fallback:** `_find_transcript()` discovers the most recently modified `.jsonl` transcript from the Claude Code project directory when stdin is unavailable. Workaround for macOS bug where async hooks receive empty stdin ([#38162](https://github.com/anthropics/claude-code/issues/38162)).
- **Slug derivation fix:** Project slug now replaces both `/` and `.` with `-`, matching Claude Code's actual behaviour (e.g. `/Users/wiktor.depina/...` → `-Users-wiktor-depina-...`).

### SSL trust store for corporate proxies
- **`truststore` integration:** New `setup_ssl()` in `src/mait_code/ssl.py` injects the OS trust store into Python's `ssl` module at startup, so corporate proxy CA certificates (e.g. Netskope) are trusted automatically.
- **Wired into entry points:** `mc-hook-observe` and `mc-tool-memory` call `setup_ssl()` before any network requests.
- **Graceful degradation:** If `truststore` is unavailable or injection fails, the system continues with Python's default cert bundle.
- **New dependency:** `truststore>=0.9`.

### Test coverage
- 10 tests for stdin parsing and transcript fallback (including dot-in-path slug derivation).
- 4 tests for SSL setup (injection, idempotency, missing package, injection failure).

## [0.12.0] — 2026-03-12

**Decision log.**
ADR-lite decision records for capturing why technical choices were made.

- **`mc-tool-decisions` CLI tool:** 8 subcommands — `record`, `list`, `show`, `amend`, `supersede`, `search`, `remove`, `sync`. SQLite-backed with FTS5 full-text search across title, context, alternatives, and consequences.
- **Automatic markdown rendering:** Every mutation regenerates `docs/decisions.md` at the git root with a summary table and full decision sections. Skips silently outside git repos.
- **`/decision` skill:** Record a decision via slash command; model-invocable so Claude can suggest recording significant technical choices during sessions.
- **`/decisions` skill:** Browse and search decision records with preprocessing.
- **FK-safe removal:** Deleting a decision clears `superseded_by` references from other decisions before deletion.
- **Test coverage:** 39 tests covering migrations, FTS sync triggers, all CLI commands, rendering (strikethrough, field omission, superseded links), and file writing.
- **3 initial decisions recorded** from project memory: SQLite as DB engine (DR-1), CLI tools over MCP (DR-2), watermark-based reflection idempotency (DR-3).

## [0.11.0] — 2026-03-12

**Idempotent reflection with batching.**
Reflection is now idempotent and supports batched processing of large backlogs.

- **Watermark tracking:** New `reflection_watermark` table (migration 9) tracks the highest entry ID reflected per project. Running `/reflect` twice without new observations is a no-op.
- **Batching:** New `--batch-size N` flag (default 50) limits entries processed per reflection. Entries are processed oldest-first via ascending ID order.
- **Drain mode:** New `--drain` flag loops until all unreflected entries are processed, with a safety cap of 20 iterations.
- **JSONL removed from reflect:** Observation JSONL logs are no longer read during reflection — observations are already in `memory_entries` via the observe hook. `read_observation_logs()` remains for `restore`.
- **Deprecated functions:** `get_last_reflection_date()`, `count_entries_since()`, `check_novelty_gate()`, `get_recent_entries()` kept for backward compatibility but replaced by watermark-based equivalents.
- **New functions:** `get_watermark()`, `update_watermark()`, `check_novelty_gate_v2()`, `get_unreflected_entries()`.
- **Test coverage:** 60 tests for the reflection system including idempotency, incremental processing, batch limiting, and failure safety.

## [0.10.0] — 2026-03-11

**Scoped memory and tasks alignment.**
Three-tier memory scoping (global/project/branch) and removal of the projects registry from tasks.

### Scoped memory
- **Three-tier scope:** Memory entries are now scoped as `global`, `project`, or `branch`. Scope is auto-detected from git context and can be overridden with `--scope`, `--project`, `--branch` flags.
- **Shared context module:** New `src/mait_code/context.py` with `get_project()`, `get_branch()`, `get_context()` — used by memory, tasks, and hooks.
- **Scope-aware search:** All search functions (`search`, `list`, `hybrid_search`, `vector_search`) filter by scope — global entries are always visible, project/branch entries only visible in matching context. Use `--scope all` to disable filtering.
- **Scope-aware dedup:** Deduplication is project-scoped — same content in different projects creates separate entries.
- **Scope-aware scoring:** New `scope_boost()` multiplier in composite scoring — branch match: 1.0, project match: 0.85, global: 0.7.
- **Scope-aware reflection:** `mc-tool-memory reflect` filters by current project context.
- **LLM scope classification:** Extraction prompt now includes scope guidance; `resolve_scope()` heuristic promotes preferences to global, defaults decisions to project, bugs on feature branches to branch.
- **Schema migration 8:** Adds `scope`, `project`, `branch` columns to `memory_entries`, rebuilds FTS5 index with `project` and `scope` columns, recreates sync triggers.

### Tasks alignment
- **Removed projects table:** Migration 3 drops the `projects` table and FK constraint from `tasks.db`. Tasks store project as a plain string column.
- **Removed `ensure_project()`:** No longer needed without the projects registry.
- **Removed `/projects` skill:** Project discovery via `mc-tool-memory stats` (by-project breakdown) or `mc-tool-tasks list-all`.
- **Updated PR skills:** `/prs`, `/standup`, `/today` now use `gh search prs --author=@me --state=open` instead of iterating over registered projects.
- **Updated `/status`:** Derives project info from git directly instead of the projects table.

### Skill updates
- `/recall`, `/remember`, `memory-store`, `/reflect` — updated instructions for scope-aware behaviour.
- `/standup`, `/today` — use `--scope all` for cross-project memory queries.

## [0.9.0] — 2026-03-11

**Database hardening and LLM resilience.**
- **Database context managers:** New `connection()` context manager in all three `db.py` modules (`memory`, `reminders`, `tasks`) — guarantees connection cleanup on exit. All CLI commands and hooks migrated from manual `try/finally/conn.close()`.
- **LLM retry/backoff:** `call_claude()` now accepts `retries` and `backoff_base` parameters with exponential backoff on transient failures (timeouts, non-zero exits). `FileNotFoundError` is not retried (permanent). Default `retries=0` preserves existing fail-fast behaviour for interactive tools.
- **Observe hook resilience:** Extraction calls now retry twice (3 total attempts) with 1s/2s backoff, reducing silent data loss from transient LLM failures.
- **Python 3.13:** Downgrade minimum Python from 3.14 to 3.13 for broader compatibility.
- **Docs:** Convert architecture diagrams from ASCII to Mermaid, update setup and memory docs.

## [0.8.2] — 2026-03-10

**Maintenance updates.**
- **Docs:** Convert architecture diagrams from ASCII to Mermaid
- **Install:** Pin Python 3.13 in uv tool install
- **Uninstall:** Use `uv run python` instead of `python3` for consistency

## [0.8.1] — 2026-03-10

**Fix observe hook recursion.**
Prevent recursive hook invocations when `call_claude()` spawns nested CLI sessions.

- **Recursion guard:** Set `MAIT_CODE_NESTED=1` env var in `call_claude()` subprocess environment
- **Early exit:** Observe hook checks for `MAIT_CODE_NESTED` and skips execution in nested invocations

## [0.8.0] — 2026-03-09

**Projects registry and workflow skills.**
Cross-project awareness via a projects registry, 7 new skills for daily workflow, and time-filtered memory queries.

- **Projects table:** New `projects` table in `tasks.db` storing project name, full disk path, GitHub remote URL, and registration date; foreign key from `tasks.project` to `projects.name` with `PRAGMA foreign_keys=ON` enforcement
- **`ensure_project()`:** Auto-registers the current project on any task subcommand — resolves path via `git rev-parse --show-toplevel` and GitHub URL via `git remote get-url origin`; no-op if project already registered
- **`mc-tool-tasks list-all`:** New subcommand listing open tasks across all registered projects, grouped by project
- **`mc-tool-tasks projects`:** New subcommand listing all registered projects with path, GitHub URL, and added date
- **`mc-tool-memory list --since`:** New time-period filter accepting `24h`, `7d`, `1w` etc. for listing recent memories
- **`/commit` skill:** Detect changes, generate conventional commit message, confirm with user, commit
- **`/standup` skill:** Standup summary from git history (24h), all open tasks, recent memories, reminders, and open PRs across registered projects via `gh`
- **`/work-history` skill:** Project-specific work history for today/yesterday/week from git log and memory
- **`/today` skill:** Daily overview dashboard — open tasks (all projects), reminders, recent activity, open PRs
- **`/status` skill:** Generate STATUS.md with project overview, tasks, recent work, and reminders
- **`/prs` skill:** List open PRs across all registered projects via `gh pr list`
- **`/projects` skill:** List all registered projects
- **Documentation:** Updated architecture (projects table schema, new CLI subcommands), skills reference (7 new skill sections), memory docs (tasks CLI reference, `--since` flag), and config CLAUDE.md (replaced explicit skills list with categorised summary — skills are auto-discovered)

## [0.7.0] — 2026-03-08

**Project tasks.**
Per-project task tracking with CLI tool, skills, and session start integration.

- **`mc-tool-tasks` CLI tool:** Subcommands `add`, `list`, `done`, `remove`, `check` with SQLite storage, project scoping by git root basename (falls back to cwd basename)
- **`/task` skill:** Add tasks via slash command (e.g. `/task Fix login bug`, `/task --priority high Fix auth race`); model-invocable so Claude can proactively suggest tasks during sessions (always asks before adding)
- **`/tasks` skill:** List open tasks for the current project with preprocessing
- **Session start hook:** Now surfaces open project tasks alongside overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `tasks.db` with `tasks` table indexed on `(project, status)`, priority ordering (high → medium → low), connection factory and migration system matching existing patterns
- **Test coverage:** 18 tests covering schema migrations, all CLI commands, project scoping, and priority ordering

## [0.6.0] — 2026-03-08

**Reflection system.**
Synthesise observations into durable insights with the new `/reflect` skill and reflection engine.

- **Reflection engine:** `mc-tool-memory reflect` reads last 7 days of memory entries + observation JSONL logs, calls Claude Haiku to identify patterns and themes, stores insights as `type=insight` (importance=6) in memory.db
- **`/reflect` skill:** Slash command with preprocessing — presents insights and proposes MEMORY.md additions for user approval
- **Novelty gate:** Skips reflection if fewer than 3 new observations since last reflection; overridable with `--min-new 0`
- **CLI flags:** `--days` (default 7) and `--min-new` (default 3) for controlling reflection scope
- **Shared LLM module:** Extracted `call_claude()` from observe hook into `src/mait_code/llm.py` — reused by both extraction and reflection
- **Refactored extractor:** `call_haiku` now delegates to shared `call_claude` with `model="haiku"`, `timeout=45`
- **Test coverage:** 15 new tests covering reflection logic, `_format_extraction`, `read_memory_md`, observation log edge cases, CLI output, and `call_haiku` delegation

## [0.5.0] — 2026-03-08

**Vector embeddings and shared logging.**
Added semantic search via vector embeddings and a shared logging system across all entry points.

- **Vector embeddings:** `nomic-ai/nomic-embed-text-v1.5` via `fastembed` (ONNX Runtime, no PyTorch) — 768-dimensional embeddings stored in sqlite-vec, auto-computed on memory write
- **Hybrid search:** New default search mode combining FTS5 keyword search with vector cosine similarity; `--mode` flag to select `hybrid`, `fts`, or `vector`; graceful degradation to FTS-only if embeddings unavailable
- **Reindex command:** `mc-tool-memory reindex` recomputes vector embeddings for all existing entries in batches of 64 (renamed from `rebuild`)
- **Restore command:** `mc-tool-memory restore` replays observation JSONL logs into the database (memories, entities, relationships), then reindexes embeddings; supports `--dry-run` to preview without writing
- **Stats updated:** `mc-tool-memory stats` now shows embedding coverage and model availability
- **Migration 7:** Recreates `memory_vec` at 768 dimensions (from placeholder 1536), adds delete trigger to keep vec in sync
- **Shared logging:** `src/mait_code/logging.py` with `setup_logging()` and `@log_invocation()` decorator — file-based rotating logs (`~/.claude/mait-code-data/logs/`), configurable via `MAIT_CODE_LOG_LEVEL` and `MAIT_CODE_LOG_FILE` env vars
- **All entry points wired:** `mc-tool-memory`, `mc-tool-reminders`, `mc-hook-session-start`, `mc-hook-observe`, `mc-hook-format` all log invocations with automatic parameter truncation for sensitive fields
- **settings.json:** Added `env` block with `MAIT_CODE_LOG_LEVEL` configuration
- **New dependency:** `fastembed>=0.4.0`
- **Bug fix:** Fixed Python 2 exception syntax in session_start hook (`except A, B:` → `except (A, B):`)

## [0.4.0] — 2026-03-08

**Entity system, observation hooks, and hooks reorganisation.**
Added knowledge graph entity tracking, automatic observation extraction from conversations, and reorganised hooks to follow the same package convention as tools.

- **Entity system:** `memory_entities` and `memory_relationships` tables (migrations 5–6) with CRUD operations — upsert, case-insensitive lookup, relationship tracking with mention counts
- **Observation hook:** Automatic knowledge extraction via Claude Haiku on `PreCompact` and `SessionEnd` — extracts facts, preferences, decisions, bugs, entities, and relationships from conversation transcripts
- **Async PreCompact hook:** Observation hook now runs asynchronously to avoid blocking the main conversation during context compaction
- **Hooks reorganisation:** All hooks now follow `hooks/<hook_name>/cli.py` package pattern (matching `tools/<tool_name>/cli.py`), eliminating the flat-file/submodule inconsistency
- **CLI commands:** Added `mc-tool-memory entities` and `mc-tool-memory relationships` subcommands for querying the knowledge graph
- **Cursor-based incremental extraction:** Only processes new transcript lines since last invocation, with automatic pruning of stale cursors (>30 days)
- **Updated conventions:** CLAUDE.md, docs, and pyproject.toml entry points updated to reflect new package structure

## [0.3.1] — 2026-03-07

**Replace reminders MCP server with CLI tool.**
Replaced the last MCP server (`mait-reminders`) with a sync CLI tool and skills, eliminating the `mcp` dependency entirely.

- **`mc-tool-reminders` CLI tool:** Subcommands `set`, `list`, `dismiss`, `check` with SQLite storage, dateparser for flexible time input, UTC normalization
- **`/remind` skill:** Set reminders via slash command (e.g. `/remind in 2 hours check deploy`)
- **`/reminders` skill:** List active and overdue reminders with preprocessing
- **Session start hook:** Now surfaces overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `reminders.db` with connection factory and migration system matching the memory tool patterns
- **Removed** `mait-reminders` MCP server, `src/mait_code/mcp/` directory, and `mcp[cli]` dependency
- **Restructured tests:** Mirror `src/mait_code/` directory structure (`tests/tools/memory/`, `tests/tools/reminders/`) with per-tool conftest fixtures

## [0.3.0] — 2026-03-06

**Replace memory MCP server with CLI tools + skills.**
Replaced the `mait-memory` MCP server with a sync CLI tool (`mc-tool-memory`) and three skills, eliminating process overhead and simplifying the architecture.

- **`mc-tool-memory` CLI tool:** Subcommands `search`, `store`, `list`, `delete`, `stats` — same functionality as the former MCP server, now invoked via Bash
- **`/recall` skill:** Uses preprocessing (`!`mc-tool-memory search ...``) to inject results before Claude sees the prompt — zero tool-call overhead
- **`/remember` skill:** Manual-only (`disable-model-invocation: true`) skill to store memories via slash command
- **`memory-store` skill:** Auto-invoked by Claude (`user-invocable: false`) to proactively store observations about the user
- **Removed** `mait-memory` MCP server (`src/mait_code/mcp/memory_server.py`) and its `settings.json` registration
- **Renamed** all entry points to `mc-{hook|tool|mcp}-*` convention (e.g. `mc-hook-session-start`, `mc-tool-reflect`)
- **Updated** all documentation to reflect the new architecture

## [0.2.0] — 2026-03-05

**Phase 1: Memory Core.**
Persistent memory system — the defining feature that makes this a companion, not a tool.

- **Database schema:** `memory_entries` table with FTS5 full-text search, vec0 virtual table (ready for vector search in Phase 2), automatic schema migrations via `ensure_schema()`
- **Connection factory:** `get_connection()` loads sqlite-vec, enables WAL mode, runs migrations; data dir configurable via `MAIT_CODE_DATA_DIR`
- **Composite scoring:** `score = 0.3 × recency + 0.3 × importance + 0.4 × relevance` with exponential decay (episodic: 3-day half-life, semantic: 90-day half-life)
- **Memory writer:** Deduplication via FTS5 candidate retrieval + SequenceMatcher ≥ 0.90 similarity; on duplicate updates timestamp and keeps max importance
- **Keyword search:** FTS5 BM25 ranking with LIKE fallback, listing by recency, deletion by ID
- **MCP memory server:** Five tools — `search_memory`, `store_memory`, `list_recent_memories`, `delete_memory`, `memory_stats`
- **`/recall` skill:** Slash command to search memory for past facts, decisions, and patterns
- **Test suite:** 70 tests covering migrations, scoring, writer, search, and MCP server
- **Docs:** Updated architecture (schema, scoring formula, dedup algorithm, MCP tool reference), development guide (memory module structure, migration guide, test patterns), skills reference, setup verification steps

## [0.1.0] — 2026-03-04

**Phase 0: Foundation.**
Initial project scaffold establishing the core structure and tooling.

- **Packaging:** uv/hatchling build system with Python 3.13+, dependencies on `mcp`, `sqlite-vec`, `dateparser`, `pyyaml`
- **Hooks:** Stub entry points for `session_start`, `observe`, and `auto_format` hooks
- **MCP servers:** Stub `memory_server` and `reminders_server`
- **CLI tools:** Stub `reflect` and `rebuild_db` commands
- **Identity:** Soul document and user context templates adapted from the mait gateway
- **Config:** Global `CLAUDE.md` with companion behaviour rules, `settings.json` with hook and MCP server registrations
- **Scripts:** `install.sh` and `uninstall.sh` for automated setup/teardown
- **Docs:** Architecture overview, philosophy, setup guide, skills reference, multi-machine sync guide, and development guide

## [0.0.0] — 2026-03-04

**Init.**
Repository initialised with README.


[Unreleased]: https://github.com/wiktordepina/mait-code/compare/v0.58.0...HEAD
[0.58.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.58.0
[0.57.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.57.0
[0.56.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.56.0
[0.55.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.55.0
[0.54.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.54.0
[0.53.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.53.0
[0.52.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.52.0
[0.51.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.51.0
[0.50.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.50.0
[0.49.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.49.0
[0.48.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.48.0
[0.47.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.47.0
[0.46.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.46.1
[0.46.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.46.0
[0.45.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.45.1
[0.45.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.45.0
[0.44.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.44.0
[0.43.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.43.0
[0.42.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.42.0
[0.41.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.41.0
[0.40.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.40.1
[0.40.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.40.0
[0.39.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.39.0
[0.38.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.38.0
[0.37.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.37.1
[0.37.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.37.0
[0.36.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.36.0
[0.35.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.35.0
[0.34.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.34.1
[0.34.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.34.0
[0.33.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.33.0
[0.32.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.32.0
[0.31.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.31.0
[0.30.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.30.0
[0.29.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.29.1
[0.29.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.29.0
[0.28.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.28.0
[0.27.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.27.0
[0.26.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.26.0
[0.25.4]: https://github.com/wiktordepina/mait-code/releases/tag/v0.25.4
[0.25.3]: https://github.com/wiktordepina/mait-code/releases/tag/v0.25.3
[0.25.2]: https://github.com/wiktordepina/mait-code/releases/tag/v0.25.2
[0.25.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.25.1
[0.25.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.25.0
[0.24.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.24.0
[0.23.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.23.0
[0.22.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.22.1
[0.22.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.22.0
[0.21.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.21.0
[0.20.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.20.0
[0.19.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.19.1
[0.19.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.19.0
[0.18.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.18.0
[0.17.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.17.0
[0.16.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.16.0
[0.15.5]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.5
[0.15.4]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.4
[0.15.3]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.3
[0.15.2]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.2
[0.15.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.1
[0.15.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.0
[0.14.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.14.1
[0.14.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.14.0
[0.13.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.13.0
[0.12.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.12.1
[0.12.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.12.0
[0.11.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.11.0
[0.10.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.10.0
[0.9.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.9.0
[0.8.2]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.2
[0.8.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.1
[0.8.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.0
[0.7.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.7.0
[0.6.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.6.0
[0.5.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.5.0
[0.4.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.4.0
[0.3.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.3.1
[0.3.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.3.0
[0.2.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.2.0
[0.1.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.1.0
[0.0.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.0.0
