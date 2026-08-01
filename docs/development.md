# Development Guide

## Setup

```bash
git clone https://github.com/wiktordepina/mait-code.git
cd mait-code
uv sync
```

## Tests

```bash
uv run pytest          # run the full suite
uv run pytest -v       # verbose
uv run pytest tests/tools/memory/   # narrow to a package
```

The suite covers every package under `src/mait_code/` (close to two thousand
tests and growing). Fixtures live in tool-specific `tests/<area>/conftest.py`
files; the root `tests/conftest.py` keeps cross-cutting setup. See the "Writing
Tests for Memory Components" section below for the established patterns.

`tests/test_imports.py` is the smoke test that asserts every reference-surface
module declares a non-empty `__all__`. CI's `ci.yml` runs the full suite on every
PR, plus a weekly scheduled run at 06:00 Monday — there is no push trigger. The
test job gates on coverage (`pytest --cov-fail-under=93`, a backstop set a couple
of points below the working baseline), and a separate `audit` job runs
`pip-audit --strict` over the exported locked requirements.

### Snapshot tests

The TUIs are guarded by `pytest-textual-snapshot`: a test renders an app at a
fixed terminal size and compares it against an accepted baseline under
`tests/cli/__snapshots__/`. Regenerate baselines intentionally — and eyeball the
change — after a deliberate visual edit:

```bash
uv run pytest tests/cli/test_board_tui_snapshot.py --snapshot-update
```

Keep snapshots deterministic: pin `terminal_size`, seed fixed data, and
neutralise anything environment-dependent (e.g. the settings snapshot clears
`MAIT_CODE_*` so every row resolves to its default source). `MaitApp` applies
`mait-dark` as the default, so there's no need to pin it.

## Linting, formatting, typechecking

```bash
uv run ruff check src/ tests/          # Lint
uv run ruff format src/ tests/         # Format
uv run pyright                         # Typecheck (standard mode, src/ only)
```

Both ruff commands cover `src/` and `tests/` — that's what CI runs, so narrowing
them to `src/` will pass locally and fail on the PR.

Pyright reads the optional `boto3` import in `tools/memory/embeddings.py`,
so the bedrock extra must be installed for typechecking. Sync the extra and the
docs group together:

```bash
uv sync --extra bedrock --group docs
```

A bare `uv sync`, or `uv sync --group docs` on its own, *uninstalls* `boto3` and
re-breaks the typecheck. The CI typecheck job (`ci.yml`) handles this itself.

## Project Conventions

- **Use `uv run` everywhere** — Never activate venvs manually
- **Entry points in pyproject.toml** — All CLI commands are registered as `[project.scripts]`
- **Data dir via env var** — Use `MAIT_CODE_DATA_DIR` (defaults to `~/.claude/mait-code-data/`)
- **No asyncio in CLI tools** — Tools and hooks are synchronous; MCP servers (if any) use async
- **Connections via `get_connection()`** — All memory modules use the shared connection factory
- **Package convention** — Both hooks and tools use `<name>/cli.py` as the entry point containing `main()`

## Memory Module Structure

```
src/mait_code/tools/memory/
├── __init__.py    # Public API re-exports
├── cli.py         # CLI entry point (mc-tool-memory)
├── db.py          # Connection factory (get_connection, get_data_dir)
├── migrate.py     # Schema migrations (ensure_schema)
├── scoring.py     # Composite scoring (pure functions, no DB)
├── search.py      # FTS5 keyword, vector, and hybrid search + list + delete
├── writer.py      # Store with deduplication + auto-embedding, supersede/retire/merge
├── entities.py    # Entity and relationship CRUD
├── embeddings.py  # Embedding providers (local fastembed / AWS Bedrock, lazy-loading, graceful degradation)
├── reflect.py     # Observation synthesis — insights, MEMORY.md proposals
├── review.py      # Review resurfacing — the decayed-memory due queue
├── observations.py # Query layer over the raw extraction tier
├── native.py      # Claude Code's own auto-memory files, read-only
└── stats.py       # Counts by type, class, scope, and embedding coverage
```

**Dependency order:** `migrate.py` ← `db.py` ← everything else. `scoring.py` has no internal dependencies. `embeddings.py` depends only on `db.py` (for data dir).

**Pattern:** All search/writer/entity functions receive a `sqlite3.Connection` as their first argument. The CLI tool opens and closes connections per subcommand invocation.

