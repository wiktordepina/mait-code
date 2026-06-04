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
| Remind | `/remind <when> <what>` | Set a reminder for a future time | **Implemented** |
| Reminders | `/reminders` | Show active and overdue reminders | **Implemented** |
| Task | `/task [--priority high\|medium\|low] <title>` | Add a task for the current project | **Implemented** |
| Tasks | `/tasks` | Show open tasks for the current project | **Implemented** |
| Board | `/board` | View and drive the project kanban board | **Implemented** |
| Triage | `/triage` | Route quick-capture inbox items to board, tasks, or memory | **Implemented** |
| Web Fetch | `/web-fetch <url>` | Fetch web page content as markdown (bypasses claude.ai proxy) | **Implemented** |

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
/reflect                                    # Reflect on unreflected entries
```

**How it works:**

1. Preprocesses via `mc-tool-memory reflect` (injected before Claude sees the skill)
2. Checks the novelty gate — skips if fewer than 3 unreflected entries exist
3. Gathers unreflected memory entries (tracked by per-project watermark)
4. Calls Claude Haiku to identify patterns, themes, and recurring issues
5. Stores insights as `type=insight` (importance=6) in memory.db
6. Advances the watermark — running `/reflect` again without new entries is a no-op
7. If MEMORY.md updates are proposed, presents them for user approval
8. For large backlogs: `mc-tool-memory reflect --drain --batch-size 20`

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

### /board

View and drive the manually-driven kanban board for the current project. Claude acts as the worker — there is no autonomous dispatcher.

**Usage:**
```
/board                                  # Show the board, then act on requests
```

**How it works:**

1. Preprocesses the current project's board via `mc-tool-board list` (injected before Claude sees the skill)
2. Teaches Claude the verb vocabulary so conversational requests map to `mc-tool-board` calls:
   - "pick up the next refined card" → `mc-tool-board next --claim` (top refined card → `in_progress`)
   - "refine card N" → draft description + acceptance criteria, confirm, then `mc-tool-board refine N ...`
   - complete / block / unblock / tag / untag / archive / move / add / edit / comment via the matching subcommands
3. Cards flow through fixed columns: backlog → refined → in_progress → done, plus a hidden `archived` side-state; `blocked` is a tag carried in place, not a column
4. Never moves, completes, or archives cards without the user's confirmation

### /triage

Drain the quick-capture inbox by routing each captured item to where it belongs. Suggestion-based — Claude proposes a destination per item; the user decides.

**Usage:**
```
/triage                                 # Walk the inbox, route each item out
```

**How it works:**

1. Preprocesses the current inbox via `mc-tool-inbox list` (injected before Claude sees the skill)
2. For each item, proposes the best destination and, on confirmation, creates it there:
   - Board card → `mc-tool-board add ...` · Task → `mc-tool-tasks add ...`
   - Memory → `/remember`
3. After an item lands in its destination, drains it with `mc-tool-inbox remove <id>` so the inbox stays near-empty
4. Never routes or removes an item without the user's confirmation

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

### /web-fetch

Fetch web page content directly from the local machine, bypassing the claude.ai proxy. Works behind corporate firewalls and proxies.

**Usage:**
```
/web-fetch https://example.com              # Fetch and convert to markdown
/web-fetch https://api.example.com/data     # Fetch JSON, pretty-printed
```

**How it works:**

1. Preprocesses via `mc-tool-web-fetch <url>` (injected before Claude sees the skill)
2. Returns HTML as markdown, JSON as pretty-printed text, or raw text for other content types
3. SSRF protection blocks private/loopback IPs by default

**Options** (via Bash):

- `mc-tool-web-fetch <url> --raw` — skip HTML-to-markdown conversion
- `mc-tool-web-fetch <url> --timeout 60` — increase timeout (default 30s)
- `mc-tool-web-fetch <url> --allow-private` — allow private/loopback IPs

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
├── board/
│   └── SKILL.md     # View and drive the kanban board
├── triage/
│   └── SKILL.md     # Route the quick-capture inbox to board/task/memory
├── commit/
│   └── SKILL.md     # Smart commit with conventional message
└── web-fetch/
    └── SKILL.md     # Fetch web page content (bypasses claude.ai proxy)
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
