#!/usr/bin/env bash
# Pin the working tree to a fresh `origin/main` before a scheduler tick.
#
# Captures the starting branch (the sandbox branch a Routine clones onto,
# e.g. `claude/admiring-shannon-ETCE3`) into `.scheduler-state/start-branch`
# so finalize-tick.sh can target it for the PR-merge delivery path.
#
# Steps:
#   1. Persist current HEAD branch name (or "DETACHED" if not on a branch).
#   2. `git fetch origin main` to refresh remote-tracking ref.
#   3. Branch-specific reconciliation:
#      - Already on main → `git pull --rebase origin main`. Replays any
#        local-only commits on top of origin/main.
#      - On a sandbox / other branch → `git checkout -B main origin/main`.
#
# Sandbox-branch cleanup is delegated to GitHub's "Automatically delete
# head branches" repo setting, which removes each branch immediately
# after its PR is squash-merged. No in-script sweep is needed.
#
# Usage:
#   bash scripts/scheduler/pin-main.sh
#
# Exit codes:
#   0 — on main, HEAD = origin/main (or local commits replayed on top)
#   1 — fetch / checkout / rebase failed (cause printed to stderr)

set -euo pipefail

STATE_DIR=".scheduler-state"
mkdir -p "$STATE_DIR"

START_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo DETACHED)"
printf '%s\n' "$START_BRANCH" > "$STATE_DIR/start-branch"
echo "pin-main: start branch = $START_BRANCH"

git fetch origin main || { echo "pin-main: fetch failed" >&2; exit 1; }

if [ "$START_BRANCH" = "main" ]; then
  if ! git pull --rebase origin main; then
    echo "pin-main: rebase conflict on main; aborting (local commits preserved)" >&2
    git rebase --abort >/dev/null 2>&1 || true
    exit 1
  fi
else
  git checkout -B main origin/main || { echo "pin-main: checkout failed" >&2; exit 1; }
fi

echo "pin-main: HEAD now $(git rev-parse --short HEAD) on main (origin/main)"
