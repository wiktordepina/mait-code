# `mait-code` command reference

The `mait-code` binary owns the install lifecycle. It's installed via
`uv tool install` from the local source — the bash shim
(`scripts/install.sh`) handles that bootstrap step the first time.
After that, everything goes through the CLI.

This page documents every subcommand: synopsis, flags, behaviour,
examples, exit codes.

## Conventions

| Convention | Meaning |
|------------|---------|
| `<value>` | Required positional or option argument the user supplies. |
| `[--flag]` | Optional flag. |
| `--claude-dir <path>` | Override `~/.claude` (useful for tests and non-default layouts). All subcommands accept it. |
| `--data-dir <path>` | Override `~/.claude/mait-code-data`. Install / uninstall / status / doctor accept it. |

Every subcommand also accepts `--help` and prints a one-screen summary.

## Install record

The CLI persists state at `~/.local/share/mait-code/install.json`
(XDG-aware — honours `$XDG_DATA_HOME`). It is:

- Created by `install`.
- Updated by `update` (version + timestamp).
- Read by `update`, `uninstall`, `status`, `doctor`.
- Removed by `uninstall`.

Schema (`schema_version: 1`):

```json
{
  "source_dir": "/home/wiktor/projects/mait-code",
  "version": "0.14.1",
  "embedding_provider": "local",
  "installed_at": "2026-05-27T10:00:00+00:00",
  "schema_version": 1
}
```

A binary refuses to read a record whose `schema_version` exceeds what
it understands — the error message points at `mait-code update` as the
recovery path.

---

## `mait-code install`

**Synopsis**

```
mait-code install --from <path> [--embedding-provider local|bedrock]
                  [--data-dir <path>] [--claude-dir <path>]
```

**Description**

First-time setup. Validates the source path is a mait-code clone,
creates data directories, copies templates, sets up symlinks
(`CLAUDE.md`, `skills/*`, `agents/*`), merges `settings.json`, and
writes the install record.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--from <path>` | *(required)* | Absolute path to the cloned mait-code source tree. |
| `--embedding-provider <name>` | `local` | `local` (fastembed) or `bedrock` (AWS Bedrock; install with `[bedrock]` extra). |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Verifies `<source>/pyproject.toml` exists with `name = "mait-code"` and `<source>/src/mait_code/` is a directory.
2. Creates `<data-dir>/memory/observations/` and `<data-dir>/memory/reflections/`. (`memory/graph/` is intentionally not created.)
3. Copies `templates/soul_document.md` and `templates/user_context.md` into the data dir — **never overwrites** existing files.
4. Writes a `MEMORY.md` stub into `<data-dir>/memory/` if missing.
5. Symlinks `<source>/config/CLAUDE.md` to `<claude-dir>/CLAUDE.md`. If a non-symlink `CLAUDE.md` already exists, it's first renamed to `CLAUDE.md.backup`.
6. Symlinks each `<source>/skills/<name>/` into `<claude-dir>/skills/` and each `<source>/agents/<file>` into `<claude-dir>/agents/`. `.gitkeep` placeholders are skipped.
7. Merges `<source>/config/settings.json` into `<claude-dir>/settings.json` (hooks, mcpServers, and `MAIT_CODE_EMBEDDING_PROVIDER` env). User-set keys are preserved verbatim. The write is atomic (tempfile + rename).
8. Writes the install record.

**Examples**

```bash
# Standard install from a local clone:
mait-code install --from "$PWD"

# Bedrock-backed install with a non-default data directory:
mait-code install --from /opt/mait-code/source \
                  --embedding-provider bedrock \
                  --data-dir /var/lib/mait-code
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Install succeeded. |
| `1` | `<source>` is not a mait-code clone, or `--embedding-provider` is not one of `local` / `bedrock`. |

**Notes**

- This subcommand does **not** run `uv tool install`. By the time it
  runs, the `mait-code` binary is already on PATH (that's how it was
  invoked). The bash shim handles the bootstrap.
