#!/usr/bin/env bash
# Stage owner-data changes for the current scheduler tick — DOES NOT commit
# or push. The single point that produces a commit is finalize-tick.sh, run
# once at the tail of the scheduler prompt.
#
# Engine paths are NEVER staged. The engine boundary is derived from
# `.engine-manifest.yml` (single source of truth) via the companion helper
# `_classify_paths.py`. If dirty engine paths are detected, an explanatory
# note is appended to CLARIFICATIONS.md (which is itself owner data and
# gets staged) and engine paths are left dirty in the working tree.
#
# Idempotent: re-running with no new changes is a no-op. Safe to call
# multiple times within a tick — finalize-tick.sh collapses everything
# into one commit regardless.
#
# Usage:
#   bash scripts/scheduler/stage.sh
#
# Exit codes:
#   0 — staged (or nothing to stage)
#   2 — git operation failed (see stderr)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAR="zettelkasten/_system/state/CLARIFICATIONS.md"
TS="$(date -u +%Y-%m-%dT%H:%MZ)"

extract_paths() {
  local line path
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    path="${line:3}"
    path="${path##* -> }"
    path="${path#\"}"
    path="${path%\"}"
    printf '%s\n' "$path"
  done
}

# `-c core.quotepath=false` is load-bearing: with the default (true), git
# octal-escapes non-ASCII bytes in `git status --porcelain` output (e.g. a
# Cyrillic filename becomes "…\320\222…"). extract_paths strips the wrapping
# quotes but cannot decode those escapes, so the literal backslash-octal string
# reaches `git add` and fails with "pathspec did not match". With quotepath
# off, non-ASCII prints as raw UTF-8; spaces still wrap the path in quotes,
# which extract_paths already handles.
CLASSIFIED="$(git -c core.quotepath=false status --porcelain | extract_paths | python3 "$SCRIPT_DIR/_classify_paths.py")"
CLASSIFY_RC=$?
if [ "$CLASSIFY_RC" -ne 0 ]; then
  echo "stage: path classifier failed (rc=$CLASSIFY_RC)" >&2
  exit 2
fi

declare -a ENGINE_DIRTY=()
declare -a OWNER_DIRTY=()
while IFS=$'\t' read -r label path; do
  [ -z "${path:-}" ] && continue
  if [ "$label" = "ENGINE" ]; then
    ENGINE_DIRTY+=("$path")
  else
    OWNER_DIRTY+=("$path")
  fi
done <<< "$CLASSIFIED"

if [ ${#ENGINE_DIRTY[@]} -gt 0 ]; then
  mkdir -p "$(dirname "$CLAR")"
  touch "$CLAR"
  grep -q '^### Scheduler failures$' "$CLAR" || printf '\n### Scheduler failures\n' >> "$CLAR"
  printf -- '- %s scheduler-stage: engine drift skipped from auto-commit: %s\n' \
    "$TS" "${ENGINE_DIRTY[*]}" >> "$CLAR"
  case " ${OWNER_DIRTY[*]:-} " in
    *" $CLAR "*) ;;
    *) OWNER_DIRTY+=("$CLAR") ;;
  esac
fi

if [ ${#OWNER_DIRTY[@]} -eq 0 ]; then
  echo "stage: nothing to stage"
  exit 0
fi

git add -- "${OWNER_DIRTY[@]}" || exit 2

# Defence-in-depth: re-classify what actually landed in the index. The
# manifest is authoritative; this catches index races where a stat-only
# refresh might let an engine path slip through.
INDEX_CLASSIFIED="$(git -c core.quotepath=false diff --cached --name-only | python3 "$SCRIPT_DIR/_classify_paths.py")"
STAGED_ENGINE=()
while IFS=$'\t' read -r label path; do
  [ -z "${path:-}" ] && continue
  [ "$label" = "ENGINE" ] && STAGED_ENGINE+=("$path")
done <<< "$INDEX_CLASSIFIED"
if [ ${#STAGED_ENGINE[@]} -gt 0 ]; then
  echo "stage: aborting — engine path landed in stage despite filter:" >&2
  printf '  %s\n' "${STAGED_ENGINE[@]}" >&2
  git reset HEAD -- "${STAGED_ENGINE[@]}" >/dev/null 2>&1 || true
  exit 2
fi

echo "stage: staged ${#OWNER_DIRTY[@]} owner-data path(s)"
