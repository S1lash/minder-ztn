#!/usr/bin/env bash
# migration-kind: heal
# 021-maintain-step-and-prompt-loader — the after-batch integrator gets a
# real trigger, and the scheduler stops holding a second copy of the tick
# contract.
#
# Two things reach a friend's clone with engine 0.59.0, and both need one
# action from the owner that no script can perform for them.
#
# 1. `/ztn:maintain` had no trigger at all. The process tick's prompt said
#    the integrator ran "inline" inside `/ztn:process`, and it never did —
#    the two skills hold mutually exclusive cross-skill locks, so an inline
#    tail was never possible. It had been running only when the agent
#    executing the tick chose to invoke it unprompted. When that stopped,
#    batches accumulated un-integrated while every tick reported success.
#    The prompt now carries an explicit Step 4.5.
#
# 2. A scheduler holds its prompt text verbatim, so pasting the tick body
#    into a routine put one contract in two places — and the scheduler's
#    copy silently became the older one. The documented setup is now a
#    loader: the routine holds a pointer, the repository holds the body.
#
# Required action (once, and it is the last re-paste this design needs):
#
#     Replace each routine's prompt with its loader from
#     docs/scheduling.md → «Plug-in — Claude Code /schedule».
#     At minimum replace `ztn-process`, which is the one carrying the
#     integrator fix.
#
# Until that is done, the fix is on disk but not in the loop: the scheduler
# is still running the body it was given months ago.
#
# This script does not integrate anything. Integration is `/ztn:maintain`'s
# job and it drains the whole unprocessed set on its next run, so the
# backlog this reports needs no repair — only the re-paste above. What the
# script does do is READ the clone and say how big that backlog actually
# is, because "you may have missed some" is not something an owner can act
# on and "14 batches, oldest 2026-07-30" is.
#
# The standing safety net is `/ztn:lint` Scan A.12: from this version on, a
# batch older than 26 h with no integration record surfaces as a
# `batch-not-integrated` CLARIFICATION. So a routine left un-re-pasted
# announces itself within a day rather than going quiet for weeks.
#
# Idempotent: reads two files, writes none.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# The base directory name is the owner's choice — resolve it rather than
# assuming `zettelkasten`, the same way roles_config and the scheduler
# helpers do.
# Two candidates is not a case to guess through: the notice below would be
# computed against the wrong base, and exiting 0 would record this heal as
# applied and never retry it. Exit 2 leaves it `partial` for the next update.
BASE_NAME=""
for d in "$REPO_ROOT"/*/; do
    [ -f "$d/_system/scripts/roles_run.py" ] || continue
    if [ -n "$BASE_NAME" ]; then
        echo "[migration 021] More than one ZTN base here — resolve by hand." >&2
        exit 2
    fi
    BASE_NAME="$(basename "${d%/}")"
done
[ -z "$BASE_NAME" ] && [ -d "$REPO_ROOT/zettelkasten" ] && BASE_NAME="zettelkasten"

if [ -z "$BASE_NAME" ]; then
    echo "021: no ZTN base found — nothing to announce (fresh install)."
    exit 0
fi

STATE="$REPO_ROOT/$BASE_NAME/_system/state"

BACKLOG="(could not be determined — state files not found)"
if [ -f "$STATE/BATCH_LOG.md" ] && [ -f "$STATE/log_maintenance.md" ]; then
    BACKLOG="$(python3 - "$STATE" <<'PY' 2>/dev/null || echo "(could not be determined)"
import pathlib
import re
import sys

state = pathlib.Path(sys.argv[1])
# A BATCH_LOG row opens with `| {batch_id} |`; the id is YYYYMMDD-HHMMSS,
# optionally with a trailing sequence number.
row = re.compile(r"^\|\s*(\d{8}-\d{6}(?:-\d+)?)\s*\|")
produced = []
for line in state.joinpath("BATCH_LOG.md").read_text(encoding="utf-8").splitlines():
    m = row.match(line)
    if m:
        produced.append(m.group(1))

log = state.joinpath("log_maintenance.md").read_text(encoding="utf-8")
integrated = set(re.findall(r"batch:\s*([0-9A-Za-z\-]+)", log))

pending = sorted(b for b in dict.fromkeys(produced) if b not in integrated)
if not pending:
    print("none — every batch on record has been integrated")
else:
    print(f"{len(pending)} batch(es) not yet integrated, oldest {pending[0]}")
PY
)"
fi

cat <<MSG

────────────────────────────────────────────────────────────────────────
Engine 0.59.0 — the integrator gets a trigger; routines get a loader
────────────────────────────────────────────────────────────────────────

Your notes are processed by one tick and CONNECTED by a second pass —
threads, hub links, back-references, the weekly health and activity
rollups. That second pass had no trigger. The scheduler prompt claimed it
ran inside the processing skill, and it could never have: the two refuse
to run at the same time by design.

It is now an explicit step of the process tick.

Your base right now: $BACKLOG

Nothing needs repairing — the integrator drains every pending batch on its
next run. But it only gets a next run once your scheduler is reading the
new prompt, which is the one thing this script cannot do for you:

  ACTION — your scheduled routines need updating. Ask your assistant
           "update my ZTN routines" and it will do it for you.

This is the last time an update will ask you to touch a routine: after
this change they read their instructions from this repository, so future
engine updates reach them on their own.

And if it gets missed, you will not find out in a month — from this
version the nightly check raises un-integrated work for you the next
morning.

────────────────────────────────────────────────────────────────────────

MSG

exit 0
