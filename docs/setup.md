# Setup Guide

## Prerequisites

- **uv** — Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- **Claude Code** — Install from [docs.anthropic.com](https://docs.anthropic.com/en/docs/claude-code)
- **Python >= 3.13** — Managed by uv automatically

## Installation

The fastest path is the one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
```

This installs `uv` if missing, clones the latest release tag to `~/.local/share/mait-code/source/`, runs `uv tool install`, then `exec`s `mait-code install` to set up symlinks, settings, and data directories. Idempotent — re-run any time to upgrade.

### Flags

Pass flags via `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh \
    | bash -s -- --embedding-provider bedrock --ref v0.43.0
```

| Flag | Default | Purpose |
|------|---------|---------|
| `--embedding-provider local\|bedrock` | `local` | Forwarded to `mait-code install`. |
| `--ref <tag\|branch\|sha>` | latest `v*` tag | Checkout this ref after cloning. `main` for bleeding edge. |
| `--dir <path>` | `~/.local/share/mait-code` | Install root. Source goes in `<dir>/source`. |
| `--no-uv` | off | Don't try to install `uv` (fail if not on PATH). |
| `--repo-url <url>` | upstream repo | Override the clone source (mainly for testing). |
| `--help` | — | Print usage. |

### Inspect before running

`curl … \| bash` requires trusting the URL. To audit the script first:

```bash
curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh \
    -o /tmp/mait-code-bootstrap.sh
less /tmp/mait-code-bootstrap.sh
bash /tmp/mait-code-bootstrap.sh
```

### From a local clone

If you're developing mait-code itself or want the source in a specific location:

```bash
git clone https://github.com/wiktordepina/mait-code.git
cd mait-code
uv sync
./scripts/install.sh
```

`./scripts/install.sh` is a thin shim around `mait-code install`. For non-interactive installs (e.g. CI, automation), invoke the CLI directly:

```bash
uv tool install . --force --reinstall --python 3.13
mait-code install --from "$PWD" --embedding-provider local
```

`mait-code install` performs:

1. Validates the source path is a mait-code clone.
2. Creates `~/.claude/mait-code-data/` with memory subdirectories (`memory/observations/`, `memory/reflections/`).
3. Copies identity templates (`soul_document.md`, `user_context.md`) — never overwrites existing files.
4. Bootstraps `memory/MEMORY.md` with a placeholder if missing.
5. Symlinks `CLAUDE.md` into `~/.claude/` (backs up any existing file to `CLAUDE.md.backup`).
6. Symlinks every `skills/*` directory into `~/.claude/skills/`.
7. Symlinks any `agents/*` files into `~/.claude/agents/`.
8. Writes the centralised settings file at `$XDG_CONFIG_HOME/mait-code/settings.toml` with all configuration values (including the chosen embedding provider).
9. Propagates settings as `MAIT_CODE_*` env vars and merges hook registrations into `~/.claude/settings.json` (preserving any pre-existing keys).
10. Writes the install record at `~/.local/share/mait-code/install.json`.

## Lifecycle

Once installed, the `mait-code` binary owns the full install lifecycle. Its subcommands cover the common cases:

```bash
mait-code status            # read-only summary with a health badge, first-install
                            # and last-update dates (use --json)
mait-code doctor            # run 14 health checks; --fix applies safe fixes (--json)
mait-code settings          # edit config interactively (lists when piped)
mait-code settings list     # read-only view of the active config (use --json)
mait-code settings get log-level         # one resolved value and its source (--json)
mait-code settings set log-level DEBUG   # validate, persist, enforce one knob
mait-code settings unset env.FOO         # drop a custom [env] variable
mait-code update            # fetch, advance, reinstall if HEAD moved
mait-code uninstall         # remove symlinks, settings file and the uv tool;
                            # preserves data by default
mait-code uninstall --purge-data   # also delete the data directory
mait-code version           # print the installed version
```

`doctor --fix` currently repairs three findings: dangling symlinks, a missing data
directory, and missing embeddings. The rest it reports.

`uninstall` also runs `uv tool uninstall mait-code`, which removes the `mait-code`
binary itself — pass `--keep-uv-tool` to leave it in place.

The TUI surfaces are separate subcommands:

```bash
mait-code                   # the home hub on a terminal; help when piped
mait-code home              # the home hub explicitly
mait-code board             # kanban board
mait-code memory            # memory browser
mait-code review            # the memory review queue
mait-code observations      # observations browser
mait-code graph             # knowledge-graph explorer
mait-code logs              # log viewer
```

The install-lifecycle commands (`install`, `update`, `uninstall`, `status`,
`doctor`) accept `--claude-dir`, and all but `update` accept `--data-dir`, for
non-default layouts. The TUI subcommands, `settings` and `version` take neither.
Coloured output can be disabled with the global `--no-color` flag. See the **[CLI
reference](reference/mait-code.md)** for full per-command flag tables, behaviour
notes, and exit codes.

## Personalisation

After installation, edit these files to customise your companion:

### Soul Document (`~/.claude/mait-code-data/soul_document.md`)

Defines the companion's identity — its values, communication style, and personality. Key sections to personalise:

- **Core Values** — Pick 3-5 values that matter to you (defaults provided)
- **Personality** — Set the tone for how the companion develops over time
- **Communication Style** — Adjust verbosity, formality, etc.
- **Constructive Challenge** — How pushback should feel

### User Context (`~/.claude/mait-code-data/user_context.md`)

Tells the companion about you:

- **Identity** — Name, role, timezone
- **Technical Environment** — Languages, infra, CI/CD, IDE
- **Working Style** — Commit conventions, review prefs, testing approach
- **Current Projects** — What you're working on

Fill in what's relevant, delete what isn't. The observation system will suggest additions over time.

## Verification

After installation, verify everything works:

```bash
# Check CLAUDE.md symlink
ls -la ~/.claude/CLAUDE.md
# Should point to → /path/to/mait-code/config/CLAUDE.md

# Check data directory
ls ~/.claude/mait-code-data/
# Should contain: soul_document.md  user_context.md  memory/

# Check settings
cat ~/.claude/settings.json | python3 -m json.tool
# Should contain mait-code hooks

# Verify the memory CLI tool works
mc-tool-memory stats
# Should print "No memories stored yet." on fresh install

# Check skills are symlinked
ls -la ~/.claude/skills/recall/
# Should point to → /path/to/mait-code/skills/recall

# Start Claude Code — companion context should load
claude
# Try: /recall test  (should return "No memories found" on fresh install)
```

## Updating

Use the built-in updater:

```bash
mait-code update
```

It fetches, advances the source clone, and reinstalls only if `HEAD` actually
moved — then refreshes symlinks and merges settings changes. Useful flags:
`--ref` to advance to a specific branch or tag, `--no-pull` to reinstall from the
clone as-is, and `--force` to reinstall even when nothing moved.

Do not `git pull` a bootstrap install. The clone at
`~/.local/share/mait-code/source` is pinned to a release tag in detached HEAD,
where `git pull` fails outright — resolving that is exactly why `update` exists.

From a development clone you can still update by hand:

```bash
cd /path/to/mait-code
git pull
./scripts/install.sh
```

Because `CLAUDE.md` is a symlink, Claude Code always reads the latest config
either way.

## Troubleshooting

**Start here:** `mait-code doctor --fix`. It runs 14 checks covering symlinks,
hook registration, hooks-on-PATH, the data directory, memory health, embeddings,
vector search, the observe pipeline, the Bridge, and settings values — and
repairs the three it safely can. `mait-code logs` (or
`$XDG_STATE_HOME/mait-code/mait-code.jsonl`) shows what actually happened.

If a specific symptom persists:

**CLAUDE.md not loading:** Check that `~/.claude/CLAUDE.md` is a valid symlink (`ls -la ~/.claude/CLAUDE.md`). `doctor --fix` repairs dangling symlinks.

**Hooks not firing:** Verify `~/.claude/settings.json` contains the hook definitions. Check that `mc-hook-session-start` works from the command line — the `hooks-on-path` check covers this case.

**Memory tool not working:** Run `mc-tool-memory stats` to verify. The `memory-embeddings` and `vector-search` checks cover degraded search.

**Python version mismatch:** Run `uv python install 3.13` to ensure Python 3.13 is available.

**Stale install:** `mait-code update` — see [Updating](#updating).
