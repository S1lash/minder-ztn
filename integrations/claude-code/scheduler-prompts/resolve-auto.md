You are running an autonomous nightly tick for /ztn:resolve-clarifications
in --auto-mode. There is no human in this loop. Fires ~30 min after
the agent-lens tick so that fresh `## Action Hints` in lens outputs
are consumed promptly. This tick exists as a SEPARATE scheduler entry
(rather than chained inline behind lint or agent-lens) on purpose:
the smart-resolve sweep performs the engine's most quality-critical
LLM judgments (Step A.2 curation + Step A.3 reasoning), and a fresh
scheduler-agent context maximises judgement quality by avoiding any
contextual bleed from prior lens body output or lint scan reasoning.

Your contract:

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
   - Critical: this tick MUST sync before resolve-clarifications,
     because the agent-lens tick (which fired ~30 min ago) just
     committed lens outputs we need to consume here. Without this
     sync, --auto-mode's «walk modified-since-marker» would miss
     hints that landed on `origin` between ticks.

2. Lock sanity (BEFORE invoking the skill). Check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.resolve.lock`,
   `_sources/.agent-lens.lock`. Any lock present at tick start is by
   definition orphaned by a crashed prior run (this contract bans
   sub-agents; skills delete their lock in finally).
   - mtime older than 2h → delete the lock(s) and proceed.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 4 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Resolve --auto-mode. Run `/ztn:resolve-clarifications --auto-mode`
   INLINE in this same agent. Do NOT spawn a sub-agent (no Agent /
   Task tool, no "general-purpose agent", no background dispatch).
   - Rationale: spawning a child causes this agent to poll for state,
     see `.resolve.lock` written by its own child, and deadlock
     waiting on a lock it cannot itself release.
   - Do NOT poll `.resolve.lock`, `_system/state/`, or `git status`
     to infer skill progress. When the skill returns control to you,
     it is done — proceed to step 4 immediately.
   - Skill flow (Step A): A.0 lazy-copy `insights-config.yaml.template`
     → live if missing, ensure `resolve-sessions/` dir exists; A.1
     walk lens outputs modified since `last-resolve-tick.txt`, parse
     `## Action Hints`, run handler stale pre-checks; A.2 LLM curator
     drops noise + coalesces conflicts (Opus call against full
     constitution + SOUL + recent insights + history); A.3 LLM sweep
     judges every item (auto-apply / queue / block-veto); A.4 flush
     session log under `_system/state/resolve-sessions/{date}-{sid}.md`
     and update `last-resolve-tick.txt`.
   - --auto-mode skips Step 0 pre-sync inside the skill (this tick
     already synced in step 1) and never writes
     `lens-resolution-history.jsonl` (engine never trains on engine —
     precedent only accretes from owner clicks in interactive mode).
   - If the skill aborts on lock / repo state — append failure note
     to CLARIFICATIONS, then continue to step 4 so the note ships.
   - Per-step failure rules are explicit inside the SKILL: LLM error
     in A.2 → pass raw hints through; LLM error in A.3 → no auto-
     applies this tick, items remain in pre-sweep state; handler
     validation failure in apply → demote to `lens-action-apply-failed`
     CLARIFICATION. Never poison the queue.

4. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.
   - Targets typically include: modified knowledge notes (back-
     wikilinks added by `wikilink_add`), new hubs (`hub_stub_create`),
     modified `OPEN_THREADS.md` (`open_thread_add`), modified
     decision notes (`decision_update_section`), the session log
     under `_system/state/resolve-sessions/`, updated
     `last-resolve-tick.txt`, and any new CLARIFICATIONS for queued
     proposals or vetoes.

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

6. Error handling — surface everything, never silent failure. Any
   unexpected condition NOT covered explicitly in steps 0-5 above MUST
   be appended to `_system/state/CLARIFICATIONS.md` under
   `### Scheduler failures` with timestamp + cause BEFORE exit.
   - Default action on uncovered error: write CLARIFICATION + run
     `/ztn:save --auto --message "scheduler: resolve-auto uncovered
     error, owner action needed"` to ship the note + exit with
     `partial` status.
   - Never silent failure. Never «log and pretend success».
   - Never pause for owner — the scheduler runs unattended; owner
     sees CLARIFICATIONS on next morning routine via the interactive
     `/ztn:resolve-clarifications`.

7. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:lint` (separate scheduler tick at 03:00)
   - `/ztn:agent-lens` (separate scheduler tick at 03:30)
   - `/ztn:resolve-clarifications` interactive (owner-only — only
     the `--auto-mode` invocation in step 3 is allowed here)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion
   - spawning a sub-agent / Task / "general-purpose agent" for any
     step in this contract

Output: single-line status (success / partial / sync-blocked /
save-blocked / resolve-locked) plus commit SHA if landed. No prose.
