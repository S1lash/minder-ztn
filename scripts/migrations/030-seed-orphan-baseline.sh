#!/usr/bin/env bash
# migration-kind: heal
# 030-seed-orphan-baseline — the orphan check starts from your base as it is.
#
# From this version a tag naming an identity no registry declares is residue,
# and residue is what the `/ztn:process` completion gate refuses to pass. On a
# clone that predates the check that is a new verdict about old data: tags that
# have sat in notes for a year suddenly fail tonight's run, for drift the tick
# did not create and cannot resolve — which of register, retag or drop applies
# is a judgement about what the note meant.
#
# So the check starts where the base already is. This runs the scan once and
# writes what it finds into `_system/state/identity-orphan-baseline.txt`, the
# closed list the audit excludes from residue. Nothing is repaired and no note
# is touched. From that moment a NEW orphan fails, which is the whole point of
# the check, while the existing ones are surfaced through the ordinary
# interactive path and leave the list one at a time as they are resolved.
#
# Writes only when the file is absent. A base that already carries one has
# either been seeded or curated, and re-deriving it would silently re-admit
# every orphan the owner has since resolved — the one thing a list that «only
# shrinks» must never do.
#
# Zero orphans writes nothing at all: an empty baseline and no baseline mean the
# same thing to the audit, and the file exists to record exceptions, not to
# announce their absence.
#
# `heal`, because an un-run seeding means a gate that complains about old data,
# not an engine in the wrong shape. A repair of historical data must never be
# able to block a future update, so a failure here is recorded and retried.
#
# With no engine library on disk yet it writes nothing, says why, and exits
# non-zero — recorded `partial`, so the next update runs it for real. Exiting
# zero would be recorded `applied` and the base would meet the gate unseeded.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 "$SCRIPT_DIR/_030_seed_orphan_baseline.py" --repo-root "$REPO_ROOT"
