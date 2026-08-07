#!/usr/bin/env bash
# migration-kind: heal
# 016-roles-subsystem-removed — Tell the owner that the roles subsystem was
# removed from the engine, and that any role they created is now inert.
#
# The removal itself is delivered by the engine sync: the runner scripts, the
# five role skills, the tools registry template and the shared frame are engine
# paths, so by the time this migration runs they are already gone from the
# clone. What survives is the owner's own data — their `_system/roles/{id}/`
# directories, which sync never touches. Those directories are now orphaned:
# nothing can read them and no tick can run.
#
# This migration therefore DELETES NOTHING. It detects orphaned role dirs and
# says plainly what happened and what the owner's options are. Deleting a
# person's own data on their behalf is not a migration's job.
#
# Idempotent: re-running just re-prints the notice.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"
ROLES_DIR="$ZK/_system/roles"

if [ ! -d "$ROLES_DIR" ]; then
    echo "[migration 016] No roles directory — nothing to report."
    exit 0
fi

# Count instance dirs (any subdirectory of _system/roles/).
COUNT=0
for d in "$ROLES_DIR"/*/; do
    [ -d "$d" ] || continue
    COUNT=$((COUNT + 1))
done

if [ "$COUNT" -eq 0 ]; then
    echo "[migration 016] No roles were set up on this clone — nothing to report."
    exit 0
fi

cat >&2 <<EOF

[migration 016] The roles subsystem has been REMOVED from the engine.

  You have $COUNT role directory(ies) under zettelkasten/_system/roles/.
  They are now inert: the tick runner, the /ztn:role:* skills and the tools
  registry are gone, so nothing reads them and no role will run again.

  Nothing of yours was deleted. Your role directories, their tracked state and
  their decision logs are exactly as you left them.

  Roles are being rebuilt on a much simpler shape. When that lands, migration
  018 turns each of these directories into a readable record of what you asked
  for — quoted in your own words — so you can re-create the role in one
  conversation. If you are updating past both in one go, you will see 018's
  notice below this one; that is the one with the file to read.

  If you want them gone now, delete zettelkasten/_system/roles/ yourself and
  commit. Your data, your call.

EOF

exit 0
