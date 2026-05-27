---
name: standup
description: Generate a cross-project standup summary from git history, tasks, memory, and PRs. Use when you ask what to report, what you worked on across projects, or are prepping for a standup or check-in.
allowed-tools: Bash(git *), Bash(gh *), Bash(mc-tool-tasks *), Bash(mc-tool-memory *), Bash(mc-tool-reminders *)
---

# /standup

Generate a standup summary.

## Data

Open tasks (all projects):

!`mc-tool-tasks list-all 2>/dev/null || echo "No open tasks."`

Recent memories (last 24h):

!`mc-tool-memory list --since 24h --limit 15 --scope all 2>/dev/null || echo "No recent memories."`

Reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders."`

## Instructions

1. Fetch recent commits by running `git log --since="24 hours ago" --oneline --all --author="$(git config user.name)"` via Bash.
2. Using the data above plus the commit log, format a standup report with these sections:
   - **Yesterday** — what was accomplished (from git log and memories)
   - **Today** — what's planned (from open tasks and reminders)
   - **Blockers** — any issues or blockers (from memories/tasks, or "None" if clear)
3. Check for open PRs by running `gh search prs --author=@me --state=open --limit 20` via Bash. Include an **Open PRs** section if any are found.
4. Keep it concise — bullet points, not paragraphs.
