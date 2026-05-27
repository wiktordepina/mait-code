# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the project is pre-1.0, minor version bumps track meaningful additions
of functionality; patch bumps cover docs, internal tidy-ups, and fixes that
don't change the public surface. Everything is still in flux.

## [Unreleased]

### Fixed

- **Failed extractions no longer silently lose their transcript window.** When
  the extraction LLM call timed out or errored, the observe hook still advanced
  its read cursor, so that slice of conversation was skipped permanently. It
  now leaves the cursor in place and re-attempts the window on the next
  session, giving up only after three consecutive failures so a single
  un-extractable transcript can't stall extraction forever. The extraction
  timeout is also raised from 45s to 90s to accommodate longer transcripts.

## [0.15.3] — 2026-05-27

**Memory extraction data-quality fixes.**

### Fixed

- **Project- and branch-scoped preferences are no longer flattened to
  global.** The observe hook hard-coded every extracted preference to
  `scope=global`, discarding the scope the model classified. It now honours a
  valid project/branch classification and only falls back to global when none
  is given, so a preference learned in one project no longer leaks into
  others.
- **Extracted relationship types are constrained to a fixed vocabulary.**
  Relationships are coerced on write to the canonical set (`uses`, `owns`,
  `contributes_to`, `depends_on`, `manages`, `related_to`), and the extraction
  prompt is generated from that same set so the two cannot drift. This stops
  the long tail of one-off relationship labels; the edge is preserved, only an
  out-of-set label is normalised to `related_to`.

## [0.15.2] — 2026-05-27

**Fix `mait-code update` on tag-pinned installs.**

### Fixed

- **`mait-code update` no longer fails on a tag-pinned install.** The
  bootstrap installer checks out a release tag, leaving the source in
  detached HEAD; `update` then ran `git pull` unconditionally, which
  aborts with "You are not currently on a branch". `update` now fetches
  and advances based on the source state: `--ref` checks out that ref,
  a branch fast-forwards (`git merge --ff-only`), and a detached HEAD
  moves to the latest `v*` tag. `--no-pull` reinstalls from the current
  checkout without touching git.

## [0.15.1] — 2026-05-27

**One-liner installer.** Adds `curl … | bash` as the primary install
path. Closes the master release-infra checklist — every brick (A
through F) has now shipped.

### Added