- Re-running `install` is safe — it's idempotent. Symlinks that
  already point at the right target are left alone; templates are
  never overwritten.

---

## `mait-code update`

**Synopsis**

```
mait-code update [--no-pull] [--ref <tag|branch|sha>] [--claude-dir <path>]
```

**Description**

Advance the source tree to the right ref, reinstall via `uv tool install --force --reinstall`, refresh symlinks and settings, bump the install record.

How the source is advanced depends on its current state — a bootstrap install pins to a release **tag** (detached HEAD), while a local-clone dev install sits on a **branch**:

- `--ref <X>` given → checkout `X`.
- On a branch → fast-forward it (`git merge --ff-only`).
- Detached HEAD (typical post-bootstrap) → checkout the latest `v*` tag.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--no-pull` | off | Skip the network fetch and branch fast-forward; reinstall from whatever is currently checked out. `--ref` still checks out a local ref. |
| `--ref <ref>` | *(none)* | `git checkout <ref>` (after a fetch unless `--no-pull`). Pins to a tag/branch/sha. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Reads the install record. Aborts with exit `1` if missing.
2. Verifies the recorded source dir still looks like a mait-code clone.
3. Unless `--no-pull`: `git fetch origin --tags --prune`.
4. Advance to the target ref:
    - `--ref` given → `git checkout <ref>`.
    - on a branch → `git merge --ff-only` (skipped under `--no-pull`).
    - detached HEAD → `git checkout <latest v* tag>`. Aborts if there are no tags and no `--ref`.
5. `uv tool install <source>[<extra>] --force --reinstall --python 3.13`. The `[bedrock]` extra is applied when the install record records the bedrock provider.
6. Re-runs the symlink and settings-merge steps from `install` (picks up new skills, settings.json changes).
7. Rewrites the install record with the new version and timestamp.

**Examples**

```bash
# Standard update — fetch, advance to latest tag (or fast-forward
# branch), reinstall, refresh:
mait-code update

# Pin to a specific release tag:
mait-code update --ref v0.14.1

# Reinstall from the current checkout without touching git:
mait-code update --no-pull
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Update succeeded. |
| `1` | No install record, source dir no longer valid, detached HEAD with no `v*` tags (and no `--ref`), or any subprocess (`git`, `uv`) failed. |

---

## `mait-code uninstall`

**Synopsis**

```
mait-code uninstall [--purge-data] [--keep-uv-tool]
                    [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Reverse the install footprint. Removes symlinks, strips mait-code
entries from `settings.json`, runs `uv tool uninstall mait-code`,
deletes the install record. Preserves the data directory by default.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--purge-data` | off | Also delete the data directory (memories, personalised soul / user-context files). Destructive. |
| `--keep-uv-tool` | off | Skip `uv tool uninstall mait-code` (useful when temporarily downgrading or switching extras). |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Behaviour**

1. Reads the install record (best-effort — missing record is a warning, not an error).
2. Removes `<claude-dir>/CLAUDE.md` if it's a symlink pointing into the recorded source. Restores `CLAUDE.md.backup` if present.
3. Removes skill symlinks under `<claude-dir>/skills/` that resolve into the recorded source. Foreign symlinks (e.g. from other tools) are preserved.
4. Same for agents.
5. Cleans mait-code-owned entries from `<claude-dir>/settings.json` (hook commands with the `mc-hook-` prefix; legacy `mait-reminders` MCP server; the `MAIT_CODE_EMBEDDING_PROVIDER` env). Empty top-level sections are dropped.
6. `uv tool uninstall mait-code` (unless `--keep-uv-tool`). Failure here is a warning — the binary may already be gone.
7. With `--purge-data`: deletes the data directory.
8. Deletes the install record.

**Examples**

