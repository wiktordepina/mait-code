# How Memory Works

This guide explains how mait-code remembers things across sessions — from automatic observation extraction through to semantic search over accumulated knowledge.

## Overview

Memory flows through three tiers, from raw to refined:

```mermaid
graph LR
    C[Conversations] --> T1

    T1["**Tier 1: Observations**<br>*(raw)*<br>JSONL logs<br>memory.db<br>embeddings"]
    T2["**Tier 2: Reflections**<br>*(synthesised)*<br>batch synthesis<br>via /reflect"]
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
| **Decisions** | `decision` (semantic) | "Chose REST over GraphQL for the public API" |
| **Procedures** | `procedure` (procedural) | "To debug a failing pages deploy: check the env protection rules first, then the tag ref" |
| **Bugs fixed** | `event` (episodic) | "Fixed race condition in the connection pool" |
| **Entities** | knowledge graph | People, projects, tools, services, concepts, organisations |
| **Relationships** | knowledge graph | "User → contributes_to → mait-code", "mait-code → depends_on → sqlite-vec" |

Each item includes an importance rating (1-10) that influences search ranking.

The boundary between the three semantic-adjacent categories: a **procedure**
answers *"how do I do X next time?"* (a repeatable workflow, usually with
steps); a **decision** answers *"what did we pick?"* (a choice made once); a
**preference** answers *"what does the user like?"*.

### Raw observation logs

Every extraction is also appended to a daily JSONL file at `~/.claude/mait-code-data/memory/observations/YYYY-MM-DD.jsonl`. These serve as the source of truth — the database can be restored from them using `mc-tool-memory restore`.

To *see* this tier — what's been captured, and what's still waiting for
reflection — open the [observations browser](observations.md) with
`mait-code observations`.

### Deduplication

Before storing a new memory, the writer checks for near-duplicates:

1. Extracts key words from the new content
2. Gathers candidates from both FTS5 keyword search and vector similarity search (scoped to the entry's project)
3. Compares candidates two ways — `SequenceMatcher` string similarity ≥ 0.85, or vector cosine similarity ≥ 0.92; a hit on either marks it a duplicate
4. Duplicates update the existing entry's timestamp and keep the highest importance

This means the same fact can be re-observed across sessions without creating clutter. Superseded entries (see below) are never offered as duplicate candidates.

### Evolving memory: supersede, don't duplicate

A duplicate is the *same* fact restated. A **contradiction** is a related-but-different fact — "uses X" when an earlier entry says "uses Y". Those sit below the dedup thresholds, so they aren't merged. Instead the writer flags them:

- Cosine similarity in the band `[dedup-conflict-threshold, dedup-vector-threshold)` (default `[0.60, 0.92)`) marks a **possible conflict**.
- The new entry is still stored — the write is never blocked. `store_memory` returns the conflicting entries under `potential_conflicts`, and `mc-tool-memory store` prints a `⚠ This may contradict …` notice.

When a fact has genuinely changed, replace the stale entry rather than letting two coexist:

```bash
mc-tool-memory supersede <old_id> "<new, current content>"
```

This inserts the new content as a fresh entry (inheriting the old one's type and scope), then marks the old entry **superseded** — recording `superseded_by` (the new id) and `superseded_at` (the timestamp). The old row is kept for auditability but hidden from all default search, listing, and dedup. To see superseded entries:

```bash
mc-tool-memory list --include-superseded
```

Supersede is one of three consolidation moves that leave a row in place but drop it from the live set:

```bash
mc-tool-memory supersede <old_id> "<new content>"        # replace one entry
mc-tool-memory merge <id1> <id2> … --into "<consolidated>"  # fold several into one
mc-tool-memory retire <id>                                # drop a stale entry, no replacement
```

**Merge** is the N→1 counterpart to supersede: it inserts one consolidated entry (inheriting type/scope from the first row, importance promoted to the max of the sources) and points every merged row's `superseded_by` at it. **Retire** drops a fact that has no successor — it stamps `superseded_at` while leaving `superseded_by` null. A row is **live** (surfaced by default) only when *both* are null; superseded and retired rows are hidden from all default search, listing, and dedup but kept for audit.

This is manually-driven: the companion *suggests* these moves — during [reflection](#tier-2-reflections), or when it spots a conflict — and you decide. Nothing is replaced automatically.

### Review: keeping curated memory fresh

Left alone, an important fact can quietly go stale — still stored, never re-checked. **Review resurfacing** surfaces important-but-ageing memories for a quick "still true? refine? promote? retire?" pass.

It reuses the same per-class exponential decay that ranks retrieval (see [Recency](#recency)), but measured from a memory's `reviewed_at` anchor rather than `created_at`. A memory is **due for review** when its recall probability has fallen below `review-threshold` (default `0.5` — one half-life since it was last reviewed) *and* its `importance` is at least `review-min-importance` (default `5`, so trivia decays without nagging).

```bash
mc-tool-memory review                 # list memories due for review, most-decayed first
mc-tool-memory review --json          # same, as structured JSON
mc-tool-memory reviewed <id>          # mark one reviewed — stamps reviewed_at = now, resetting its curve
```

Reviewing an entry (confirming, refining, or retiring it) resets its decay curve so it drops out of the due set until a fresh half-life passes. The home hub (`mait-code`) shows a **Due for review** count under Memory, and [`mait-code review`](review.md) is the interactive way to work the batch — confirm, refine, or retire each in place, without reaching for the CLI. This is a nudge, not an alarm: nothing is changed for you.

## Storage: The Memory Database

All structured data lives in a single SQLite file (`memory.db`) with three search layers:

### Memory entries

The core table stores every observation with metadata:

| Field | Description |
|-------|-------------|
| `content` | The memory text |
| `entry_type` | `fact`, `preference`, `event`, `decision`, `procedure`, `insight`, `task`, `relationship` |
| `importance` | 1-10 scale |
| `memory_class` | `episodic` (fast decay), `semantic` (slow decay), or `procedural` (slowest decay) |
| `scope` | `global`, `project`, or `branch` (controls visibility) |
| `project` | Project identifier (null for global scope) |
| `branch` | Git branch (set only for branch scope) |
| `created_at` | Timestamp, refreshed on deduplication |
| `reviewed_at` | When the memory was last reviewed — the anchor for [review resurfacing](#review-keeping-curated-memory-fresh) (null = never, treated as `created_at`) |
| `superseded_by` | Id of the entry that replaced this one (null = current) |
| `superseded_at` | When it was superseded (null = current) |

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

Run `mait-code settings list` to see the active configuration and where each value comes from, or bare `mait-code settings` to edit it interactively. To change one value non-interactively, use `mait-code settings set <key> <value>` — it validates the value, persists it to `settings.toml`, keeps any mirrored entry in `~/.claude/settings.json` in step, and warns if a shell export still shadows the change.

**Derived values (read-only):** `mait-code settings` also reports values that are *computed* rather than configured — listed with source `derived`. They can't be set, but they answer "where does my data live?" and "why does a provider switch force a reindex?":

| Derived value | Computed from |
|---------------|---------------|
| `embedding-dim` | provider + model (768 for local nomic, 1024 for Bedrock Titan v2) |
| `memory-db-path`, `reminders-db-path` | `data-dir` |
| `model-cache-dir` | `data-dir` + `/models` (local model cache, can be ~550MB) |
| `observations-dir` | `data-dir` + `/memory/observations` |
| `project-aliases-path` | `data-dir` + `/project-aliases.json` |

**Important:** The embedding dimension is a deployment-time decision. Once you commit to a provider and start storing embeddings, switching providers requires re-embedding, which detects the dimension mismatch and recreates the vec table. The simplest path is `mait-code settings set embedding-provider bedrock --reindex` (a migration key requires an explicit `--reindex`/`--no-reindex`), which re-embeds in one step; the interactive editor offers the same as an inline confirmation. You can still set the env var by hand and run `mc-tool-memory reindex` yourself. `mait-code settings list` shows the active provider and whether it still matches the one recorded at install time — it flags drift and points you at `reindex`.

#### Advanced settings

The settings file also carries an **Advanced** section of operational knobs, written **commented-out** so the built-in default stays in effect until you opt in — either with `mait-code settings set <key> <value>` (which writes the line active) or by uncommenting it by hand. They never need touching for normal use; bad values fall back to the default and are flagged by `mait-code doctor`.

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
2. Ensure AWS credentials are available (e.g. via `aws configure` or IAM role).
   If you authenticate via a named profile, declare it once in the `[env]`
   table of `settings.toml` so every tool picks it up — inside and outside
   Claude Code sessions:

   ```toml
   [env]
   AWS_PROFILE = "dev-bedrock"
   ```

   See [Custom environment variables](settings.md#custom-environment-variables-the-env-table).
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

Both vocabularies are canonical and enforced at write time: entity types
(`person`, `project`, `tool`, `service`, `concept`, `org`) coerce to `unknown`
when the extraction model invents something else, and relationship types
(`uses`, `owns`, `contributes_to`, `depends_on`, `manages`, `related_to`)
coerce to `related_to`. The extraction prompt enums are built from the same
tuples (`ENTITY_TYPES`, `RELATIONSHIP_TYPES` in `tools/memory/entities.py`),
so prompt and enforcement cannot drift. Every relationship carries a free-text
context field explaining the connection.

The graph has its own interactive surface — [the graph
explorer](graph.md) (`mait-code graph`) — which renders any entity's
neighbourhood as a node-link diagram or a flat relationship table.

Aliases the extractor coins for the same thing (e.g. `User` alongside the
user's actual name) can be folded together with
`mc-tool-memory entities merge <source> <target>`: the source's relationships
are repointed to the target (deduplicating where the target already has the
edge), mention counts are summed, the seen window widens to span both, and
the source entity is deleted.

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
| Semantic | `fact`, `preference`, `decision`, `insight`, `relationship` | 90 days | Persists — architectural decisions stay relevant for months |
| Procedural | `procedure` | 180 days | Most durable — workflows go stale when superseded, not with time |

Formula: `recency = exp(-ln(2) × age_days / half_life)`

### Importance

Normalized from the 1-10 scale to 0.0-1.0: `(importance - 1) / 9`

### Relevance

Depends on search mode:

- **Hybrid:** cosine similarity from vector search (for entries found by both methods)
- **FTS:** hardcoded 0.7 (BM25 already filtered for relevance)
- **Vector:** cosine similarity converted from distance

### Tuning (advanced)

The scoring and deduplication knobs are exposed as **advanced** settings (commented-out in `settings.toml`). They directly affect retrieval quality — leave them alone unless you know why you're changing them, and re-check with `mait-code doctor`, which validates ranges and the weight sum. The dedup, half-life and scope-boost knobs can be changed with `mait-code settings set`. The three scoring **weights** can't (setting one alone would leave a transient invalid sum) — retune all three together in the interactive editor (`mait-code settings`), which enforces the sum before saving, or edit `settings.toml` by hand and let `doctor` validate the result.

| Setting key | Default | Sensible range | Notes |
|-------------|---------|----------------|-------|
| `score-weight-recency` | `0.3` | 0.0–1.0 | The three weights **must sum to 1.0**; a bad sum falls back to defaults and is flagged by `doctor`. |
| `score-weight-importance` | `0.3` | 0.0–1.0 | |
| `score-weight-relevance` | `0.4` | 0.0–1.0 | |
| `half-life-episodic` | `3.0` | days | Too short and events vanish; too long and they crowd out facts. |
| `half-life-semantic` | `90.0` | days | Too short and facts fade; too long and stale facts persist. |
| `half-life-procedural` | `180.0` | days | Procedures decay when superseded, not with time — keep this long. |
| `dedup-string-threshold` | `0.85` | 0.0–1.0 | Too low misses near-duplicates; too high admits false positives. |
| `dedup-vector-threshold` | `0.92` | 0.0–1.0 | Same trade-off, on cosine similarity. Also the upper edge of the conflict band. |
| `dedup-conflict-threshold` | `0.60` | 0.0–1.0 | Lower edge of the contradiction band. Too low floods every write with spurious conflicts; too high lets real contradictions slip through as separate facts. |
| `scope-boost-global` | `0.7` | 0.0–1.0 | Relevance multiplier for global memories. |
| `scope-boost-cross-project` | `0.3` | 0.0–1.0 | Relevance multiplier across project boundaries. |
| `review-threshold` | `0.5` | 0.0–1.0 | Recall probability below which a memory is [due for review](#review-keeping-curated-memory-fresh). `0.5` = one half-life since last review; lower surfaces only more-decayed items. |
| `review-min-importance` | `5` | 1–10 | Importance floor for review resurfacing; memories below it decay without nagging. |

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
2. Gathers unreflected `memory_entries` (excluding insights to avoid feedback loops), limited by batch size — each is shown to the model with its `#id`
3. Sends entries + MEMORY.md to Claude Haiku with a synthesis prompt
4. Parses `INSIGHT:` lines and structured MEMORY.md **operations** from the response — `add`, `rewrite`, `merge`, and `retire`, each optionally naming the backing entry `#id`s to consolidate in the store
5. Stores insights in memory.db
6. Advances the watermark to the highest entry ID processed
7. Presents the operations as a before/after diff for **per-op** user approval; approved ops are applied to MEMORY.md and — where they name backing entries — carried through to the store via `supersede`/`merge`/`retire`

