# How Memory Works

This guide explains how mait-code remembers things across sessions — from automatic observation extraction through to semantic search over accumulated knowledge.

## Overview

Memory flows through three tiers, from raw to refined:

```mermaid
graph LR
    C[Conversations] --> T1

    T1["**Tier 1: Observations**<br>*(raw)*<br>JSONL logs<br>memory.db<br>embeddings"]
    T2["**Tier 2: Reflections**<br>*(synthesised)*<br>Monthly summaries"]
    T3["**Tier 3: MEMORY.md**<br>*(curated)*<br>~150 lines<br>loaded every session"]

    T1 --> T2 --> T3
```

## Tier 1: Observations

### Automatic extraction

The `observe` hook fires on two events:

- **PreCompact** — when Claude Code's context window fills up (runs async, no blocking)
- **SessionEnd** — when a session closes (runs async, no blocking)

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
| `scope` | `global`, `project`, or `branch` (controls visibility) |
| `project` | Project identifier (null for global scope) |
| `branch` | Git branch (set only for branch scope) |
| `created_at` | Timestamp, refreshed on deduplication |

### Scoping

Memories are scoped so that branch-local context (e.g. "we're spiking foo on this branch") doesn't leak into other projects.

- **global** — visible everywhere (e.g. "user prefers tabs over spaces")
- **project** — visible across all branches of one project
- **branch** — visible only on one branch of one project

At write time the default is: `branch` if both project and branch are detected, `project` if only project is detected, otherwise `global`. Override with `--scope`. At query time, the CLI filters to the current context by default; pass `--scope all` to disable filtering, or `--project`/`--branch` to override the auto-detection.

The project is the basename of the git root (or working directory). If you rename a working directory, its slug changes and memories split across two names. A **project-alias map** keeps them unified: create `project-aliases.json` in the data directory mapping old slugs to canonical ones, e.g. `{"h-cc-bridge": "hermes-cc-bridge"}`. New writes are canonicalised automatically; run `mc-tool-memory canonicalize-projects` once to rewrite existing rows under the old slug.

### Keyword search (FTS5)

Every entry is automatically indexed in a full-text search table using SQLite's FTS5 extension. This enables fast keyword matching with BM25 relevance ranking. Triggers keep the FTS index in sync on insert, update, and delete.

### Vector search (sqlite-vec)

Every entry gets a vector embedding stored in a `vec0` virtual table for semantic search via cosine distance.

#### Embedding providers

Two providers are supported, configured via the `embedding-provider` setting in `$XDG_CONFIG_HOME/mait-code/settings.toml`:

| Provider | Value | Model | Dimensions | Use case |
|----------|-------|-------|-----------|----------|
| **Local** (default) | `local` | `nomic-ai/nomic-embed-text-v1.5` via fastembed | 768 | Personal use — runs locally via ONNX Runtime |
| **AWS Bedrock** | `bedrock` | `amazon.titan-embed-text-v2:0` (default) | 1024 | Corporate environments where HuggingFace is blocked |

**Configuration:**

All embedding settings live in `~/.config/mait-code/settings.toml` (or `$XDG_CONFIG_HOME/mait-code/settings.toml`). The file is written by `mait-code install` and `mait-code update`, and can also be edited by hand. Environment variables (`MAIT_CODE_*`) override settings file values when set.

