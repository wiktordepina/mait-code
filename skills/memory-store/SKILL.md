---
name: memory-store
description: Store observations to memory when you learn something new about the user, their preferences, projects, or technical decisions. Use proactively after learning new facts.
user-invocable: false
allowed-tools: Bash(mc-tool-memory store *)
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

Types: fact, preference, event, insight, task, relationship
Importance: 1 (trivial) to 10 (critical), default 5

## Guidelines

- Keep content concise — one fact per entry
- Don't store session-specific ephemera (current file being edited, temporary errors)
- Don't store information already in MEMORY.md or user_context.md
- Deduplication is automatic — storing similar content updates the existing entry
- Memories are automatically scoped to the current project and branch
- User preferences are promoted to global scope automatically
- If the user explicitly says something applies to all their projects, add `--scope global`
