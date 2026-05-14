#!/usr/bin/env bash
# 004-scheduler-single-commit-protocol — Reminder migration for friends
# updating from engine 0.22.x or earlier.
#
# Engine 0.23.0 replaces the per-step `/ztn:save --auto` pattern with a
# single-commit protocol: `scripts/scheduler/stage.sh` (idempotent staging)
# + `scripts/scheduler/finalize-tick.sh <tag>` (one commit + one push at
# the tail of every scheduler tick). The prior `scripts/scheduler/save.sh`
# is removed.
#
# Anyone running ZTN scheduler Routines (Claude Code `/schedule`, cron,
# launchd, GitHub Actions) MUST re-paste the three updated prompt bodies
# from `integrations/claude-code/scheduler-prompts/` into their scheduler
# after this update. The old bodies reference `save.sh` and `/ztn:save
# --auto` and will fail post-update.
#
# This migration:
#   1. Detects whether the local clone has scheduler-related state files
#      that suggest the owner is actually running scheduled ticks.
#   2. Prints a clear re-paste reminder. No file mutation.
#
# Idempotent: prints the reminder on every run; no state to track.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROMPTS_DIR="$REPO_ROOT/integrations/claude-code/scheduler-prompts"

cat <<MSG

────────────────────────────────────────────────────────────────────────
Engine 0.23.0 — Scheduler single-commit protocol
────────────────────────────────────────────────────────────────────────

The autonomous scheduler protocol changed:

  OLD: Step 5 = /ztn:save --auto --tag scheduler/<x>
       (produced N commits per tick when the agent grouped by theme)

  NEW: Step 5 = bash scripts/scheduler/finalize-tick.sh scheduler/<x>
       (one commit + one push per tick, guaranteed)

scripts/scheduler/save.sh has been removed. If you are running ZTN ticks
via Claude Code /schedule, cron, launchd, or GitHub Actions, re-paste
the updated prompt bodies into your scheduler:

  $PROMPTS_DIR/process-scheduled.md
  $PROMPTS_DIR/agent-lens-nightly.md
  $PROMPTS_DIR/lint-nightly.md

The new helper scripts are already in place after this update:

  scripts/scheduler/stage.sh        — idempotent staging
  scripts/scheduler/finalize-tick.sh — single commit + push

The /ztn:save skill remains available for OWNER interactive use. Only
the scheduler protocol changed.

────────────────────────────────────────────────────────────────────────

MSG

exit 0
