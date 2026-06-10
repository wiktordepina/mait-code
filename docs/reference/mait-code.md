# `mait-code` command reference

The `mait-code` binary owns the install lifecycle. It's installed via
`uv tool install` from the local source — the bash shim
(`scripts/install.sh`) handles that bootstrap step the first time.
After that, everything goes through the CLI.

Run bare on a terminal — `mait-code` with no subcommand — it opens the
[home hub](../home.md), the companion's front door; piped or redirected it
prints this help instead. The subcommands below are the rest of the surface.

This page documents every subcommand: synopsis, flags, behaviour,
examples, exit codes.

## Conventions

| Convention | Meaning |
|------------|---------|
| `<value>` | Required positional or option argument the user supplies. |
| `[--flag]` | Optional flag. |
| `--claude-dir <path>` | Override `~/.claude` (useful for tests and non-default layouts). Accepted by install / update / uninstall / status / doctor. |
| `--data-dir <path>` | Override `~/.claude/mait-code-data`. Accepted by install / uninstall / status / doctor. |
| `--no-color` | Disable coloured output. A global flag (`mait-code --no-color doctor`); colour is also dropped automatically off a TTY and under `NO_COLOR` / `TERM=dumb`. |

Every subcommand also accepts `--help` and prints a one-screen summary.

## Install record

The CLI persists state at `~/.local/share/mait-code/install.json`
(XDG-aware — honours `$XDG_DATA_HOME`). It is:

