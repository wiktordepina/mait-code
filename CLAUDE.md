# mait-code — Development Guide

## Overview

Companion framework extending Claude Code with persistent memory, identity, and skills. Uses `uv` for Python packaging, hooks for reactive observation, and CLI tools + skills for mid-session memory access.

## Key Conventions

- **Always use `uv run`** to execute scripts and tools — never activate venvs manually
- **Entry points** are defined in `pyproject.toml` under `[project.scripts]`
- **Data directory** is `~/.claude/mait-code-data/` — configurable via `MAIT_CODE_DATA_DIR` env var
- **No asyncio in CLI tools** — tools use sync code; MCP servers use async
- **No background services** — everything is reactive (hooks, skill invocations, CLI tools)
- **Prefer CLI tools + skills over MCP** — simpler, no process overhead, supports preprocessing

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
├── llm.py           # Shared LLM invocation (call_claude)
├── logging.py       # Shared logging (setup_logging, @log_invocation)
├── hooks/           # Claude Code hook handlers (session_start, observe, auto_format)
├── mcp/             # MCP servers
└── tools/           # CLI tools
config/              # CLAUDE.md and settings.json templates
templates/           # Identity templates (soul_document, user_context)
scripts/             # install.sh, uninstall.sh
skills/              # Skill definitions (loaded by Claude Code)
agents/              # Agent definitions
docs/                # Documentation
```

## Adding New Components

- **New hook:** Add package in `src/mait_code/hooks/<hook_name>/` with `cli.py` as the entry point containing `main()`, add entry point (`mc-hook-*`) in `pyproject.toml`, register in `config/settings.json`. Use `"async": true` for observation/logging hooks that don't need to feed results back into the conversation, to avoid blocking the user. Wire in `setup_logging()` and `@log_invocation()`.
- **New CLI tool:** Add package in `src/mait_code/tools/<tool_name>/` with `cli.py` as the entry point containing `main()`, add entry point (`mc-tool-*`) in `pyproject.toml`. Wire in `setup_logging()` and `@log_invocation()`.
- **New skill:** Create directory in `skills/` with `SKILL.md` — skills can invoke CLI tools via preprocessing or Bash
- **New MCP server:** Only if persistent connection/streaming needed; add package in `src/mait_code/mcp/<server_name>/` with `cli.py` as the entry point containing `main()` , entry point (`mc-mcp-*`) in `pyproject.toml`
