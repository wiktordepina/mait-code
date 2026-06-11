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
- **CLI Tools** — Memory, reminders, a cross-project kanban board, a quick-capture inbox, and web fetch (`mc-tool-memory`, `mc-tool-reminders`, `mc-tool-board`, `mc-tool-inbox`, `mc-tool-web-fetch`)
- **TUIs** — Full-screen Textual apps sharing one house theme: the home hub (`mait-code home`, or just `mait-code` on a terminal), the kanban board (`mait-code board`), the settings editor (`mait-code settings`), and the read-only memory browser (`mait-code memory`), observations browser (`mait-code observations`) and log viewer (`mait-code logs`)
- **Home Hub** — A tree-navigable front door to the board, memory, reminders, inbox, identity and system health, with live status badges; press Enter to jump into the board, memory browser, observations browser, settings editor or log viewer, plus a system prompt view showing exactly what the companion is presented with at session start
- **Skills** — Slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), the board (`/board`), capture triage (`/triage`), web fetch (`/web-fetch`), and workflow (`/commit`)

## Quick Start

One-liner install (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
```

This installs [uv](https://docs.astral.sh/uv/) if missing, clones the latest release to `~/.local/share/mait-code/source/`, runs `uv tool install`, then runs `mait-code install` to wire up symlinks, settings, and data directories. Idempotent — re-running upgrades in place.

Pass flags after `bash -s --`:

```bash
# AWS Bedrock embeddings instead of the local default:
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash -s -- --embedding-provider bedrock

# Pin to a specific release:
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash -s -- --ref v0.15.0
```

Prefer to inspect before running:

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh -o /tmp/mait-code-bootstrap.sh
less /tmp/mait-code-bootstrap.sh   # review
bash /tmp/mait-code-bootstrap.sh
```

After the install:

```bash
# Personalise your companion
$EDITOR ~/.claude/mait-code-data/soul_document.md
$EDITOR ~/.claude/mait-code-data/user_context.md

# Start Claude Code in any project — the companion loads automatically
claude
```

### From a local clone

If you're developing mait-code itself, or want a clone in a specific location:

```bash
git clone https://github.com/wiktordepina/mait-code.git
cd mait-code
uv sync
./scripts/install.sh    # thin shim around `mait-code install`
```

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI — install separately
- `uv` is installed automatically by the bootstrap; otherwise grab it from <https://docs.astral.sh/uv/>
- Python ≥ 3.13 (managed by uv)

## Project Structure

```
mait-code/
├── src/mait_code/        # Python package
│   ├── hooks/            #   Hooks: session_start, observe, auto_format
│   └── tools/            #   CLI tools: memory, reminders, board, inbox, web_fetch
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
