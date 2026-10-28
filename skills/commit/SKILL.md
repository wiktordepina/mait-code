---
name: commit
description: Commit changes with a generated conventional-commit message, after confirming with you. Use whenever you ask to commit, check in, or save changes — invoke this instead of running git commit directly, so messages stay conventional.
allowed-tools: Bash(git status --porcelain:*), Bash(git diff --stat), Bash(git diff --cached --stat), Bash(git diff --cached), Bash(git ls-files --others --exclude-standard:*), Bash(git add:*), Bash(git commit -m:*), Bash(git commit -F:*)
---

# /commit

Generate a conventional commit for the current changes.

## Current state

Staged changes (empty when nothing is staged):

!`git diff --cached --stat`

Unstaged changes (empty when there are none):

!`git diff --stat`

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
