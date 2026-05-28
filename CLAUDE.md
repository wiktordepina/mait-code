# mait-code — Development Guide

## Overview

Companion framework extending Claude Code with persistent memory, identity, and skills. Uses `uv` for Python packaging, hooks for reactive observation, and CLI tools + skills for mid-session memory access.

## Key Conventions

- **Always use `uv run`** to execute scripts and tools — never activate venvs manually
- **Entry points** are defined in `pyproject.toml` under `[project.scripts]`
- **Data directory** is `~/.claude/mait-code-data/` — configurable via `data-dir` in settings.toml or `MAIT_CODE_DATA_DIR` env var
- **Settings file** is `$XDG_CONFIG_HOME/mait-code/settings.toml` — single source of truth for all `MAIT_CODE_*` knobs (embedding provider, log level, etc.). Resolution: env var → settings file → hardcoded default. See `docs/memory.md` for embedding config
- **Logs** go to `$XDG_STATE_HOME/mait-code/` (default `~/.local/state/mait-code/`)
- **No asyncio in CLI tools** — tools use sync code; MCP servers use async
- **No background services** — everything is reactive (hooks, skill invocations, CLI tools)
- **Prefer CLI tools + skills over MCP** — simpler, no process overhead, supports preprocessing

## Working notes — `.wip/`

Temporary and interim documents (plans, research notes, reports, scratch work) live in `.wip/` at the repo root, organised by kind into subfolders:

- `.wip/plan/` — implementation plans
- `.wip/research/` — research notes, investigations
- `.wip/report/` — audits, retrospectives, status reports
- add new subfolders as the kind of work calls for them

Rules:

- **`.wip/` is always gitignored.** These are local-only working documents, never committed.
- **Never mention `.wip/` in commits, PR descriptions, or user-facing documentation** (READMEs, `docs/`, `CHANGELOG.md`, code comments). It is invisible to the outside world — outputs should read as if it didn't exist.
- **Format**: documents in `.wip/` are rich HTML, built from `.wip/template.html` as the starting point. Copy the template, replace the body, keep the inline CSS.
- **Naming**: `YYYY-MM-DD-<short-slug>.html` (matches the existing pattern under `.wip/report/`).
- **Don't create planning/analysis `.md` files at the repo root or under `docs/`** — if you're about to, stop: it belongs in `.wip/`.

The point is a strict separation between polished, shipped artefacts (committed, public-facing) and scratchpad working notes (rich, exploratory, local).

## Lint, format, typecheck, test

```bash
uv run ruff check src/         # Lint
uv run ruff format src/        # Format
uv run pyright                 # Typecheck (standard mode, src/ only)
uv run pytest                  # Test suite (~460 tests)
```

`pyright` reads the optional `boto3` import in `tools/memory/embeddings.py`,
so the bedrock extra must be installed: `uv sync --extra bedrock` once,
then `uv run pyright` works.

Tests live under `tests/` mirroring the `src/mait_code/` layout. Tool-specific
fixtures in `tests/<area>/conftest.py`; cross-cutting setup in the root
`tests/conftest.py`. `tests/test_imports.py` is the smoke test that asserts every
reference-surface module declares a non-empty `__all__`.

## Docs

Docstrings follow **Google style** and modules that surface in the API reference declare `__all__` with `# Section` comments. See [`docs/contributing-docs.md`](docs/contributing-docs.md) for the conventions and the regeneration workflow.

```bash
uv sync --group docs                                # install mkdocs deps
uv run python docs/gen_ref_pages.py                 # regenerate docs/reference/*
uv run mkdocs serve                                 # local preview
uv run mkdocs build --strict                        # CI-equivalent build
```

## Directory Structure

```
src/mait_code/
├── context.py       # Project/branch detection (get_context, get_project)
├── llm.py           # Shared LLM invocation (call_claude)
├── logging.py       # Shared logging (setup_logging, @log_invocation)
├── ssl.py           # OS trust store injection (setup_ssl, for corporate proxies)
├── hooks/           # Claude Code hook handlers (session_start, observe, auto_format)
└── tools/           # CLI tools (memory, reminders, tasks, decisions, web_fetch)
config/              # CLAUDE.md and settings.json templates
templates/           # Identity templates (soul_document, user_context)
scripts/             # install.sh, uninstall.sh
skills/              # Skill definitions (loaded by Claude Code)
agents/              # Agent definitions (currently empty)
docs/                # Documentation
```

> No MCP servers currently. The "Adding New Components" section keeps the pattern
> documented in case one is added later — at that point a `src/mait_code/mcp/` package
> would join the layout above.

## Adding New Components

- **New hook:** Add package in `src/mait_code/hooks/<hook_name>/` with `cli.py` as the entry point containing `main()`, add entry point (`mc-hook-*`) in `pyproject.toml`, register in `config/settings.json`. Use `"async": true` for observation/logging hooks that don't need to feed results back into the conversation, to avoid blocking the user. Wire in `setup_logging()` and `@log_invocation()`. If the hook makes outbound HTTPS requests, also call `setup_ssl()`.
- **New CLI tool:** Add package in `src/mait_code/tools/<tool_name>/` with `cli.py` as the entry point containing `main()`, add entry point (`mc-tool-*`) in `pyproject.toml`. Wire in `setup_logging()` and `@log_invocation()`. If the tool makes outbound HTTPS requests, also call `setup_ssl()`.
- **New skill:** Create directory in `skills/` with `SKILL.md` — skills can invoke CLI tools via preprocessing or Bash
- **New MCP server:** Only if persistent connection/streaming needed; add package in `src/mait_code/mcp/<server_name>/` with `cli.py` as the entry point containing `main()` , entry point (`mc-mcp-*`) in `pyproject.toml`
