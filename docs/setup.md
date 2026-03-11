# Setup Guide

## Prerequisites

- **uv** — Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- **Claude Code** — Install from [docs.anthropic.com](https://docs.anthropic.com/en/docs/claude-code)
- **Python >= 3.13** — Managed by uv automatically

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mait-code.git
cd mait-code

# Install Python dependencies and create lockfile
uv sync

# Deploy companion configuration to ~/.claude/
./scripts/install.sh
```

The install script:
1. Creates `~/.claude/mait-code-data/` with memory subdirectories
2. Copies identity templates (won't overwrite existing files)
3. Symlinks `CLAUDE.md` into `~/.claude/`
4. Registers hooks in `~/.claude/settings.json`

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
