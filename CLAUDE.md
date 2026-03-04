# mait-code — Development Guide

## Overview

Companion framework extending Claude Code with persistent memory, identity, and skills. Uses `uv` for Python packaging, hooks for reactive observation, and MCP servers for mid-session memory access.

## Key Conventions

- **Always use `uv run`** to execute scripts and tools — never activate venvs manually
- **Entry points** are defined in `pyproject.toml` under `[project.scripts]`
- **Data directory** is `~/.claude/mait-code-data/` — configurable via `MAIT_CODE_DATA_DIR` env var
- **No asyncio in CLI tools** — tools use sync code; only MCP servers use async
- **No background services** — everything is reactive (hooks, MCP requests, CLI invocations)

## Testing

```bash
uv run pytest                  # Run all tests
uv run pytest tests/ -x        # Stop on first failure
uv run ruff check src/         # Lint
uv run ruff format src/        # Format
```

## Directory Structure

```
src/mait_code/
├── hooks/           # Claude Code hook handlers (session_start, observe, auto_format)
├── mcp/             # MCP servers (memory, reminders)
├── memory/          # Memory storage, retrieval, and vector search
└── tools/           # CLI tools (reflect, rebuild_db)
config/              # CLAUDE.md and settings.json templates
templates/           # Identity templates (soul_document, user_context)
scripts/             # install.sh, uninstall.sh
skills/              # Skill definitions (loaded by Claude Code)
agents/              # Agent definitions
docs/                # Documentation
```

## Adding New Components

- **New hook:** Add module in `src/mait_code/hooks/`, add entry point in `pyproject.toml`, register in `config/settings.json`
- **New MCP tool:** Add to existing server in `src/mait_code/mcp/` or create new server with entry point
- **New skill:** Create directory in `skills/` with skill definition file
- **New CLI tool:** Add module in `src/mait_code/tools/`, add entry point in `pyproject.toml`