## TUI Layer

The Textual TUIs share one identity through `src/mait_code/tui/`:

```
src/mait_code/tui/
├── __init__.py    # Re-exports palette only (kept Textual-free)
├── palette.py     # Canonical role→hex colours — the single source of truth
├── theme.py       # The mait-* house Textual Themes, built from palette
├── render.py      # Palette-coloured Rich chip helpers (for DataTable/OptionList cells)
├── brand.py       # Wordmark, signature glyph, companion-voice helpers (Textual-free)
├── banner.py      # BrandBanner — the size-responsive masthead every TUI wears
├── help.py        # Shared `?` HelpScreen (live key-binding cheat-sheet)
├── confirm.py     # Shared confirmation modal
├── filters.py     # Shared pick-one filter modals (generic + project-flavoured)
├── markdown.py    # Markdown rendering helpers for detail panes
├── app.py         # MaitApp base class + SHARED_TCSS path
└── app.tcss       # Shared stylesheet (modal geometry, conventions)
```

**Dependency order:** `palette.py` ← `theme.py` ← `app.py`; `render.py` and
`help.py` sit on top of `palette.py`/`app.py` respectively. The one hard rule:
**`palette.py` imports nothing from Textual or the rest of `mait_code`.** It
sits on the CLI hot path — `console.py` imports it to colour plain output — so
pulling Textual in there would slow every CLI invocation. `theme.py` and
`app.py` *do* import Textual; import those submodules directly
(`from mait_code.tui.app import MaitApp`), never via the package, so that
`import mait_code.tui` stays cheap.

**One palette, two consumers.** `palette.py` is the single source of truth for
both the Rich CLI theme (`console.py`) and the Textual TUI theme (`theme.py`),
so plain CLI output and the TUIs share a colour identity. Tune a colour once and
both follow. Every value clears WCAG AA (≥4.5:1) against the dark backgrounds.

**Theming model.** `MaitApp` registers the five house themes in `HOUSE_THEMES`
(`mait-dark`, `mait-bubblegum`, `mait-aurora`, `mait-ember`, `mait-syntax`),
defaults to `mait-dark`, and leaves Textual's built-in themes registered — so the
Ctrl+P command palette's "Change theme" offers all of them. A user's pick is
persisted across sessions via the `theme` setting (`MAIT_CODE_THEME`), so the TUIs
reopen in the last-chosen theme. Because every style is driven off `$`-variables,
adding a house theme is just another `Theme` in `theme.py`; a user can also drop in
their own theme file and it works mechanically, though only the house themes are
maintained.

## Logging

All entry points use the shared logging module at `src/mait_code/logging.py`.

### Log format

Logs are structured JSON Lines — one JSON object per line, with a deterministic, ECS-inspired schema. Core fields on every line:

| Field | Content |
|-------|---------|
| `ts` | Epoch seconds as a float (cast to a timezone at the presentation layer) |
| `level` | `debug` / `info` / `warning` / `error` (lowercase) |
| `logger` | Logger name with the `mait_code.` prefix stripped |
| `msg` | The rendered message |
| `tool` | Entry-point name (e.g. `mc-tool-board`), captured at `setup_logging()` |
| `pid` | Process id |

Invocation events (emitted by `@log_invocation`) add `event` (`invoked` / `completed` / `failed` / `exited`), `duration_ms`, and `args` (the parsed parameters, with sensitive values truncated). Exceptions add `error_type`, `error_message`, and `stack` (the traceback as a single string — every line stays one JSON object).

Call sites can attach structured fields via `extra`:

```python
logger.info("memory stored", extra={"memory_id": 42, "store": "semantic"})
```

Extra fields merge into the line at top level; core fields win on collision.

### Adding logging to a new component

```python
from mait_code.logging import log_invocation, setup_logging

@log_invocation(name="mc-tool-mycommand")
def main():
    setup_logging()
    # ... your code here
```

For internal modules, use standard `logging.getLogger(__name__)`:

```python
import logging
logger = logging.getLogger(__name__)

def my_function():
    logger.debug("Processing...")
```

The `mait_code` logger hierarchy is configured by `setup_logging()` in the entry point — internal modules don't need to call it.

### SSL setup for network-calling entry points

Entry points that make outbound HTTPS requests (e.g. embedding model downloads, API calls) should also call `setup_ssl()` after `setup_logging()`:

