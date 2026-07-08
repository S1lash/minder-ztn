#!/usr/bin/env bash
# 014-repair-evidence-trail-fence — Detect notes whose YAML fence closes AFTER a
# body heading (the `## Evidence Trail`-inside-frontmatter corruption) and nudge
# the owner to repair them through the pipeline.
#
# The producer now guards against this structurally (process Step 3.6/4.5 call
# `_common.frontmatter_closed_before_body`), and `/ztn:lint` Scan A.2 repairs
# existing broken notes deterministically via `_common.repair_misplaced_fence`.
# This migration cannot repair them itself — knowledge notes are owner-data,
# off-limits to migrations (see scripts/migrations/README.md). So it only
# DETECTS + reports the manual one-liner to stderr. It is a SOFT nag: it exits 0
# in every case (a broken note is not a sync failure — the engine pull must land
# so /ztn:lint can then repair). Exiting non-zero here would abort sync_engine.sh
# under `set -e`, leave 014 unrecorded, and re-abort every future update — the
# soft-nag/hard-fail split follows 007-backfill-manifest-conformance.sh.
# Idempotent: zero broken notes → clean no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
SCRIPTS="$ZK/_system/scripts"

if [[ ! -d "$ZK/_records" ]]; then
    echo "info: $ZK/_records not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

count="$(
    cd "$SCRIPTS" && python3 - "$ZK" <<'PY'
import sys
from pathlib import Path

import _common as c  # type: ignore

base = Path(sys.argv[1])
roots = ["_records", "1_projects", "2_areas", "3_resources", "4_archive"]
broken = []
for root in roots:
    for path in (base / root).rglob("*.md"):
        if path.name in {"README.md"}:
            continue
        # Genuine corruption fails BOTH: the structural fence invariant AND the
        # parser. ANDing suppresses false positives (valid multiline YAML that
        # happens to fold a '## ' into a value) — same detection lint A.2 uses.
        if not c.frontmatter_closed_before_body(path) and c.read_frontmatter(path) is None:
            broken.append(path.relative_to(base))

for rel in sorted(broken):
    print(f"  - {rel}", file=sys.stderr)
print(len(broken))
PY
)"

if [[ "$count" -eq 0 ]]; then
    echo "[migration 014] no notes with a misplaced frontmatter fence — no-op"
    exit 0
fi

cat >&2 <<EOF

[migration 014] Found $count note(s) whose YAML frontmatter fence closes AFTER a
body heading (the '## Evidence Trail'-inside-frontmatter corruption). These notes
are currently unparseable to every frontmatter consumer. The paths are listed
above.

They are owner-data, so this migration does not touch them. To repair them
deterministically, run once:

    /ztn:lint

Scan A.2 will move each misplaced fence back into place (fix-id
frontmatter-fence-repair-autofix); any ambiguous case is surfaced as a
'frontmatter-fence-misplaced' CLARIFICATION for you to resolve.
EOF
exit 0
