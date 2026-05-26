#!/usr/bin/env bash
set -euo pipefail

# mait-code install shim.
#
# Resolves the chicken-and-egg of a first-time install: the `mait-code`
# binary needs to be on PATH before `mait-code install` can run, so we
# `uv tool install` from the local source first, then exec into the CLI
# for everything else (symlinks, settings merge, data dir, install
# record).
#
# Once the CLI is installed, all subsequent operations should be invoked
# directly: `mait-code update`, `mait-code uninstall`, `mait-code status`,
# `mait-code doctor`. This shim exists so existing muscle memory
# (./scripts/install.sh) keeps working.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Pick an embedding provider (interactive only when stdin is a TTY).
EMBED="${MAIT_CODE_EMBEDDING_PROVIDER:-}"
if [[ -z "$EMBED" ]]; then
    if [[ -t 0 ]]; then
        echo "Embedding provider:"
        echo "  1) local    — fastembed/HuggingFace (runs locally, ~550 MB)"
        echo "  2) bedrock  — AWS Bedrock (requires AWS credentials)"
        read -rp "Choose [1/2] (default: 1): " EMBED_CHOICE
        case "$EMBED_CHOICE" in
            2|bedrock) EMBED="bedrock" ;;
            *)         EMBED="local"   ;;
        esac
    else
        EMBED="local"
    fi
fi

EXTRA=""
if [[ "$EMBED" == "bedrock" ]]; then
    EXTRA="[bedrock]"
fi

# 1. Install the `mait-code` binary from the local source.
echo "Installing mait-code CLI from: $PROJECT_DIR"
uv tool install "${PROJECT_DIR}${EXTRA}" --force --reinstall --python 3.13

# 2. Hand off to the CLI for the rest of the install lifecycle.
exec mait-code install --from "$PROJECT_DIR" --embedding-provider "$EMBED" "$@"
