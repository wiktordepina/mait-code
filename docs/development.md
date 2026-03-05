# Development Guide

## Setup

```bash
git clone https://github.com/yourusername/mait-code.git
cd mait-code
uv sync
```

## Running Tests

```bash
uv run pytest                  # All tests
uv run pytest tests/ -x        # Stop on first failure
uv run pytest -k "test_name"   # Run specific test
uv run pytest -v                # Verbose output
```

## Linting and Formatting

```bash
uv run ruff check src/ tests/  # Lint
uv run ruff format src/ tests/ # Format
```

## Project Conventions

- **Use `uv run` everywhere** — Never activate venvs manually
- **Entry points in pyproject.toml** — All CLI commands are registered as `[project.scripts]`
- **Data dir via env var** — Use `MAIT_CODE_DATA_DIR` (defaults to `~/.claude/mait-code-data/`)
- **No asyncio in CLI tools** — Only MCP servers use async; tools and hooks are synchronous
- **Connections via `get_connection()`** — All memory modules use the shared connection factory

## Memory Module Structure

```
src/mait_code/memory/
├── __init__.py    # Public API re-exports
├── db.py          # Connection factory (get_connection, get_data_dir)
├── migrate.py     # Schema migrations (ensure_schema)
├── scoring.py     # Composite scoring (pure functions, no DB)
├── search.py      # FTS5 keyword search + list + delete
└── writer.py      # Store with deduplication
```

**Dependency order:** `migrate.py` ← `db.py` ← everything else. The `scoring.py` module has no internal dependencies.

**Pattern:** All search/writer functions receive a `sqlite3.Connection` as their first argument. The MCP server opens and closes connections per tool call.

## Adding New Memory Types

1. Add the type to `MEMORY_CLASS_MAP` in `src/mait_code/memory/writer.py`
2. The type is automatically available in `VALID_ENTRY_TYPES`
3. Choose the appropriate memory class:
   - `episodic` — Short-lived, 3-day half-life (events, tasks)
   - `semantic` — Long-lived, 90-day half-life (facts, preferences, insights)
4. Add tests in `tests/test_writer.py`

## Writing Tests for Memory Components

Use the shared fixtures from `tests/conftest.py`:

```python
def test_something(memory_db):
    """memory_db provides a fresh temp database with full schema."""
    from mait_code.memory.writer import store_memory
    result = store_memory(memory_db, "test content", "fact", 5)
    assert result["action"] == "created"

def test_with_data(populated_db):
    """populated_db has 7 sample entries pre-loaded."""
    from mait_code.memory.search import search_entries
    results = search_entries(populated_db, "dark mode")
    assert len(results) >= 1
```

For MCP server tests, patch `get_connection` to use a temp DB:

```python
from unittest.mock import patch
from mait_code.memory.db import get_connection

@pytest.fixture
def mcp_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    def patched():
        return get_connection(db_path)
    with patch("mait_code.mcp.memory_server.get_connection", side_effect=patched):
        yield conn
    conn.close()
```

## Database Migrations

### Adding a new migration

1. Open `src/mait_code/memory/migrate.py`
2. Append a new tuple to the `MIGRATIONS` list:
   ```python
   MIGRATIONS.append((
       5,  # Next version number
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

   MIGRATIONS.append((5, "Complex migration", _migrate_something))
   ```
4. Migrations run automatically on next `get_connection()` call
5. Add tests in `tests/test_migrate.py` to verify the new schema

### Migration safety

- Migrations are forward-only (no rollback)
- Each migration is recorded in `schema_version` table
- `ensure_schema()` is idempotent — safe to call on every connection
- Vec0 migrations gracefully skip if `sqlite-vec` is not loaded

## Adding a New Skill

1. Create `skills/<skill-name>/skill.md` with the skill definition
2. Re-run `./scripts/install.sh` to symlink into `~/.claude/skills/`
3. The skill will be available as `/<skill-name>` in Claude Code

## Adding a New Hook

1. Create module in `src/mait_code/hooks/<hook_name>.py` with a `main()` function
2. Add entry point in `pyproject.toml`:
   ```toml
   mait-code-<hook-name> = "mait_code.hooks.<hook_name>:main"
   ```
3. Register in `config/settings.json` under the appropriate hook event
4. Run `uv sync` and re-run `./scripts/install.sh`

## Adding a New MCP Tool

To add a tool to an existing server:

1. Add a `@server.tool()` function in the appropriate server file (`src/mait_code/mcp/`)
2. The tool is available immediately after restart

To create a new MCP server:

1. Create `src/mait_code/mcp/<server_name>.py` with a `FastMCP` instance and `main()` function
2. Add entry point in `pyproject.toml`
3. Register in `config/settings.json` under `mcpServers`
4. Run `uv sync` and re-run `./scripts/install.sh`

## Adding a New CLI Tool

1. Create `src/mait_code/tools/<tool_name>.py` with a `main()` function
2. Add entry point in `pyproject.toml`
3. Run `uv sync`
