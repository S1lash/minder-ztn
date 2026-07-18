#!/usr/bin/env bash
# 016 — Roles moved from a single scalar `archetype` to a composite `parts[]`.
#
# A role created under the old model has `config.yml` with `archetype: <kind>`
# (no `parts:`), a single top-level `ledger.json`, and a single-zone `state.md`.
# The current engine composes a role from `parts: [{id, kind}]` and rejects the
# scalar form fail-closed (with a rebuild pointer) at load.
#
# SOFT-NAG, detection-only. Role instances (`_system/roles/{id}/`) are OWNER DATA
# — a migration MUST NOT rewrite them (README rule). So this script only DETECTS a
# pre-composite role config and tells the owner to re-create it with the concierge
# (`/ztn:role:add`), which builds the richer composite role. It writes nothing and
# exits 0 so the sync completes. If there are no roles (the common case), it is a
# silent no-op.
#
# Cross-platform: pure python3 logic, no bash-4 constructs, repo-relative paths.
set -euo pipefail

python3 - <<'PY'
import sys
from pathlib import Path

roles_dir = Path("zettelkasten/_system/roles")
if not roles_dir.is_dir():
    sys.exit(0)  # engine-only clone / no owner data here — nothing to check

legacy = []
for child in sorted(roles_dir.iterdir()):
    if child.name.startswith("_") or not child.is_dir():
        continue
    cfg = child / "config.yml"
    if not cfg.is_file():
        continue
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        continue
    # A pre-composite role: declares a scalar `archetype:` and no `parts:` key.
    has_parts = any(ln.strip().startswith("parts:") for ln in text.splitlines())
    has_scalar_archetype = any(
        ln.strip().startswith("archetype:") for ln in text.splitlines()
    )
    if has_scalar_archetype and not has_parts:
        legacy.append(child.name)

if legacy:
    ids = ", ".join(legacy)
    sys.stderr.write(
        "\n[016] Roles now use a composite parts[] model. These role(s) still use "
        f"the old single-archetype format and will not tick until re-created: {ids}.\n"
        "      Re-create each with the concierge — `/ztn:role:add` — which builds "
        "the richer composite role (workstreams + meaning). Your notes are untouched; "
        "only the role definition needs rebuilding.\n\n"
    )
# Detection-only: exit 0 so the sync completes and this migration is recorded.
sys.exit(0)
PY
