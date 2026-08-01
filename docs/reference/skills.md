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
| Board | `/board` | View and drive the project kanban board | **Implemented** |
| Triage | `/triage` | Route quick-capture inbox items to the board or memory | **Implemented** |
| Web Fetch | `/web-fetch <url>` | Fetch web page content as markdown (bypasses claude.ai proxy) | **Implemented** |
| Pre-PR Review | `/pre-pr-review` | Independent, zero-context review of the current branch | **Implemented** |

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
   - Board card → `mc-tool-board add ...`
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

### /pre-pr-review

Review the current branch with a reviewer that shares none of the session's context.

**Usage:**
```
/pre-pr-review                   # Review main...HEAD before opening a PR
```

**Why it exists:**

You cannot review your own work in the session that produced it. Knowing why every
decision was made, you check whether the code matches the intent — not whether the
intent was right. A reviewer with no context checks the second thing.

**How it works:**

1. Preprocesses the branch name, commits vs `main`, diff stat, and uncommitted files
2. Warns which files are dirty and therefore *not* under review, then spawns one
   `pre-pr-reviewer` agent (see [Agents](#agents)) with a deliberately bare prompt —
   repository path, diff range, and the brief, and nothing about why the change was
   made
3. Relays the review in the session, verifies its concrete `file:line` claims, and
   separates merge-blockers from follow-up material

The reviewer also writes its own description of the change from the diff alone.
Comparing that against the author's framing is diagnostic: a difference in described
*scope* usually means the diff does more than intended, and a reviewer who cannot say
*why* the change is wanted has found a real problem with its legibility.

**Cost:** roughly 100k+ subagent tokens and ten to fifteen minutes for a substantial
branch. Worth it before a merge that is hard to walk back; not worth it per commit.

**Nothing is posted to GitHub** — no review, no comment, no approval — unless you
ask for that separately afterwards.

## Agents

Agent definitions live in `agents/` as individual markdown files with YAML
frontmatter, symlinked into `~/.claude/agents/` at install time. They hold a
subagent's standing instructions, so a skill that spawns one passes only the task —
never the persona.

### pre-pr-reviewer

The reviewer behind `/pre-pr-review`. Reads a diff cold and reports defects, design
objections, and — importantly — the classes of problem it looked for and did *not*
find, so silence can be told from diligence.

Its brief includes explicit licence to reject the premise: if the change solves the
wrong problem, saying so is more useful than a tidy review of a bad idea. It is told
to distrust green CI, on the grounds that the tests were written by whoever wrote the
bug.

**Read-only, with a caveat.** The definition forbids writes, mutating git commands
and any `gh` write. But agent frontmatter lists tool *names*, not permission
patterns, and the reviewer needs a real shell to run tests and typecheckers — so the
constraint is enforced by instruction plus the usual permission prompts, not
mechanically. If it asks to run something that writes, that is a bug in the review.

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
├── board/
│   └── SKILL.md     # View and drive the kanban board
├── triage/
│   └── SKILL.md     # Route the quick-capture inbox to the board or memory
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
