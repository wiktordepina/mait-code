# Skills Reference

Skills are slash commands available in Claude Code sessions when mait-code is installed.

| Skill | Trigger | Description | Status |
|-------|---------|-------------|--------|
| Recall | `/recall <query>` | Search memory for past facts, decisions, patterns | **Implemented** |
| Reflect | `/reflect` | Synthesise recent observations into insights, update MEMORY.md | Planned |
| Observe | `/observe` | Manually trigger observation extraction from current session | Planned |
| Standup | `/standup` | Generate standup summary from recent work and observations | Planned |
| Work History | `/work-history [period]` | Show recent work activity over a time period | Planned |
| Commit | `/commit` | Smart commit with conventional commit message | Planned |
| Today | `/today` | Dashboard of open tasks, reminders, and standup | Planned |
| Status | `/status` | Generate comprehensive status dashboard | Planned |
| Remind | `/remind <when> <what>` | Set a reminder for a future time | Planned |
| Reminders | `/reminders` | Show active and overdue reminders | Planned |
| Incident | `/incident <description>` | Log an incident with timestamp and context | Planned |

## Implemented Skills

### /recall

Search memory for past facts, decisions, patterns, and preferences.

**Usage:**
```
/recall database preferences     # Search for past database decisions
/recall testing patterns         # Find remembered testing approaches
/recall kubernetes               # Look up stored Kubernetes knowledge
/recall                          # Show recent memories (no query)
```

**How it works:**
1. Uses the `search_memory` tool from the `mait-memory` MCP server
2. Results are ranked by composite score (recency + importance + relevance)
3. If no query is provided, lists recent memories instead

**MCP tools used:** `search_memory`, `list_recent_memories`

## Skill Architecture

Each skill is a directory in `skills/` containing:

```
skills/
└── recall/
    └── skill.md     # Skill definition (prompt, triggers, description)
```

Skills are symlinked into `~/.claude/skills/` by `install.sh` and loaded by Claude Code automatically.

### Skill Definition Format

```yaml
---
name: skill-name
description: What the skill does
argument-hint: "<args>"
user-invocable: true
allowed-tools:
  - mcp__server-name__tool_name
---

# /skill-name

Instructions for Claude when this skill is invoked.
```

Key fields:
- `user-invocable: true` — Makes it available as a slash command
- `allowed-tools` — MCP tools the skill is allowed to use
- `argument-hint` — Shown in autocomplete to guide usage