- Created by `install`.
- Updated by `update` (version + timestamp).
- Read by `update`, `uninstall`, `status`, `doctor`, `settings` (the
  recorded embedding provider drives `settings`' drift check).
- Removed by `uninstall`.

Schema (`schema_version: 1`):

```json
{
  "source_dir": "/home/wiktor/projects/mait-code",
  "version": "0.14.1",
  "embedding_provider": "local",
  "installed_at": "2026-05-27T10:00:00+00:00",
  "schema_version": 1
}
```

A binary refuses to read a record whose `schema_version` exceeds what
it understands — the error message points at `mait-code update` as the
recovery path.

---

## `mait-code install`

**Synopsis**

```
mait-code install --from <path> [--embedding-provider local|bedrock]
                  [--data-dir <path>] [--claude-dir <path>]
```

**Description**

First-time setup. Validates the source path is a mait-code clone,
creates data directories, copies templates, sets up symlinks
(`CLAUDE.md`, `skills/*`, `agents/*`), merges `settings.json`, and
writes the install record.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--from <path>` | *(required)* | Absolute path to the cloned mait-code source tree. |
| `--embedding-provider <name>` | `local` | `local` (fastembed) or `bedrock` (AWS Bedrock; install with `[bedrock]` extra). |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Verifies `<source>/pyproject.toml` exists with `name = "mait-code"` and `<source>/src/mait_code/` is a directory.
2. Creates `<data-dir>/memory/observations/` and `<data-dir>/memory/reflections/`. (`memory/graph/` is intentionally not created.)
3. Copies `templates/soul_document.md` and `templates/user_context.md` into the data dir — **never overwrites** existing files.
4. Writes a `MEMORY.md` stub into `<data-dir>/memory/` if missing.
5. Symlinks `<source>/config/CLAUDE.md` to `<claude-dir>/CLAUDE.md`. If a non-symlink `CLAUDE.md` already exists, it's first renamed to `CLAUDE.md.backup`.
6. Symlinks each `<source>/skills/<name>/` into `<claude-dir>/skills/` and each `<source>/agents/<file>` into `<claude-dir>/agents/`. `.gitkeep` placeholders are skipped.
7. Merges `<source>/config/settings.json` into `<claude-dir>/settings.json` (hooks, mcpServers, and `MAIT_CODE_EMBEDDING_PROVIDER` env). User-set keys are preserved verbatim. The write is atomic (tempfile + rename).
8. Writes the install record.

**Examples**

```bash
# Standard install from a local clone:
mait-code install --from "$PWD"

# Bedrock-backed install with a non-default data directory:
mait-code install --from /opt/mait-code/source \
                  --embedding-provider bedrock \
                  --data-dir /var/lib/mait-code
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Install succeeded. |
| `1` | `<source>` is not a mait-code clone, or `--embedding-provider` is not one of `local` / `bedrock`. |

**Notes**

- This subcommand does **not** run `uv tool install`. By the time it
  runs, the `mait-code` binary is already on PATH (that's how it was
  invoked). The bash shim handles the bootstrap.
- Re-running `install` is safe — it's idempotent. Symlinks that
  already point at the right target are left alone; templates are
  never overwritten.

---

## `mait-code update`

**Synopsis**

```
mait-code update [--no-pull] [--ref <tag|branch|sha>] [--force] [--claude-dir <path>]
```

**Description**

Advance the source tree to the right ref and — only if `HEAD` actually moved — reinstall via `uv tool install`, then refresh symlinks and settings and bump the install record. A repeated update with nothing new upstream is a cheap no-op: the reinstall is skipped rather than rebuilding every package.

How the source is advanced depends on its current state — a bootstrap install pins to a release **tag** (detached HEAD), while a local-clone dev install sits on a **branch**:

- `--ref <X>` given → checkout `X`.
- On a branch → fast-forward it (`git merge --ff-only`).
- Detached HEAD (typical post-bootstrap) → checkout the latest `v*` tag.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--no-pull` | off | Skip the network fetch and branch fast-forward; reinstall from whatever is currently checked out. `--ref` still checks out a local ref. |
| `--ref <ref>` | *(none)* | `git checkout <ref>` (after a fetch unless `--no-pull`). Pins to a tag/branch/sha. |
| `--force` | off | Reinstall even when the source `HEAD` did not move — e.g. to rebuild uncommitted working-tree edits on a dev checkout. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Reads the install record. Aborts with exit `1` if missing.
2. Verifies the recorded source dir still looks like a mait-code clone.
3. Unless `--no-pull`: `git fetch origin --tags --prune`.
4. Advance to the target ref:
    - `--ref` given → `git checkout <ref>`.
    - on a branch → `git merge --ff-only` (skipped under `--no-pull`).
    - detached HEAD → `git checkout <latest v* tag>`. Aborts if there are no tags and no `--ref`.
5. If `HEAD` moved during step 4 (or `--force` was given): `uv tool install <source>[<extra>] --force --reinstall-package mait-code --python 3.13`. `--reinstall-package mait-code` forces a rebuild of just the local source — whose version does not bump between commits — while leaving unchanged third-party deps in place. The `[bedrock]` extra is applied when the install record records the bedrock provider. If `HEAD` did not move and `--force` was not given, this step is skipped.
6. Re-runs the symlink and settings-merge steps from `install` (picks up new skills, settings.json changes). These run even when the reinstall is skipped.
7. Rewrites the install record with the new version and timestamp.

**Examples**

```bash
# Standard update — fetch, advance to latest tag (or fast-forward
# branch), reinstall, refresh:
mait-code update

# Pin to a specific release tag:
mait-code update --ref v0.14.1

# Reinstall from the current checkout without touching git:
mait-code update --no-pull

# Force a rebuild even when nothing moved (e.g. uncommitted dev edits):
mait-code update --no-pull --force
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Update succeeded. |
| `1` | No install record, source dir no longer valid, detached HEAD with no `v*` tags (and no `--ref`), or any subprocess (`git`, `uv`) failed. |

---

## `mait-code uninstall`

**Synopsis**

```
mait-code uninstall [--purge-data] [--keep-uv-tool]
                    [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Reverse the install footprint. Removes symlinks, strips mait-code
entries from `settings.json`, runs `uv tool uninstall mait-code`,
deletes the install record. Preserves the data directory by default.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--purge-data` | off | Also delete the data directory (memories, personalised soul / user-context files). Destructive. |
| `--keep-uv-tool` | off | Skip `uv tool uninstall mait-code` (useful when temporarily downgrading or switching extras). |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Reads the install record (best-effort — missing record is a warning, not an error).
2. Removes `<claude-dir>/CLAUDE.md` if it's a symlink pointing into the recorded source. Restores `CLAUDE.md.backup` if present.
3. Removes skill symlinks under `<claude-dir>/skills/` that resolve into the recorded source. Foreign symlinks (e.g. from other tools) are preserved.
4. Same for agents.
5. Cleans mait-code-owned entries from `<claude-dir>/settings.json` (hook commands with the `mc-hook-` prefix; legacy `mait-reminders` MCP server; the `MAIT_CODE_EMBEDDING_PROVIDER` env). Empty top-level sections are dropped.
6. `uv tool uninstall mait-code` (unless `--keep-uv-tool`). Failure here is a warning — the binary may already be gone.
7. With `--purge-data`: deletes the data directory.
8. Deletes the install record.

**Examples**

```bash
# Standard uninstall — keeps memories and personalised files:
mait-code uninstall

# Full wipe (data dir too):
mait-code uninstall --purge-data

# Downgrade to an older release without losing settings:
mait-code uninstall --keep-uv-tool
uv tool install mait-code --version 0.14.0
mait-code install --from /path/to/old-source
```

**Exit codes**

`0` always. Uninstall is best-effort; missing components produce
warnings on stderr, not non-zero exit. If you need failure on broken
state, run `mait-code doctor` first.

---

## `mait-code status`

**Synopsis**

```
mait-code status [--json] [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Read-only summary of the current install. Always exits `0` — there's
no diagnostic intent here, just a report. The text output is grouped
into sections under a one-line health badge (`healthy` / `degraded` /
`not installed`); `degraded` flags fixable oddities such as an unlinked
`CLAUDE.md`, with a git-style hint on how to fix them.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit a machine-readable JSON document instead of human-readable text. The JSON shape is stable and independent of the text grouping. |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Reports**

| Group | Fields |
|-------|--------|
| Header | Version and a health badge: `healthy`, `degraded`, or `not installed`. |
| Install | `source_dir`, the resolved `mait-code` binary path, install date |
| Identity | `CLAUDE.md` symlink status, and presence of `soul_document.md` / `user_context.md` / `memory/MEMORY.md` |
| Components | Linked / available skills and agents; registered hook events |
| Memory | Embedding provider; data-dir path and humanised size |

**Examples**

```bash
mait-code status
mait-code status --json | jq '.embedding_provider'
```

**Exit code:** always `0`.

---

## `mait-code doctor`

**Synopsis**

```
mait-code doctor [--fix] [--json] [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Validate the install. Surfaces silent breakage — broken symlinks,
unparseable settings, hook commands missing from PATH. Exits `1` if
any check reports a `fail`-level finding, `0` otherwise. Each failing or
warning check carries the exact command or URL to fix it, and the run
ends with a one-line pass/fail verdict. The `--json` output includes a
`fix_hint` field per check.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--fix` | off | Apply safe fixes for findings that support it. |
| `--json` | off | Emit a machine-readable JSON document. |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Checks**

| Name | Levels | Description |
|------|--------|-------------|
| `install-record` | ok / fail | Record exists and parses at the expected schema version. |
| `source-dir` | ok / warn / fail | The recorded source still exists and looks like a mait-code clone. `warn` when there's no record to validate against. |
| `settings-values` | ok / fail | Every setting's value is valid for its type and range, and cross-field invariants hold (the scoring weights must sum to `1.0`). `fail` lists each offending value. |
| `settings` | ok / warn / fail | `<claude-dir>/settings.json` parses as JSON. `warn` if missing. |
| `hooks-on-path` | ok / warn / fail | Every registered hook with the `mc-hook-` prefix resolves on `PATH`. |
| `symlinks` | ok / warn | No dangling symlinks under `<claude-dir>/skills/` or `<claude-dir>/agents/`. Dangling links are a **warning** (auto-fixable, so they don't fail the run); `--fix` removes them. |
| `data-dir` | ok / fail | The data dir exists and is writable. With `--fix`, creates it (plus the `memory/observations` and `memory/reflections` subdirs) if missing. |
| `memory-embeddings` | ok / warn | Every live memory entry carries a vector. Entries stored while the embedding provider was unavailable are invisible to semantic search; `warn` reports the count and points at `mc-tool-memory reindex`. With `--fix`, embeds just the missing entries — existing vectors are left alone (progress goes to stderr, so `--json` output stays parseable); if the embedding provider can't run, the warning stands and reports why. |
| `vector-search` | ok / warn | The sqlite-vec extension loads and the vector table is queryable. `warn` means recall silently degrades to keyword-only search; the message names the configured embedding provider and model. |
| `observe-pipeline` | ok / warn | The observe hook has recorded a capture recently. `warn` when the newest capture is over 7 days old, or when a memory database exists but the hook has never captured anything. |
| `uv-on-path` | ok / fail | `uv` is on `PATH` — required for `install` / `update`. |

**Examples**

```bash
mait-code doctor                       # diagnose
mait-code doctor --fix                 # diagnose and clean up safe findings
mait-code doctor --json | jq '.checks[] | select(.level=="fail")'
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No `fail`-level findings (warnings are allowed). |
| `1` | One or more checks reported `fail`. |

---

## `mait-code settings`

**Synopsis**

```
mait-code settings                          # interactive editor (TTY) / list (piped)
mait-code settings list [--json]            # read-only, provenance-aware view
mait-code settings get <key> [--json]       # one resolved value + source
mait-code settings set <key> <value> [flags]
```

**Description**

View and edit the active configuration. Bare `mait-code settings` opens a
full-screen editor (a [Textual](https://textual.textualize.io/) TUI) when
attached to a terminal, and falls back to the read-only view (`list`) when
piped or redirected, so scripts are unaffected. Every write — from `set` or
the editor — goes through one shared path: validate → persist
`settings.toml` → keep `settings.json` in step → run the required follow-up.

### The interactive editor

A master–detail layout: the settings list on the left, an inline edit form
on the right that adapts to the highlighted setting — a radio set for enums
(`embedding-provider`, `log-level`), a text input with live validation for
everything else, and a read-only view for derived values. The three scoring
weights collapse into one **grouped** row whose editor retunes all three at
once and only enables *Apply* when they sum to `1.0`. Migration and
`data-dir` changes confirm their follow-up in a modal; a re-embed drops out
to the terminal so `reindex` prints its normal progress, then returns.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move between settings |
| `Ctrl+S` / `Enter` | Apply the edit (or open the grouped weight editor) |
| `q` | Quit |

### `settings list`

Read-only view of every knob the framework reads, with its resolved value
and *source*. Modelled on `aws configure list`. Always exits `0`: it
*reports* configuration, it doesn't validate it (that's `doctor`'s job, via
the `settings-values` check).

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit a machine-readable JSON document instead of text. |

| Column | Meaning |
|--------|---------|
| `SETTING` | The knob (see the groups below). |
| `VALUE` | The resolved value (`default` values are dimmed). |
| `SOURCE` | `env`, `settings` (the TOML file), `default`, or `derived` (computed, read-only). Migration-sensitive knobs are marked `⚠`. |

Settings fall into three groups:

- **Primary** — written uncommented in `settings.toml`: `data-dir`, `log-level`, `log-file`, `embedding-provider`, `embedding-model`, `bedrock-model-id`, `bedrock-region`.
- **Advanced** — written commented-out (the built-in default applies until you opt in via `set` or by uncommenting): `log-backup-count`, `extraction-model`, `reflection-model`, `llm-timeout`, `reflection-batch-size`, `reflection-novelty-gate`, `git-timeout`, and the scoring/dedup tuning knobs `score-weight-recency`, `score-weight-importance`, `score-weight-relevance`, `half-life-episodic`, `half-life-semantic`, `dedup-string-threshold`, `dedup-vector-threshold`, `dedup-conflict-threshold`, `scope-boost-global`, `scope-boost-cross-project`.
- **Derived** (source `derived`, not settable): `embedding-dim`, `memory-db-path`, `reminders-db-path`, `model-cache-dir`, `observations-dir`, `project-aliases-path`.

See the [Memory guide](../memory.md) for per-setting defaults and the scoring/dedup tuning ranges.

### `settings get`

Print one resolved value and its source, for scripting. `--json` emits
`{"key", "value", "source"}`. Exits `1` on an unknown key.

### `settings set`

Validate `<value>` against the same rules `doctor` runs, write it to
`settings.toml`, then run the required follow-up. Validation reuses each
setting's own validator (and enum `choices`, e.g. `embedding-provider` ∈
{`local`, `bedrock`}, `log-level` ∈ {`DEBUG`, `INFO`, `WARNING`,
`ERROR`}).

| Flag | Default | Description |
|------|---------|-------------|
| `--reindex` / `--no-reindex` | unset | For a migration key: re-embed memories now, or defer. |
| `--move-data` / `--no-move-data` | unset | For `data-dir`: relocate existing data, or leave it in place. |

Follow-ups by key:

| Key(s) | Follow-up | Flag (required) |
|--------|-----------|-----------------|
| `embedding-provider`, `embedding-model`, `bedrock-model-id` | re-embed stored memories (rebuild the vector table) | `--reindex` / `--no-reindex` |
| `data-dir` | move the existing data directory to the new path | `--move-data` / `--no-move-data` |
| everything else | none — applies on the next invocation | — |

For migration keys and `data-dir`, omitting the flag is an error that
explains the destructive follow-up rather than guessing. The three scoring
weights (`score-weight-*`) are **rejected** by `set` — they must sum to
`1.0`, so changing one alone would leave an invalid file; use the
interactive editor (which retunes all three at once) or edit `settings.toml`
directly (`doctor` validates the result).

**Env shadowing.** Resolution is env → file → default. `set` keeps an
**already-mirrored** `MAIT_CODE_*` key in `~/.claude/settings.json` in step
with the TOML, so the value `install` mirrored there (e.g.
`embedding-provider`) can't silently shadow your change. It never *adds*
keys to `settings.json`. If a shell export still overrides the new value,
`set` warns precisely and names the variable to unset.

**Examples**

```bash
mait-code settings                                  # edit interactively
mait-code settings list --json | jq '.settings[] | select(.source == "env")'
mait-code settings get embedding-provider
mait-code settings set log-level DEBUG
mait-code settings set embedding-provider bedrock --reindex
mait-code settings set data-dir ~/mait-data --move-data
```

**Exit codes:** `list`/bare always `0`; `get` and `set` exit `1` on an
unknown key, invalid value, or a missing required follow-up flag.

---

## `mait-code board`

**Synopsis**

```
mait-code board                             # interactive kanban (TTY) / text render (piped)
```

**Description**

Open the project kanban board. Attached to a terminal, it launches a
full-screen [Textual](https://textual.textualize.io/) TUI; when piped or
redirected it falls back to a read-only text render, so scripts and the
session-start summary are unaffected.

The board has a single fixed workflow shared by every project — the columns
are not configurable. Cards flow left-to-right through four visible columns:

| Column | Status | Meaning |
|--------|--------|---------|
| Backlog | `backlog` | Captured, not yet refined. |
| Refined | `refined` | Scoped and ready to pick up. |
| In Progress | `in_progress` | Being worked on. |
| Done | `done` | Completed. |

A fifth status, `archived`, is hidden from the board by default (toggle it
into view with `a` in the TUI).

`blocked` is **not** a column — it is a free-form *tag* carried in place, so a
blocked card keeps its real flow position. Blocking is the first consumer of a
general tagging system (`tag` / `untag` on the CLI, `t` in the TUI).

### The interactive board

A column-per-status layout you navigate by card. Movement keys reslot the
highlighted card; the rest open detail, annotate, tag, or change what's shown.

| Key | Action |
|-----|--------|
| `←` / `→` | Move focus between columns |
| `<` / `>` | Move the highlighted card to the previous / next column |
| `Enter` | Open the card detail view |
| `c` | Add a comment to the highlighted card |
| `t` | Toggle a tag on the highlighted card (type the tag; present → removed, absent → added) |
| `b` / `u` | Add / remove the `blocked` tag on the highlighted card (in place) |
| `p` | Filter by project (dropdown picker) |
| `a` | Toggle visibility of archived cards |
| `r` | Reload the board from the database |
| `q` | Quit |

### The non-TTY render

Off a TTY, the board prints every project's cards grouped by column in
board order, skipping empty columns:

```
Backlog (5):
  [#12] (high) Wire up the reflection batch gate [mait-code]
  ...

In Progress (1):
  [#9] (med) Document the board subcommand [mait-code]
```

Each line is `[#<id>] (<priority>) <title> [<project>]`. When there are no
cards at all it prints `No cards on the board.`

**Examples**

```bash
mait-code board            # drive the board interactively
mait-code board | cat      # plain text render (e.g. for piping or logs)
```

**Exit code:** always `0`.

> The board is also reachable mid-session through the `board` skill — see
> [Skills](skills.md). The CLI tool behind both is `mc-tool-board`.

---

## `mait-code observations`

**Synopsis**

```
mait-code observations                      # interactive browser (TTY) / text summary (piped)
```

**Description**

Browse the raw extraction tier — what the observe hook has captured that
reflection hasn't yet synthesised. Attached to a terminal it launches a
full-screen [Textual](https://textual.textualize.io/) TUI: observations
grouped by capture day, each flagged **pending** or **reflected** against the
reflection watermark, with the selected one rendered in full. Piped or
redirected it falls back to a read-only day-grouped summary.

The browser is read-only — it never reflects, edits or deletes. See the
[observations browser guide](../observations.md) for the full tour.

### The interactive browser

| Key | Action |
|-----|--------|
| `↑` / `↓` | Move the highlight; the detail pane follows |
| `Enter` / `Space` | Expand or collapse a day |
| `/` | Focus the live content filter |
| `p` | Filter by project (dropdown picker) |
| `Esc` | Back to the tree; from the tree, quit |
| `r` | Reload from the database |
| `q` | Quit |

### The non-TTY render

Off a TTY, the command prints the pending tally and each day's entries,
pending marked `●` and reflected `·`:

```
Observations: 12 pending of 87

2026-06-09 (5 pending of 5):
  ● [#1873] event Board snapshots failing on version bump …
  …
```

When the store is empty it prints `No observations yet.`

**Examples**

```bash
mait-code observations         # audit the backlog interactively
mait-code observations | head  # quick pending check (e.g. for piping or logs)
```

**Exit code:** always `0`.

---

## `mait-code home`

**Synopsis**

```
mait-code home                              # interactive hub (TTY) / text summary (piped)
mait-code                                   # bare invocation — same hub on a TTY
```

**Description**

Open the companion's home hub — a navigable map over the board, memory,
reminders, the quick-capture inbox, the identity stack, and the install's
health. Attached to a terminal it launches a full-screen
[Textual](https://textual.textualize.io/) TUI; piped or redirected it prints a
compact text summary instead.

A bare `mait-code` with no subcommand is the same front door: it opens the hub
on a TTY and falls back to the root help when piped, so scripts and
`mait-code | grep` are unaffected.

The hub is read-only — it never writes a store or shells out. It renders the
same data the `mc-tool-*` CLIs and skills work from, so it always reflects the
real state. See the [home hub guide](../home.md) for the full tour.

### The interactive hub

A tree of sections down the left (Board, Memory, Reminders, Inbox, Identity,
System), each carrying a live status badge; the highlighted section renders in
full on the right.

| Key | Action |
|-----|--------|
| `↑` / `↓` (or `k` / `j`) | Move the highlight; the detail pane follows |
| `Enter` | Toggle a section, or open a TUI from a `↗ Open …` launch leaf |
| `r` | Reload every store (refresh the badges and current detail) |
| `Ctrl+P` | Command palette (Open board / memory / observations / settings, Reload, themes) |
| `q` / `Esc` | Quit |

Pressing `Enter` on a launch leaf (`↗ Open board`, `↗ Open memory browser`,
`↗ Open observations`, `↗ Open settings`) hands off to that dedicated TUI and
returns to the hub when it quits, with the badges refreshed.

### The non-TTY render

Off a TTY, `mait-code home` prints a one-block summary of each store:

```
Board:
  mait-code: 1 in progress · 1 refined
Reminders: 1 overdue · 0 upcoming
Inbox: 1
Memory: 128 entries · 0 unembedded · 3 unreflected
```

**Examples**

```bash
mait-code                  # open the hub — the front door
mait-code home             # the same, explicitly
mait-code home | cat       # plain text summary (e.g. for piping or logs)
```

**Exit code:** always `0`.

---

## `mait-code version`

**Synopsis**

```
mait-code version
```

**Description**

Print the installed `mait-code` package version (from
`importlib.metadata`). Falls back to `mait_code.__version__` when
running from a checkout that hasn't been `uv tool install`ed.

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Version printed. |
| `1` | Neither metadata nor in-tree `__version__` could be read. |

---

## See also

- [Setup](../setup.md) — first-time install walkthrough using the bash shim.
- [Skills](skills.md) — slash commands available inside a Claude Code session.
- [Python API → CLI](cli.md) — the helpers that power these subcommands (for contributors / extension authors).
