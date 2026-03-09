# How Memory Works

This guide explains how mait-code remembers things across sessions — from automatic observation extraction through to semantic search over accumulated knowledge.

## Overview

Memory flows through three tiers, from raw to refined:

```
Conversations
      │
      ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Tier 1      │     │ Tier 2      │     │ Tier 3      │
│ Observations│ ──► │ Reflections │ ──► │ MEMORY.md   │
│ (raw)       │     │ (synthesised│     │ (curated)   │
│             │     │  — planned) │     │             │
│ JSONL logs  │     │ Monthly     │     │ ~150 lines  │
│ memory.db   │     │ summaries   │     │ loaded every│
│ embeddings  │     │             │     │ session     │
└─────────────┘     └─────────────┘     └─────────────┘
```

**Tier 1** is fully implemented and automatic. **Tier 2** is planned. **Tier 3** exists but is currently updated manually.

## Tier 1: Observations

### Automatic extraction

The `observe` hook fires on two events:

- **PreCompact** — when Claude Code's context window fills up (runs async, no blocking)
- **SessionEnd** — when a session closes (runs sync)

Each time, it:

1. Reads new transcript lines since the last invocation (cursor-based, incremental)
2. Sends them to Claude Haiku for structured extraction
3. Stores results in both the database and daily JSONL logs

### What gets extracted

Claude Haiku analyses the conversation and returns structured JSON:

| Category | Stored as | Examples |
|----------|-----------|---------|
| **Facts** | `fact` (semantic) | "The auth service uses JWT with RS256", "Database runs on PostgreSQL 16" |
| **Preferences** | `preference` (semantic) | "User prefers dark mode", "Always use tabs for Go code" |
| **Decisions** | `insight` (semantic) | "Chose REST over GraphQL for the public API" |
| **Bugs fixed** | `event` (episodic) | "Fixed race condition in the connection pool" |
| **Entities** | knowledge graph | People, projects, tools, services, concepts, organisations |
| **Relationships** | knowledge graph | "User → contributes_to → mait-code", "mait-code → depends_on → sqlite-vec" |

Each item includes an importance rating (1-10) that influences search ranking.

### Raw observation logs

Every extraction is also appended to a daily JSONL file at `~/.claude/mait-code-data/memory/observations/YYYY-MM-DD.jsonl`. These serve as the source of truth — the database can be restored from them using `mc-tool-memory restore`.

### Deduplication

Before storing a new memory, the writer checks for near-duplicates:

1. Extracts key words from the new content
2. Queries FTS5 for candidate matches (up to 20) of the same entry type
3. Compares using `SequenceMatcher` — if similarity >= 90%, it's a duplicate
4. Duplicates update the existing entry's timestamp and keep the highest importance

This means the same fact can be re-observed across sessions without creating clutter.

## Storage: The Memory Database

All structured data lives in a single SQLite file (`memory.db`) with three search layers:

### Memory entries

The core table stores every observation with metadata:

| Field | Description |
|-------|-------------|
| `content` | The memory text |
| `entry_type` | `fact`, `preference`, `event`, `insight`, `task`, `relationship` |
| `importance` | 1-10 scale |
| `memory_class` | `episodic` (fast decay) or `semantic` (slow decay) |
| `created_at` | Timestamp, refreshed on deduplication |

### Keyword search (FTS5)

Every entry is automatically indexed in a full-text search table using SQLite's FTS5 extension. This enables fast keyword matching with BM25 relevance ranking. Triggers keep the FTS index in sync on insert, update, and delete.

### Vector search (sqlite-vec)

Every entry also gets a 768-dimensional vector embedding computed by `nomic-ai/nomic-embed-text-v1.5` via the `fastembed` library (ONNX Runtime, no PyTorch required).

How it works:

