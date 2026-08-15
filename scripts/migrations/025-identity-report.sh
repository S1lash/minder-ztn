#!/usr/bin/env bash
# migration-kind: heal
# 025-identity-report — the identity report reaches the owner's queue.
#
# From this version the engine resolves every identifier against its registry
# across six surfaces. On a clone that predates the contract that scan has
# things to say, and nobody has ever seen them. This migration runs it once and
# writes what it finds into `_system/state/CLARIFICATIONS.md`, one item per
# identity with live residue.
#
# It changes no content, ever. A friend's renames are their own history, and
# which identifier survived a merge is a decision rather than a lookup — the
# engine has no standing to guess it. So this surfaces and stops. Each item is
# resolved through the ordinary interactive path, `/ztn:resolve-clarifications`,
# which owns `entity-retire` / `entity-reclassify` and refuses to finalise
# either unless the same scan afterwards returns zero.
#
# Zero residue writes nothing at all, silently. An empty finding is not news,
# and a queue that fills with «nothing to report» stops being read.
#
# `heal`, because it neither moves data nor changes what the engine reads: an
# un-run report means a question unasked, not a wrong engine. A repair of
# historical data must never be able to block a future update, and a notice
# even less so — so a failure here is recorded and retried, never fatal.
#
# With no engine library on disk yet it writes nothing, says why, and exits
# non-zero — recorded `partial`, so the update continues and the next one runs
# it for real. Exiting zero would be recorded `applied` and the report would
# never be produced.
#
# Idempotent: every item carries an anchor, and an anchor already present in
# the open queue or in the resolved archive is skipped. A second run adds
# nothing; an item the owner has already answered never comes back.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

python3 "$SCRIPT_DIR/_025_identity_report.py" --repo-root "$REPO_ROOT"
