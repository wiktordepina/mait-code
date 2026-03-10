# Changelog

## v0.8.2 — Maintenance updates (2026-03-10)

- **Docs:** Convert architecture diagrams from ASCII to Mermaid
- **Install:** Pin Python 3.14 in uv tool install
- **Uninstall:** Use `uv run python` instead of `python3` for consistency

## v0.8.1 — Fix observe hook recursion (2026-03-10)

Prevent recursive hook invocations when `call_claude()` spawns nested CLI sessions.

- **Recursion guard:** Set `MAIT_CODE_NESTED=1` env var in `call_claude()` subprocess environment
- **Early exit:** Observe hook checks for `MAIT_CODE_NESTED` and skips execution in nested invocations

## v0.8.0 — Projects registry and workflow skills (2026-03-09)

Cross-project awareness via a projects registry, 7 new skills for daily workflow, and time-filtered memory queries.

- **Projects table:** New `projects` table in `tasks.db` storing project name, full disk path, GitHub remote URL, and registration date; foreign key from `tasks.project` to `projects.name` with `PRAGMA foreign_keys=ON` enforcement
- **`ensure_project()`:** Auto-registers the current project on any task subcommand — resolves path via `git rev-parse --show-toplevel` and GitHub URL via `git remote get-url origin`; no-op if project already registered
- **`mc-tool-tasks list-all`:** New subcommand listing open tasks across all registered projects, grouped by project
- **`mc-tool-tasks projects`:** New subcommand listing all registered projects with path, GitHub URL, and added date
- **`mc-tool-memory list --since`:** New time-period filter accepting `24h`, `7d`, `1w` etc. for listing recent memories
- **`/commit` skill:** Detect changes, generate conventional commit message, confirm with user, commit
- **`/standup` skill:** Standup summary from git history (24h), all open tasks, recent memories, reminders, and open PRs across registered projects via `gh`
- **`/work-history` skill:** Project-specific work history for today/yesterday/week from git log and memory
- **`/today` skill:** Daily overview dashboard — open tasks (all projects), reminders, recent activity, open PRs
- **`/status` skill:** Generate STATUS.md with project overview, tasks, recent work, and reminders
- **`/prs` skill:** List open PRs across all registered projects via `gh pr list`
- **`/projects` skill:** List all registered projects
- **Documentation:** Updated architecture (projects table schema, new CLI subcommands), skills reference (7 new skill sections), memory docs (tasks CLI reference, `--since` flag), and config CLAUDE.md (replaced explicit skills list with categorised summary — skills are auto-discovered)

## v0.7.0 — Project tasks (2026-03-08)

Per-project task tracking with CLI tool, skills, and session start integration.

- **`mc-tool-tasks` CLI tool:** Subcommands `add`, `list`, `done`, `remove`, `check` with SQLite storage, project scoping by git root basename (falls back to cwd basename)
- **`/task` skill:** Add tasks via slash command (e.g. `/task Fix login bug`, `/task --priority high Fix auth race`); model-invocable so Claude can proactively suggest tasks during sessions (always asks before adding)
- **`/tasks` skill:** List open tasks for the current project with preprocessing
- **Session start hook:** Now surfaces open project tasks alongside overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `tasks.db` with `tasks` table indexed on `(project, status)`, priority ordering (high → medium → low), connection factory and migration system matching existing patterns
- **Test coverage:** 18 tests covering schema migrations, all CLI commands, project scoping, and priority ordering

## v0.6.0 — Reflection system (2026-03-08)

Synthesise observations into durable insights with the new `/reflect` skill and reflection engine.

- **Reflection engine:** `mc-tool-memory reflect` reads last 7 days of memory entries + observation JSONL logs, calls Claude Haiku to identify patterns and themes, stores insights as `type=insight` (importance=6) in memory.db
- **`/reflect` skill:** Slash command with preprocessing — presents insights and proposes MEMORY.md additions for user approval
- **Novelty gate:** Skips reflection if fewer than 3 new observations since last reflection; overridable with `--min-new 0`
- **CLI flags:** `--days` (default 7) and `--min-new` (default 3) for controlling reflection scope
- **Shared LLM module:** Extracted `call_claude()` from observe hook into `src/mait_code/llm.py` — reused by both extraction and reflection
- **Refactored extractor:** `call_haiku` now delegates to shared `call_claude` with `model="haiku"`, `timeout=45`
- **Test coverage:** 15 new tests covering reflection logic, `_format_extraction`, `read_memory_md`, observation log edge cases, CLI output, and `call_haiku` delegation

