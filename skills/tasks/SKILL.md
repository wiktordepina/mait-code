---
name: tasks
description: Show open tasks for the current project
allowed-tools: Bash(mc-tool-tasks *)
---

# /tasks

Show open tasks for the current project.

## Instructions

Project tasks:

!`mc-tool-tasks list 2>/dev/null || echo "No tasks found."`

Present the results clearly. If the user wants to complete or remove a task, run `mc-tool-tasks done <id>` or `mc-tool-tasks remove <id>` via Bash.
