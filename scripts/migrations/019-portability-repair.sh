#!/usr/bin/env bash
# migration-kind: heal
# 019-portability-repair — unstick a clone the old update machinery could jam,
# and re-run the repairs that machinery could not finish.
#
# Two things, both idempotent, both no-ops on a clone that was never stuck:
#
#   1. Re-run the manifest retrofit with the on-disk repairs and quarantine.
#      Migration 007 predates them: it could reach the schema for most batches
#      but not for manifests missing a `path`, carrying a null `id`/`title`, a
#      truncated `timestamp` or `checksum`, or a `batch_id` with the skill
#      suffix. Those are now derivable; anything still unreachable is marked in
#      `section_extras.quarantine` so lint records it once instead of raising it
#      nightly forever.
#
#   2. On Git Bash, re-run the installer with real symlinks enabled. A clone
#      that installed before install.sh grew its platform guard has stub files
#      or a partial `~/.claude/skills/` tree; the installer is idempotent and
#      now clears residue itself.
#
# Declared `heal`: every step repairs existing state rather than changing the
# engine's shape, so a failure here records an outcome and lets the update
# finish. That is the whole point — the failure mode this migration exists to
# clear was a repair migration blocking every future update.
#
# Cross-platform: bash 3.2 / Git Bash safe — no arrays, no `mapfile`, no
# `${x,,}`; all non-trivial logic is python3.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# The base folder name is the owner's choice, not a constant. Two candidates is
# not a case to guess through: repairing the wrong base does nothing to the
# right one, and exiting 0 would record this heal as applied and never retry it.
# Exit 2 leaves it `partial`, so the next update tries again.
BASE=""
for d in */; do
    [ -f "$d/_system/scripts/roles_run.py" ] || continue
    if [ -n "$BASE" ]; then
        echo "[migration 019] More than one ZTN base here — resolve by hand." >&2
        exit 2
    fi
    BASE="${d%/}"
done
[ -z "$BASE" ] && [ -d "zettelkasten" ] && BASE="zettelkasten"

if [ -z "$BASE" ] || [ ! -d "$BASE/_system" ]; then
    echo "019-portability-repair: no ZTN base found — nothing to repair (fresh install)."
    exit 0
fi

SCRIPTS="$BASE/_system/scripts"
BATCHES="$BASE/_system/state/batches"

# Set when a step fails. The ledger records a non-zero `heal` as `partial` and
# retries it next update; exit 0 records `applied` and it never runs again. So
# a step that failed must not be reported through a zero exit — that is the
# script telling the ledger a story about itself.
FAILED=0

# --- 1. Finish the manifest retrofit ----------------------------------------
if [ -d "$BATCHES" ] && [ -f "$SCRIPTS/rewrite_manifest_violations.py" ]; then
    echo "019-portability-repair: re-running the manifest retrofit with on-disk repairs…"
    if python3 "$SCRIPTS/rewrite_manifest_violations.py" \
            --batches-dir "$BATCHES" --base "$BASE" --apply --quarantine; then
        echo "019-portability-repair: manifest retrofit complete."
    else
        echo "019-portability-repair: manifest retrofit reported failures (see above)." >&2
        echo "  Nothing is lost; the update continues and this migration is retried next time." >&2
        FAILED=1
    fi
else
    echo "019-portability-repair: no batches to retrofit."
fi

# --- 2. Re-install on Git Bash, where symlinks needed a guard ---------------
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW* | MSYS* | CYGWIN*)
        if [ -f integrations/claude-code/install.sh ]; then
            echo "019-portability-repair: Git Bash — re-running the installer so symlinks are real…"
            if bash integrations/claude-code/install.sh; then
                echo "019-portability-repair: installer finished."
            else
                echo "019-portability-repair: installer reported a problem (see above)." >&2
                echo "  Re-run it by hand: bash integrations/claude-code/install.sh" >&2
                FAILED=1
            fi
        fi
        ;;
    *)
        echo "019-portability-repair: not Git Bash — installer re-run not needed."
        ;;
esac

# 2, not 1: `partial` in the ledger, retried next update — which is what the
# messages above promise the reader.
if [ "$FAILED" -ne 0 ]; then
    exit 2
fi

exit 0
