#!/usr/bin/env bash
# Best-effort first-pass cleanup of the sandbox branch a Routine cloned
# the repo onto.
#
# A Routine session HOLDS its own sandbox branch as the active session
# ref while running, so `git push origin --delete` on that ref is often
# rejected by the platform. The leftover branch then gets garbage-
# collected by the GC pass in pin-main.sh on the NEXT tick (different
# session, branch is no longer active). This script is kept as the
# first-attempt cleanup that succeeds on platforms which do allow
# deleting the active session ref.
#
# Reads the captured starting branch from `.scheduler-state/start-branch`
# (written by pin-main.sh). If that branch is non-empty and not `main`,
# delete it locally and remotely.
#
# Usage:
#   bash scripts/scheduler/cleanup-sandbox.sh
#
# Exit codes:
#   0 — always (cleanup is best-effort by contract)

set -u

STATE_FILE=".scheduler-state/start-branch"

if [ ! -f "$STATE_FILE" ]; then
  echo "cleanup-sandbox: no start-branch state file; skipping"
  exit 0
fi

START_BRANCH="$(cat "$STATE_FILE" 2>/dev/null || echo "")"
rm -f "$STATE_FILE"

if [ -z "$START_BRANCH" ] || [ "$START_BRANCH" = "main" ] || [ "$START_BRANCH" = "DETACHED" ]; then
  echo "cleanup-sandbox: nothing to delete (start branch was '$START_BRANCH')"
  exit 0
fi

# Local delete — agent should always have permission for local refs.
local_err="$(git branch -D "$START_BRANCH" 2>&1 >/dev/null)"
if [ -z "$local_err" ]; then
  echo "cleanup-sandbox: deleted local branch $START_BRANCH"
else
  echo "cleanup-sandbox: local delete of $START_BRANCH skipped — $local_err"
fi

# Remote delete — may fail on platforms holding the active session ref.
# Capture stderr explicitly so the diagnostic surfaces in the tick log
# instead of being silently swallowed. The pin-main GC pass on the next
# tick will retry from a fresh session.
remote_err="$(git push origin --delete "$START_BRANCH" 2>&1 >/dev/null)"
if [ -z "$remote_err" ]; then
  echo "cleanup-sandbox: deleted remote branch origin/$START_BRANCH"
else
  echo "cleanup-sandbox: remote delete of origin/$START_BRANCH deferred to next-tick gc — $remote_err"
fi

exit 0
