#!/usr/bin/env bash
# 012-backfill-calendar-aggregation — Detect notes with a future 📅 event that
# never reached CALENDAR.md (the aggregation silent-drop) and nudge the owner to
# recover them through the pipeline.
#
# Process Step 4.2 now runs `reconcile_calendar.py` as a deterministic backstop
# and its gate fails unless the reconciler reports `consistent: true`. This
# migration recovers a friend's PRE-EXISTING drop. The check is coarse (by
# note-link, future events only — the calendar aggregate carries no stable
# ^meeting-id and dates are fuzzy), and cannot re-aggregate events (needs the
# LLM), so it only DETECTS + reports. Soft nag: exits 0 in every case (a dropped
# event is not a sync failure; a non-zero exit would abort sync_engine.sh under
# `set -e` — see 007 / 011 / 014). Idempotent: zero orphans → clean no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
RECONCILE="$ZK/_system/scripts/reconcile_calendar.py"

if [[ ! -f "$ZK/_system/CALENDAR.md" || ! -f "$RECONCILE" ]]; then
    echo "info: CALENDAR.md or reconcile_calendar.py not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# Capture + parse defensively — a crash / empty output yields sentinel -1 so a
# failed run is never coerced into a false "all clear" (surface, don't decide).
raw="$(python3 "$RECONCILE" --base "$ZK" --report --json 2>/dev/null || true)"
count="$(printf '%s' "$raw" | python3 -c '
import sys, json
try:
    print(int(json.load(sys.stdin).get("orphan_note_count", -1)))
except Exception:
    print(-1)
' 2>/dev/null || echo -1)"
count="${count:--1}"

if [[ "$count" -lt 0 ]]; then
    echo "[migration 012] reconcile_calendar.py produced no valid output — NOT assuming all-clear." >&2
    echo "  Inspect manually: python3 $RECONCILE --base \"$ZK\" --report" >&2
    exit 0
fi

if [[ "$count" -eq 0 ]]; then
    echo "[migration 012] calendar aggregate is consistent — no dropped future events, no-op"
    exit 0
fi

cat >&2 <<EOF

[migration 012] Found $count note(s) with a future 📅 event whose link is absent
from every forward-facing CALENDAR.md section (the aggregation gap). Nothing is
lost — the events live in the notes. To re-aggregate them, run once:

    /ztn:process --reconcile-calendar

(Inspect them first with:
    python3 $RECONCILE --base "$ZK" --report )
EOF
exit 0