- **On store:** the content is prefixed with `"search_document: "` and embedded. The vector is stored in a `vec0` virtual table alongside the entry.
- **On search:** the query is prefixed with `"search_query: "` and embedded. sqlite-vec finds the nearest neighbours by cosine distance.
- **On delete:** a database trigger automatically removes the corresponding embedding.
- **Model caching:** the ONNX model (~550 MB) downloads on first use and caches in `~/.claude/mait-code-data/models/`.
- **Graceful degradation:** if `fastembed` is not installed or the model fails to load, everything falls back to keyword-only search. Memory storage is never blocked by embedding failures.

### Hybrid search

The default search mode (`hybrid`) runs both FTS5 and vector search, then merges:

- Entries found by **both** methods use vector cosine similarity as the relevance score
- Entries found by **only one** method get a default relevance of 0.3
- All results are then ranked by the composite scoring formula (see below)

You can also force a single mode: `mc-tool-memory search "query" --mode fts` or `--mode vector`.

### Knowledge graph

Entities (people, projects, tools, services, concepts, organisations) and their relationships are stored in dedicated tables. Each entity tracks:

- Name (case-insensitive, deduplicated)
- Type (upgradeable — starts as `unknown`, refined when the real type is observed)
- Mention count (incremented each time the entity is seen)
- First and last seen timestamps

Relationships between entities are typed (`uses`, `owns`, `contributes_to`, `depends_on`, `manages`, `related_to`) with a free-text context field explaining the connection.

## Scoring: How Results Are Ranked

Search results are ranked by a composite score:

```
score = 0.3 × recency + 0.3 × importance + 0.4 × relevance
```

### Recency

Exponential decay based on memory class:

| Class | Types | Half-life | Effect |
|-------|-------|-----------|--------|
| Episodic | `event`, `task` | 3 days | Fades fast — yesterday's deploy matters less next week |
| Semantic | `fact`, `preference`, `insight`, `relationship` | 90 days | Persists — architectural decisions stay relevant for months |

Formula: `recency = exp(-ln(2) × age_days / half_life)`

### Importance

Normalized from the 1-10 scale to 0.0-1.0: `(importance - 1) / 9`

### Relevance

Depends on search mode:
- **Hybrid:** cosine similarity from vector search (for entries found by both methods)
- **FTS:** hardcoded 0.7 (BM25 already filtered for relevance)
- **Vector:** cosine similarity converted from distance

## Reminders

Reminders are a separate system stored in `reminders.db`. They are time-based triggers, not memories.

| Command | Description |
|---------|-------------|
| `mc-tool-reminders set "in 2 hours" check deploy` | Schedule a reminder |
| `mc-tool-reminders list` | Show active reminders |
| `mc-tool-reminders list --all` | Include dismissed reminders |
| `mc-tool-reminders dismiss <id>` | Dismiss a reminder |
| `mc-tool-reminders check` | Check for overdue (used by session_start hook) |

The session start hook automatically surfaces overdue reminders at the beginning of each session, so you don't need to manually check.

Time parsing uses `dateparser` with UTC normalisation — you can write `"tomorrow 9am"`, `"in 30 minutes"`, `"next friday"`, or ISO dates.

## Tier 2: Reflections

The reflection system synthesises recent observations into higher-level insights:

- **Trigger:** `/reflect` skill (manual)
- **Input:** Last 7 days of memory entries + observation JSONL logs + current MEMORY.md
- **Process:** Calls Claude Haiku to identify patterns, themes, and recurring issues across entries
- **Output:** 3-5 insights stored as `type=insight` in memory.db (importance=6)
- **MEMORY.md proposals:** High-confidence facts are proposed as additions for user approval
- **Novelty gate:** Skips reflection if fewer than 3 new observations since the last reflection

### Usage

```
/reflect                                    # Standard reflection (last 7 days)
mc-tool-memory reflect --days 14            # Reflect on last 14 days
mc-tool-memory reflect --min-new 0          # Force reflection (skip novelty gate)
```

### How it works

