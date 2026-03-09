---
name: prs
description: List open PRs across all registered projects
allowed-tools: Bash(gh *), Bash(mc-tool-tasks *)
---

# /prs

Show open pull requests across all registered projects.

## Data

Registered projects:

!`mc-tool-tasks projects 2>/dev/null || echo "No projects registered."`

## Instructions

1. For each registered project that has a github_url, run `gh pr list --repo <github_url> --state open --limit 20` via Bash.
2. Present results grouped by project, showing for each PR:
   - PR number and title
   - Author
   - Review status (if available via `gh pr list --json number,title,author,reviewDecision`)
3. If a project has no open PRs, note that briefly.
4. Show a total count at the end.