```python
from mait_code.logging import log_invocation, setup_logging

@log_invocation(name="mc-tool-mycommand")
def main():
    setup_logging()

    from mait_code.ssl import setup_ssl
    setup_ssl()

    # ... your code here
```

This injects the OS trust store into Python's `ssl` module via the `truststore` package, so corporate proxy CA certificates (e.g. Netskope) are trusted automatically. It is idempotent and fails silently if `truststore` is unavailable.

### Configuration

- `MAIT_CODE_LOG_LEVEL` env var (default: `INFO`) — set via `settings.json` `env` block
- `MAIT_CODE_LOG_FILE` env var — override log file path
- Logs write to `~/.local/state/mait-code/mait-code.jsonl` (rotates at midnight, keeps `log-backup-count` days — default 14)
- Logs never go to stdout/stderr

## Adding New Memory Types

1. Add the type to `MEMORY_CLASS_MAP` in `src/mait_code/tools/memory/writer.py`
2. The type is automatically available in `VALID_ENTRY_TYPES`
3. Choose the appropriate memory class:
   - `episodic` — Short-lived, 3-day half-life (events, tasks)
   - `semantic` — Long-lived, 90-day half-life (facts, preferences, insights)
   - `procedural` — Most durable, 180-day half-life (workflows, how-tos)
4. Add tests in `tests/tools/memory/` (see the Tests section above)

## Writing Tests for Memory Components

Use the shared fixtures from `tests/tools/memory/conftest.py`:

```python
def test_something(memory_db):
    """memory_db provides a fresh temp database with full schema."""
    from mait_code.tools.memory.writer import store_memory
    result = store_memory(memory_db, "test content", "fact", 5)
    assert result["action"] == "created"

def test_with_data(populated_db):
    """populated_db has 7 sample entries pre-loaded."""
    from mait_code.tools.memory.search import search_entries
    results = search_entries(populated_db, "dark mode")
    assert len(results) >= 1
```

For memory tool tests, patch `get_connection` to use a temp DB:

```python
from unittest.mock import patch
from mait_code.tools.memory.db import get_connection

@pytest.fixture
def mem_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    def patched(**_kwargs):
        return get_connection(db_path)
    with patch("mait_code.tools.memory.db.get_connection", side_effect=patched):
        yield conn
    conn.close()
```

## Database Migrations

### Adding a new migration

1. Open `src/mait_code/tools/memory/migrate.py`
2. Append a new tuple to the `MIGRATIONS` list:
   ```python
   MIGRATIONS.append((
       7,  # Next version number
       "Description of what this migration does",
       [
           "SQL statement 1",
           "SQL statement 2",
       ],
   ))
   ```
3. For complex migrations, use a callable instead of SQL list:
   ```python
   def _migrate_something(conn: sqlite3.Connection) -> None:
       # Complex migration logic here
       pass

   MIGRATIONS.append((7, "Complex migration", _migrate_something))
   ```
4. Migrations run automatically on next `get_connection()` call
5. Add tests in `tests/tools/memory/test_migrate.py` to verify the new schema

### Migration safety

- Migrations are forward-only (no rollback)
- Each migration is recorded in `schema_version` table
- `ensure_schema()` is idempotent — safe to call on every connection
- Vec0 migrations gracefully skip if `sqlite-vec` is not loaded

## Adding a New TUI Surface

1. Subclass `MaitApp` (from `mait_code.tui.app`) — it wires the house theme and
   the shared stylesheet, and inherits the `q`-to-quit binding.
2. Put the surface's layout in its own `.tcss` next to the module, and load it
   alongside the shared sheet. `CSS_PATH` is read only from the most-derived
   class (it does **not** merge across the MRO), so list both explicitly:
   ```python
   from pathlib import Path
   from mait_code.tui.app import MaitApp, SHARED_TCSS

   class MyApp(MaitApp):
       CSS_PATH = [SHARED_TCSS, Path(__file__).parent / "_my.tcss"]
   ```
3. Reuse the shared modal styling: wrap a modal's body in a container with
   `classes="modal-dialog"`, its heading with `classes="modal-title"`, and its
   button row with `classes="modal-buttons"`. Only a *scrolling* modal should
   cap its height (`max-height`); a plain one must grow to its content, or its
   buttons clip off-screen on a short terminal.
