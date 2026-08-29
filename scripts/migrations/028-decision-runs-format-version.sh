#!/usr/bin/env bash
# migration-kind: heal
# 028-decision-runs-format-version — state the format version on decision-run
# lines written before the recorder emitted one.
#
# Both audit substrates this engine writes are read by consumers — the
# `decision-review` lens today, anything else later — and a consumer that
# cannot tell which format it is reading has to guess from the field set. The
# tick odometer carries `format_version` from its first line. The decision
# recorder now does too, which leaves the lines already on disk as the only
# ones a reader cannot place.
#
# The edit is additive and value-preserving: one field inserted after `kind`,
# nothing else touched, no line reordered, no number changed. That is why it
# is safe to run over an append-only substrate the owner never edits by hand.
#
# `heal`: an un-run migration leaves older lines unversioned, which a consumer
# reads as pre-versioning and handles. Nothing reads a wrong place, so this
# must never be able to block an update.
#
# Idempotent: a line that already carries `format_version` is left exactly as
# it is, so re-running is a no-op rather than a rewrite.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "warning: python3 not found — skipping decision-run backfill" >&2
    exit 0
fi

if ! python3 "$SCRIPT_DIR/_028_decision_runs_backfill.py"; then
    echo "warning: 028 decision-run backfill did not complete" >&2
    echo "  Lines without a format_version in" >&2
    echo "  _system/state/check-decision-runs.jsonl are read as pre-versioning;" >&2
    echo "  nothing breaks, and the next update retries this." >&2
    exit 1
fi
