#!/usr/bin/env bash
# migration-kind: heal
# 020-roles-previous-shape-memory — Reach the clones that already ran 018.
#
# WHY A SECOND MIGRATION AND NOT A FIX TO THE FIRST
#
# 018 parked previous-shape roles and wrote the owner a hand-off plus one
# conversion plan per role. Both described the role's ASSIGNMENT and nothing
# else. What the role had LEARNT — its board, its readings, its verdicts, its
# decision log, sitting in `state.md`, `parts/*.json` and `decisions.jsonl` —
# was named only as proof that it had run once. Every byte survived the move and
# nothing pointed at it, so the owner re-created the role from its assignment
# alone and it woke up remembering nothing. Data that is present but
# unreferenced is lost in every way that matters to the person who needs it.
#
# 018 now carries it. That repair reaches a clone which has not run 018 yet.
# It reaches NO clone that already has, and the reason is the ledger: a
# migration recorded `applied` never runs again. `heal` retries only while a
# migration keeps FAILING — 018 succeeded, so its improvement cannot arrive by
# itself. The ledger is the only mechanism that reaches an already-migrated
# clone, and using it means a new entry.
#
# WHAT IT DOES
#
# Nothing of its own. It re-runs 018's two producers, which are idempotent and
# rebuild from the parked directory:
#
#   - `_018_handoff.py` — sees the roles are already parked and refreshes the
#     hand-off when what it would write differs from what is on disk.
#   - `_018_plan.py`    — rebuilds every conversion plan, memory included.
#
# So there is no second copy of the logic here, and a clone that never had a
# previous-shape role does nothing and says so.
#
# WHAT IT COSTS, SAID PLAINLY
#
# A refreshed hand-off overwrites the file. It is engine-generated, in an
# engine-created directory the owner is told to delete once they are done with
# it — but an owner who annotated it loses that annotation. The alternative is
# leaving a generated file on disk asserting that the role's own memory is
# «твоё, смотри при желании», which is what this whole line of work exists to
# stop saying. The role's own files are not touched at all.
#
# DELETES NOTHING. Idempotent: once both artifacts are current, a further run
# rewrites neither.
#
# Cross-platform: bash 3.2 / Git Bash safe — no arrays, no `mapfile`, no
# `${x,,}`; all non-trivial logic is python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# The base name is the owner's choice, not a constant.
BASE=""
for d in */; do
    [ -f "$d/_system/scripts/roles_run.py" ] || continue
    if [ -n "$BASE" ]; then
        echo "[migration 020] More than one ZTN base here — resolve by hand." >&2
        exit 2
    fi
    BASE="${d%/}"
done
[ -z "$BASE" ] && [ -d "zettelkasten" ] && BASE="zettelkasten"

PARKED=""
[ -n "$BASE" ] && PARKED="$BASE/_system/roles/_previous"

if [ -z "$PARKED" ] || [ ! -d "$PARKED" ]; then
    echo "[migration 020] No previously-parked roles — nothing to refresh."
    exit 0
fi

python3 "$SCRIPT_DIR/_018_handoff.py" "$BASE"
python3 "$SCRIPT_DIR/_018_plan.py" "$PARKED"

# Same posture as 018: verify the work rather than report the intent, and stay
# advisory. A non-zero self-check must not fail the update — the parked data is
# intact either way, and stranding an owner mid-update over a reportable
# condition is worse than telling them plainly and moving on.
python3 "$SCRIPT_DIR/_018_selfcheck.py" "$BASE" || {
    echo "[migration 020] The self-check above did not pass." >&2
    echo "  Nothing was deleted. Read what failed; re-running this migration" >&2
    echo "  would report the same, because it is idempotent." >&2
}
