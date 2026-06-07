# Multi-Machine Sync

The companion's data directory (`~/.claude/mait-code-data/`) can be synchronised across machines using git.

## Setup

```bash
cd ~/.claude/mait-code-data
git init
```

### .gitignore

Not every database should be synced. `memory.db` is **regenerable** — the JSONL
observation logs under `memory/observations/` are its source of truth, so it is
gitignored and rebuilt with `mc-tool-memory restore` after a pull. The other
databases (`board.db`, `reminders.db`, `inbox.db`) have **no such source**, so
they are committed directly — gitignoring them would silently lose your board,
reminders, and inbox on every other machine.

Create `~/.claude/mait-code-data/.gitignore`:

```gitignore
# Regenerable from the observation logs (mc-tool-memory restore) — don't sync.
memory.db

# SQLite sidecar files (WAL mode) — never sync these.
*.db-wal
*.db-shm
*.db-journal

# Cached embedding models (large; re-downloaded on demand)
models/

# Temporary files
*.tmp
```

> `board.db`, `reminders.db`, and `inbox.db` are deliberately **not** ignored.
> They are small and have no source to rebuild from, so they travel with the
> repo. As SQLite binaries they don't merge cleanly — for a single user across
> machines the practical rule is to push from the machine you just worked on and
> pull before starting on another.

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
# Rebuild memory.db from the synced observation logs
mc-tool-memory restore
```

### Post-merge hook for auto DB restore

Create `~/.claude/mait-code-data/.git/hooks/post-merge`:

```bash
#!/usr/bin/env bash
# Restore memory DB from observation logs after pulling
if command -v mc-tool-memory &> /dev/null; then
    mc-tool-memory restore &
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

## Embedding Provider

Ensure the same embedding provider (`MAIT_CODE_EMBEDDING_PROVIDER`) is configured on all machines. If you switch providers (e.g. from `local` to `bedrock`), run `mc-tool-memory reindex` on each machine after pulling — it will detect the dimension mismatch and recreate the vec table automatically.

## Security Note

Your companion data may contain sensitive information (project details, preferences, work patterns). Use a **private** repository and consider encrypting sensitive fields in the future.
