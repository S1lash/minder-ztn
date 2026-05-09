#!/usr/bin/env bash
# 003-lens-precedent-pre-biometric-mark — Tag pre-patch precedent rows.
#
# Engine 0.22.0 patched four lens prompts (stated-vs-lived,
# energy-pattern, weekly-insights, global-navigator) so they read
# biometric records / Tier II output / new biometric lens runs.
#
# Existing rows in `_system/state/lens-resolution-history.jsonl` were
# logged against the OLD prompt scope. Smart-resolve uses these as
# precedent for auto-apply decisions; mixing pre-patch and post-patch
# rows under the same lens-id could over-weight stale calibration.
#
# This migration appends `pre_patch_022: true` to every row whose
# `lens_id` is in the patched set. Owner's first interactive resolve
# session post-update naturally accretes new precedent. Smart-resolve's
# precedent walker can opt to discount or ignore pre_patch rows.
#
# Idempotent: rows already carrying `pre_patch_022: true` are not
# rewritten on re-run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HISTORY="$REPO_ROOT/zettelkasten/_system/state/lens-resolution-history.jsonl"

if [[ ! -f "$HISTORY" ]]; then
    echo "info: $HISTORY not found — fresh clone, no precedent to migrate (no-op)"
    exit 0
fi

python3 - "$HISTORY" <<'PY'
import json
import sys
from pathlib import Path

PATCHED = {"stated-vs-lived", "energy-pattern", "weekly-insights", "global-navigator"}

p = Path(sys.argv[1])
src = p.read_text(encoding="utf-8")
out_lines: list[str] = []
modified = 0
for raw in src.splitlines():
    raw = raw.strip()
    if not raw:
        continue
    try:
        row = json.loads(raw)
    except json.JSONDecodeError:
        out_lines.append(raw)
        continue
    if row.get("lens_id") in PATCHED and not row.get("pre_patch_022"):
        row["pre_patch_022"] = True
        modified += 1
    out_lines.append(json.dumps(row, ensure_ascii=False))

if modified == 0:
    print(f"info: no rows needed migration ({p})")
else:
    p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"migrated: tagged {modified} pre-patch rows in {p}")
PY

echo "003-lens-precedent-pre-biometric-mark: done"
