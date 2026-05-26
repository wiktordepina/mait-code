#!/usr/bin/env bash
#
# mait-code one-liner installer.
#
# From a fresh machine to a working install:
#   curl -fsSL https://raw.githubusercontent.com/wiktordepina/mait-code/main/scripts/bootstrap.sh | bash
#
# Pass flags after `bash -s --`:
#   curl -fsSL ... | bash -s -- --embedding-provider bedrock --ref v0.15.0
#
# Flags:
#   --embedding-provider <name>   local (default) or bedrock
#   --ref <tag|branch|sha>        Checkout this ref after cloning. Default: latest v* tag.
#   --dir <path>                  Install root. Default: ~/.local/share/mait-code
#   --repo-url <url>              Override the upstream repo URL (mainly for testing).
#   --no-uv                       Fail if uv isn't on PATH (don't try to install it).
#   --help, -h                    Print this usage.
#
# What it does:
#   1. Detects or installs `uv`.
#   2. Warns (does not fail) if Claude Code is missing.
#   3. Clones the repo to <dir>/source (or fetches if already there).
#   4. Checks out the requested ref.
#   5. `uv tool install` from the source, with the bedrock extra if requested.
#   6. Execs `mait-code install --from <dir>/source --embedding-provider <provider>`.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

REPO_URL="${MAIT_CODE_REPO_URL:-https://github.com/wiktordepina/mait-code.git}"
DEFAULT_DIR="${HOME}/.local/share/mait-code"
DIR="${DEFAULT_DIR}"
REF=""
PROVIDER="local"
SKIP_UV=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { printf '\033[1;34m::\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

show_help() {
    sed -n '2,/^$/p' "$0" | sed 's/^#//' | sed 's/^ //'
}

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)
            [[ $# -ge 2 ]] || die "--dir requires a value"
            DIR="$2"
            shift 2
            ;;
        --ref)
            [[ $# -ge 2 ]] || die "--ref requires a value"
            REF="$2"
            shift 2
            ;;
        --embedding-provider)
            [[ $# -ge 2 ]] || die "--embedding-provider requires a value"
            PROVIDER="$2"
            shift 2
            ;;
        --repo-url)
            [[ $# -ge 2 ]] || die "--repo-url requires a value"
            REPO_URL="$2"
            shift 2
            ;;
        --no-uv)
            SKIP_UV=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            die "unknown flag: $1 (try --help)"
            ;;
    esac
done

case "$PROVIDER" in
    local|bedrock) ;;
    *) die "--embedding-provider must be 'local' or 'bedrock' (got '$PROVIDER')" ;;
esac

SOURCE_DIR="${DIR}/source"

# ---------------------------------------------------------------------------
# 1. Detect or install uv
# ---------------------------------------------------------------------------

if ! command -v uv >/dev/null 2>&1; then
    if "$SKIP_UV"; then
        die "uv not on PATH and --no-uv was given. Install uv from https://docs.astral.sh/uv/"
    fi
    log "Installing uv from astral.sh..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv's installer writes ~/.local/bin/uv but does not modify PATH for the
    # current shell. Add it explicitly so the rest of this script sees it.
    export PATH="${HOME}/.local/bin:${PATH}"
    command -v uv >/dev/null 2>&1 \
        || die "uv installed but still not on PATH; check ~/.local/bin"
fi

log "Using uv at $(command -v uv)"

# ---------------------------------------------------------------------------
# 2. Warn (do not fail) if Claude Code is missing
# ---------------------------------------------------------------------------

if ! command -v claude >/dev/null 2>&1; then
    warn "Claude Code ('claude' binary) not on PATH."
    warn "Install separately at https://docs.anthropic.com/en/docs/claude-code"
fi

# ---------------------------------------------------------------------------
# 3. Clone or update the source tree
# ---------------------------------------------------------------------------

if [[ -d "${SOURCE_DIR}/.git" ]]; then
    log "Updating existing clone at ${SOURCE_DIR}..."
    git -C "$SOURCE_DIR" fetch --tags --quiet origin
else
    log "Cloning mait-code to ${SOURCE_DIR}..."
    mkdir -p "$DIR"
    git clone --quiet "$REPO_URL" "$SOURCE_DIR"
fi

# ---------------------------------------------------------------------------
# 4. Resolve and check out the ref
# ---------------------------------------------------------------------------

if [[ -z "$REF" ]]; then
    REF="$(git -C "$SOURCE_DIR" tag --list --sort=-v:refname 'v*' | head -n 1)"
    if [[ -z "$REF" ]]; then
        warn "No v* tags found; falling back to main"
        REF="main"
    fi
fi
log "Checking out ${REF}..."
git -C "$SOURCE_DIR" checkout --quiet "$REF"

# ---------------------------------------------------------------------------
# 5. Install via uv tool
# ---------------------------------------------------------------------------

EXTRA=""
if [[ "$PROVIDER" == "bedrock" ]]; then
    EXTRA="[bedrock]"
fi
log "Installing mait-code via uv tool..."
uv tool install "${SOURCE_DIR}${EXTRA}" --force --reinstall --python 3.13

# Make sure ~/.local/bin is on PATH for the exec below.
export PATH="${HOME}/.local/bin:${PATH}"
command -v mait-code >/dev/null 2>&1 \
    || die "uv tool install succeeded but mait-code is not on PATH (~/.local/bin missing from PATH?)"

# ---------------------------------------------------------------------------
# 6. Hand off to the CLI
# ---------------------------------------------------------------------------

log "Handing off to mait-code install..."
exec mait-code install --from "$SOURCE_DIR" --embedding-provider "$PROVIDER"
