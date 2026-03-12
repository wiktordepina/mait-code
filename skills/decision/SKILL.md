---
name: decision
description: Record a technical decision for the current project
argument-hint: "[--status accepted|proposed] [--tags <tags>] <title>"
allowed-tools: Bash(mc-tool-decisions record *)
---

# /decision

Record a technical decision for the current project.

## Instructions

When the user invokes `/decision <args>`:

1. Parse the arguments. Pass through any `--status`, `--tags`, `--context`, `--alternatives`, or `--consequences` flags.

2. If the user provides only a title and no flags, ask them briefly about context and alternatives before recording. Keep it conversational — don't force a full ADR template if they just want a quick note.

3. Run: `mc-tool-decisions record [flags] <title>`

4. Confirm the decision was recorded.

## Proactive decision suggestions

During a session, if a significant technical choice is made (architecture, library selection, API design, trade-off resolution), you may **suggest** recording it as a decision. **Always ask for confirmation before recording** — never record decisions without the user's explicit approval.

Example: "That's a meaningful architectural choice. Want me to record it? e.g. `/decision --tags api,auth Use JWT with short-lived tokens`"

## Examples

- `/decision Use PostgreSQL for primary store` → prompts for context, then records
- `/decision --context "Need structured data" --tags db Use PostgreSQL` → `mc-tool-decisions record --context "Need structured data" --tags db Use PostgreSQL`
- `/decision --status proposed Migrate to gRPC` → `mc-tool-decisions record --status proposed Migrate to gRPC`
