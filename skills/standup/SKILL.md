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

Registered projects:

!`mc-tool-tasks projects 2>/dev/null || echo "No projects registered."`

Recent memories (last 24h):

!`mc-tool-memory list --since 24h --limit 15 2>/dev/null || echo "No recent memories."`

Reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders."`

## Instructions

1. Using the data above, format a standup report with these sections:
   - **Yesterday** — what was accomplished (from git log and memories)
   - **Today** — what's planned (from open tasks and reminders)
   - **Blockers** — any issues or blockers (from memories/tasks, or "None" if clear)
2. For each registered project that has a github_url, run `gh pr list --repo <github_url> --author @me --state open` via Bash to check for open PRs. Include a **Open PRs** section if any are found.
3. Keep it concise — bullet points, not paragraphs.
