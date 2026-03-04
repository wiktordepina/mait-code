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
```

## Linting and Formatting

```bash
uv run ruff check src/         # Lint
uv run ruff format src/        # Format
```

## Project Conventions

- **Use `uv run` everywhere** — Never activate venvs manually
- **Entry points in pyproject.toml** — All CLI commands are registered as `[project.scripts]`
- **Data dir via env var** — Use `MAIT_CODE_DATA_DIR` (defaults to `~/.claude/mait-code-data/`)
- **No asyncio in CLI tools** — Only MCP servers use async; tools and hooks are synchronous
- **Markdown for storage** — Observations and reflections are stored as markdown, not in databases

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
