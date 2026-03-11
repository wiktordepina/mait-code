---
name: prs
description: List my open PRs across all known projects
allowed-tools: Bash(gh *)
---

# /prs

Show my open pull requests across all known projects.

## Data

My open PRs:

!`gh search prs --author=@me --state=open --limit 30 2>/dev/null || echo "Could not fetch PRs."`

## Instructions

1. Present results grouped by repository, showing for each PR:
   - PR number and title
   - Repository
   - Review status (if available — run `gh pr view <url> --json reviewDecision` for details if needed)
2. If there are no open PRs, say so briefly.
3. Show a total count at the end.
