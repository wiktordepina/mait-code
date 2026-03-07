---
description: Bump the project version number across all locations
user-invocable: true
---

# Bump Version

Step-by-step instructions for bumping the mait-code project version.

## Semver guidance

- **Patch** (0.3.0 -> 0.3.1): Bug fixes, minor tweaks, no new features
- **Minor** (0.3.0 -> 0.4.0): New features, backward-compatible changes
- **Major** (0.3.0 -> 1.0.0): Breaking changes, major milestones

## Files to update

All three files **must** be updated to the same version string:

### 1. `pyproject.toml` (line ~7)

```toml
version = "X.Y.Z"
```

### 2. `src/mait_code/__init__.py` (line 1)

```python
__version__ = "X.Y.Z"
```

### 3. `CHANGELOG.md` (after line 2)

Add a new section at the top of the changelog (below the `# Changelog` heading):

```markdown
## vX.Y.Z — <Short Title> (<YYYY-MM-DD>)

<One-sentence summary of the release.>

- **Item:** Description
```

Use today's date. Follow the existing format — see previous entries for style.

## Procedure

1. Ask the user for the new version number and a short release title (if not provided)
2. Update `pyproject.toml`
3. Update `src/mait_code/__init__.py`
4. Add new section to `CHANGELOG.md` — ask the user for bullet points or draft them from recent commits
5. Run validation: `grep -rn "X.Y.Z" pyproject.toml src/mait_code/__init__.py CHANGELOG.md` to confirm all three files match
6. Commit with message: `chore: bump version to vX.Y.Z`
