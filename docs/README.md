# mait-code

A companion framework that extends [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with persistent memory, a customisable identity, and reusable skills. It transforms Claude Code from a stateless coding assistant into a coding companion that remembers your projects, preferences, and patterns across sessions.

## Key features

- **Persistent memory** — three-tier memory system (raw observations, curated facts, hybrid FTS5 + vector search) with global, project, and branch scoping.
- **Knowledge graph** — entity and relationship tracking extracted automatically from conversations.
- **Companion identity** — customisable soul document and user context that shape how the companion communicates and makes decisions.
- **Reactive hooks** — `SessionStart` injects companion context; `PreCompact` and `SessionEnd` extract observations asynchronously.
- **Observation pipeline** — automatic extraction of facts, preferences, decisions, entities, and relationships via Claude Haiku.
- **CLI tools** — memory, reminders, tasks, decision records, and web fetch (`mc-tool-memory`, `mc-tool-reminders`, `mc-tool-tasks`, `mc-tool-decisions`, `mc-tool-web-fetch`).
- **Skills** — slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), tasks (`/task`, `/tasks`), decisions (`/decision`, `/decisions`), web fetch (`/web-fetch`), and workflow (`/commit`, `/standup`, `/today`, `/work-history`, `/status`, `/prs`).

## Quick start

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

- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python ≥ 3.13

See [Setup](setup.md) for the full walkthrough, including verification steps and personalisation tips.

## Where to go next

- **[Guide](setup.md)** — step-by-step setup and the multi-machine sync workflow.
- **[Concepts](philosophy.md)** — the mait philosophy and how the memory system works.
- **[Architecture](architecture.md)** — system design and component overview.
- **[Reference](reference/skills.md)** — slash-command catalogue and Python API reference.
- **[Decisions](decisions.md)** — ADR-style records of technical decisions.
- **[Contributing](development.md)** — development guide and documentation conventions.

## Source &amp; issues

The project is developed on GitHub at [`wiktordepina/mait-code`](https://github.com/wiktordepina/mait-code). Bug reports and contributions are welcome.