4. Drive every colour off theme `$`-variables (e.g. `$text-primary`; `$border`
   vs `$border-blurred` for a focus signal) — never hard-code a hex in a `.tcss`.
   For Rich `Text` in a `DataTable` cell or an `OptionList` option (which can't
   read `$`-variables), use the palette-coloured chip helpers in
   `mait_code.tui.render`.
5. A `?` help screen comes free from `MaitApp` — it lists the app's live
   key-bindings, so new bindings appear automatically. Expose the app's actions
   in the Ctrl+P palette by overriding `get_system_commands` and yielding
   `SystemCommand`s after `yield from super().get_system_commands(screen)`.
6. Give every empty state the companion voice: route the copy through
   `mait_code.tui.brand.empty_state` (which leads with the signature glyph)
   instead of a bare "no data" string. Toast glyphs come free from
   `MaitApp.notify`.
7. Add a snapshot test (see "Snapshot tests" above).

The ten shipped surfaces are worked examples: `cli/_home_tui.py` (the home
hub, a tree-navigable master–detail that launches the others), `cli/_board_tui.py`
(the board), `cli/_settings_tui.py` (the settings editor, a master–detail tree),
`cli/_memory_tui.py` (the memory browser, a read-only master–detail),
`cli/_observations_tui.py` (the observations browser, the same shape over the
raw extraction tier), `cli/_logs_tui.py` (the log viewer, the same shape
again over the structured JSONL logs), `cli/_review_tui.py` (the review queue,
the master–detail shape with write verbs), `cli/_graph_tui.py` (the graph
explorer, a list/canvas/detail three-pane), `cli/_bridge_tui.py` (the Bridge
configurator, a form with a connection probe), and `cli/_dashboard_tui.py` (the
guided start-page setup editor). Each has a snapshot directory under
`tests/cli/__snapshots__/`. Theme
persistence is free — `MaitApp.on_unmount` writes the active theme back to the
`theme` setting for every surface, so a user's pick survives across sessions.

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with frontmatter and instructions
2. Re-run `./scripts/install.sh` to symlink into `~/.claude/skills/`
3. The skill will be available as `/<skill-name>` in Claude Code

### Granting `allowed-tools`

Grant the narrowest set covering the commands the skill actually runs.

<a id="allowed-tools-semantics"></a>

There are three grant forms. Their behaviour was measured against **Claude Code
2.1.220** by giving a throwaway project a single `permissions.allow` entry and
running `claude -p` (headless denies instead of prompting):

| form | meaning | example |
| --- | --- | --- |
| `Bash(cmd)` | exact match only | `Bash(git push)` refuses `git push --dry-run` |
| `Bash(cmd:*)` | prefix match **at a token boundary** | `Bash(git push:*)` permits `git push --dry-run`, refuses `git pushfoo` |
| `Bash(cmd *)` | the older space form — a real wildcard, identical to `cmd:*` on every case tested | `Bash(git *)` permits `git push`, refuses `gitfoo` |

Two consequences worth internalising:

- **The space form is not narrow.** `Bash(mc-tool-board *)` permits
  `mc-tool-board remove`, not just the read-only subcommands. It is a wildcard,
  not a literal.
- **A boundary is not a subcommand.** Everything after the boundary is
  permitted, flags included, so `Bash(git branch:*)` does span `git branch -D`.
  Narrowing has to happen inside the prefix: `Bash(git diff --stat:*)`, or an
  exact invocation with no wildcard at all.

What `:*` does **not** do is span into a longer token —
`Bash(git diff:*)` refuses `git difftool --extcmd=<anything>`. Earlier revisions
of this page claimed the opposite; that claim was tested and is false on 2.1.220.

**A grant buys unsandboxed execution, not merely a quiet prompt.** An ungranted
command is not always refused — if Claude Code can contain it, it runs in a
filesystem-isolated sandbox with no prompt at all, and its writes are discarded.
Measured: `touch marker.txt` under an unrelated rule reported success and
created nothing; under `Bash(touch:*)` the file appeared. Commands that cannot
be contained (`git commit`, `git push`) are refused outright when ungranted.

Two practical consequences:

- Narrowing a grant does not necessarily break a skill. Read-only commands keep
  working sandboxed; only the ones needing real effects need a rule.
- "It worked without a prompt" is not evidence that a rule matched. When testing
  a pattern, use a command that is *refused* when ungranted, or you are measuring
  the sandbox rather than the matcher.

