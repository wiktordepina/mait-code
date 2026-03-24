---
name: bump
description: Bump the project version in pyproject.toml, __init__.py, and CHANGELOG.md. Use when the user asks to bump, update, or increment the version number.
argument-hint: "<version> [changelog title]"
allowed-tools: Read, Edit, Bash(git diff *)
---

# /bump

Bump the project version across all version-bearing files.

## Current versions

pyproject.toml:
!`grep '^version' pyproject.toml`

__init__.py:
!`grep '__version__' src/mait_code/__init__.py`

## Instructions

The user invokes this as `/bump <version>` or `/bump <version> <changelog title>`, or asks conversationally (e.g. "bump the version to 0.14.0", "update version number").

1. **Parse the version** from the user's argument. If no version is provided, ask for it.
   - Strip a leading `v` if present (e.g. `v0.14.0` → `0.14.0`)
   - Validate it looks like semver: `MAJOR.MINOR.PATCH` (all integers)
   - Reject invalid versions with a clear error

2. **Update both source files** to the new version using the Edit tool:
   - `pyproject.toml`: the `version = "..."` line
   - `src/mait_code/__init__.py`: the `__version__ = "..."` line

3. **Update CHANGELOG.md** — insert a new section after the `# Changelog` heading and before the first existing `## v...` entry:
   - Format: `## v<version> — <title> (YYYY-MM-DD)` where the date is today
   - If a changelog title was provided, use it
   - If no title was provided, use a placeholder like `TODO` and tell the user to fill it in
   - Add an empty line below the heading for the user to fill in later

4. **Show the diff** by running `git diff` so the user can review the changes.

5. **Do not commit.** Tell the user they can use `/commit` when ready.

## Examples

- `/bump 0.14.0 Configurable embedding providers` → updates all three files, changelog title is "Configurable embedding providers"
- `/bump 0.14.0` → updates all three files, changelog title placeholder
- "Can you bump the version to 1.0.0 for the public release?" → same as `/bump 1.0.0 Public release`
