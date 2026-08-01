# Multi-Machine Sync

The companion's data directory — `~/.claude/mait-code-data/` by default, wherever
`data-dir` points otherwise — can be synchronised across machines using git.

## Setup

```bash
cd ~/.claude/mait-code-data
git init
```

### .gitignore

All four databases — `memory.db`, `board.db`, `reminders.db`, `inbox.db` — are
committed. None of them can be rebuilt from anything else in the directory.

`memory.db` deserves a word, because it is easy to assume otherwise. The JSONL
observation logs under `memory/observations/` are the source for entries the
observe hook extracted, and `mc-tool-memory restore` replays them. But they are
not a source for anything else the database holds:

- memories you stored by hand, via `/remember` or `mc-tool-memory store`
- insights written back by `/reflect`
- review state (`reviewed_at`), which anchors every decay curve
- supersede, retire, and merge history

Gitignoring `memory.db` and restoring after a pull loses all of it. Restore is
also *additive* rather than authoritative: replaying an entry that already exists
resets its `created_at` to now, re-ageing it and skewing both its score and the
review queue. Treat `restore` as a recovery tool for a lost or corrupted
database, not as part of the sync loop.

Create a `.gitignore` in the data directory:

```gitignore
# SQLite sidecar files (WAL mode) — never sync these.
*.db-wal
*.db-shm
*.db-journal

# Local database backups
memory.db.bak-*

# Per-machine state — syncing these corrupts the other machine's bookkeeping.
bridge-state.json
memory/observations/cursors.json

# Cached embedding models (large; re-downloaded on demand)
models/

# Temporary files
*.tmp
```

> The two per-machine files matter. `bridge-state.json` is the Bridge's inbound
> drain watermark and `memory/observations/cursors.json` holds transcript byte
> offsets — both describe how far *this* machine has read. Shared, they make the
> other machine skip work it never did.

Everything else travels with the repo, including `dashboard.toml`, `bridge.json`,
and `project-aliases.json`. As SQLite binaries the databases don't merge cleanly
— for a single user across machines the practical rule is to push from the
machine you just worked on and pull before starting on another.

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
```

The databases arrive intact — there is no rebuild step.

### Recovering a lost memory database

If `memory.db` is deleted or corrupted and no good copy exists, replay the
observation logs:

```bash
mc-tool-memory restore
```

This recovers observation-derived entries only. Hand-stored memories, `/reflect`
insights, and review state have no log to replay from, so a restored database
comes back thinner than the one it replaces.

## Conflict Resolution

### MEMORY.md conflicts

MEMORY.md is the most likely file to have merge conflicts (both machines may update curated facts). To resolve:

1. Accept both versions — the file should stay under ~150 lines
2. Remove duplicates
3. Re-run `/reflect` to consolidate if needed

### Observation conflicts

Observations are timestamped files, so conflicts are rare. If they occur, keep both versions — the reflection system will deduplicate.

## Embedding Provider

The embedding provider lives in `$XDG_CONFIG_HOME/mait-code/settings.toml`, which
sits *outside* the data directory and so is not synced — set it on each machine:

```bash
mait-code settings set embedding-provider bedrock
```

Ensure every machine agrees. If you switch providers (e.g. from `local` to
`bedrock`), run `mc-tool-memory reindex` on each machine — it detects the
dimension mismatch and recreates the vec table automatically. `mait-code settings
set` offers the reindex as a follow-up.

## Security Note

Your companion data may contain sensitive information (project details,
preferences, work patterns), and `bridge.json` can hold a channel token. Use a
**private** repository and consider encrypting sensitive fields in the future.