Claude Code is also operator-aware: it decomposes compound commands and requires
each part to be permitted. `Bash(git push:*)` refuses
`git push --dry-run || git commit --allow-empty -m x`.

All of the above is pinned to 2.1.220 and is undocumented matcher behaviour — a
future release could change it, so prefer prefixes that would still be safe if
the boundary were dropped. After a Claude Code upgrade, re-measure:

```bash
./scripts/probe_permissions.py          # exits non-zero if behaviour has drifted
```

It re-runs the measurements above against the installed `claude` and reports any
case that no longer matches. The test suite cannot catch this — it pins our
*model* of the matcher, not the matcher.

Check your patterns mechanically rather than by eye:

```python
from mait_code.cli import _permissions as perms
bad = [(p, c) for p in MY_PATTERNS for c in perms.MUTATING_INVOCATIONS
       if perms.matches_command(p, c)]
```

`MUTATING_INVOCATIONS` is a floor, not a proof — a clean result means "no *known*
mutating command is permitted", not "safe". Think about siblings the list does not
cover.

`skills/pre-pr-review/SKILL.md` is the worked example.

## Adding a New Agent

Agents are single markdown files, not directories.

1. Create `agents/<agent-name>.md` with YAML frontmatter — `name`, `description`,
   `tools` (a comma-separated list of tool *names*), and optionally `model`
2. Write the standing brief in the body. Keep it task-independent: a skill that
   spawns the agent passes only the job, never the persona, so anything specific to
   one invocation belongs in the spawn prompt instead
3. Re-run `./scripts/install.sh` to symlink into `~/.claude/agents/`
4. **Restart Claude Code.** The agent registry is read at session start, so a newly
   installed agent will not resolve until then — unlike skills, which are picked up
   live. A skill that spawns an agent should fail loudly if the type is missing
   rather than falling back to `general-purpose`, which carries no tool restriction

Note the ceiling on what `tools:` can express: it lists tool names, so an agent that
needs a shell gets an unrestricted one. There is no way to pattern-restrict `Bash`
in an agent definition the way `allowed-tools` does for a skill. If an agent must
not write, say so in its brief, and treat that as a convention backed by permission
prompts rather than a mechanical guarantee.

## Adding a New Hook

1. Create package in `src/mait_code/hooks/<hook_name>/` with `cli.py` containing a `main()` function
2. Wire in logging:
   ```python
   from mait_code.logging import log_invocation, setup_logging

   @log_invocation(name="mc-hook-<hook-name>")
   def main():
       setup_logging()
       # ...
   ```
3. Add entry point in `pyproject.toml`:
   ```toml
   mc-hook-<hook-name> = "mait_code.hooks.<hook_name>.cli:main"
   ```
4. Register in `config/settings.json` under the appropriate hook event
5. Use `"async": true` for observation/logging hooks that don't feed results back into the conversation. **Note:** Async hooks on macOS may receive empty stdin due to a Claude Code bug ([#38162](https://github.com/anthropics/claude-code/issues/38162)) — handle this by falling back to filesystem discovery or other means.
6. Run `uv sync` and re-run `./scripts/install.sh`

## Adding a New CLI Tool

1. Create package in `src/mait_code/tools/<tool_name>/` with `cli.py` containing a `main()` function
2. Wire in logging:
   ```python
   from mait_code.logging import log_invocation, setup_logging

   @log_invocation(name="mc-tool-<tool-name>")
   def main():
       setup_logging()
       # ...
   ```
3. Add entry point in `pyproject.toml`:
   ```toml
   mc-tool-<tool-name> = "mait_code.tools.<tool_name>.cli:main"
   ```
4. Run `uv sync`
5. Skills can invoke the tool via preprocessing (`!`mc-tool-<name> ...``) or `Bash(mc-tool-<name> *)`

## Adding a New MCP Server

> There are no MCP servers in mait-code today. This section documents the pattern in case one is added later — `src/mait_code/mcp/` does not yet exist.

Only use MCP when you need a persistent connection or streaming. Prefer CLI tools + skills for simpler cases.

1. Create package in `src/mait_code/mcp/<server_name>/` with `cli.py` containing a `main()` function
2. Add entry point in `pyproject.toml`:
   ```toml
   mc-mcp-<server-name> = "mait_code.mcp.<server_name>.cli:main"
   ```
3. Register in `config/settings.json` under `mcpServers`
4. Run `uv sync` and re-run `./scripts/install.sh`
