# mait-code

A companion framework that extends [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with persistent memory, a customisable identity, and reusable skills. It transforms Claude Code from a stateless coding assistant into a coding companion that remembers your projects, preferences, and patterns across sessions.

## Key features

- **Persistent memory** — three-tier memory system (raw observations, reflections, curated `MEMORY.md`) with hybrid keyword + vector search and global, project, and branch scoping.
- **Knowledge graph** — entity and relationship tracking extracted automatically from conversations.
- **Companion identity** — customisable soul document and user context that shape how the companion communicates and makes decisions.
- **Reactive hooks** — `SessionStart` injects companion context; `PreCompact` and `SessionEnd` extract observations asynchronously.
- **Observation pipeline** — automatic extraction of facts, preferences, decisions, entities, and relationships via Claude Haiku, run with no tools so a transcript can't make it act; `mc-tool-memory observe` runs the same pipeline over prepared text, such as an automated job's digest.
- **CLI tools** — memory, reminders, a cross-project kanban board, and a quick-capture inbox (`mc-tool-memory`, `mc-tool-reminders`, `mc-tool-board`, `mc-tool-inbox`).
- **TUIs** — full-screen Textual apps sharing one house theme: the [home hub](home.md) (`mait-code home`, or just `mait-code` on a terminal) with its [user-authored start page](home.md#the-start-page) of widget and shell-command tiles, the [kanban board](board.md) (`mait-code board`) with its [Initiatives view](board.md#initiatives-view) of epics and dependencies, the [settings editor](settings.md) (`mait-code settings`), the [review queue](review.md) (`mait-code review`), and the read-only [memory browser](memory-browser.md) (`mait-code memory`), [observations browser](observations.md) (`mait-code observations`), [graph explorer](graph.md) (`mait-code graph`) and [log viewer](logs.md) (`mait-code logs`).
- **Memory review** — important-but-ageing memories resurface in a due queue; confirm, refine or retire each in place so curated memory stays true instead of quietly decaying.
- **[The Bridge](bridge.md)** — an opt-in link to your phone: capture into the inbox from anywhere, and get due reminders as notifications with a Done button that round-trips back. Disabled by default, with zero network calls until switched on.
- **[Companion mod](companion-mod.md)** — an opt-in Claude Code mod that adds `/capture` straight to the inbox and a live status bar above the prompt (the cards in hand, what's waiting on you, where the session is).
- **[Remote API](remote.md)** — a Python module a host service you run can import to read and raise board cards, search memories and list reminders; mait-code itself never opens a port.
- **Skills** — slash commands for memory (`/recall`, `/remember`, `/reflect`), reminders (`/remind`, `/reminders`), the board (`/board`), capture triage (`/triage`), and workflow (`/commit`, `/pre-pr-review`, `/design-review`, `/outward-comms`).

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
- **[Companion mod](companion-mod.md)** and **[Remote API](remote.md)** — the opt-in status bar, and driving mait-code from another service.
- **[Reference](reference/skills.md)** — slash-command catalogue and Python API reference.
- **[Contributing](development.md)** — development guide and documentation conventions.

## Source &amp; issues

The project is developed on GitHub at [`wiktordepina/mait-code`](https://github.com/wiktordepina/mait-code). Bug reports and contributions are welcome.
