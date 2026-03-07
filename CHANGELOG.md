# Changelog

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
