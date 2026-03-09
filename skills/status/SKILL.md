---
name: status
description: Generate STATUS.md with project overview, tasks, recent work, and reminders
allowed-tools: Bash(git *), Bash(mc-tool-tasks *), Bash(mc-tool-memory *), Bash(mc-tool-reminders *), Read, Write
---

# /status

Generate a STATUS.md for the current project.

## Data

Project tasks:

!`mc-tool-tasks list --all 2>/dev/null || echo "No tasks."`

Reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders."`

Recent commits (last 7 days):

!`git log --since="7 days ago" --oneline 2>/dev/null || echo "No recent commits."`

Recent memories (last 7 days):

!`mc-tool-memory list --since 7d --limit 20 2>/dev/null || echo "No recent memories."`

Project info:

!`mc-tool-tasks projects 2>/dev/null || echo "No project info."`

## Instructions

1. Read the existing STATUS.md if present (for continuity), and README.md or CLAUDE.md for project context.
2. Generate a STATUS.md with these sections:
   - **Project** — name, path, github URL (from project info above)
   - **Open Tasks** — current tasks by priority
   - **Recent Work** — summary of last week's activity from git log and memories
   - **Completed Tasks** — recently completed tasks
   - **Reminders** — any active reminders
3. Write the file to the project root as STATUS.md.
4. Show a brief summary of what was written.
