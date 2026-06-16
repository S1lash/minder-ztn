#!/usr/bin/env bash
# 007-backfill-manifest-conformance — bring existing batch manifests to the v2
# schema contract after the producer-conformance fix.
#
# Engine 0.34.0 makes emit_batch_manifest a "valid by construction" gate:
# unmapped concept types fail-safe to `other`, every legacy list/entry/array
# shape is coerced, and rewrite_manifest_violations gained identity/section
# synthesis to retrofit structurally-incomplete early-dialect manifests.
#
# Installs before this carry historical batches under
# `_system/state/batches/` that still fail the v2 schema. This migration
# re-runs them through the (now complete) normaliser so the whole corpus
# reaches 0 violations — the same backfill the maintainer ran upstream.
#
# Idempotent: the retrofit is a no-op on already-conformant batches; all
# original values are preserved under `section_extras.legacy_*`. Touches only
# engine-generated state (`_system/state/batches/`), never hand-authored owner
# content. Reversible via the friend's own git history.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZTN="$REPO_ROOT/zettelkasten"
SCRIPTS="$ZTN/_system/scripts"
BATCHES="$ZTN/_system/state/batches"
SCHEMAS="$ZTN/_system/docs/manifest-schema"

if [ ! -d "$BATCHES" ]; then
  echo "007-backfill-manifest-conformance: no batches dir ($BATCHES) — nothing to backfill (fresh install)."
  exit 0
fi

if [ ! -f "$SCRIPTS/rewrite_manifest_violations.py" ]; then
  echo "007-backfill-manifest-conformance: rewrite_manifest_violations.py missing — re-run install/update first." >&2
  exit 1
fi

echo "007-backfill-manifest-conformance: retrofitting historical batch manifests…"
python3 "$SCRIPTS/rewrite_manifest_violations.py" --batches-dir "$BATCHES" --apply || {
  echo "007-backfill-manifest-conformance: retrofit reported failures — inspect output above." >&2
  echo "  Your batches are unchanged on any file that failed; re-run manually:" >&2
  echo "    python3 $SCRIPTS/rewrite_manifest_violations.py --batches-dir $BATCHES --apply" >&2
  exit 1
}

# Verify — surface (do not fail) any residual violation so the friend can flag
# an unusual shape upstream rather than living with a broken manifest silently.
if [ -f "$SCRIPTS/lint_manifest_schema.py" ]; then
  remaining=$(python3 "$SCRIPTS/lint_manifest_schema.py" \
      --batches-dir "$BATCHES" --schemas-dir "$SCHEMAS" --all 2>/dev/null \
    | python3 -c 'import sys,json; print(sum(1 for l in sys.stdin if l.strip() and json.loads(l).get("kind")=="violation"))' \
      2>/dev/null || echo "?")
  if [ "$remaining" = "0" ]; then
    echo "007-backfill-manifest-conformance: done — 0 schema violations across all batches."
  else
    echo "007-backfill-manifest-conformance: done — $remaining batch(es) still violate the schema." >&2
    echo "  Likely a manifest shape not yet covered by the normaliser; please report it upstream." >&2
  fi
fi

exit 0
