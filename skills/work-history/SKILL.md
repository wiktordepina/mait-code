---
name: work-history
description: Show recent work history for current project (git log + memory)
argument-hint: "[today|yesterday|week]"
allowed-tools: Bash(git *), Bash(mc-tool-memory *), Bash(mc-tool-tasks *)
---

# /work-history

Show work history for the current project.

## Instructions

1. Parse the argument to determine the time period:
   - `today` (default if no argument) — since midnight today
   - `yesterday` — last 24-48 hours
   - `week` — last 7 days
2. Run the following via Bash, adjusting `--since` accordingly:
   - `git log --since="<period>" --oneline --all`
   - `mc-tool-memory list --since <period> --limit 30` (use `24h`, `48h`, or `7d`)
   - `mc-tool-tasks list --all` to show tasks completed in the period
3. Present a formatted work history grouped by day if spanning multiple days.