1. Checks the novelty gate — counts non-insight entries since the last `type=insight` was stored
2. Gathers recent `memory_entries` (excluding insights to avoid feedback loops)
3. Reads raw observation JSONL logs for richer context
4. Sends everything to Claude Haiku with a synthesis prompt
5. Parses `INSIGHT:` lines and `MEMORY_UPDATE:` proposals from the response
6. Stores insights in memory.db
7. Presents proposed MEMORY.md changes for user approval

## Tier 3: MEMORY.md (Curated)

`~/.claude/mait-code-data/memory/MEMORY.md` is loaded into every Claude Code session via the `@MEMORY.md` reference in CLAUDE.md. It contains the highest-confidence, most stable facts — things the companion should always know.

**Constraints:**
- ~150 lines maximum (context budget)
- Organised by topic, not chronologically
- Updated by the reflection system (`/reflect`) which proposes additions for user approval

**Examples of what belongs here:**
- "User works with Kubernetes on GKE"
- "Preferred test runner: pytest with -x flag"
- "Auth service: JWT with RS256, token refresh every 15 minutes"

**What does NOT belong here:**
- Temporary tasks or in-progress work
- Session-specific details
- Anything that changes frequently

## CLI Reference

### Memory tool (`mc-tool-memory`)

| Command | Description |
|---------|-------------|
| `search <query>` | Hybrid search (FTS5 + vector) with composite scoring |
| `search <query> --mode fts` | Keyword-only search |
| `search <query> --mode vector` | Semantic-only search |
| `search <query> --type fact` | Filter by entry type |
| `store <content> --type preference --importance 8` | Store a memory manually |
| `list` | Recent entries by creation time |
| `list --since 24h` | Filter by time period (`24h`, `7d`, `1w`, etc.) |
| `list --type event` | Filter by type |
| `delete <id>` | Delete an entry (embedding cleaned up by trigger) |
| `stats` | Entry counts, class distribution, embedding coverage |
| `entities [query]` | Search or list knowledge graph entities |
| `relationships <entity>` | Show relationships for an entity |
| `reindex` | Recompute all vector embeddings from scratch |
| `restore` | Replay observation JSONL logs into the database, then reindex |
| `restore --dry-run` | Show what would be restored without writing |
| `reflect` | Synthesise recent observations into insights |
| `reflect --days 14` | Reflect on last 14 days |
| `reflect --min-new 0` | Force reflection (skip novelty gate) |

### Tasks tool (`mc-tool-tasks`)

| Command | Description |
|---------|-------------|
| `add <title> [--priority high]` | Add a task for the current project |
| `list [--all]` | List open (or all) tasks for the current project |
| `done <id>` | Mark a task as completed |
| `remove <id>` | Remove a task |
| `check [--project <name>]` | Check open tasks (used by session_start hook) |
| `list-all` | List open tasks across all registered projects |
| `projects` | List all registered projects (name, path, GitHub URL) |

Projects are auto-registered when any task subcommand runs in a project directory.

### Skills

| Skill | Usage |
|-------|-------|
| `/recall <query>` | Search memory (results injected via preprocessing) |
| `/remember <content>` | Manually store a memory |
| `/reflect` | Synthesise observations into insights, propose MEMORY.md updates |
| `/remind <when> <what>` | Set a reminder |
| `/reminders` | Show active and overdue reminders |
| `/commit` | Detect changes, generate conventional commit, confirm and commit |
| `/standup` | Standup summary from git, tasks, memory, and PRs |
| `/work-history [period]` | Project work history (today/yesterday/week) |
| `/today` | Daily overview — tasks, reminders, activity, PRs |
| `/status` | Generate STATUS.md for current project |
| `/prs` | List open PRs across all registered projects |
| `/projects` | List all registered projects |

## Multi-Machine Sync

The data directory can be synced via git. Binary databases (`*.db`) are gitignored — after pulling on a new machine, run `mc-tool-memory restore` to replay the synced observation logs into the database and reindex embeddings. If the database already has entries and you only need to recompute embeddings, use `mc-tool-memory reindex`. See [Multi-Machine Sync](sync.md) for the full workflow.
