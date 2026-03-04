#!/usr/bin/env bash
set -euo pipefail

# Mait Code — Install Script
# Deploys companion configuration into ~/.claude/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
DATA_DIR="$CLAUDE_DIR/mait-code-data"

echo "Installing mait-code from: $PROJECT_DIR"
echo ""

# --- 1. Create data directory structure ---
echo "Creating data directories..."
mkdir -p "$DATA_DIR/memory/observations"
mkdir -p "$DATA_DIR/memory/reflections"
mkdir -p "$DATA_DIR/memory/graph"

# --- 2. Copy templates (never overwrite user's personalised files) ---
echo "Copying templates..."
if [ ! -f "$DATA_DIR/soul_document.md" ]; then
    cp "$PROJECT_DIR/templates/soul_document.md" "$DATA_DIR/soul_document.md"
    echo "  Created soul_document.md (personalise this!)"
else
    echo "  soul_document.md already exists, skipping"
fi

if [ ! -f "$DATA_DIR/user_context.md" ]; then
    cp "$PROJECT_DIR/templates/user_context.md" "$DATA_DIR/user_context.md"
    echo "  Created user_context.md (personalise this!)"
else
    echo "  user_context.md already exists, skipping"
fi

# --- 3. Create initial MEMORY.md ---
if [ ! -f "$DATA_DIR/memory/MEMORY.md" ]; then
    cat > "$DATA_DIR/memory/MEMORY.md" << 'MEMEOF'
# Memory

<!-- Curated facts about the user, their projects, and preferences. -->
<!-- Updated by the reflection system and manual editing. -->
<!-- Keep under ~150 lines for context budget. -->
MEMEOF
    echo "  Created MEMORY.md"
else
    echo "  MEMORY.md already exists, skipping"
fi

# --- 4. Symlink CLAUDE.md ---
echo "Setting up CLAUDE.md symlink..."
if [ -f "$CLAUDE_DIR/CLAUDE.md" ] && [ ! -L "$CLAUDE_DIR/CLAUDE.md" ]; then
    cp "$CLAUDE_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md.backup"
    echo "  Backed up existing CLAUDE.md to CLAUDE.md.backup"
fi
ln -sf "$PROJECT_DIR/config/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
echo "  Linked CLAUDE.md"

# --- 5. Symlink skills ---
if [ -d "$PROJECT_DIR/skills" ]; then
    mkdir -p "$CLAUDE_DIR/skills"
    for skill_dir in "$PROJECT_DIR/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        skill_name="$(basename "$skill_dir")"
        target="$CLAUDE_DIR/skills/$skill_name"
        if [ -L "$target" ] && [ "$(readlink "$target")" = "$skill_dir" ]; then
            echo "  Skill $skill_name already linked"
        else
            ln -sf "$skill_dir" "$target"
            echo "  Linked skill: $skill_name"
        fi
    done
fi

# --- 6. Symlink agents ---
if [ -d "$PROJECT_DIR/agents" ]; then
    mkdir -p "$CLAUDE_DIR/agents"
    for agent_file in "$PROJECT_DIR/agents"/*; do
        [ -f "$agent_file" ] || continue
        agent_name="$(basename "$agent_file")"
        [ "$agent_name" = ".gitkeep" ] && continue
        target="$CLAUDE_DIR/agents/$agent_name"
        if [ -L "$target" ] && [ "$(readlink "$target")" = "$agent_file" ]; then
            echo "  Agent $agent_name already linked"
        else
            ln -sf "$agent_file" "$target"
            echo "  Linked agent: $agent_name"
        fi
    done
fi

# --- 7. Merge settings.json ---
echo "Merging settings.json..."
SETTINGS_SRC="$PROJECT_DIR/config/settings.json"
SETTINGS_DST="$CLAUDE_DIR/settings.json"

uv run --project "$PROJECT_DIR" python -c "
import json, sys

project_dir = '$PROJECT_DIR'

# Read source settings and replace placeholder
with open('$SETTINGS_SRC') as f:
    src = json.load(f)

def replace_placeholder(obj):
    if isinstance(obj, str):
        return obj.replace('__MAIT_CODE_PROJECT__', project_dir)
    elif isinstance(obj, list):
        return [replace_placeholder(v) for v in obj]
    elif isinstance(obj, dict):
        return {k: replace_placeholder(v) for k, v in obj.items()}
    return obj

src = replace_placeholder(src)

# Read or create destination settings
try:
    with open('$SETTINGS_DST') as f:
        dst = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    dst = {}

# Merge hooks
if 'hooks' not in dst:
    dst['hooks'] = {}
for hook_name, hook_config in src.get('hooks', {}).items():
    dst['hooks'][hook_name] = hook_config

# Merge MCP servers
if 'mcpServers' not in dst:
    dst['mcpServers'] = {}
for server_name, server_config in src.get('mcpServers', {}).items():
    dst['mcpServers'][server_name] = server_config

with open('$SETTINGS_DST', 'w') as f:
    json.dump(dst, f, indent=2)
    f.write('\n')

print('  Settings merged successfully')
"

# --- 8. Summary ---
echo ""
echo "=== Installation complete ==="
echo ""
echo "Installed:"
echo "  CLAUDE.md    → $CLAUDE_DIR/CLAUDE.md"
echo "  Data dir     → $DATA_DIR/"
echo "  Settings     → $SETTINGS_DST"
echo ""
echo "Next steps:"
echo "  1. Personalise $DATA_DIR/soul_document.md"
echo "  2. Fill in $DATA_DIR/user_context.md"
echo "  3. Start Claude Code in any project — the companion will load automatically"
