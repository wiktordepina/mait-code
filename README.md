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
- **TUIs** — Full-screen Textual apps sharing one house theme: the home hub (`mait-code home`, or just `mait-code` on a terminal) with a user-authored start page of widget and shell-command tiles, the kanban board (`mait-code board`), the settings editor (`mait-code settings`), the memory review queue (`mait-code review`), and the read-only memory browser (`mait-code memory`), observations browser (`mait-code observations`), knowledge-graph explorer (`mait-code graph`) and log viewer (`mait-code logs`)
- **Memory Review** — Important-but-ageing memories resurface in a due queue; confirm, refine or retire each in place so curated memory stays true instead of quietly decaying
- **Bridge** — An opt-in link to your phone: capture thoughts into the inbox from anywhere and get due reminders as notifications with a Done button that round-trips back. Disabled by default and makes zero network calls until you switch it on
- **Home Hub** — A tree-navigable front door to the board, memory, reminders, inbox, identity and system health, with live status badges; press Enter to jump into any sibling TUI, plus a system prompt view showing exactly what the companion is presented with at session start
- **Skills** — Slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), the board (`/board`), capture triage (`/triage`), web fetch (`/web-fetch`), and workflow (`/commit`, `/pre-pr-review`)

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
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash -s -- --ref v0.69.0
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
│   ├── tools/            #   CLI tools: memory, reminders, board, inbox, web_fetch
│   ├── bridge/           #   Opt-in capture-in / notify-out transport
│   ├── cli/              #   The mait-code CLI and its Textual TUIs
│   └── tui/              #   Shared TUI layer: house theme, palette, base app
├── config/               # CLAUDE.md and settings.json templates
├── templates/            # Identity templates
├── scripts/              # Install/uninstall scripts
├── skills/               # Skill definitions
├── agents/               # Agent definitions
├── tests/                # Test suite (mirrors src/mait_code/)
└── docs/                 # Documentation
```

## Documentation

- [Philosophy](docs/philosophy.md) — The mait concept: why companion, not assistant
- [Setup Guide](docs/setup.md) — Detailed installation and personalisation
- [How Memory Works](docs/memory.md) — Observations, search, embeddings, reminders, and reflections
- [Architecture](docs/architecture.md) — System design and technical decisions
- [Skills Reference](docs/reference/skills.md) — Available slash commands
- [Multi-Machine Sync](docs/sync.md) — Syncing data across machines
- [The Bridge](docs/bridge.md) — The opt-in phone link, and how to set it up
- [Development Guide](docs/development.md) — Contributing and extending

Per-surface guides for each TUI — the [home hub](docs/home.md), [board](docs/board.md),
[settings editor](docs/settings.md), [memory browser](docs/memory-browser.md),
[review queue](docs/review.md), [observations browser](docs/observations.md),
[graph explorer](docs/graph.md) and [log viewer](docs/logs.md) — live alongside
these on the [documentation site](https://wiktordepina.github.io/mait-code/).

## Uninstalling

```bash
./scripts/uninstall.sh
```

This removes symlinks and hook registrations from `~/.claude/`. Your personalised data in `~/.claude/mait-code-data/` is preserved by default (you'll be asked).
