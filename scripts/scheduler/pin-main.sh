#!/usr/bin/env bash
# Pin the working tree to a fresh `origin/main` before a scheduler tick.
#
# Captures the starting branch (the sandbox branch a Routine clones onto,
# e.g. `claude/admiring-shannon-ETCE3`) into `.scheduler-state/start-branch`
# so finalize-tick.sh can target it for the PR-merge delivery path.
#
# Steps:
#   1. Persist current HEAD branch name (or "DETACHED" if HEAD is detached).
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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/../lib/git.sh"

STATE_DIR=".scheduler-state"
mkdir -p "$STATE_DIR"

# `git_current_branch_or` — never `rev-parse --abbrev-ref`, which exits 0 and
# prints the literal string `HEAD` on a detached checkout, so an `|| echo
# DETACHED` fallback never fires. That literal then reaches finalize-tick.sh,
# which reads it as a sandbox branch name and tries to deliver via
# `git push origin HEAD:HEAD` and a PR against a branch called `HEAD`.
START_BRANCH="$(git_current_branch_or DETACHED)"
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
