#!/usr/bin/env bash
# 018-roles-previous-shape-handoff — Carry a role built on the previous shape
# across to the current one, without pretending it can be converted.
#
# WHAT THE OWNER HITS WITHOUT THIS
#
# A role built on the previous shape is a directory holding `config.yml`,
# `hooks/tick.md`, `hooks/ask.md` and sometimes `brief.md`. The current engine
# discovers a role by the presence of `role.md` and skips every directory
# without one — so those roles are not broken, not reported, not listed. They
# are INVISIBLE. `/ztn:role:list` shows nothing, no tick mentions them, and the
# only trace is a migration notice that scrolled past during an update.
#
# The owner's reasonable conclusion is that the update deleted their roles. It
# did not: every byte is still there. Silence is the entire defect, and it is
# the one this migration exists to break.
#
# WHY IT DOES NOT AUTO-CONVERT
#
# Converting looks tempting — copy `hooks/tick.md` into a `role.md` body and
# map the header. It is refused for two reasons, and the second is the serious
# one:
#
#   1. The prose was written against a vocabulary that no longer exists —
#      parts, ledger ops, staged acts, slots. Carried across verbatim it would
#      instruct a role to do things nothing implements. The role would not
#      fail; it would improvise, which is worse, because it looks like it
#      worked.
#   2. `writes:` is the security boundary of the current shape, and the
#      previous shape had no equivalent to derive it from. Guessing where a
#      role may write is precisely the guess that must not be made
#      automatically. It is a decision, and it belongs to the owner in a
#      conversation with `/ztn:role:add`.
#
# So: preserve everything, make it visible, and hand the owner what they wrote
# in their own words so re-creating the role takes one conversation and loses
# nothing.
#
# WHAT IT DOES
#
#   - moves each previous-shape role directory to `_system/roles/_previous/{id}/`.
#     The `_` prefix is what the engine already uses to mean "not a role", so
#     the move also removes a real hazard: without it, an owner re-creating a
#     role under the same id would get a fresh `role.md` written INTO the old
#     directory, next to `config.yml` and `hooks/`, where `state/` is expected.
#   - writes `_system/roles/_previous/HANDOFF.md` — one section per role, in
#     the owner's own words, quoting what they actually wrote.
#   - names `_system/registries/TOOLS.md` if it exists. It is owner data, it
#     survives every sync, and after this update nothing reads it.
#
# DELETES NOTHING. Moves are `git mv` when the path is tracked, so history
# follows. Idempotent: a second run finds the work done and re-prints where.
#
# Cross-platform: bash 3.2 / Git Bash safe — no arrays, no `mapfile`, no
# `${x,,}`; all non-trivial logic is python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# The base name is the owner's choice, not a constant.
BASE=""
for d in */; do
    [ -f "$d/_system/scripts/roles_run.py" ] || continue
    if [ -n "$BASE" ]; then
        echo "[migration 018] More than one ZTN base here — resolve by hand." >&2
        exit 2
    fi
    BASE="${d%/}"
done
[ -z "$BASE" ] && [ -d "zettelkasten" ] && BASE="zettelkasten"

if [ -z "$BASE" ] || [ ! -d "$BASE/_system/roles" ]; then
    echo "[migration 018] No roles directory — nothing to carry across."
    exit 0
fi

python3 "$SCRIPT_DIR/_018_handoff.py" "$BASE"

# The credential store is the SAME file, shape and primitive in both shapes —
# only the environment variable holding the key was renamed. So the names are
# readable here without any key at all, and they go into each conversion plan.
STORE="$BASE/_system/state/secrets.enc.json"
NAMES="$(python3 -c 'import sys,json,pathlib; p=pathlib.Path(sys.argv[1]); print(json.dumps(sorted(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else []))' "$STORE" 2>/dev/null || echo "[]")"
python3 "$SCRIPT_DIR/_018_plan.py" "$BASE/_system/roles/_previous" "$NAMES"

# The migration verifies its OWN work rather than reporting intent. A run that
# half-succeeded and said nothing is the failure mode this whole migration
# exists to prevent — repeating it here would be its own joke.
#
# Advisory by design: a non-zero self-check must NOT fail the update. The
# parked data is intact either way, and stranding an owner mid-update over a
# reportable condition is worse than telling them plainly and moving on.
python3 "$SCRIPT_DIR/_018_selfcheck.py" "$BASE" || {
    echo "[migration 018] The self-check above did not pass." >&2
    echo "  Nothing was deleted. Read what failed, and do NOT re-run this" >&2
    echo "  migration to «fix» it — it is idempotent and would report the same." >&2
}
