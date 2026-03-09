---
name: commit
description: Detect changes, generate conventional commit message, confirm with user, commit
allowed-tools: Bash(git *)
---

# /commit

Generate a conventional commit for the current changes.

## Current state

Staged changes:

!`git diff --cached --stat 2>/dev/null || echo "No staged changes."`

Unstaged changes:

!`git diff --stat 2>/dev/null || echo "No unstaged changes."`

Untracked files:

!`git ls-files --others --exclude-standard 2>/dev/null | head -20`

## Instructions

1. Analyse the changes above. If nothing is staged, look at unstaged changes and untracked files and suggest what to stage.
2. If changes are staged, run `git diff --cached` via Bash to read the actual diff content.
3. Generate a conventional commit message:
   - Format: `type(scope): description` (scope is optional)
   - Types: feat, fix, refactor, docs, chore, test, style, perf, ci, build
   - Description should be concise, lowercase, no period at end
   - Add a blank line and body paragraph if the change is non-trivial
4. Present the proposed commit message and ask the user to confirm or edit.
5. On approval, stage files if needed and run `git commit -m "<message>"`.
6. Show the commit result.
