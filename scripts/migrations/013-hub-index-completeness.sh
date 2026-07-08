#!/usr/bin/env bash
# 013-hub-index-completeness — Detect hub files missing from HUB_INDEX.md (the
# LLM-maintained index silently lagging the hub files at scale) and nudge the
# owner to regenerate it.
#
# HUB_INDEX.md is maintain-owned; `/ztn:lint` A.6.2 also surfaces this drift on
# its next run. This migration surfaces a friend's PRE-EXISTING drift right after
# update. Deterministic (no LLM): it compares `5_meta/mocs/hub-*.md` files on
# disk against the `[[hub-*]]` ids listed in HUB_INDEX.md. It does not rewrite
# HUB_INDEX (regen is maintain's job — needs member counts + key people). Soft
# nag: exits 0 in every case (drift is not a sync failure — a non-zero exit would
# abort sync_engine.sh under `set -e`; see 007 / 011 / 012 / 014). Idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
HUB_INDEX="$ZK/_system/views/HUB_INDEX.md"
MOCS="$ZK/5_meta/mocs"

if [[ ! -f "$HUB_INDEX" || ! -d "$MOCS" ]]; then
    echo "info: HUB_INDEX.md or 5_meta/mocs not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# The python is internally crash-safe (any read/parse error → 0 missing), and
# the `|| echo 0` is a backstop so a python-level failure can never make the
# command substitution non-zero and abort sync_engine.sh under `set -e`.
missing="$(
    python3 - "$MOCS" "$HUB_INDEX" <<'PY' || echo 0
import re
import sys
from pathlib import Path

try:
    mocs, hub_index = Path(sys.argv[1]), Path(sys.argv[2])
    on_disk = {p.stem for p in mocs.glob("hub-*.md") if not p.name.endswith(".template.md")}
    listed = set(re.findall(r"\[\[(hub-[^\]]+?)\]\]", hub_index.read_text(encoding="utf-8")))
    missing = sorted(on_disk - listed)
    for mid in missing:
        print(mid, file=sys.stderr)
    print(len(missing))
except Exception:
    print(0)
PY
)"
missing="${missing:-0}"

if [[ "$missing" -eq 0 ]]; then
    echo "[migration 013] HUB_INDEX.md lists every hub file — no-op"
    exit 0
fi

cat >&2 <<EOF

[migration 013] HUB_INDEX.md is missing $missing hub file(s) that exist on disk
(ids listed above). To rebuild the index, run once:

    /ztn:maintain
EOF
exit 0
