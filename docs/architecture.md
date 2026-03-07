# Architecture

## Design Principles

1. **No background services** — Everything runs reactively in response to Claude Code events (hooks, MCP requests, CLI invocations). No daemons, no cron jobs.
2. **Standalone project** — Self-contained Python package managed by `uv`. No system-wide installation required.
3. **Memory-first** — The memory system is the core differentiator. All other features feed into or read from memory.
4. **Companion identity** — Not a generic assistant. The soul document and user context create a consistent personality.
5. **uv-managed** — All Python execution goes through `uv run --project`. No manual venv activation.

## System Architecture

```
┌─────────────────────────────────────────────────┐
│                  Claude Code                    │
│                                                 │
│ ┌───────────┐  ┌─────────────┐  ┌─────────────┐ │
│ │ CLAUDE.md │  │    Hooks    │  │   Skills    │ │
│ │ (identity │  │             │  │             │ │
│ │  + rules) │  │ SessionStart│  │ /recall     │ │
│ │           │  │ PreCompact  │  │ /remember   │ │
│ │ @soul_doc │  │ SessionEnd  │  │ memory-store│ │
│ │ @user_ctx │  │             │  │             │ │
│ │ @MEMORY   │  └────┬────────┘  └──────┬──────┘ │
│ └───────────┘       │                  │        │
└─────────────────────┼──────────────────┼────────┘
                      │                  │
              ┌───────▼──────────────────▼────────┐
              │        mait-code (Python)         │
              │                                   │
              │  hooks/          tools/           │
              │    session_start   memory (CLI)   │
              │    observe         reflect        │
              │                   rebuild_db      │
              │  memory/         mcp/             │
              │    db             reminders       │
              │    migrate                        │
              │    writer                         │
              │    search                         │
              │    scoring                        │
              └───────────────┬───────────────────┘
                              │
              ┌───────────────▼───────────────────┐
              │    ~/.claude/mait-code-data/      │
              │                                   │
              │  soul_document.md                 │
              │  user_context.md                  │
              │  memory/                          │
              │    MEMORY.md        (curated)     │
              │    memory.db        (SQLite)      │
              │    observations/    (raw JSONL)   │
              │    reflections/     (synthesised) │
              │    graph/           (relations)   │
              └───────────────────────────────────┘
```

## Memory Architecture

### Overview

The memory system combines three tiers of storage with a SQLite database for structured search. Raw observations flow in from hooks, get indexed in the database, and the highest-confidence facts are promoted to MEMORY.md for always-on context.

### Database Schema

The memory database (`memory.db`) uses SQLite with two extensions:

**Core table: `memory_entries`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-incrementing identifier |
| `content` | TEXT | The memory content |
| `entry_type` | TEXT | fact, preference, event, insight, task, relationship |
| `importance` | INTEGER | 1-10 scale (default 5) |
| `memory_class` | TEXT | episodic or semantic (controls decay rate) |
| `created_at` | DATETIME | Timestamp of creation |

**Entry type to memory class mapping:**
- **Episodic** (fast decay, 3-day half-life): `event`, `task`
- **Semantic** (slow decay, 90-day half-life): `fact`, `preference`, `insight`, `relationship`

**FTS5 virtual table: `memory_entries_fts`**
- Full-text search with BM25 ranking
- Kept in sync via triggers on insert/update/delete

**Vec0 virtual table: `memory_vec`**
- 1536-dimension cosine distance vectors via `sqlite-vec`
- Schema present, populated in Phase 2 (semantic search)

**Indexes:**
- `idx_memory_entries_created_at` — temporal queries
- `idx_memory_entries_type` — type filtering
- `idx_memory_entries_importance` — importance ranking
- `idx_memory_entries_class` — class filtering

### Composite Scoring

Memory retrieval results are ranked by a composite score:

```
score = 0.3 × recency + 0.3 × importance + 0.4 × relevance
```

**Recency** uses exponential decay:
- `recency = exp(-ln(2) × age_days / half_life)`
- Episodic half-life: 3 days (events decay fast)
- Semantic half-life: 90 days (facts persist)
- Default half-life: 7 days (unknown class)

**Importance** is normalized from 1-10 to 0.0-1.0:
- `importance_norm = (importance - 1) / 9`

**Relevance** is provided by the search method (FTS BM25 or semantic similarity).

### Deduplication

Before storing a new memory, the writer checks for near-duplicates:

1. Extract first 8 significant words (length > 2) from new content
2. Query FTS5 for candidate matches (up to 20)
3. Compare each candidate using `SequenceMatcher`
4. If similarity >= 0.90: update existing entry's timestamp and keep max importance
5. If no match: insert as new entry

