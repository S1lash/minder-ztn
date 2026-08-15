#!/usr/bin/env bash
# migration-kind: heal
# 022-retire-old-roles-log — remove the tick log of a roles subsystem that no
# longer exists.
#
# The engine's roles subsystem was replaced wholesale. Its files are retired
# automatically from this version on (`retired:` in `.engine-manifest.yml`,
# applied by every sync), but one of them sits in owner space —
# `_system/state/log_roles.md` — and a sweep is not allowed to delete from
# there. That boundary is deliberate, so this is the migration that says out
# loud what it is doing.
#
# Why it must go rather than simply sit there: nothing writes it any more, and
# nothing marks it dead either, so it reads exactly like a live log that
# stopped updating. That is not a harmless leftover — a review of the nightly
# runs reported it as an outage («log_roles.md has not been appended since
# 06-08»), which is a false alarm costing real attention. The live record of
# every role run is `_system/roles/{id}/log.jsonl`, one line per executed run,
# and it is unaffected.
#
# The file is in git. If it is wanted back:
#   git log --diff-filter=D -- '*/log_roles.md'   → find the commit
#   git checkout <sha>^ -- <path>                 → restore it
#
# Idempotent: absent file → nothing to do.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# The base directory name is the owner's choice — resolve it rather than
# assuming `zettelkasten`, the same way roles_config and the scheduler
# helpers do.
# Two candidates is not a case to guess through: the dead log would be looked
# for in the wrong base and reported absent, and exiting 0 would record this
# heal as applied — so the real log survives forever. Exit 2 leaves it
# `partial` for the next update.
BASE_NAME=""
for d in "$REPO_ROOT"/*/; do
    [ -f "$d/_system/scripts/roles_run.py" ] || continue
    if [ -n "$BASE_NAME" ]; then
        echo "[migration 022] More than one ZTN base here — resolve by hand." >&2
        exit 2
    fi
    BASE_NAME="$(basename "${d%/}")"
done
[ -z "$BASE_NAME" ] && [ -d "$REPO_ROOT/zettelkasten" ] && BASE_NAME="zettelkasten"

if [ -z "$BASE_NAME" ]; then
    echo "022: no ZTN base found — nothing to retire (fresh install)."
    exit 0
fi

DEAD_LOG="$REPO_ROOT/$BASE_NAME/_system/state/log_roles.md"

if [ ! -f "$DEAD_LOG" ]; then
    echo "022: no old roles log on this clone — nothing to do"
    exit 0
fi

rm -f "$DEAD_LOG"

cat <<MSG

────────────────────────────────────────────────────────────────────────
Removed a log belonging to a roles subsystem that no longer exists
────────────────────────────────────────────────────────────────────────

  $BASE_NAME/_system/state/log_roles.md

Nothing had written it for a long time, and nothing marked it dead either,
so it read like a live log that had stopped — the kind of thing that gets
reported as an outage when it is only a leftover.

What your roles actually record is untouched: one line per run in
$BASE_NAME/_system/roles/<role>/log.jsonl.

The file is still in your git history if you want it back.

────────────────────────────────────────────────────────────────────────

MSG

exit 0
