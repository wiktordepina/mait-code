---
name: today
description: Daily overview — open tasks, reminders, and recent activity across all projects
allowed-tools: Bash(git *), Bash(gh *), Bash(mc-tool-tasks *), Bash(mc-tool-memory *), Bash(mc-tool-reminders *)
---

# /today

Daily overview dashboard.

## Data

Open tasks (all projects):

!`mc-tool-tasks list-all 2>/dev/null || echo "No open tasks."`

Reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders."`

Recent commits (current project):

!`git log --since="24 hours ago" --oneline 2>/dev/null || echo "No recent commits."`

Recent memories (last 24h):

!`mc-tool-memory list --since 24h --limit 10 2>/dev/null || echo "No recent memories."`

Registered projects:

!`mc-tool-tasks projects 2>/dev/null || echo "No projects registered."`

## Instructions

1. Present a daily overview with these sections:
   - **Tasks** — open tasks grouped by project
   - **Reminders** — any active reminders
   - **Recent Activity** — summary of recent commits and memory events
   - **Open PRs** — for each registered project with a github_url, run `gh pr list --repo <github_url> --author @me --state open` via Bash
2. Keep formatting clean and scannable — use bullet points.