| Setting key | Env var override | Default | Description |
|-------------|-----------------|---------|-------------|
| `embedding-provider` | `MAIT_CODE_EMBEDDING_PROVIDER` | `local` | `local` (fastembed) or `bedrock` |
| `embedding-model` | `MAIT_CODE_EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | Model for local provider |
| `bedrock-region` | `MAIT_CODE_BEDROCK_REGION` | `eu-west-2` | AWS region for Bedrock |
| `bedrock-model-id` | `MAIT_CODE_BEDROCK_MODEL_ID` | `amazon.titan-embed-text-v2:0` | Bedrock model ID |

Run `mait-code settings` to see the active configuration and where each value comes from.

**Derived values (read-only):** `mait-code settings` also reports values that are *computed* rather than configured — listed with source `derived`. They can't be set, but they answer "where does my data live?" and "why does a provider switch force a reindex?":

| Derived value | Computed from |
|---------------|---------------|
| `embedding-dim` | provider + model (768 for local nomic, 1024 for Bedrock Titan v2) |
| `memory-db-path`, `tasks-db-path`, `decisions-db-path`, `reminders-db-path` | `data-dir` |
| `model-cache-dir` | `data-dir` + `/models` (local model cache, can be ~550MB) |
| `observations-dir` | `data-dir` + `/memory/observations` |
| `project-aliases-path` | `data-dir` + `/project-aliases.json` |

**Important:** The embedding dimension is a deployment-time decision. Once you commit to a provider and start storing embeddings, switching providers requires a `mc-tool-memory reindex` which detects the dimension mismatch and recreates the vec table. Run `mait-code settings` to see the active provider and whether it still matches the one recorded at install time — it flags drift and points you at `reindex`.

#### Advanced settings

The settings file also carries an **Advanced** section of operational knobs, written **commented-out** so the built-in default stays in effect until you deliberately uncomment a line. They never need touching for normal use; bad values fall back to the default and are flagged by `mait-code doctor`.

| Setting key | Env var override | Default | Description |
|-------------|-----------------|---------|-------------|
| `log-backup-count` | `MAIT_CODE_LOG_BACKUP_COUNT` | `14` | Days of rotated log files to keep |
| `extraction-model` | `MAIT_CODE_EXTRACTION_MODEL` | `haiku` | Model used for memory extraction |
| `reflection-model` | `MAIT_CODE_REFLECTION_MODEL` | `haiku` | Model used for reflection synthesis |
| `llm-timeout` | `MAIT_CODE_LLM_TIMEOUT` | `90` | Timeout (seconds) for subprocess LLM calls |
| `reflection-batch-size` | `MAIT_CODE_REFLECTION_BATCH_SIZE` | `50` | Default `--batch-size` for reflection |
| `reflection-novelty-gate` | `MAIT_CODE_REFLECTION_NOVELTY_GATE` | `3` | Default `--min-new` for reflection |
| `git-timeout` | `MAIT_CODE_GIT_TIMEOUT` | `5` | Timeout (seconds) for git context probes |

#### How it works

- **On store:** the content is embedded and the vector is stored in a `vec0` virtual table alongside the entry. For the local provider, content is prefixed with `"search_document: "` (nomic-embed requires this); Bedrock providers receive raw text.
- **On search:** the query is embedded (with `"search_query: "` prefix for local). sqlite-vec finds the nearest neighbours by cosine distance.
- **On delete:** a database trigger automatically removes the corresponding embedding.
- **Model caching (local):** the ONNX model (~550 MB) downloads on first use and caches in `~/.claude/mait-code-data/models/`.
- **Graceful degradation:** if the provider fails to load (missing `fastembed` or `boto3`), everything falls back to keyword-only search. Memory storage is never blocked by embedding failures.
- **Corporate proxy support:** the `truststore` package injects the OS trust store into Python's `ssl` module, so model downloads and API calls work behind corporate proxies (e.g. Netskope) without manual certificate management.

#### Corporate setup (Bedrock)

If HuggingFace is blocked on your corporate network, use the Bedrock provider:

1. Install with the bedrock flag: `mait-code install --from <source> --embedding-provider bedrock`
   (or re-install if already installed)
2. Ensure AWS credentials are available (e.g. via `aws configure` or IAM role)
3. If you have existing local embeddings, run `mc-tool-memory reindex` to migrate

The install command writes `embedding-provider = "bedrock"` to `~/.config/mait-code/settings.toml` and propagates it to `~/.claude/settings.json` automatically.

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

### Tuning (advanced)

The scoring and deduplication knobs are exposed as **advanced** settings (commented-out in `settings.toml`). They directly affect retrieval quality — leave them alone unless you know why you're changing them, and re-check with `mait-code doctor`, which validates ranges and the weight sum.

| Setting key | Default | Sensible range | Notes |
|-------------|---------|----------------|-------|
| `score-weight-recency` | `0.3` | 0.0–1.0 | The three weights **must sum to 1.0**; a bad sum falls back to defaults and is flagged by `doctor`. |
| `score-weight-importance` | `0.3` | 0.0–1.0 | |
| `score-weight-relevance` | `0.4` | 0.0–1.0 | |
| `half-life-episodic` | `3.0` | days | Too short and events vanish; too long and they crowd out facts. |
| `half-life-semantic` | `90.0` | days | Too short and facts fade; too long and stale facts persist. |
| `dedup-string-threshold` | `0.85` | 0.0–1.0 | Too low misses near-duplicates; too high admits false positives. |
| `dedup-vector-threshold` | `0.92` | 0.0–1.0 | Same trade-off, on cosine similarity. |
| `scope-boost-global` | `0.7` | 0.0–1.0 | Relevance multiplier for global memories. |
| `scope-boost-cross-project` | `0.3` | 0.0–1.0 | Relevance multiplier across project boundaries. |

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
- **Input:** Unreflected memory entries + current MEMORY.md
- **Process:** Calls Claude Haiku to identify patterns, themes, and recurring issues across entries
- **Output:** 3-5 insights stored as `type=insight` in memory.db (importance=6)
- **MEMORY.md proposals:** High-confidence facts are proposed as additions for user approval
- **Idempotent:** A per-project watermark tracks the last reflected entry ID. Each observation is only reflected on once.
- **Novelty gate:** Skips reflection if fewer than 3 unreflected entries exist
- **Batching:** Processes entries in configurable batches (default 50), oldest first

### Usage

```
/reflect                                    # Standard reflection
mc-tool-memory reflect --days 14            # Bootstrap window for first reflection
mc-tool-memory reflect --min-new 0          # Force reflection (skip novelty gate)
mc-tool-memory reflect --drain              # Process all unreflected entries in batches
mc-tool-memory reflect --batch-size 20      # Limit entries per batch
```

### How it works

1. Checks the novelty gate — counts unreflected non-insight entries (entries with ID > watermark)
2. Gathers unreflected `memory_entries` (excluding insights to avoid feedback loops), limited by batch size
3. Sends entries + MEMORY.md to Claude Haiku with a synthesis prompt
4. Parses `INSIGHT:` lines and `MEMORY_UPDATE:` proposals from the response
5. Stores insights in memory.db
6. Advances the watermark to the highest entry ID processed
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
| `stats` | Entry counts, class/scope/project distribution, embedding coverage, provider info |
| `entities [query]` | Search or list knowledge graph entities |
| `relationships <entity>` | Show relationships for an entity |
| `reindex` | Recompute all vector embeddings from scratch |
| `restore` | Replay observation JSONL logs into the database, then reindex |
| `restore --dry-run` | Show what would be restored without writing |
| `canonicalize-projects` | Rewrite stored project slugs per the project-alias map |
| `canonicalize-projects --dry-run` | Show what would change without writing |
| `reflect` | Synthesise unreflected observations into insights |
| `reflect --days 14` | Bootstrap window for first reflection |
| `reflect --min-new 0` | Force reflection (skip novelty gate) |
| `reflect --batch-size 20` | Limit entries per batch (default 50) |
| `reflect --drain` | Loop until all unreflected entries are processed |

**Scope flags** apply to `search`, `store`, `list`, and `reflect`:

| Flag | Effect |
|------|--------|
| `--project <name>` | Override auto-detected project |
| `--branch <name>` | Override auto-detected branch |
| `--scope global\|project\|branch` | Filter (or set, on `store`) to a specific scope |
| `--scope all` | Query-time: disable scope filtering entirely |

### Tasks tool (`mc-tool-tasks`)

| Command | Description |
|---------|-------------|
| `add <title> [--priority high]` | Add a task for the current project |
| `list [--all]` | List open (or all) tasks for the current project |
| `done <id>` | Mark a task as completed |
| `remove <id>` | Remove a task |
| `check [--project <name>]` | Check open tasks (used by session_start hook) |
| `list-all` | List open tasks across all projects |

### Skills

| Skill | Usage |
|-------|-------|
| `/recall <query>` | Search memory (results injected via preprocessing) |
| `/remember <content>` | Manually store a memory |
| `/reflect` | Synthesise observations into insights, propose MEMORY.md updates |
| `/remind <when> <what>` | Set a reminder |
| `/reminders` | Show active and overdue reminders |
| `/task <title>` | Add a task for the current project |
| `/tasks` | Show open tasks for the current project |
| `/decision <title>` | Record a technical decision |
| `/decisions` | Browse and search decision records |
| `/web-fetch <url>` | Fetch a web page as markdown (bypasses claude.ai proxy) |
| `/commit` | Detect changes, generate conventional commit, confirm and commit |
| `/standup` | Standup summary from git, tasks, memory, and PRs |
| `/work-history [period]` | Project work history (today/yesterday/week) |
| `/today` | Daily overview — tasks, reminders, activity, PRs |
| `/status` | Generate STATUS.md for current project |
| `/prs` | List open PRs across all projects |

## Multi-Machine Sync

The data directory can be synced via git. Binary databases (`*.db`) are gitignored — after pulling on a new machine, run `mc-tool-memory restore` to replay the synced observation logs into the database and reindex embeddings. If the database already has entries and you only need to recompute embeddings, use `mc-tool-memory reindex`. See [Multi-Machine Sync](sync.md) for the full workflow.