## Tier 3: MEMORY.md (Curated)

`~/.claude/mait-code-data/memory/MEMORY.md` is loaded into every Claude Code session via the `@MEMORY.md` reference in CLAUDE.md. It contains the highest-confidence, most stable facts — things the companion should always know.

**Constraints:**

- ~150 lines maximum (context budget)
- Organised by topic, not chronologically
- Updated by the reflection system (`/reflect`), which proposes additions, rewrites, merges, and retirements for per-op user approval — it consolidates the file, not just grows it

**Examples of what belongs here:**

- "User works with Kubernetes on GKE"
- "Preferred test runner: pytest with -x flag"
- "Auth service: JWT with RS256, token refresh every 15 minutes"

**What does NOT belong here:**

- Temporary tasks or in-progress work
- Session-specific details
- Anything that changes frequently
- Per-project *code* facts — those belong to Claude Code's native auto memory (see below)

## The Other Curated Layer: Claude Code's Native Auto Memory

Claude Code (v2.1.59+) ships its own **auto memory**: a per-project directory
at `~/.claude/projects/<munged-path>/memory/` holding a `MEMORY.md` index plus
one markdown file per fact, loaded automatically into that project's sessions.
It sits alongside mait-code's curated tier — two curated layers that would
drift and double-spend context tokens if they carried the same facts.

