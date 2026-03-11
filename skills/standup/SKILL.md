---
name: standup
description: Generate standup summary from git history, tasks, memory, and PRs across all projects
allowed-tools: Bash(git *), Bash(gh *), Bash(mc-tool-tasks *), Bash(mc-tool-memory *), Bash(mc-tool-reminders *)
---

# /standup

Generate a standup summary.

## Data

Recent commits (current project):

!`git log --since="24 hours ago" --oneline --all 2>/dev/null || echo "No recent commits."`

Open tasks (all projects):

!`mc-tool-tasks list-all 2>/dev/null || echo "No open tasks."`

Recent memories (last 24h):

!`mc-tool-memory list --since 24h --limit 15 --scope all 2>/dev/null || echo "No recent memories."`

Reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders."`

## Instructions

1. Using the data above, format a standup report with these sections:
   - **Yesterday** — what was accomplished (from git log and memories)
   - **Today** — what's planned (from open tasks and reminders)
   - **Blockers** — any issues or blockers (from memories/tasks, or "None" if clear)
2. Check for open PRs by running `gh search prs --author=@me --state=open --limit 20` via Bash. Include an **Open PRs** section if any are found.
3. Keep it concise — bullet points, not paragraphs.
