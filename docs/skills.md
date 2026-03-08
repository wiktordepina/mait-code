# Skills Reference

Skills are slash commands available in Claude Code sessions when mait-code is installed.

| Skill | Trigger | Description | Status |
|-------|---------|-------------|--------|
| Recall | `/recall <query>` | Search memory for past facts, decisions, patterns | **Implemented** |
| Remember | `/remember <content>` | Manually store a memory observation | **Implemented** |
| Memory Store | *(auto)* | Claude auto-stores observations about user/projects | **Implemented** |
| Reflect | `/reflect` | Synthesise recent observations into insights, update MEMORY.md | Planned |
| Observe | `/observe` | Manually trigger observation extraction from current session | Planned |
| Standup | `/standup` | Generate standup summary from recent work and observations | Planned |
| Work History | `/work-history [period]` | Show recent work activity over a time period | Planned |
| Commit | `/commit` | Smart commit with conventional commit message | Planned |
| Today | `/today` | Dashboard of open tasks, reminders, and standup | Planned |
| Status | `/status` | Generate comprehensive status dashboard | Planned |
| Remind | `/remind <when> <what>` | Set a reminder for a future time | **Implemented** |
| Reminders | `/reminders` | Show active and overdue reminders | **Implemented** |
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
1. Preprocesses search results via `mc-tool-memory search` (injected before Claude sees the skill)
2. Results are ranked by composite score (recency + importance + relevance)
3. If no query is provided, shows recent memories via `mc-tool-memory list`
4. For follow-up searches, uses Bash to call `mc-tool-memory search` directly

### /remember

Manually store a memory observation. This is a manual-only skill (`disable-model-invocation: true`) — Claude won't auto-invoke it.

**Usage:**
```
/remember always use tabs for Go code
/remember deployed v2.3 to production today
/remember the auth service uses JWT with RS256
```

**How it works:**
1. Determines the best entry type and importance for the content
2. Stores via `mc-tool-memory store`

### memory-store (auto-invoked)

Not a slash command — Claude uses this skill proactively when it learns something new about the user. Uses `mc-tool-memory store` via Bash.

### /remind

Set a reminder for a future time.

**Usage:**
```
/remind in 2 hours check deploy status
/remind tomorrow 9am standup prep
/remind friday review PR #42
```

**How it works:**
1. Parses the time and content from the arguments
2. Stores via `mc-tool-reminders set "<when>" <what>`
3. Uses `dateparser` for flexible natural language time parsing with UTC normalization

### /reminders

Show active and overdue reminders.

**Usage:**
```
/reminders                    # Show active reminders
```

**How it works:**
1. Preprocesses results via `mc-tool-reminders list` (injected before Claude sees the skill)
2. Presents active and overdue reminders
3. Supports dismissing reminders via `mc-tool-reminders dismiss <id>`

## Skill Architecture

Each skill is a directory in `skills/` containing:

```
skills/
├── recall/
│   └── SKILL.md     # Search memory
├── remember/
│   └── SKILL.md     # Store memory (manual)
├── memory-store/
│   └── SKILL.md     # Store memory (auto-invoked by Claude)
├── remind/
│   └── SKILL.md     # Set a reminder
└── reminders/
    └── SKILL.md     # Show reminders
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
- `disable-model-invocation: true` — Prevents Claude from auto-invoking (for side-effect skills)
- `allowed-tools` — Tools the skill is allowed to use (e.g. `Bash(mc-tool-memory *)`)
- `argument-hint` — Shown in autocomplete to guide usage
