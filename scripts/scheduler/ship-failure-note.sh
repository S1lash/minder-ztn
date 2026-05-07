#!/usr/bin/env bash
# Append a one-line failure note to CLARIFICATIONS.md and ship it via
# scripts/scheduler/save.sh so the owner sees what went wrong on the
# next interactive resolve session.
#
# Idempotent: ensures the `### Scheduler failures` section exists before
# appending. printf uses `--` end-of-options guard because the appended
# bullet starts with `-` (a leading dash is otherwise parsed as a flag —
# observed failure 2026-05-07T01:06Z).
#
# Usage:
#   bash scripts/scheduler/ship-failure-note.sh "<cause>" <tick-name>
#
# Example:
#   bash scripts/scheduler/ship-failure-note.sh \
#     "lock-check failed: .lint.lock recent" lint-nightly
#
# Exit codes:
#   0 — note appended and shipped
#   1 — bad invocation
#   2 — save.sh failed (note may be uncommitted; see stderr)

set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 \"<cause>\" <tick-name>" >&2
  exit 1
fi

CAUSE="$1"
TICK="$2"
CLAR="zettelkasten/_system/state/CLARIFICATIONS.md"
TS="$(date -u +%Y-%m-%dT%H:%MZ)"

mkdir -p "$(dirname "$CLAR")"
touch "$CLAR"
grep -q '^### Scheduler failures$' "$CLAR" || printf '\n### Scheduler failures\n' >> "$CLAR"
printf -- '- %s scheduler-%s: %s\n' "$TS" "$TICK" "$CAUSE" >> "$CLAR"

# Ship via canonical save (engine-aware). save.sh stages CLARIFICATIONS as
# owner-data, so the note lands on origin/main as a [scheduled] commit.
if ! bash scripts/scheduler/save.sh "scheduler: $TICK failed: $CAUSE"; then
  echo "ship-failure-note: save.sh failed; CLARIFICATIONS note may be uncommitted" >&2
  exit 2
fi