- **One-liner installer** (`scripts/bootstrap.sh`). Detects or installs
  `uv`, clones the repo to `~/.local/share/mait-code/source/`, runs
  `uv tool install`, and execs `mait-code install` to wire up symlinks,
  settings, and data directories. Idempotent. Served from
  `raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh`:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
  ```

  Flags: `--embedding-provider`, `--ref` (default: latest `v*` tag),
  `--dir`, `--no-uv`, `--help`. Pass via `bash -s --` when curl-piping.
- **`scripts/test-bootstrap.sh`** — Docker-based smoke test against
  `ubuntu:24.04`. Invoke locally before merging changes to
  `bootstrap.sh`. Not run by CI in v1.

### Changed

- **README, `docs/setup.md`, and the docs Home page** now lead with
  the one-liner. The from-source path stays as a secondary
  alternative for contributors.

## [0.15.0] — 2026-05-27

**`mait-code` install-lifecycle CLI.** A new top-level binary replaces
the ad-hoc bash install/uninstall scripts with a Python CLI that owns
the full lifecycle: install, update, uninstall, status, doctor,
version. The bash shims shrink to ~10–40 lines each, handling only the
chicken-and-egg bootstrap before delegating to the CLI.

### Added

- **`mait-code` CLI binary** (`uv tool install` entry point) that owns the
  install lifecycle. Six subcommands:
  - `mait-code install --from <path>` — set up data directories, symlinks
    (`CLAUDE.md`, `skills/*`, `agents/*`), merge `settings.json`, and write
    an install record at `~/.local/share/mait-code/install.json`. Non-
    interactive by default.
  - `mait-code update` — read the install record, `git pull` (or
    `--no-pull`, plus optional `--ref <tag|branch|sha>`),
    `uv tool install --force --reinstall`, refresh symlinks and settings,
    bump the install record.
  - `mait-code uninstall` — reverse the install footprint. Default
    preserves the data directory (memories, personalised identity files);
    `--purge-data` removes it. `--keep-uv-tool` skips
    `uv tool uninstall`.
  - `mait-code status` — read-only summary with `--json` for
    machine-readable output.
  - `mait-code doctor` — diagnostic checks (install record, source dir,
    settings parses, hook commands on PATH, no dangling symlinks, data
    dir writable, uv on PATH). `--fix` applies safe fixes (removes
    dangling symlinks, recreates a missing data dir).
  - `mait-code version` — prints the installed version.
- **Install record schema** (`schema_version: 1`) with versioned format
  for forward-compatible evolution.

### Changed

- **`scripts/install.sh`** shrunk to a ~40-line shim: prompts for the
  embedding provider (or honours `$MAIT_CODE_EMBEDDING_PROVIDER` and
  non-TTY environments), `uv tool install`s from the local source, then
  `exec`s `mait-code install`.
- **`scripts/uninstall.sh`** shrunk to a 10-line shim that forwards all
  arguments to `mait-code uninstall`.
- **`docs/setup.md`** documents the new CLI lifecycle commands alongside
  the bash shims, with a link to the full reference.
- **`docs/reference/mait-code.md`** — comprehensive per-subcommand
  reference (synopsis, flags, behaviour, examples, exit codes) under
  Reference / CLI. Sits alongside the existing Skills catalogue.

## [0.14.1] — 2026-05-26

**Documentation site, release pipeline, and type-checking infrastructure.**
No runtime behaviour changes — this patch release ships the project's first
hosted documentation site at <https://wiktordepina.github.io/mait-code/>,
encodes the release process in CI, and adopts pyright type-checking up to
standard mode.

### Added

- **Docs site.** `mkdocs-material` + `mkdocstrings` with auto-generated Python
  API reference driven by each surface module's `__all__`. Twelve modules
  surface — four core (`context`, `llm`, `logging`, `ssl`), five tool
  packages, three hook packages. Nested layout under `Tools/` and `Hooks/`
  mirrors the dotted module hierarchy. Hand-authored `docs/reference/skills.md`
  catalogues every slash command.
- **GitHub Pages deploy.** `docs.yml` workflow with cairn's deploy pattern —
  `dev` alias from `main`, version pin + `latest` alias from tags, managed by
  `mike`.
- **`docs/contributing-docs.md`.** Convention note covering the `__all__`
  contract, Google docstring style, the regeneration workflow, and the
  seven-tab nav layout.
- **Release pipeline.** `ci.yml` (lint, test, audit, typecheck) and
  `release.yml` (version-bump-triggered, dispatches `docs.yml` on tag).
  `tests/test_imports.py` is a parametrised smoke test asserting every
  surface module declares a non-empty `__all__`.
- **Pyright type-checking** in standard mode over `src/`. Added as a fourth
  job in `ci.yml` alongside lint / test / audit. Configured via
  `[tool.pyright]` in `pyproject.toml`.
- **CI and Docs badges plus a hosted-docs link** in root `README.md`.

### Changed

- **Codebase-wide docstrings** migrated to Google style for consistent
  rendering by `mkdocstrings`. Surface modules declare `__all__` with
  `# Section` comments grouping symbols by topic.
- **Docs nav** organised into seven tabs (Home, Guide, Concepts, Architecture,
  Reference, Decisions, Contributing). Home page rewritten as a proper landing
  experience rather than a link list.
- **`Optional` narrowing tightened** across ten sites in
  `tools/memory/cli.py`, `hooks/observe/extractor.py`,
  `tools/memory/scoring.py`, `tools/memory/writer.py`, and
  `tools/web_fetch/fetch.py`. Drive-by return / parameter annotations on
  `log_invocation` and `check_dimension_match` surfaced by
  `mkdocs build --strict`.
- **CHANGELOG** reformatted to
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) conventions while
  preserving all prior history.

### Removed

- **`run_pytest.yaml` workflow.** Superseded by the broader `ci.yml`.

## [0.14.0] — 2026-04-07

**Web fetch tool and embedding test fixes.**
Local web fetch tool that bypasses the claude.ai proxy, working behind corporate firewalls and proxies. Also fixes embedding tests to work with both local and Bedrock providers.

### Web fetch tool
- **`mc-tool-web-fetch` CLI tool:** Fetches a URL and returns content as markdown (HTML) or formatted text (JSON, plain text). Uses stdlib `urllib.request` with `truststore` for corporate proxy compatibility.
- **HTML-to-markdown conversion:** Strips noise tags (`<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`) then converts via `markdownify`. Collapses excessive blank lines.
- **Content-type routing:** HTML→markdown, JSON→pretty-printed, text→passthrough, binary→descriptive message.
- **SSRF protection:** Resolves hostnames and blocks private/loopback/link-local/reserved IPs by default. Overridable with `--allow-private`.
- **HTTPS upgrade:** Automatically upgrades `http://` to `https://`, adds scheme to bare domains.
- **Size and length limits:** `--max-size` (default 512KB response body), `--max-chars` (default 100K output characters, ~25K tokens).
- **`/web-fetch` skill:** Slash command wrapping the CLI tool with preprocessing for convenient invocation.
- **New dependency:** `markdownify>=0.14` (brings `beautifulsoup4`).

### Embedding test fixes
- **Provider-aware constant tests:** `test_default_model_name` and `test_default_dimension` now accept both local (nomic/768) and Bedrock (Titan/1024) values depending on environment configuration.
- **Provider-aware graceful degradation:** `test_embed_text_returns_none_when_unavailable` now blocks the correct dependency (`fastembed` or `boto3`) based on the active provider.
- **Provider-pinned dimension checks:** All `TestDimensionCheck` tests explicitly pin the provider via `patch.dict` so they pass regardless of environment. Added bedrock-specific matching tests.
- **New tests:** `test_local_default_dimension`, `test_local_model_name`, `test_empty_table_matching_declaration_bedrock`, `test_matching_dimension_bedrock`.

### Test coverage
- 35 tests for web fetch (URL validation, SSRF protection, HTTP errors, timeouts, HTML conversion, JSON formatting, charset handling, truncation, binary content).
- 27 tests for embeddings (up from 23), all passing with both local and Bedrock providers.

## [0.13.0] — 2026-03-24

**Configurable embedding providers.**
Support for multiple embedding providers — local (fastembed/HuggingFace) and AWS Bedrock — configurable via environment variables. Designed for corporate environments where HuggingFace may be blocked.

### Embedding provider abstraction
- **Provider abstraction:** New `EmbeddingProvider` ABC with `LocalProvider` (fastembed) and `BedrockProvider` (AWS Bedrock) implementations. Public API (`embed_text`, `embed_texts`, `is_available`, `serialize_f32`) unchanged.
- **`LocalProvider`:** Wraps fastembed with nomic-embed-text-v1.5 (768d). Reads `MAIT_CODE_EMBEDDING_MODEL` env var. Prefixes text with task type (`search_document:` / `search_query:`).
- **`BedrockProvider`:** Calls AWS Bedrock `invoke_model` API. Supports Titan and Cohere model families. Reads `MAIT_CODE_BEDROCK_MODEL_ID` and `MAIT_CODE_BEDROCK_REGION` env vars. Calls `setup_ssl()` for corporate proxy compatibility.
- **Configuration:** `MAIT_CODE_EMBEDDING_PROVIDER` env var (`local` or `bedrock`). Deployment-time decision — pick a provider and stick with it.
- **Dimension handling:** `EMBEDDING_DIM` and `EMBEDDING_MODEL` computed from env vars at import time. `check_dimension_match()` detects vec table dimension mismatches.
- **`cmd_reindex` migration:** Automatically detects dimension mismatch when switching providers, drops and recreates the vec table with the correct dimension before reindexing.
- **`cmd_stats` enhanced:** Now shows embedding provider, model name, and dimension alongside existing statistics.
- **Provider-specific error messages:** `cmd_reindex` hints at the correct dependency (`fastembed` or `boto3`) based on the configured provider.
- **Optional dependency:** `pip install mait-code[bedrock]` installs `boto3>=1.34`.
- **Graceful degradation:** Both providers fail silently if their dependency is missing — memory storage and keyword search continue to work.

### Documentation
- Updated `docs/memory.md` with provider configuration, corporate setup guide, and env var table.
- Updated `docs/architecture.md` with provider env vars, key decision, and vec table description.
- Updated `docs/development.md` with revised embeddings module description.

### Test coverage
- Rewrote `test_embeddings.py` for provider abstraction: mock provider tests for prefix handling (local vs bedrock), bedrock dimension config, bedrock invoke_model mock, dimension check (empty, matching, mismatch, error), graceful degradation.

## [0.12.1] — 2026-03-24

**macOS compatibility fixes.**
Workarounds for macOS-specific issues: async hook stdin bug and corporate proxy SSL.

### Async hook stdin fix
- **Resilient stdin parsing:** `_read_event()` returns an empty dict on empty or invalid stdin instead of crashing with `JSONDecodeError`.
- **Transcript fallback:** `_find_transcript()` discovers the most recently modified `.jsonl` transcript from the Claude Code project directory when stdin is unavailable. Workaround for macOS bug where async hooks receive empty stdin ([#38162](https://github.com/anthropics/claude-code/issues/38162)).
- **Slug derivation fix:** Project slug now replaces both `/` and `.` with `-`, matching Claude Code's actual behaviour (e.g. `/Users/wiktor.depina/...` → `-Users-wiktor-depina-...`).

### SSL trust store for corporate proxies
- **`truststore` integration:** New `setup_ssl()` in `src/mait_code/ssl.py` injects the OS trust store into Python's `ssl` module at startup, so corporate proxy CA certificates (e.g. Netskope) are trusted automatically.
- **Wired into entry points:** `mc-hook-observe` and `mc-tool-memory` call `setup_ssl()` before any network requests.
- **Graceful degradation:** If `truststore` is unavailable or injection fails, the system continues with Python's default cert bundle.
- **New dependency:** `truststore>=0.9`.

### Test coverage
- 10 tests for stdin parsing and transcript fallback (including dot-in-path slug derivation).
- 4 tests for SSL setup (injection, idempotency, missing package, injection failure).

## [0.12.0] — 2026-03-12

**Decision log.**
ADR-lite decision records for capturing why technical choices were made.

- **`mc-tool-decisions` CLI tool:** 8 subcommands — `record`, `list`, `show`, `amend`, `supersede`, `search`, `remove`, `sync`. SQLite-backed with FTS5 full-text search across title, context, alternatives, and consequences.
- **Automatic markdown rendering:** Every mutation regenerates `docs/decisions.md` at the git root with a summary table and full decision sections. Skips silently outside git repos.
- **`/decision` skill:** Record a decision via slash command; model-invocable so Claude can suggest recording significant technical choices during sessions.
- **`/decisions` skill:** Browse and search decision records with preprocessing.
- **FK-safe removal:** Deleting a decision clears `superseded_by` references from other decisions before deletion.
- **Test coverage:** 39 tests covering migrations, FTS sync triggers, all CLI commands, rendering (strikethrough, field omission, superseded links), and file writing.
- **3 initial decisions recorded** from project memory: SQLite as DB engine (DR-1), CLI tools over MCP (DR-2), watermark-based reflection idempotency (DR-3).

## [0.11.0] — 2026-03-12

**Idempotent reflection with batching.**
Reflection is now idempotent and supports batched processing of large backlogs.

- **Watermark tracking:** New `reflection_watermark` table (migration 9) tracks the highest entry ID reflected per project. Running `/reflect` twice without new observations is a no-op.
- **Batching:** New `--batch-size N` flag (default 50) limits entries processed per reflection. Entries are processed oldest-first via ascending ID order.
- **Drain mode:** New `--drain` flag loops until all unreflected entries are processed, with a safety cap of 20 iterations.
- **JSONL removed from reflect:** Observation JSONL logs are no longer read during reflection — observations are already in `memory_entries` via the observe hook. `read_observation_logs()` remains for `restore`.
- **Deprecated functions:** `get_last_reflection_date()`, `count_entries_since()`, `check_novelty_gate()`, `get_recent_entries()` kept for backward compatibility but replaced by watermark-based equivalents.
- **New functions:** `get_watermark()`, `update_watermark()`, `check_novelty_gate_v2()`, `get_unreflected_entries()`.
- **Test coverage:** 60 tests for the reflection system including idempotency, incremental processing, batch limiting, and failure safety.

## [0.10.0] — 2026-03-11

**Scoped memory and tasks alignment.**
Three-tier memory scoping (global/project/branch) and removal of the projects registry from tasks.

### Scoped memory
- **Three-tier scope:** Memory entries are now scoped as `global`, `project`, or `branch`. Scope is auto-detected from git context and can be overridden with `--scope`, `--project`, `--branch` flags.
- **Shared context module:** New `src/mait_code/context.py` with `get_project()`, `get_branch()`, `get_context()` — used by memory, tasks, and hooks.
- **Scope-aware search:** All search functions (`search`, `list`, `hybrid_search`, `vector_search`) filter by scope — global entries are always visible, project/branch entries only visible in matching context. Use `--scope all` to disable filtering.
- **Scope-aware dedup:** Deduplication is project-scoped — same content in different projects creates separate entries.
- **Scope-aware scoring:** New `scope_boost()` multiplier in composite scoring — branch match: 1.0, project match: 0.85, global: 0.7.
- **Scope-aware reflection:** `mc-tool-memory reflect` filters by current project context.
- **LLM scope classification:** Extraction prompt now includes scope guidance; `resolve_scope()` heuristic promotes preferences to global, defaults decisions to project, bugs on feature branches to branch.
- **Schema migration 8:** Adds `scope`, `project`, `branch` columns to `memory_entries`, rebuilds FTS5 index with `project` and `scope` columns, recreates sync triggers.

### Tasks alignment
- **Removed projects table:** Migration 3 drops the `projects` table and FK constraint from `tasks.db`. Tasks store project as a plain string column.
- **Removed `ensure_project()`:** No longer needed without the projects registry.
- **Removed `/projects` skill:** Project discovery via `mc-tool-memory stats` (by-project breakdown) or `mc-tool-tasks list-all`.
- **Updated PR skills:** `/prs`, `/standup`, `/today` now use `gh search prs --author=@me --state=open` instead of iterating over registered projects.
- **Updated `/status`:** Derives project info from git directly instead of the projects table.

### Skill updates
- `/recall`, `/remember`, `memory-store`, `/reflect` — updated instructions for scope-aware behaviour.
- `/standup`, `/today` — use `--scope all` for cross-project memory queries.

## [0.9.0] — 2026-03-11

**Database hardening and LLM resilience.**
- **Database context managers:** New `connection()` context manager in all three `db.py` modules (`memory`, `reminders`, `tasks`) — guarantees connection cleanup on exit. All CLI commands and hooks migrated from manual `try/finally/conn.close()`.
- **LLM retry/backoff:** `call_claude()` now accepts `retries` and `backoff_base` parameters with exponential backoff on transient failures (timeouts, non-zero exits). `FileNotFoundError` is not retried (permanent). Default `retries=0` preserves existing fail-fast behaviour for interactive tools.
- **Observe hook resilience:** Extraction calls now retry twice (3 total attempts) with 1s/2s backoff, reducing silent data loss from transient LLM failures.
- **Python 3.13:** Downgrade minimum Python from 3.14 to 3.13 for broader compatibility.
- **Docs:** Convert architecture diagrams from ASCII to Mermaid, update setup and memory docs.

## [0.8.2] — 2026-03-10

**Maintenance updates.**
- **Docs:** Convert architecture diagrams from ASCII to Mermaid
- **Install:** Pin Python 3.13 in uv tool install
- **Uninstall:** Use `uv run python` instead of `python3` for consistency

## [0.8.1] — 2026-03-10

**Fix observe hook recursion.**
Prevent recursive hook invocations when `call_claude()` spawns nested CLI sessions.

- **Recursion guard:** Set `MAIT_CODE_NESTED=1` env var in `call_claude()` subprocess environment
- **Early exit:** Observe hook checks for `MAIT_CODE_NESTED` and skips execution in nested invocations

## [0.8.0] — 2026-03-09

**Projects registry and workflow skills.**
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

## [0.7.0] — 2026-03-08

**Project tasks.**
Per-project task tracking with CLI tool, skills, and session start integration.

- **`mc-tool-tasks` CLI tool:** Subcommands `add`, `list`, `done`, `remove`, `check` with SQLite storage, project scoping by git root basename (falls back to cwd basename)
- **`/task` skill:** Add tasks via slash command (e.g. `/task Fix login bug`, `/task --priority high Fix auth race`); model-invocable so Claude can proactively suggest tasks during sessions (always asks before adding)
- **`/tasks` skill:** List open tasks for the current project with preprocessing
- **Session start hook:** Now surfaces open project tasks alongside overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `tasks.db` with `tasks` table indexed on `(project, status)`, priority ordering (high → medium → low), connection factory and migration system matching existing patterns
- **Test coverage:** 18 tests covering schema migrations, all CLI commands, project scoping, and priority ordering

## [0.6.0] — 2026-03-08

**Reflection system.**
Synthesise observations into durable insights with the new `/reflect` skill and reflection engine.

- **Reflection engine:** `mc-tool-memory reflect` reads last 7 days of memory entries + observation JSONL logs, calls Claude Haiku to identify patterns and themes, stores insights as `type=insight` (importance=6) in memory.db
- **`/reflect` skill:** Slash command with preprocessing — presents insights and proposes MEMORY.md additions for user approval
- **Novelty gate:** Skips reflection if fewer than 3 new observations since last reflection; overridable with `--min-new 0`
- **CLI flags:** `--days` (default 7) and `--min-new` (default 3) for controlling reflection scope
- **Shared LLM module:** Extracted `call_claude()` from observe hook into `src/mait_code/llm.py` — reused by both extraction and reflection
- **Refactored extractor:** `call_haiku` now delegates to shared `call_claude` with `model="haiku"`, `timeout=45`
- **Test coverage:** 15 new tests covering reflection logic, `_format_extraction`, `read_memory_md`, observation log edge cases, CLI output, and `call_haiku` delegation

## [0.5.0] — 2026-03-08

**Vector embeddings and shared logging.**
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

## [0.4.0] — 2026-03-08

**Entity system, observation hooks, and hooks reorganisation.**
Added knowledge graph entity tracking, automatic observation extraction from conversations, and reorganised hooks to follow the same package convention as tools.

- **Entity system:** `memory_entities` and `memory_relationships` tables (migrations 5–6) with CRUD operations — upsert, case-insensitive lookup, relationship tracking with mention counts
- **Observation hook:** Automatic knowledge extraction via Claude Haiku on `PreCompact` and `SessionEnd` — extracts facts, preferences, decisions, bugs, entities, and relationships from conversation transcripts
- **Async PreCompact hook:** Observation hook now runs asynchronously to avoid blocking the main conversation during context compaction
- **Hooks reorganisation:** All hooks now follow `hooks/<hook_name>/cli.py` package pattern (matching `tools/<tool_name>/cli.py`), eliminating the flat-file/submodule inconsistency
- **CLI commands:** Added `mc-tool-memory entities` and `mc-tool-memory relationships` subcommands for querying the knowledge graph
- **Cursor-based incremental extraction:** Only processes new transcript lines since last invocation, with automatic pruning of stale cursors (>30 days)
- **Updated conventions:** CLAUDE.md, docs, and pyproject.toml entry points updated to reflect new package structure

## [0.3.1] — 2026-03-07

**Replace reminders MCP server with CLI tool.**
Replaced the last MCP server (`mait-reminders`) with a sync CLI tool and skills, eliminating the `mcp` dependency entirely.

- **`mc-tool-reminders` CLI tool:** Subcommands `set`, `list`, `dismiss`, `check` with SQLite storage, dateparser for flexible time input, UTC normalization
- **`/remind` skill:** Set reminders via slash command (e.g. `/remind in 2 hours check deploy`)
- **`/reminders` skill:** List active and overdue reminders with preprocessing
- **Session start hook:** Now surfaces overdue reminders at the beginning of each session
- **SQLite storage:** Dedicated `reminders.db` with connection factory and migration system matching the memory tool patterns
- **Removed** `mait-reminders` MCP server, `src/mait_code/mcp/` directory, and `mcp[cli]` dependency
- **Restructured tests:** Mirror `src/mait_code/` directory structure (`tests/tools/memory/`, `tests/tools/reminders/`) with per-tool conftest fixtures

## [0.3.0] — 2026-03-06

**Replace memory MCP server with CLI tools + skills.**
Replaced the `mait-memory` MCP server with a sync CLI tool (`mc-tool-memory`) and three skills, eliminating process overhead and simplifying the architecture.

- **`mc-tool-memory` CLI tool:** Subcommands `search`, `store`, `list`, `delete`, `stats` — same functionality as the former MCP server, now invoked via Bash
- **`/recall` skill:** Uses preprocessing (`!`mc-tool-memory search ...``) to inject results before Claude sees the prompt — zero tool-call overhead
- **`/remember` skill:** Manual-only (`disable-model-invocation: true`) skill to store memories via slash command
- **`memory-store` skill:** Auto-invoked by Claude (`user-invocable: false`) to proactively store observations about the user
- **Removed** `mait-memory` MCP server (`src/mait_code/mcp/memory_server.py`) and its `settings.json` registration
- **Renamed** all entry points to `mc-{hook|tool|mcp}-*` convention (e.g. `mc-hook-session-start`, `mc-tool-reflect`)
- **Updated** all documentation to reflect the new architecture

## [0.2.0] — 2026-03-05

**Phase 1: Memory Core.**
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

## [0.1.0] — 2026-03-04

**Phase 0: Foundation.**
Initial project scaffold establishing the core structure and tooling.

- **Packaging:** uv/hatchling build system with Python 3.13+, dependencies on `mcp`, `sqlite-vec`, `dateparser`, `pyyaml`
- **Hooks:** Stub entry points for `session_start`, `observe`, and `auto_format` hooks
- **MCP servers:** Stub `memory_server` and `reminders_server`
- **CLI tools:** Stub `reflect` and `rebuild_db` commands
- **Identity:** Soul document and user context templates adapted from the mait gateway
- **Config:** Global `CLAUDE.md` with companion behaviour rules, `settings.json` with hook and MCP server registrations
- **Scripts:** `install.sh` and `uninstall.sh` for automated setup/teardown
- **Docs:** Architecture overview, philosophy, setup guide, skills reference, multi-machine sync guide, and development guide

## [0.0.0] — 2026-03-04

**Init.**
Repository initialised with README.


[Unreleased]: https://github.com/wiktordepina/mait-code/compare/v0.15.2...HEAD
[0.15.2]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.2
[0.15.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.1
[0.15.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.15.0
[0.14.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.14.1
[0.14.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.14.0
[0.13.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.13.0
[0.12.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.12.1
[0.12.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.12.0
[0.11.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.11.0
[0.10.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.10.0
[0.9.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.9.0
[0.8.2]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.2
[0.8.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.1
[0.8.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.8.0
[0.7.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.7.0
[0.6.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.6.0
[0.5.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.5.0
[0.4.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.4.0
[0.3.1]: https://github.com/wiktordepina/mait-code/releases/tag/v0.3.1
[0.3.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.3.0
[0.2.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.2.0
[0.1.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.1.0
[0.0.0]: https://github.com/wiktordepina/mait-code/releases/tag/v0.0.0
