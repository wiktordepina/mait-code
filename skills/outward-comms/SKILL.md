---
name: outward-comms
description: House style for text written on the user's behalf for other people to read - no AI clichés, no em dashes, ASCII prose with glyphs only where they carry structure, concise and direct. Use before drafting or sending any PR comment, review reply, issue comment, chat or email message, PR description, or commit body; also when asked to check or rewrite existing text in this style.
argument-hint: "<optional: text to check or rewrite>"
allowed-tools: Bash(mait-code identity show writing_style:*)
---

# /outward-comms

The house style for text other people read. When invoked with text, rewrite it
to the rules below and show the result. When triggered while drafting, apply
the rules as you write and show the draft for approval.

## The rules

These come from the user's `writing_style.md` in the mait-code data directory,
which they own and edit:

!`mait-code identity show writing_style 2>/dev/null || echo "No writing_style.md in the mait-code data directory; run mait-code update to install it. Until then, apply only the scope, confirmation and pre-send rules below, and tell the user the style rules are missing."`

## Scope

**In scope** (text another person reads, written as the user):

- PR comments, review replies, PR titles and descriptions
- Issue tracker comments and descriptions
- Chat messages, emails
- Commit messages and commit bodies
- Docs, ADRs, runbooks committed to a repo

**Out of scope:** session replies to the user in the terminal, internal notes,
scratch files, memory entries. The rules are about how the user sounds to
other people, not about how the companion talks to them; that is
`communication_style.md`'s job.

The rules apply to new text. Don't rewrite existing docs or comments to match
unless asked; a line you touch anyway is fair game.

## Confirm before sending

Sending is outward-facing and hard to reverse. **Always show the user the exact
message and get an explicit go-ahead before posting it.** No exceptions for
"obvious" or short replies. The user often edits the draft or writes their own
from it, so a draft is a proposal, not a queued action.

This lives here rather than in `writing_style.md` on purpose: it is a safety
rule, not a matter of style.

## Pre-send pass

Run this over every draft before showing it:

1. Search for `—` and `–` (Rule 1).
2. Scan for any non-ASCII character: `rg -n '[^\x00-\x7F]'`. For each hit, is
   it carrying structure (Rule 2a), covered by an exception, or just
   decorating prose? Keep the first two, replace the third.
3. On anything long or dense, ask the inverse question too: would a table, a
   status column or a small diagram make this easier to take in than the
   prose does? A wall of text is a style problem, not a safe default.
4. Delete the first sentence. Did the message get worse? If not, leave it
   deleted.
5. Scan every sentence against Rule 3's lists.
6. Check the answer is in the first line or two, not buried.
7. Check the spelling convention (Rule 5).
8. Show it to the user. Wait for approval.

If the user's `writing_style.md` has renumbered or replaced these rules, follow
the file: the pass above names the shipped rules, and the file wins.

## Notes

- **The rules are the user's.** `writing_style.md` is seeded on install and
  never overwritten after the user edits it, so the skill picks up their
  changes with no edit here.
- **Why `mait-code identity show`, not `cat`.** Measured on Claude Code
  2.1.312: preprocessing that reads a file under `~/.claude/` is never run
  inline, whatever the grant (an exact pin, a prefix pin, and again after a
  restart). Claude Code swaps it for an instruction to run the command, so
  the rules would arrive only if the model obeys. A probe of this exact
  `mait-code identity show` line, grant included, ran inline, as `/board`'s
  `mc-tool-board list` does. The command also follows a custom `data-dir`.
