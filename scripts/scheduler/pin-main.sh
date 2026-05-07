#!/usr/bin/env bash
# Pin the working tree to a fresh `origin/main` before a scheduler tick.
#
# Captures the starting branch (the sandbox branch a Routine clones onto,
# e.g. `claude/admiring-shannon-ETCE3`) into `.scheduler-state/start-branch`
# so cleanup-sandbox.sh can delete it after save.sh ships the tick result.
#
# Steps:
#   1. Persist current HEAD branch name (or "DETACHED" if not on a branch).
#   2. `git fetch origin main` to refresh remote-tracking ref.
#   3. Branch-specific reconciliation:
#      - Already on main → `git pull --rebase origin main`. Replays any
#        local-only commits on top of origin/main instead of clobbering
#        them. Critical for local cron / launchd schedulers where the
#        owner may have unpushed commits at tick time. Cloud Routines
#        always start on a sandbox branch, so this branch is never hit
#        there.
#      - On a sandbox / other branch (e.g. cloud Routines on
#        `claude/random`) → `git checkout -B main origin/main`. The
#        sandbox branch has no commits worth preserving by definition;
#        cleanup-sandbox.sh deletes it at end of tick.
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

# GC pass — delete leftover sandbox branches on origin from prior ticks.
# Why here and not in cleanup-sandbox: a Routine session holds its own
# sandbox branch ref while running, so the SAME tick cannot delete it
# (push --delete on the active session ref is rejected by the platform).
# A subsequent tick runs in a different session and CAN delete previous
# branches. This pass cleans them at start; cleanup-sandbox at end is
# kept too as a best-effort first-attempt.
gc_count=0
gc_failed=0
while IFS= read -r sandbox_branch; do
  [ -n "$sandbox_branch" ] || continue
  # Never delete the branch this very tick started on — that IS the
  # active session ref and the platform won't let us anyway.
  [ "$sandbox_branch" = "$START_BRANCH" ] && continue
  if git push origin --delete "$sandbox_branch" >/dev/null 2>&1; then
    gc_count=$((gc_count + 1))
    echo "pin-main: gc'd leftover sandbox branch origin/$sandbox_branch"
  else
    gc_failed=$((gc_failed + 1))
  fi
done < <(git ls-remote --heads origin 'claude/*' 2>/dev/null | awk '{sub("refs/heads/","",$2); print $2}')

if [ "$gc_count" -gt 0 ] || [ "$gc_failed" -gt 0 ]; then
  echo "pin-main: sandbox-branch gc — deleted $gc_count, failed $gc_failed"
fi
