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
mait-code status            # read-only summary, with a health badge (use --json)
mait-code doctor            # surface silent breakage; --fix applies safe fixes
mait-code settings          # edit config interactively (lists when piped)
mait-code settings list     # read-only view of the active config (use --json)
mait-code settings set log-level DEBUG   # validate, persist, enforce one knob
mait-code update            # git pull, reinstall if changed, refresh symlinks/settings
mait-code uninstall         # remove symlinks, strip settings; preserves data by default
mait-code uninstall --purge-data   # also delete the data directory
mait-code version           # print the installed version
```

Most commands accept `--claude-dir` and (where relevant) `--data-dir` overrides for non-default layouts (`settings` and `version` take neither). Coloured output can be disabled with the global `--no-color` flag. See the **[CLI reference](reference/mait-code.md)** for full per-command flag tables, behaviour notes, and exit codes.

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
