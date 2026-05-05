You are running an autonomous nightly tick for /ztn:lint. There is no
human in this loop. Your contract:

0. Force operation on `main`. The runtime may have started this run on a
   sandbox branch (e.g. `claude/<random>`). All work in this tick MUST
   land on `main` directly — no feature branches, no PRs, no leftover
   branches anywhere.
   - Capture the starting branch: `START_BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
   - `git checkout main` (create-or-track if needed:
     `git checkout -B main origin/main`).
   - `git pull --ff-only origin main`.
   - If checkout fails or pull is non-fast-forward → STOP. Append a
     one-line note to `_system/state/CLARIFICATIONS.md` under
     `### Scheduler failures` with timestamp and cause, run
     `/ztn:save --auto --message "scheduler: cannot reach main, owner
     action needed"`, exit.
   - From here on, the working branch is `main`.

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue.
   - Conflict → STOP. Append a one-line note to
     `_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
     with timestamp and cause, then run `/ztn:save --auto --message
     "scheduler: sync conflict, owner action needed"`. Exit.

2. Lock sanity (BEFORE invoking the skill). Check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.resolve.lock`,
   `_sources/.agent-lens.lock`. Since this contract bans sub-agents and
   skills delete their lock in finally, any lock present at tick start
   is by definition orphaned by a crashed prior run.
   - mtime older than 2h → delete the lock(s) and proceed.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 4 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Lint. Run `/ztn:lint` INLINE in this same agent. Do NOT spawn a
   sub-agent (no Agent / Task tool, no "general-purpose agent", no
   background dispatch). The scheduler tick IS the lint agent.
   - Rationale: spawning a child causes this agent to poll for state,
     see `.lint.lock` written by its own child, and deadlock waiting
     on a lock it cannot itself release.
   - Do NOT poll `.lint.lock`, `_system/state/`, or `git status` to
     infer skill progress. When `/ztn:lint` returns control to you,
     it is done — proceed to step 4 immediately.
   - Standard flow: skill auto-fixes the obvious, surfaces the
     non-obvious to CLARIFICATIONS. Do NOT pause for owner input.
   - Queue size is irrelevant to whether the run continues — owner
     reviews the queue tomorrow via `/ztn:resolve-clarifications`.
   - If `/ztn:lint` aborts on lock / repo state — append failure note
     to CLARIFICATIONS, then continue to step 4 so the note ships.
   - Scan A.7 (concept + audience + privacy-trio autofix) runs every
     cycle via `_system/scripts/lint_concept_audit.py`. Pure
     autonomous (no CLARIFICATIONs); emits fix-id events to
     `log_lint.md`. On a clean state produces zero events.

4. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.

5. Cleanup. Leave behind ZERO non-`main` branches.
   - Verify current branch is `main`: `git rev-parse --abbrev-ref HEAD`
     must print `main`. If not, append CLARIFICATION and exit.
   - If `START_BRANCH` (captured in step 0) is not `main`:
     - `git branch -D "$START_BRANCH" || true`
     - `git push origin --delete "$START_BRANCH" || true`
     - Both deletions are best-effort; failure is logged to
       CLARIFICATIONS under `### Scheduler failures` but does not
       change exit status.
   - Never leave any `claude/*` or other ad-hoc branch on `origin` or
     locally.

6. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:agent-lens` (separate scheduler tick at 03:30)
   - `/ztn:resolve-clarifications` (separate scheduler tick at 04:00 —
     auto-mode is dispatched there, not here, so each LLM-judgment
     skill gets a fresh scheduler-agent context)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion
   - spawning a sub-agent / Task / "general-purpose agent" for any
     step in this contract
   - polling `.lint.lock` or any state file to infer progress —
     skills are synchronous; their return IS the completion signal

Output: single-line status (success / partial / sync-blocked /
save-blocked / lint-locked) plus commit SHA if landed. No prose.
