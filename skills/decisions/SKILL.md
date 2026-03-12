---
name: decisions
description: Browse and search decision records for the current project
allowed-tools: Bash(mc-tool-decisions *)
---

# /decisions

Browse and search decision records for the current project.

## Instructions

Project decisions:

!`mc-tool-decisions list 2>/dev/null || echo "No decisions found."`

Present the results clearly. If the user wants to:

- **See details:** run `mc-tool-decisions show <id>`
- **Search:** run `mc-tool-decisions search <query>`
- **Amend:** run `mc-tool-decisions amend <id> [--context ...] [--status ...] [--tags ...]`
- **Supersede:** run `mc-tool-decisions supersede <old_id> <new_id>`
- **Remove:** run `mc-tool-decisions remove <id>`
- **Regenerate docs:** run `mc-tool-decisions sync`
