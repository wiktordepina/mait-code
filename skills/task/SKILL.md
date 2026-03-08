---
name: task
description: Add a task for the current project
argument-hint: "[--priority high|medium|low] <title>"
allowed-tools: Bash(mc-tool-tasks add *)
---

# /task

Add a task for the current project.

## Instructions

When the user invokes `/task <args>`:

1. Parse the arguments. If `--priority` is provided, pass it through. Otherwise default to medium.

2. Run: `mc-tool-tasks add [--priority <priority>] <title>`

3. Confirm the task was added.

## Proactive task suggestions

During a session, if you identify work items, TODOs, or follow-ups that the user might want to track, you may **suggest** adding them as tasks. **Always ask for confirmation before adding** — never add tasks without the user's explicit approval.

Example: "Would you like me to add a task to track this? e.g. `mc-tool-tasks add --priority high Fix the auth race condition`"

## Examples

- `/task Fix login page CSS` → `mc-tool-tasks add Fix login page CSS`
- `/task --priority high Fix auth race condition` → `mc-tool-tasks add --priority high Fix auth race condition`
- `/task --priority low Update README with new API docs` → `mc-tool-tasks add --priority low Update README with new API docs`