### Data Flow

```
store_memory() ──► find_duplicate() ──► FTS5 candidates
                        │                    │
                        ▼                    ▼
                   SequenceMatcher     memory_entries
                   similarity >= 0.90?
                        │
                   ┌────┴────┐
                   │ Yes     │ No
                   ▼         ▼
              UPDATE      INSERT
              timestamp   new entry
```

```
search_memory() ──► FTS5 BM25 search
                        │
                        ▼
                   composite_score()
                   (recency + importance + relevance)
                        │
                        ▼
                   Sort by score, return top N
```

### Tier 1: Observations (raw)
- Extracted automatically by the `observe` hook at PreCompact and SessionEnd
- Stored as JSONL files in `memory/observations/YYYY-MM-DD.jsonl`
- Contains facts, decisions, code patterns, and user preferences observed during sessions
- Indexed into `memory.db` for structured search

### Tier 2: Reflections (synthesised)
- Generated by the `reflect` tool, which aggregates recent observations
- Stored in `memory/reflections/`
- Identifies patterns, recurring themes, and evolving preferences

### Tier 3: MEMORY.md (curated)
- The highest-confidence facts, loaded into every session via CLAUDE.md
- Manually edited or updated by the reflection system
- Kept under ~150 lines for context budget

## Memory CLI Tool (`mc-tool-memory`)

Replaces the former MCP server with a sync CLI tool invoked via Bash. Skills use preprocessing (`!`command``) or direct Bash calls.

| Subcommand | Args | Description |
|------------|------|-------------|
| `search` | query, --limit?, --type? | FTS5 keyword search with composite score re-ranking |
| `store` | content, --type?, --importance? | Store with deduplication and validation |
| `list` | --limit?, --type? | List recent entries, optionally filtered |
| `delete` | id | Delete by ID |
| `stats` | — | Counts by entry type and memory class |

## MCP Servers

### mait-reminders
- `set_reminder(when, what)` — Schedule a reminder
- `list_reminders()` — Show active and overdue reminders

## Hooks

| Hook | Trigger | Purpose |
|------|---------|---------|
| `SessionStart` | Session begins | Inject companion context (recent memories, reminders) |
| `PreCompact` | Before context compaction | Extract observations before conversation is compressed |
| `SessionEnd` | Session ends | Final observation extraction, update statistics |

## Identity System

Three files compose the companion's identity:

1. **Soul Document** — Values, personality, communication style (stable, rarely changes)
2. **User Context** — Who the user is, their stack, preferences (updates occasionally)
3. **MEMORY.md** — Accumulated knowledge (updates frequently)

All three are referenced via `@` imports in `config/CLAUDE.md` and loaded into every Claude Code session.

## Migration System

Schema changes are managed via forward-only migrations in `src/mait_code/memory/migrate.py`. Each migration has a version number, description, and body (SQL list or callable). The `schema_version` table tracks which migrations have been applied.

Adding a new migration:
1. Append a tuple to `MIGRATIONS` with the next version number
2. Include SQL statements or a callable that receives `conn`
3. `ensure_schema()` runs automatically on every connection open

## Data Directory

```
~/.claude/mait-code-data/
├── soul_document.md          # Companion identity
├── user_context.md           # User profile
├── memory/
│   ├── MEMORY.md             # Curated facts (loaded every session)
│   ├── memory.db             # SQLite FTS5 + vec0 database
│   ├── observations/         # Raw JSONL session extractions
│   │   └── 2026-03-04.jsonl
│   ├── reflections/          # Synthesised insights
│   │   └── 2026-03.md
│   └── graph/                # Entity relationships
└── reminders.db              # Reminder database (future)
```

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| uv over pip/poetry | Fastest resolver, built-in project management, `uv run` eliminates venv activation |
| SQLite + FTS5 + sqlite-vec | Zero infrastructure, single file, portable, keyword + vector search in one DB |
| JSONL for observations | Append-only, merge-friendly for git sync, one object per line |
| Hooks over background services | No daemons to manage, reactive model fits Claude Code's architecture |
| CLI tools + skills over MCP for memory | No process overhead, preprocessing injects results before Claude sees the skill, simpler debugging |
| Symlinks over file copying | Updates propagate automatically via `git pull`, no re-install needed |
| Exponential decay scoring | Recent memories surface naturally, old ones fade unless high importance |
| Dedup via FTS5 + SequenceMatcher | Fast candidate narrowing, precise similarity comparison, no duplicates |