## v0.5.0 — Vector embeddings and shared logging (2026-03-08)

Added semantic search via vector embeddings and a shared logging system across all entry points.

- **Vector embeddings:** `nomic-ai/nomic-embed-text-v1.5` via `fastembed` (ONNX Runtime, no PyTorch) — 768-dimensional embeddings stored in sqlite-vec, auto-computed on memory write
- **Hybrid search:** New default search mode combining FTS5 keyword search with vector cosine similarity; `--mode` flag to select `hybrid`, `fts`, or `vector`; graceful degradation to FTS-only if embeddings unavailable
- **Reindex command:** `mc-tool-memory reindex` recomputes vector embeddings for all existing entries in batches of 64 (renamed from `rebuild`)
- **Restore command:** `mc-tool-memory restore` replays observation JSONL logs into the database (memories, entities, relationships), then reindexes embeddings; supports `--dry-run` to preview without writing
- **Stats updated:** `mc-tool-memory stats` now shows embedding coverage and model availability
- **Migration 7:** Recreates `memory_vec` at 768 dimensions (from placeholder 1536), adds delete trigger to keep vec in sync
- **Shared logging:** `src/mait_code/logging.py` with `setup_logging()` and `@log_invocation()` decorator — file-based rotating logs (`~/.claude/mait-code-data/logs/`), configurable via `MAIT_CODE_LOG_LEVEL` and `MAIT_CODE_LOG_FILE` env vars
- **All entry points wired:** `mc-tool-memory`, `mc-tool-reminders`, `mc-hook-session-start`, `mc-hook-observe`, `mc-hook-format` all log invocations with automatic parameter truncation for sensitive fields
- **settings.json:** Added `env` block with `MAIT_CODE_LOG_LEVEL` configuration
- **New dependency:** `fastembed>=0.4.0`
- **Bug fix:** Fixed Python 2 exception syntax in session_start hook (`except A, B:` → `except (A, B):`)

## v0.4.0 — Entity system, observation hooks, and hooks reorganisation (2026-03-08)

Added knowledge graph entity tracking, automatic observation extraction from conversations, and reorganised hooks to follow the same package convention as tools.

- **Entity system:** `memory_entities` and `memory_relationships` tables (migrations 5–6) with CRUD operations — upsert, case-insensitive lookup, relationship tracking with mention counts
- **Observation hook:** Automatic knowledge extraction via Claude Haiku on `PreCompact` and `SessionEnd` — extracts facts, preferences, decisions, bugs, entities, and relationships from conversation transcripts
- **Async PreCompact hook:** Observation hook now runs asynchronously to avoid blocking the main conversation during context compaction
- **Hooks reorganisation:** All hooks now follow `hooks/<hook_name>/cli.py` package pattern (matching `tools/<tool_name>/cli.py`), eliminating the flat-file/submodule inconsistency
- **CLI commands:** Added `mc-tool-memory entities` and `mc-tool-memory relationships` subcommands for querying the knowledge graph
- **Cursor-based incremental extraction:** Only processes new transcript lines since last invocation, with automatic pruning of stale cursors (>30 days)
- **Updated conventions:** CLAUDE.md, docs, and pyproject.toml entry points updated to reflect new package structure

## v0.3.1 — Replace reminders MCP server with CLI tool (2026-03-07)

Replaced the last MCP server (`mait-reminders`) with a sync CLI tool and skills, eliminating the `mcp` dependency entirely.

