---
name: reminders
description: Show active and overdue reminders
allowed-tools: Bash(mc-tool-reminders *)
---

# /reminders

Show active and overdue reminders.

## Instructions

Active reminders:

!`mc-tool-reminders list 2>/dev/null || echo "No reminders found."`

Present the results clearly. If the user wants to dismiss a reminder, run `mc-tool-reminders dismiss <id>` via Bash.
