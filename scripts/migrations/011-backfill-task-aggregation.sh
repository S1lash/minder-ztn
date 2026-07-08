#!/usr/bin/env bash
# 011-backfill-task-aggregation — Detect tasks that live in notes but never
# reached the TASKS.md aggregate (the aggregation silent-drop) and nudge the
# owner to recover them through the pipeline.
#
# Process now guarantees completeness deterministically: Step 4.1 runs
# `reconcile_tasks.py` as a backstop and the gate fails unless it reports
# `consistent: true`. This migration recovers the PRE-EXISTING backlog on a
# friend's clone. It cannot classify orphans (Action / Waiting / Delegate needs
# the LLM) and does not write owner-data, so it only DETECTS + reports the
# one-liner. Soft nag: exits 0 in every case (a backlog is not a sync failure —
# a non-zero exit would abort sync_engine.sh under `set -e`; see 007 / 014).
# Idempotent: zero orphans → clean no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
RECONCILE="$ZK/_system/scripts/reconcile_tasks.py"

if [[ ! -f "$ZK/_system/TASKS.md" || ! -f "$RECONCILE" ]]; then
    echo "info: TASKS.md or reconcile_tasks.py not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# Capture the reconciler's JSON, then parse defensively. A crash / empty output
# yields sentinel -1 so we NEVER coerce a failed run into a false "all clear"
# (surface, don't decide silently).
raw="$(python3 "$RECONCILE" --base "$ZK" --report --json 2>/dev/null || true)"
count="$(printf '%s' "$raw" | python3 -c '
import sys, json
try:
    print(int(json.load(sys.stdin).get("orphan_count", -1)))
except Exception:
    print(-1)
' 2>/dev/null || echo -1)"
count="${count:--1}"

if [[ "$count" -lt 0 ]]; then
    echo "[migration 011] reconcile_tasks.py produced no valid output — NOT assuming all-clear." >&2
    echo "  Inspect manually: python3 $RECONCILE --base \"$ZK\" --report" >&2
    exit 0
fi

if [[ "$count" -eq 0 ]]; then
    echo "[migration 011] task aggregate is consistent — no un-aggregated tasks, no-op"
    exit 0
fi

cat >&2 <<EOF

[migration 011] Found $count task(s) that live in your notes as open '- [ ]'
items but never reached TASKS.md (the aggregation gap). They are not lost — the
reconciler re-derives them from the notes on demand. To classify and file them,
run once:

    /ztn:process --reconcile-tasks

(Inspect them first with:
    python3 $RECONCILE --base "$ZK" --report )
EOF
exit 0