- **`mc-tool-reminders` CLI tool:** Subcommands `set`, `list`, `dismiss`, `check` with SQLite storage, dateparser for flexible time input, UTC normalization
- **`/remind` skill:** Set reminders via slash command (e.g. `/remind in 2 hours check deploy`)
- **`/reminders` skill:** List active and overdue reminders with preprocessing
- **Session start hook:** Now surfaces overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `reminders.db` with connection factory and migration system matching the memory tool patterns
- **Removed** `mait-reminders` MCP server, `src/mait_code/mcp/` directory, and `mcp[cli]` dependency
- **Restructured tests:** Mirror `src/mait_code/` directory structure (`tests/tools/memory/`, `tests/tools/reminders/`) with per-tool conftest fixtures

## v0.3.0 — Replace memory MCP server with CLI tools + skills (2026-03-06)

Replaced the `mait-memory` MCP server with a sync CLI tool (`mc-tool-memory`) and three skills, eliminating process overhead and simplifying the architecture.

- **`mc-tool-memory` CLI tool:** Subcommands `search`, `store`, `list`, `delete`, `stats` — same functionality as the former MCP server, now invoked via Bash
- **`/recall` skill:** Uses preprocessing (`!`mc-tool-memory search ...``) to inject results before Claude sees the prompt — zero tool-call overhead
- **`/remember` skill:** Manual-only (`disable-model-invocation: true`) skill to store memories via slash command
- **`memory-store` skill:** Auto-invoked by Claude (`user-invocable: false`) to proactively store observations about the user
- **Removed** `mait-memory` MCP server (`src/mait_code/mcp/memory_server.py`) and its `settings.json` registration
- **Renamed** all entry points to `mc-{hook|tool|mcp}-*` convention (e.g. `mc-hook-session-start`, `mc-tool-reflect`)
- **Updated** all documentation to reflect the new architecture

## v0.2.0 — Phase 1: Memory Core (2026-03-05)

Persistent memory system — the defining feature that makes this a companion, not a tool.

- **Database schema:** `memory_entries` table with FTS5 full-text search, vec0 virtual table (ready for vector search in Phase 2), automatic schema migrations via `ensure_schema()`
- **Connection factory:** `get_connection()` loads sqlite-vec, enables WAL mode, runs migrations; data dir configurable via `MAIT_CODE_DATA_DIR`
- **Composite scoring:** `score = 0.3 × recency + 0.3 × importance + 0.4 × relevance` with exponential decay (episodic: 3-day half-life, semantic: 90-day half-life)
- **Memory writer:** Deduplication via FTS5 candidate retrieval + SequenceMatcher ≥ 0.90 similarity; on duplicate updates timestamp and keeps max importance
- **Keyword search:** FTS5 BM25 ranking with LIKE fallback, listing by recency, deletion by ID
- **MCP memory server:** Five tools — `search_memory`, `store_memory`, `list_recent_memories`, `delete_memory`, `memory_stats`
- **`/recall` skill:** Slash command to search memory for past facts, decisions, and patterns
- **Test suite:** 70 tests covering migrations, scoring, writer, search, and MCP server
- **Docs:** Updated architecture (schema, scoring formula, dedup algorithm, MCP tool reference), development guide (memory module structure, migration guide, test patterns), skills reference, setup verification steps

## v0.1.0 — Phase 0: Foundation (2026-03-04)

Initial project scaffold establishing the core structure and tooling.

- **Packaging:** uv/hatchling build system with Python 3.14+, dependencies on `mcp`, `sqlite-vec`, `dateparser`, `pyyaml`
- **Hooks:** Stub entry points for `session_start`, `observe`, and `auto_format` hooks
- **MCP servers:** Stub `memory_server` and `reminders_server`
- **CLI tools:** Stub `reflect` and `rebuild_db` commands
- **Identity:** Soul document and user context templates adapted from the mait gateway
- **Config:** Global `CLAUDE.md` with companion behaviour rules, `settings.json` with hook and MCP server registrations
- **Scripts:** `install.sh` and `uninstall.sh` for automated setup/teardown
- **Docs:** Architecture overview, philosophy, setup guide, skills reference, multi-machine sync guide, and development guide

## v0.0.0 — Init (2026-03-04)

Repository initialised with README.
