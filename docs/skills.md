# Skills Reference

Skills are slash commands available in Claude Code sessions when mait-code is installed.

| Skill | Trigger | Description | Status |
|-------|---------|-------------|--------|
| Recall | `/recall <query>` | Search memory for past facts, decisions, patterns | Planned |
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

## Skill Architecture

Each skill is a directory in `skills/` containing:

```
skills/
└── recall/
    └── skill.md     # Skill definition (prompt, triggers, description)
```

Skills are symlinked into `~/.claude/skills/` by `install.sh` and loaded by Claude Code automatically.