```bash
# Standard uninstall — keeps memories and personalised files:
mait-code uninstall

# Full wipe (data dir too):
mait-code uninstall --purge-data

# Downgrade to an older release without losing settings:
mait-code uninstall --keep-uv-tool
uv tool install mait-code --version 0.14.0
mait-code install --from /path/to/old-source
```

**Exit codes**

`0` always. Uninstall is best-effort; missing components produce
warnings on stderr, not non-zero exit. If you need failure on broken
state, run `mait-code doctor` first.

---

## `mait-code status`

**Synopsis**

```
mait-code status [--json] [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Read-only summary of the current install. Always exits `0` — there's
no diagnostic intent here, just a report.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit a machine-readable JSON document instead of human-readable text. |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Reports**

| Section | Fields |
|---------|--------|
| Install record | `version`, `source_dir`, `embedding_provider`, `installed_at` |
| Binary | Resolved path of the `mait-code` binary (`shutil.which`) |
| CLAUDE.md | Symlink presence and target |
| Skills | Count of linked / available |
| Agents | Count of linked / available |
| Hooks | Names of hook events with at least one registered mait-code handler |
| Data dir | Path, size in MB, presence of `soul_document.md` / `user_context.md` / `memory/MEMORY.md` |

**Examples**

```bash
mait-code status
mait-code status --json | jq '.embedding_provider'
```

**Exit code:** always `0`.

---

## `mait-code doctor`

**Synopsis**

```
mait-code doctor [--fix] [--json] [--data-dir <path>] [--claude-dir <path>]
```

**Description**

Validate the install. Surfaces silent breakage — broken symlinks,
unparseable settings, hook commands missing from PATH. Exits `1` if
any check reports a `fail`-level finding, `0` otherwise.

**Flags**

| Flag | Default | Description |
|------|---------|-------------|
| `--fix` | off | Apply safe fixes for findings that support it. |
| `--json` | off | Emit a machine-readable JSON document. |
| `--data-dir <path>` | `$MAIT_CODE_DATA_DIR` or `~/.claude/mait-code-data` | Override the data directory location. |
| `--claude-dir <path>` | `~/.claude` | Override the Claude Code config directory. |

**Checks**

| Name | Levels | Description |
|------|--------|-------------|
| `install-record` | ok / fail | Record exists and parses at the expected schema version. |
| `source-dir` | ok / warn / fail | The recorded source still exists and looks like a mait-code clone. `warn` when there's no record to validate against. |
| `settings` | ok / warn / fail | `<claude-dir>/settings.json` parses as JSON. `warn` if missing. |
| `hooks-on-path` | ok / warn / fail | Every registered hook with the `mc-hook-` prefix resolves on `PATH`. |
| `symlinks` | ok / fail | No dangling symlinks under `<claude-dir>/skills/` or `<claude-dir>/agents/`. With `--fix`, removes them. |
| `data-dir` | ok / fail | The data dir exists and is writable. With `--fix`, creates it (plus the `memory/observations` and `memory/reflections` subdirs) if missing. |
| `uv-on-path` | ok / fail | `uv` is on `PATH` — required for `install` / `update`. |

**Examples**

```bash
mait-code doctor                       # diagnose
mait-code doctor --fix                 # diagnose and clean up safe findings
mait-code doctor --json | jq '.checks[] | select(.level=="fail")'
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No `fail`-level findings (warnings are allowed). |
| `1` | One or more checks reported `fail`. |

---

## `mait-code version`

**Synopsis**

```
mait-code version
```

**Description**

Print the installed `mait-code` package version (from
`importlib.metadata`). Falls back to `mait_code.__version__` when
running from a checkout that hasn't been `uv tool install`ed.

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Version printed. |
| `1` | Neither metadata nor in-tree `__version__` could be read. |

---

## See also

- [Setup](../setup.md) — first-time install walkthrough using the bash shim.
- [Skills](skills.md) — slash commands available inside a Claude Code session.
- [Python API → CLI](cli.md) — the helpers that power these subcommands (for contributors / extension authors).
