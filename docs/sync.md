# Multi-Machine Sync

The companion's data directory (`~/.claude/mait-code-data/`) can be synchronised across machines using git.

## Setup

```bash
cd ~/.claude/mait-code-data
git init
```

### .gitignore

Create `~/.claude/mait-code-data/.gitignore`:

```gitignore
# Binary databases — rebuilt from markdown sources
*.db
*.db-journal

# Temporary files
*.tmp
```

### Initial commit

```bash
git add -A
git commit -m "Initial companion data"
git remote add origin <your-private-repo-url>
git push -u origin main
```

## Workflow

### Push changes after a session

```bash
cd ~/.claude/mait-code-data
git add -A
git commit -m "Update memories"
git push
```

### Pull on another machine

```bash
cd ~/.claude/mait-code-data
git pull
# Rebuild vector database from synced markdown
uv run --project /path/to/mait-code mc-tool-rebuild-db
```

### Post-merge hook for auto DB rebuild

Create `~/.claude/mait-code-data/.git/hooks/post-merge`:

```bash
#!/usr/bin/env bash
# Rebuild vector DB after pulling new observations
if command -v uv &> /dev/null; then
    uv run --project /path/to/mait-code mc-tool-rebuild-db &
fi
```

```bash
chmod +x ~/.claude/mait-code-data/.git/hooks/post-merge
```

## Conflict Resolution

### MEMORY.md conflicts

MEMORY.md is the most likely file to have merge conflicts (both machines may update curated facts). To resolve:

1. Accept both versions — the file should stay under ~150 lines
2. Remove duplicates
3. Re-run `/reflect` to consolidate if needed

### Observation conflicts

Observations are timestamped files, so conflicts are rare. If they occur, keep both versions — the reflection system will deduplicate.

## Security Note

Your companion data may contain sensitive information (project details, preferences, work patterns). Use a **private** repository and consider encrypting sensitive fields in the future.
