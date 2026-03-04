#!/usr/bin/env bash
set -euo pipefail

# Mait Code — Uninstall Script
# Removes companion configuration from ~/.claude/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
DATA_DIR="$CLAUDE_DIR/mait-code-data"

echo "Uninstalling mait-code..."
echo ""

# --- 1. Remove CLAUDE.md symlink ---
if [ -L "$CLAUDE_DIR/CLAUDE.md" ]; then
    rm "$CLAUDE_DIR/CLAUDE.md"
    echo "Removed CLAUDE.md symlink"
    if [ -f "$CLAUDE_DIR/CLAUDE.md.backup" ]; then
        mv "$CLAUDE_DIR/CLAUDE.md.backup" "$CLAUDE_DIR/CLAUDE.md"
        echo "Restored CLAUDE.md.backup"
    fi
else
    echo "CLAUDE.md is not a symlink, skipping"
fi

# --- 2. Remove skill symlinks ---
if [ -d "$PROJECT_DIR/skills" ]; then
    for skill_dir in "$PROJECT_DIR/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        skill_name="$(basename "$skill_dir")"
        target="$CLAUDE_DIR/skills/$skill_name"
        if [ -L "$target" ]; then
            rm "$target"
            echo "Removed skill symlink: $skill_name"
        fi
    done
fi

# --- 3. Remove agent symlinks ---
if [ -d "$PROJECT_DIR/agents" ]; then
    for agent_file in "$PROJECT_DIR/agents"/*; do
        [ -f "$agent_file" ] || continue
        agent_name="$(basename "$agent_file")"
        [ "$agent_name" = ".gitkeep" ] && continue
        target="$CLAUDE_DIR/agents/$agent_name"
        if [ -L "$target" ]; then
            rm "$target"
            echo "Removed agent symlink: $agent_name"
        fi
    done
fi

# --- 4. Remove mait-code hooks and MCP servers from settings.json ---
SETTINGS_DST="$CLAUDE_DIR/settings.json"
if [ -f "$SETTINGS_DST" ]; then
    echo "Cleaning settings.json..."
    python3 -c "
import json

with open('$SETTINGS_DST') as f:
    settings = json.load(f)

# Remove mait-code hooks
hooks = settings.get('hooks', {})
for hook_name in ['SessionStart', 'PreCompact', 'SessionEnd']:
    if hook_name in hooks:
        # Remove entries that reference mait-code
        hooks[hook_name] = [
            entry for entry in hooks[hook_name]
            if not any(
                'mait-code' in h.get('command', '')
                for h in entry.get('hooks', [])
            )
        ]
        if not hooks[hook_name]:
            del hooks[hook_name]

# Remove mait-code MCP servers
servers = settings.get('mcpServers', {})
for server_name in ['mait-memory', 'mait-reminders']:
    servers.pop(server_name, None)

# Clean up empty sections
if not hooks:
    settings.pop('hooks', None)
if not servers:
    settings.pop('mcpServers', None)

with open('$SETTINGS_DST', 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print('  Removed mait-code entries from settings.json')
"
fi

# --- 5. Optionally remove data directory ---
if [ -d "$DATA_DIR" ]; then
    echo ""
    read -rp "Remove data directory ($DATA_DIR)? This deletes your memories and personalised files. [y/N] " response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        rm -rf "$DATA_DIR"
        echo "Removed data directory"
    else
        echo "Kept data directory"
    fi
fi

echo ""
echo "=== Uninstall complete ==="
