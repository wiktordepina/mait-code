# mait-code

A companion framework that extends [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with persistent memory, a customisable identity, and reusable skills. It transforms Claude Code from a stateless coding assistant into a coding companion that remembers your projects, preferences, and patterns across sessions.

## Key features

- **Persistent memory** — three-tier memory system (raw observations, curated facts, hybrid FTS5 + vector search) with global, project, and branch scoping.
- **Knowledge graph** — entity and relationship tracking extracted automatically from conversations.
- **Companion identity** — customisable soul document and user context that shape how the companion communicates and makes decisions.
- **Reactive hooks** — `SessionStart` injects companion context; `PreCompact` and `SessionEnd` extract observations asynchronously.
- **Observation pipeline** — automatic extraction of facts, preferences, decisions, entities, and relationships via Claude Haiku.
- **CLI tools** — memory, reminders, a cross-project kanban board, a quick-capture inbox, and web fetch (`mc-tool-memory`, `mc-tool-reminders`, `mc-tool-board`, `mc-tool-inbox`, `mc-tool-web-fetch`).
- **TUIs** — full-screen Textual apps sharing one house theme: the kanban board (`mait-code board`), the settings editor (`mait-code settings`), and the read-only memory browser (`mait-code memory`).
- **Skills** — slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), the board (`/board`), capture triage (`/triage`), web fetch (`/web-fetch`), and workflow (`/commit`).

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
```

This installs `uv` if missing, clones the latest release, runs `uv tool install`, then sets up symlinks, settings, and data directories.

Then personalise:

```bash
$EDITOR ~/.claude/mait-code-data/soul_document.md
$EDITOR ~/.claude/mait-code-data/user_context.md

# Start Claude Code in any project — the companion loads automatically
claude
```

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI — install separately
- `uv` is installed automatically by the bootstrap; otherwise grab it from <https://docs.astral.sh/uv/>
- Python ≥ 3.13 (managed by uv)

See [Setup](setup.md) for the full walkthrough, flag reference, and the from-source alternative.

## Where to go next

- **[Guide](setup.md)** — step-by-step setup and the multi-machine sync workflow.
- **[Concepts](philosophy.md)** — the mait philosophy and how the memory system works.
- **[Architecture](architecture.md)** — system design and component overview.
- **[Reference](reference/skills.md)** — slash-command catalogue and Python API reference.
- **[Contributing](development.md)** — development guide and documentation conventions.

## Source &amp; issues

The project is developed on GitHub at [`wiktordepina/mait-code`](https://github.com/wiktordepina/mait-code). Bug reports and contributions are welcome.
