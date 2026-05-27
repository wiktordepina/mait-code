#!/usr/bin/env bash
#
# Smoke-test scripts/bootstrap.sh inside a fresh Ubuntu container.
#
# Spins up an `ubuntu:24.04` container with no preinstalled tooling,
# installs the minimum needed to run a curl-pipe-bash-style install
# (`curl`, `git`, `ca-certificates`), then runs bootstrap.sh against
# the LOCAL repo (passed via `--repo-url file:///mait-code-src`). After
# the install completes, verifies the post-state.
#
# Run from the repo root:
#   ./scripts/test-bootstrap.sh
#
# Requires Docker on the host. Not invoked by CI in v1 — run locally
# before merging changes to bootstrap.sh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '\033[1;34m::\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not on PATH"

log "Running bootstrap inside ubuntu:24.04 (this may take a few minutes)..."

docker run --rm \
    -v "${REPO_DIR}:/mait-code-src:ro" \
    -e DEBIAN_FRONTEND=noninteractive \
    ubuntu:24.04 \
    bash -c '
        set -euo pipefail

        echo "::group::install prerequisites"
        apt-get update -qq
        apt-get install -y -qq curl git ca-certificates >/dev/null
        # The bind-mounted /mait-code-src has its owner UID from the host;
        # inside the container we are uid 0, so git refuses to operate on
        # it without an explicit safe.directory exception.
        git config --global --add safe.directory /mait-code-src
        git config --global --add safe.directory /mait-code-src/.git
        echo "::endgroup::"

        echo "::group::run bootstrap from local source"
        # Use file:// URL so the bootstrap clones from the mounted
        # local copy rather than github.com — this lets us validate
        # PR changes without needing them merged to main first.
        bash /mait-code-src/scripts/bootstrap.sh \
            --repo-url "file:///mait-code-src" \
            --ref HEAD \
            --embedding-provider local \
            --dir "$HOME/.local/share/mait-code"
        echo "::endgroup::"

        echo "::group::verify post-state"
        export PATH="$HOME/.local/bin:$PATH"

        # mait-code binary on PATH
        which mait-code

        # version prints something
        ver=$(mait-code version)
        echo "Installed version: $ver"
        [[ -n "$ver" && "$ver" != "unknown" ]] || { echo "version failed"; exit 1; }

        # status shows installed state
        mait-code status --json | head -20

        # install record exists
        test -f "$HOME/.local/share/mait-code/install.json" \
            || { echo "install.json missing"; exit 1; }

        # data dir layout
        test -d "$HOME/.claude/mait-code-data/memory/observations" \
            || { echo "data dir not set up"; exit 1; }

        # CLAUDE.md symlinked
        test -L "$HOME/.claude/CLAUDE.md" \
            || { echo "CLAUDE.md not symlinked"; exit 1; }

        # settings.json merged
        test -f "$HOME/.claude/settings.json" \
            || { echo "settings.json missing"; exit 1; }

        echo "::endgroup::"
        echo
        echo "SMOKE TEST PASSED"
    '

log "Container exited cleanly. Bootstrap works end-to-end."
