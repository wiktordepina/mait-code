---
name: remind
description: Set a reminder for a future time
argument-hint: "<when> <what>"
disable-model-invocation: true
allowed-tools: Bash(mc-tool-reminders set *)
---

# /remind

Set a reminder for a future time.

## Instructions

When the user invokes `/remind <when> <what>`:

1. Parse the time and content from the arguments. The first word or phrase describing time is `when`, the rest is `what`.
   - Examples: "in 2 hours check deploy status", "tomorrow 9am standup prep", "friday review PR #42"

2. Run: `mc-tool-reminders set "<when>" <what>`

3. Confirm the reminder was set with the parsed time.

## Examples

- `/remind in 30 minutes check CI pipeline` → `mc-tool-reminders set "in 30 minutes" check CI pipeline`
- `/remind tomorrow 9am prepare standup notes` → `mc-tool-reminders set "tomorrow 9am" prepare standup notes`
- `/remind friday EOD submit timesheet` → `mc-tool-reminders set "friday EOD" submit timesheet`
