#!/usr/bin/env bash
# Convenience launcher.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
exec python3 -m megatui "$@"
