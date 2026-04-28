#!/usr/bin/env bash
# Personal-data linter — bash wrapper around scripts/check_no_personal_data.py.
# Used by CI and local pre-extraction checks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/check_no_personal_data.py" "$@"
