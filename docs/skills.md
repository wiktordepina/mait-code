# Skills Reference

Skills are slash commands available in Claude Code sessions when mait-code is installed.

| Skill | Trigger | Description | Status |
|-------|---------|-------------|--------|
| Recall | `/recall <query>` | Search memory for past facts, decisions, patterns | **Implemented** |
| Remember | `/remember <content>` | Manually store a memory observation | **Implemented** |
| Memory Store | *(auto)* | Claude auto-stores observations about user/projects | **Implemented** |
| Reflect | `/reflect` | Synthesise recent observations into insights, update MEMORY.md | **Implemented** |
| Observe | `/observe` | Manually trigger observation extraction from current session | Planned |
| Commit | `/commit` | Detect changes, generate conventional commit message, confirm and commit | **Implemented** |
| Standup | `/standup` | Generate standup summary from git history, tasks, memory, and PRs | **Implemented** |
| Work History | `/work-history [period]` | Show project work history (git log + memory) for a time period | **Implemented** |
| Today | `/today` | Daily overview — open tasks, reminders, recent activity, PRs | **Implemented** |
| Status | `/status` | Generate STATUS.md with project overview, tasks, recent work | **Implemented** |
| PRs | `/prs` | List open PRs across all projects | **Implemented** |
| Remind | `/remind <when> <what>` | Set a reminder for a future time | **Implemented** |
| Reminders | `/reminders` | Show active and overdue reminders | **Implemented** |
| Task | `/task [--priority high\|medium\|low] <title>` | Add a task for the current project | **Implemented** |
| Tasks | `/tasks` | Show open tasks for the current project | **Implemented** |

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

### /reflect

Synthesise recent observations into high-level insights and propose MEMORY.md updates.

**Usage:**
```
/reflect                                    # Reflect on last 7 days
```

**How it works:**
1. Preprocesses via `mc-tool-memory reflect` (injected before Claude sees the skill)
2. Checks the novelty gate — skips if fewer than 3 new observations since last reflection
3. Gathers recent memory entries and raw observation JSONL logs
4. Calls Claude Haiku to identify patterns, themes, and recurring issues
5. Stores insights as `type=insight` (importance=6) in memory.db
6. If MEMORY.md updates are proposed, presents them for user approval
7. User can force reflection with different parameters: `mc-tool-memory reflect --days 14 --min-new 0`

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

### /task

Add a task for the current project. Model-invocable — Claude can proactively suggest tasks during a session, but always asks for confirmation before adding.

**Usage:**
```
/task Fix login page CSS
/task --priority high Fix auth race condition
/task --priority low Update README with new API docs
```

**How it works:**
1. Parses the title and optional `--priority` flag
2. Stores via `mc-tool-tasks add [--priority <priority>] <title>`
3. Tasks are scoped to the current project (git root basename or cwd basename)

### /tasks

Show open tasks for the current project.

**Usage:**
```
/tasks                        # Show open tasks
```

**How it works:**
1. Preprocesses results via `mc-tool-tasks list` (injected before Claude sees the skill)
2. Presents open tasks sorted by priority (high → medium → low)
3. Supports completing tasks via `mc-tool-tasks done <id>` or removing via `mc-tool-tasks remove <id>`

### /commit

Detect changes, generate a conventional commit message, confirm with user, and commit.

**Usage:**
```
/commit                          # Analyse changes and propose a commit
```

**How it works:**
1. Preprocesses `git diff --cached --stat`, `git diff --stat`, and untracked files
2. Analyses the changes and generates a conventional commit message (`type(scope): description`)
3. Presents the proposed message for user confirmation or editing
4. On approval, stages files if needed and runs `git commit`

### /standup

Generate a standup summary from git history, tasks, memory, and open PRs.

**Usage:**
```
/standup                         # Generate standup report
```

**How it works:**
1. Preprocesses: git log (last 24h), all open tasks, recent memories, reminders
2. Checks for open PRs via `gh search prs --author=@me --state=open`
3. Formats as standup: Yesterday, Today, Blockers, Open PRs

### /work-history

Show recent work history for the current project.

**Usage:**
```
/work-history                    # Today's work (default)
/work-history today              # Same as above
/work-history yesterday          # Last 24-48 hours
/work-history week               # Last 7 days
```

**How it works:**
1. Parses the time period argument (defaults to "today")
2. Runs `git log` and `mc-tool-memory list --since` with the appropriate time range
3. Shows completed tasks from the period
4. Presents a formatted work history

### /today

Daily overview dashboard — open tasks, reminders, recent activity, and open PRs.

**Usage:**
```
/today                           # Show daily overview
```

**How it works:**
1. Preprocesses: all open tasks, reminders, recent commits, recent memories
2. Checks for open PRs via `gh search prs --author=@me --state=open`
3. Presents sections: Tasks, Reminders, Recent Activity, Open PRs

### /status

Generate a STATUS.md for the current project.

**Usage:**
```
/status                          # Generate STATUS.md
```

**How it works:**
1. Preprocesses: project tasks, reminders, git log (7 days), recent memories
2. Gets project info from git (name, remote URL)
3. Reads existing STATUS.md (if present) for continuity
4. Generates STATUS.md with sections: Project, Open Tasks, Recent Work, Completed Tasks, Reminders
5. Writes to the project root

### /prs

List open PRs across all projects.

**Usage:**
```
/prs                             # Show all open PRs
```

**How it works:**
1. Preprocesses via `gh search prs --author=@me --state=open`
2. Shows PR number, title, and review status grouped by repository

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
├── reflect/
│   └── SKILL.md     # Synthesise observations into insights
├── remind/
│   └── SKILL.md     # Set a reminder
├── reminders/
│   └── SKILL.md     # Show reminders
├── task/
│   └── SKILL.md     # Add a project task
├── tasks/
│   └── SKILL.md     # Show project tasks
├── commit/
│   └── SKILL.md     # Smart commit with conventional message
├── standup/
│   └── SKILL.md     # Standup summary
├── work-history/
│   └── SKILL.md     # Project work history
├── today/
│   └── SKILL.md     # Daily overview dashboard
├── status/
│   └── SKILL.md     # Generate STATUS.md
└── prs/
    └── SKILL.md     # Cross-project PR listing
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
