# Setup Guide

## Prerequisites

- **uv** — Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- **Claude Code** — Install from [docs.anthropic.com](https://docs.anthropic.com/en/docs/claude-code)
- **Python >= 3.13** — Managed by uv automatically

## Installation

```bash
# Clone the repository
git clone https://github.com/wiktordepina/mait-code.git
cd mait-code

# Install Python dependencies and create lockfile
uv sync

# Deploy companion configuration to ~/.claude/
./scripts/install.sh
```

`./scripts/install.sh` is a thin shim. It prompts for an embedding provider (`local`/`bedrock`), runs `uv tool install` so the `mait-code` and `mc-*` binaries land on `PATH`, then hands off to `mait-code install` for the rest. For non-interactive installs (e.g. CI, automation), invoke the CLI directly:

```bash
uv tool install . --force --reinstall --python 3.13
mait-code install --from "$PWD" --embedding-provider local
```

`mait-code install` performs:

1. Validates the source path is a mait-code clone.
2. Creates `~/.claude/mait-code-data/` with memory subdirectories (`observations/`, `reflections/`).
3. Copies identity templates (`soul_document.md`, `user_context.md`) — never overwrites existing files.
4. Bootstraps `memory/MEMORY.md` with a placeholder if missing.
5. Symlinks `CLAUDE.md` into `~/.claude/` (backs up any existing file to `CLAUDE.md.backup`).
6. Symlinks every `skills/*` directory into `~/.claude/skills/`.
7. Symlinks any `agents/*` files into `~/.claude/agents/`.
8. Merges hook registrations and the `MAIT_CODE_EMBEDDING_PROVIDER` env entry into `~/.claude/settings.json` (preserving any pre-existing keys).
9. Writes the install record at `~/.local/share/mait-code/install.json`.

## Lifecycle

Once installed, the `mait-code` binary owns the full install lifecycle. Six subcommands cover the common cases:

```bash
mait-code status            # read-only summary (use --json for machine-readable)
mait-code doctor            # surface silent breakage; --fix applies safe fixes
mait-code update            # git pull + reinstall + refresh symlinks/settings
mait-code uninstall         # remove symlinks, strip settings; preserves data by default
mait-code uninstall --purge-data   # also delete the data directory
mait-code version           # print the installed version
```

Every command accepts `--claude-dir` and (where relevant) `--data-dir` overrides for non-default layouts. See the **[CLI reference](reference/mait-code.md)** for full per-command flag tables, behaviour notes, and exit codes.

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

Since `CLAUDE.md` is a symlink, updating is simple:

```bash
cd /path/to/mait-code
git pull
./scripts/install.sh
```

The symlink ensures Claude Code always reads the latest config. Re-run `./scripts/install.sh` after pulling to reinstall CLI tools and merge any settings changes.

## Troubleshooting

**CLAUDE.md not loading:** Check that `~/.claude/CLAUDE.md` is a valid symlink (`ls -la ~/.claude/CLAUDE.md`). Re-run `./scripts/install.sh` if broken.

**Hooks not firing:** Verify `~/.claude/settings.json` contains the hook definitions. Check that `mc-hook-session-start` works from the command line.

**Memory tool not working:** Run `mc-tool-memory stats` to verify. Check that `./scripts/install.sh` has been run.

**Python version mismatch:** Run `uv python install 3.13` to ensure Python 3.13 is available.
