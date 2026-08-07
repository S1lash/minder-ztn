#!/usr/bin/env bash
# migration-kind: heal
# 017-roles-subsystem-returns — Bring an existing clone in line with the roles
# subsystem being present again.
#
# Two things a plain file-pull cannot do for the owner:
#
#   1. The `roles` row in their LIVE SOURCES.md carries a description that is
#      now false ("No producer at present"). SOURCES.md is a template seed, so
#      engine sync never touches it and the stale sentence would sit there
#      forever, telling /ztn:process that nothing writes to that inbox. This
#      migration rewrites that ONE row's Description cell, and only when it
#      still matches the stale text — an owner who edited the row keeps theirs.
#
#   2. The scheduler routine. Migration 016 told the owner to remove their
#      `ztn-roles` job; a routine lives in their scheduler, not in the repo, so
#      nothing here can restore it. Soft-nag with the exact cron + prompt file.
#
# Deletes nothing, creates no role. Idempotent: re-running finds the row already
# current and just re-prints the scheduler notice.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCES_LIVE="$REPO_ROOT/zettelkasten/_system/registries/SOURCES.md"

if [ -f "$SOURCES_LIVE" ]; then
    python3 - "$SOURCES_LIVE" <<'PY'
import sys
sys.stdout.reconfigure(newline="\n", encoding="utf-8")  # LF on Git Bash
from pathlib import Path

STALE = (
    "The inbox door for the owner's ZTN roles — an engine-level source "
    "registered ONCE for all roles. A role that reflects a fact worth the "
    "base's attention drops one human-phrased note here; `/ztn:process` folds "
    "it in like any source. No producer at present: the roles subsystem is "
    "being rebuilt."
)
FRESH = (
    "The inbox door for the owner's ZTN roles — an engine-level source "
    "registered ONCE for all roles, never per role. A role that finds a fact "
    "worth the base's attention drops one human-phrased note here, flat, named "
    "`YYYY-MM-DD-{role-id}-{slug}.md` with `source: role:{role-id}` "
    "frontmatter; `/ztn:process` folds it in like any source. Producer: a role "
    "with `inbox` in its `writes:`, run by the `/ztn:roles` tick. Shape spec: "
    "`_system/roles/_minder.md`."
)

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

if STALE not in text:
    print("info: SOURCES.md `roles` row already current — no-op")
    sys.exit(0)

path.write_text(text.replace(STALE, FRESH), encoding="utf-8")
print("migrated: SOURCES.md — `roles` row now names its producer")
PY
else
    echo "info: $SOURCES_LIVE not found — skipping (fresh clone or non-ZTN base)"
fi

cat >&2 <<'EOF'

[migration 017] Roles are back in the engine.

  Create one by describing it:  /ztn:role:add
  See what you have:            /ztn:role:list

  They only run if you schedule the tick. Add one routine:

      name:   ztn-roles
      cron:   0 7 * * *
      prompt: <body of integrations/claude-code/scheduler-prompts/roles-nightly.md>

  A role directory left over from before does NOT carry over — its shape is
  gone. Nothing of yours was deleted; describe the role again and the concierge
  builds it in the current shape.

EOF

exit 0
