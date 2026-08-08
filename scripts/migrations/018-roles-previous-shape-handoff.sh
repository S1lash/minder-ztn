#!/usr/bin/env bash
# migration-kind: heal
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
#   - writes `_system/roles/_previous/{id}.plan.json` — what `/ztn:role:add
#     --from-previous` carries across without asking, what it must not decide
#     alone, and an inventory of the memory the role built up between runs with
#     the path to every file of it. A long-running role is half assignment and
#     half accumulated state; naming only the assignment re-creates a role that
#     has forgotten everything, while every byte of it sits intact one
#     directory away.
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

# The plans are rebuilt on every run, from the parked directory — which is the
# source of what a role holds; the plan file is only a view of it. Credential
# names are read by the plan builder itself, from the store's position relative
# to the parked directory, so this call needs one argument and «what is in the
# store» has one owner.
python3 "$SCRIPT_DIR/_018_plan.py" "$BASE/_system/roles/_previous"

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
