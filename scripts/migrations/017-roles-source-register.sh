#!/usr/bin/env bash
# 017-roles-source-register — register the `roles` inbox source for existing clones.
#
# The roles engine adds an inbox DOOR (CONTRACT §4.2): a role with `emit_inbox: true`
# drops one human-phrased note per emission under `_sources/inbox/roles/`, folded in by
# /ztn:process like any source. A FRESH clone is born with the `roles` row because
# SOURCES.template.md ships it (strip-seed). But an EXISTING clone's live SOURCES.md is
# owner-data — templates never sync into it, and no prior migration adds the row — so an
# existing friend's `emit_inbox` role would write emissions that /ztn:process (a
# whitelist over SOURCES.md rows) silently never scans. This migration closes that gap.
#
# This script:
#   1. creates `_sources/{inbox,processed}/roles/` (+ .gitkeep) if absent
#   2. appends the canonical `roles` row to the live SOURCES.md Active Sources table
#      if no `roles` row exists
#
# Idempotent: re-running on an already-registered clone is a no-op. A fresh clone that
# already has the row (from the template) is likewise a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZTN="$REPO_ROOT/zettelkasten"
SOURCES_LIVE="$ZTN/_system/registries/SOURCES.md"

mkdir -p "$ZTN/_sources/inbox/roles" "$ZTN/_sources/processed/roles"
touch "$ZTN/_sources/inbox/roles/.gitkeep" "$ZTN/_sources/processed/roles/.gitkeep"

if [[ ! -f "$SOURCES_LIVE" ]]; then
    echo "info: $SOURCES_LIVE not found — skipping registry rewrite (fresh clone or pre-bootstrap)"
    exit 0
fi

python3 - "$SOURCES_LIVE" <<'PY'
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")

# Already registered? (a `roles` row anywhere) -> no-op.
if re.search(r"^\|\s*roles\s*\|", text, re.MULTILINE):
    print("info: SOURCES.md already has the roles row — no-op")
    sys.exit(0)

row = (
    "| roles | `_sources/inbox/roles/` | transcript | flat-md | auto | — | "
    "The inbox door for the owner's ZTN roles (CONTRACT §4.2) — an engine-level source "
    "registered ONCE for all roles. A role with `emit_inbox: true` drops one "
    "human-phrased note per emission (`{role-id}--{date}-{hash}.md`, carrying "
    "`source: role:{id}`); `/ztn:process` folds it in like any source. Dormant until a "
    "role enables emission. | active |"
)

# Append to the end of the Active Sources table (last table row before a blank line / ---).
m = re.search(r"(## Active Sources\n.*?)(\n\n|\n---|\Z)", text, re.DOTALL)
if m:
    text = text[: m.end(1)] + "\n" + row + text[m.end(1):]
else:
    # Non-canonical registry (no `## Active Sources` header) — never silently drop the
    # row (that would leave emit_inbox emissions orphaned). Append a fresh section so the
    # row always lands and /ztn:process whitelists the folder.
    sep = "" if text.endswith("\n") else "\n"
    text = text + sep + "\n## Active Sources\n\n" + row + "\n"
p.write_text(text, encoding="utf-8")
print(f"migrated: {p} — roles inbox-source row ensured")
PY

echo "017-roles-source-register: done"
