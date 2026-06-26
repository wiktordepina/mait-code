---
name: memory-store
description: Store observations to memory when you learn something new about the user, their preferences, projects, or technical decisions. Use proactively after learning new facts.
user-invocable: false
allowed-tools: Bash(mc-tool-memory store *), Bash(mc-tool-memory supersede *)
---

# Memory Store

When you learn something new about the user or their projects during a session, store it as a memory for future reference.

## When to store

- User states a preference or convention
- A technical decision is made
- You discover a recurring pattern in their workflow
- User shares context about their role, team, or projects
- An important event occurs (deployment, incident, milestone)

## How to store

Run: `mc-tool-memory store "<content>" --type <type> --importance <N>`

Types (pick the most specific):
- `fact` — objective information (default)
- `preference` — a like/dislike or convention
- `decision` — a choice made and its rationale (e.g. "chose X over Y because …")
- `insight` — a conclusion or recurring pattern
- `event` — something that happened (deployment, incident, milestone)
- `task` — a to-do or action item
- `relationship` — a connection between entities
- `procedure` — a repeatable how-to or workflow step

Importance: 1 (trivial) to 10 (critical), default 5

## Guidelines

- Keep content concise — one fact per entry
- Don't store session-specific ephemera (current file being edited, temporary errors)
- Don't store information already in MEMORY.md or user_context.md
- Don't store per-project *code* facts (architecture, build/test commands,
  repo gotchas) — those belong in Claude Code's native auto memory
  (`~/.claude/projects/<munged-path>/memory/`), which it maintains itself.
  mait-code memory carries facts about the **user**: preferences,
  conventions, working style, and cross-project context
- Deduplication is automatic — storing similar content updates the existing entry
- Memories are automatically scoped to the current project and branch
- User preferences are promoted to global scope automatically
- If the user explicitly says something applies to all their projects, add `--scope global`

## When a fact has changed (supersede, don't duplicate)

A `store` of related-but-different content (e.g. "uses X" when an earlier entry
says "uses Y") doesn't merge — it's stored as a new entry, and the command
prints a `⚠ This may contradict …` block listing the conflicting entries.

When that happens, don't silently leave two contradictory facts coexisting:

1. Decide whether this is a genuine evolution (the old fact is now wrong) or a
   distinct new fact (both are true).
2. If it's an evolution, **suggest superseding** the stale entry — surface it to
   the user rather than acting unprompted (the store is manually-driven):
   `mc-tool-memory supersede <old_id> "<new content>"`.
3. Supersession keeps the old entry for audit but hides it from recall, and
   carries over the old entry's type, scope, and importance (override the
   importance with `--importance <N>` if the priority has changed). If the
   entries are simply different facts that happen to be similar, leave both.
