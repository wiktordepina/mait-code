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

The suite covers every package under `src/mait_code/` (~845 tests at the time of
writing). Fixtures live in tool-specific `tests/<area>/conftest.py` files; the
root `tests/conftest.py` keeps cross-cutting setup. See the "Writing Tests for
Memory Components" section below for the established patterns.

`tests/test_imports.py` is the smoke test that asserts every reference-surface
module declares a non-empty `__all__`. CI's `ci.yml` runs the full suite on
every PR and push to `main`.

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
`MAIT_CODE_*` so every row resolves to its default source). The `mait-dark`
theme is applied by `MaitApp`, so there's no need to pin it.

## Linting, formatting, typechecking

```bash
uv run ruff check src/         # Lint
uv run ruff format src/        # Format
uv run pyright                 # Typecheck (standard mode, src/ only)
```

Pyright reads the optional `boto3` import in `tools/memory/embeddings.py`,
so the bedrock extra must be installed for typechecking: run
`uv sync --extra bedrock` once before invoking `uv run pyright`.
The CI typecheck job (`ci.yml`) does this automatically.

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
├── writer.py      # Store with deduplication + auto-embedding
├── entities.py    # Entity and relationship CRUD
└── embeddings.py  # Embedding providers (local fastembed / AWS Bedrock, lazy-loading, graceful degradation)
```

**Dependency order:** `migrate.py` ← `db.py` ← everything else. `scoring.py` has no internal dependencies. `embeddings.py` depends only on `db.py` (for data dir).

**Pattern:** All search/writer/entity functions receive a `sqlite3.Connection` as their first argument. The CLI tool opens and closes connections per subcommand invocation.

## TUI Layer

The Textual TUIs share one identity through `src/mait_code/tui/`:

```
src/mait_code/tui/
├── __init__.py    # Re-exports palette only (kept Textual-free)
├── palette.py     # Canonical role→hex colours — the single source of truth
├── theme.py       # The mait-dark Textual Theme, built from palette
├── app.py         # MaitApp base class + SHARED_TCSS path
└── app.tcss       # Shared stylesheet (modal geometry, conventions)
```

**Dependency order:** `palette.py` ← `theme.py` ← `app.py`. The one hard rule:
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

**Theming model.** `MaitApp` registers the `mait-dark` house theme as the
default and leaves Textual's built-in themes registered, so the Ctrl+P command
palette's "Change theme" offers the house theme alongside them. Because every
style is driven off `$`-variables, a user *can* drop in their own theme file and
it works mechanically — but arbitrary themes are not a supported surface.

## Logging

All entry points use the shared logging module at `src/mait_code/logging.py`.

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
- Logs write to `~/.local/state/mait-code/mait-code.log` (rotates at midnight, keeps `log-backup-count` days — default 14)
- Logs never go to stdout/stderr

## Adding New Memory Types

1. Add the type to `MEMORY_CLASS_MAP` in `src/mait_code/tools/memory/writer.py`
2. The type is automatically available in `VALID_ENTRY_TYPES`
3. Choose the appropriate memory class:
   - `episodic` — Short-lived, 3-day half-life (events, tasks)
   - `semantic` — Long-lived, 90-day half-life (facts, preferences, insights)
4. Add tests once `tests/` exists (see the Tests section above)

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
6. Add a snapshot test (see "Snapshot tests" above).

## Adding a New Skill

1. Create `skills/<skill-name>/SKILL.md` with frontmatter and instructions
2. Re-run `./scripts/install.sh` to symlink into `~/.claude/skills/`
3. The skill will be available as `/<skill-name>` in Claude Code

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