mait-code keeps them **cleanly separated** rather than merged:

| Layer | Carries | Scope | Maintained by |
|-------|---------|-------|---------------|
| **Native auto memory** | Code facts: architecture, build/test commands, repo gotchas | Per project | Claude Code itself |
| **mait-code memory** | User/identity facts: preferences, conventions, working style, cross-project decisions | Cross-project | The three-tier pipeline above |

The routing rule of thumb: **facts about the project belong in the native
layer; facts about you belong in mait-code.** The `/reflect` and
`memory-store` skills apply this rule when deciding where a fact goes, so
project-specific code knowledge no longer accretes into mait-code's
MEMORY.md.

The native directory name is the project's absolute path with `/` replaced by
`-` (`/home/w/mait-code` → `-home-w-mait-code`). That munging is lossy — a
literal dash is indistinguishable from a path separator — so the memory
browser's native view recovers readable project names best-effort, by
checking which candidate paths actually exist on disk.

Both layers are visible from one surface: the [memory
browser](#memory-browser-mait-code-memory)'s native view (`n`) lists every
project's native memory files, read-only, regardless of where the browser was
launched.

## CLI Reference

### Memory tool (`mc-tool-memory`)

| Command | Description |
|---------|-------------|
| `search <query>` | Hybrid search (FTS5 + vector) with composite scoring |
| `search <query> --mode fts` | Keyword-only search |
| `search <query> --mode vector` | Semantic-only search |
| `search <query> --type fact` | Filter by entry type |
| `store <content> --type preference --importance 8` | Store a memory manually (prints any contradiction warnings) |
| `supersede <old_id> <content>` | Replace an entry with an evolved version; the old one is kept for audit but hidden from recall |
| `merge <ids…> --into <content>` | Fold several entries into one consolidated entry (importance promoted to the max among them); the sources are kept for audit but hidden |
| `retire <id>` | Drop a stale entry with no replacement (kept for audit, hidden from recall) |
| `list` | Recent entries by creation time |
| `list --since 24h` | Filter by time period (`24h`, `7d`, `1w`, etc.) |
| `list --type event` | Filter by type |
| `list --include-superseded` | Include superseded entries (hidden by default) |
| `review` | List memories [due for review](#review-keeping-curated-memory-fresh) — recall decayed since last review, most-decayed first |
| `review --json` | Same, as structured JSON |
| `reviewed <id>` | Mark a memory reviewed, resetting its resurfacing decay curve |
| `delete <id>` | Delete an entry (embedding cleaned up by trigger) |
| `stats` | Entry counts, class/scope/project distribution, superseded and retired counts, embedding coverage, provider info, unreflected backlog + last reflection run |
| `entities [query]` | Search or list knowledge graph entities |
| `entities merge <source> <target>` | Fold one entity into another: repoint relationships, sum mentions, delete the source (quote multi-word names) |
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

**Scope flags** apply to `search`, `store`, `list`, `review`, and `reflect`:

| Flag | Effect |
|------|--------|
| `--project <name>` | Override auto-detected project |
| `--branch <name>` | Override auto-detected branch |
| `--scope global\|project\|branch` | Filter (or set, on `store`) to a specific scope |
| `--scope all` | Query-time: disable scope filtering entirely |

### Memory browser (`mait-code memory`)

Open the interactive, read-only memory browser with:

```bash
mait-code memory
```

This is a full-screen [Textual](https://textual.textualize.io/) app over the
same store: a tree of memories grouped by entry type on the left (newest
first, counts per group), and the selected memory's body — rendered as
markdown — with its metadata (created, importance, scope, class) on the
right. `/` filters the list live by substring, `p` narrows to one project,
`r` re-reads the store, and `?` shows the key cheat-sheet. It browses
*everything*, across projects and scopes — the reading companion to
`mc-tool-memory`'s query verbs.

`n` switches to the **native view**: Claude Code's [native auto
memory](#the-other-curated-layer-claude-codes-native-auto-memory) across
*every* project — not just the one the browser was launched from — grouped
by project, with each file's markdown rendered in the detail pane. The same
keys apply (`/` filters by file name or content, `p` narrows to one project,
`r` rescans, `n` returns to the store view). Like the rest of the browser
it is strictly read-only: the native layer is Claude Code's to maintain.

When you're not on a terminal that supports it (e.g. piping output, or in
CI), `mait-code memory` falls back to a read-only grouped summary.

### Observations browser (`mait-code observations`)

The memory browser's sibling over **Tier 1**: the same full-screen,
read-only layout, but scoped to the raw observations and their reflection
standing — grouped by capture day, each entry flagged pending or reflected
against the reflection watermark, with each day's capture sessions read from
the JSONL logs. It answers "what has the observe hook collected, and what
will the next `/reflect` chew on?" — see [the observations browser
guide](observations.md) for the full tour.

### Graph explorer (`mait-code graph`)

The knowledge graph's own surface: a mention-ranked entity list, the selected
entity's 1-hop neighbourhood as a node-link diagram or a flat relationship
table (`t` swaps), and a detail pane carrying each relationship's free-text
context. Single-mention and orphan entities are hidden by default (`a`
reveals them). See [the graph explorer guide](graph.md) for the full tour.

### Skills

| Skill | Usage |
|-------|-------|
| `/recall <query>` | Search memory (results injected via preprocessing) |
| `/remember <content>` | Manually store a memory |
| `/reflect` | Synthesise observations into insights, propose MEMORY.md updates |
| `/remind <when> <what>` | Set a reminder |
| `/reminders` | Show active and overdue reminders |
| `/web-fetch <url>` | Fetch a web page as markdown (bypasses claude.ai proxy) |
| `/commit` | Detect changes, generate conventional commit, confirm and commit |

## Multi-Machine Sync

The data directory can be synced via git. `memory.db` is regenerable, so it is gitignored — the JSONL observation logs are the source of truth. After pulling on a new machine, run `mc-tool-memory restore` to replay the synced observation logs into the database and reindex embeddings. If the database already has entries and you only need to recompute embeddings, use `mc-tool-memory reindex`. The other databases (`board.db`, `reminders.db`, `inbox.db`) have no such source and are committed instead. See [Multi-Machine Sync](sync.md) for the full workflow.
