#!/usr/bin/env bash
# 005-scheduler-pr-merge-delivery — Reminder for friends running scheduler
# Routines that delivery now goes through `gh pr create + gh pr merge
# --squash` (or the github MCP equivalent) in Cloud Routines
# environments.
#
# Engine 0.25.0 splits scheduler delivery into two modes auto-detected
# from `.scheduler-state/start-branch`:
#
#   - LOCAL mode (start branch = main) — direct `git push origin main`.
#
#   - ROUTINES mode (start branch = `claude/...`) — push HEAD to the
#     sandbox branch, then create + squash-merge a PR. Routes around
#     Cloud Routines' git proxy refusing direct push to main.
#
# When gh CLI is available in the sandbox, finalize-tick.sh handles the
# full flow including `--delete-branch`. When gh is absent (typical
# Cloud Routines case), the prompt's Step 5b routes the create + merge
# through the github MCP server. Branch deletion in either case is
# delegated to GitHub's «Automatically delete head branches» repo
# setting.
#
# Required actions after this update:
#
#   1. Re-paste the three updated prompt bodies into your /schedule:
#        integrations/claude-code/scheduler-prompts/process-scheduled.md
#        integrations/claude-code/scheduler-prompts/agent-lens-nightly.md
#        integrations/claude-code/scheduler-prompts/lint-nightly.md
#
#   2. Enable «Automatically delete head branches» on the GitHub repo
#      (Settings → General → Pull Requests). The new architecture
#      assumes this setting; without it, scheduler sandbox branches
#      accumulate on origin.
#
#   3. Optional one-time cleanup of any pre-existing `claude/*` sandbox
#      branches accumulated before this update:
#        git push origin --delete <branch>
#      from a local clone with push rights. The new architecture creates
#      no stranded branches going forward.
#
# Idempotent: prints the reminder on every run; no state to track.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROMPTS_DIR="$REPO_ROOT/integrations/claude-code/scheduler-prompts"

cat <<MSG

────────────────────────────────────────────────────────────────────────
Engine 0.25.0 — Scheduler PR-merge delivery (Cloud Routines support)
────────────────────────────────────────────────────────────────────────

If you are running ZTN scheduler ticks in Anthropic Cloud Routines and
have been seeing «push failed HTTP 403» from finalize-tick.sh — that is
the Routines git proxy refusing direct push to main. Engine 0.25.0
adds a second delivery mode that routes via sandbox branch + PR +
squash merge, which the proxy accepts.

Required actions after this update:

1. Re-paste the updated scheduler prompt bodies into your /schedule:
     $PROMPTS_DIR/process-scheduled.md
     $PROMPTS_DIR/agent-lens-nightly.md
     $PROMPTS_DIR/lint-nightly.md

2. Enable «Automatically delete head branches» on your GitHub repo:
     Settings → General → Pull Requests → «Automatically delete head
     branches» ☑
   The new architecture relies on this for sandbox-branch cleanup.

3. (Optional one-time) Delete any pre-existing `claude/*` sandbox
   branches accumulated before this update:
     git push origin --delete <branch>
   from a local clone with push rights.

Local cron / launchd / GitHub Actions schedulers with direct push rights
to main are unaffected — they auto-detect LOCAL mode and keep pushing
directly.

────────────────────────────────────────────────────────────────────────

MSG

exit 0
