# mait-code

[![CI](https://github.com/wiktordepina/mait-code/actions/workflows/ci.yml/badge.svg)](https://github.com/wiktordepina/mait-code/actions/workflows/ci.yml)
[![Docs](https://github.com/wiktordepina/mait-code/actions/workflows/docs.yml/badge.svg)](https://wiktordepina.github.io/mait-code/)

A companion framework that extends [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with persistent memory, a customisable identity, and reusable skills. It transforms Claude Code from a stateless coding assistant into a coding companion that remembers your projects, preferences, and patterns across sessions.

**Documentation:** <https://wiktordepina.github.io/mait-code/>

## Key Features

- **Persistent Memory** — Three-tier memory system (raw observations, curated facts, hybrid FTS5 + vector search) with global/project/branch scoping
- **Knowledge Graph** — Entity and relationship tracking extracted automatically from conversations
- **Companion Identity** — Customisable soul document and user context that shape how the companion communicates and makes decisions
- **Reactive Hooks** — `SessionStart` injects companion context, `PreCompact` and `SessionEnd` extract observations asynchronously
- **Observation Pipeline** — Automatic extraction of facts, preferences, decisions, entities, and relationships via Claude Haiku
- **CLI Tools** — Memory, reminders, tasks, decision records, and web fetch (`mc-tool-memory`, `mc-tool-reminders`, `mc-tool-tasks`, `mc-tool-decisions`, `mc-tool-web-fetch`)
- **Skills** — Slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), tasks (`/task`, `/tasks`), decisions (`/decision`, `/decisions`), web fetch (`/web-fetch`), and workflow (`/commit`, `/standup`, `/today`, `/work-history`, `/status`, `/prs`)

## Quick Start

```bash
# Clone and install dependencies
git clone https://github.com/wiktordepina/mait-code.git
cd mait-code
uv sync

# Deploy to ~/.claude/
./scripts/install.sh

# Personalise your companion
$EDITOR ~/.claude/mait-code-data/soul_document.md
$EDITOR ~/.claude/mait-code-data/user_context.md

# Start Claude Code in any project — the companion loads automatically
claude
```

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python >= 3.13

## Project Structure

```
mait-code/
├── src/mait_code/        # Python package
│   ├── hooks/            #   Hooks: session_start, observe, auto_format
│   └── tools/            #   CLI tools: memory, reminders, tasks, decisions, web_fetch
├── config/               # CLAUDE.md and settings.json templates
├── templates/            # Identity templates
├── scripts/              # Install/uninstall scripts
├── skills/               # Skill definitions
├── agents/               # Agent definitions (currently empty)
└── docs/                 # Documentation
```

## Documentation

- [Philosophy](docs/philosophy.md) — The mait concept: why companion, not assistant
- [Setup Guide](docs/setup.md) — Detailed installation and personalisation
- [How Memory Works](docs/memory.md) — Observations, search, embeddings, reminders, and reflections
- [Architecture](docs/architecture.md) — System design and technical decisions
- [Skills Reference](docs/reference/skills.md) — Available slash commands
- [Multi-Machine Sync](docs/sync.md) — Syncing data across machines
- [Development Guide](docs/development.md) — Contributing and extending

## Uninstalling

```bash
./scripts/uninstall.sh
```

This removes symlinks and hook registrations from `~/.claude/`. Your personalised data in `~/.claude/mait-code-data/` is preserved by default (you'll be asked).
