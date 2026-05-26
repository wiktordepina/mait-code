#!/usr/bin/env bash
set -euo pipefail

# mait-code uninstall shim.
#
# Forwards all arguments to `mait-code uninstall`. Kept for muscle
# memory; prefer invoking `mait-code uninstall` directly.

exec mait-code uninstall "$@"
