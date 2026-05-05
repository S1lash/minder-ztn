You are running an autonomous scheduled tick. There is no human in this
loop. Your contract:

0. Force operation on `main`. The runtime may have started this run on a
   sandbox branch (e.g. `claude/<random>`). All work in this tick MUST
   land on `main` directly — no feature branches, no PRs, no leftover
   branches anywhere.
   - Capture the starting branch: `START_BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
   - `git fetch origin main`.
   - `git checkout main` (create-or-track if needed:
     `git checkout -B main origin/main`).
   - `git pull --rebase origin main` — rebase variant on purpose:
     sandbox-local commits on `main` (e.g. an unpushed commit from a
     previous failed tick) get replayed on top of `origin/main`
     instead of blocking on non-fast-forward. Force-push remains
     forbidden; rebase only re-orders local-only commits.
   - If checkout fails on a dirty working tree, or rebase encounters
     conflicts → run `git rebase --abort || true`, append a one-line
     note to `_system/state/CLARIFICATIONS.md` under a
     `### Scheduler failures` section with timestamp and cause, run
     `/ztn:save --auto --message "scheduler: cannot reach main, owner
     action needed"` (this will commit + push on whatever branch we're
     on so the note still ships), then exit.
   - From here on, the working branch is `main`. All subsequent steps
     operate on `main` only.

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue.
   - Conflict / non-fast-forward → STOP. Append a one-line note to
     `_system/state/CLARIFICATIONS.md` under a `### Scheduler failures`
     section with timestamp and short cause, then run `/ztn:save --auto
     --message "scheduler: sync conflict, owner action needed"` so the
     note itself ships to remote. Exit.

2. Process.
   - **2a. Lock sanity (BEFORE invoking the skill).** Check
     `_sources/.processing.lock`, `_sources/.maintain.lock`,
     `_sources/.lint.lock`, `_sources/.agent-lens.lock`,
     `_sources/.resolve.lock`. Since this contract bans sub-agents
     and skills delete their lock in finally, any lock present at
     tick start is by definition orphaned by a crashed prior run.
     - mtime older than 2h → delete the lock(s) and proceed.
     - mtime younger than 2h → assume a concurrent owner session
       may be active. Append CLARIFICATION «recent lock at tick
       start, possible concurrent owner session» under
       `### Scheduler failures`, then jump to step 3 (commit the
       CLARIFICATION) and exit cleanly. Do NOT touch the lock.
   - **2b. Run `/ztn:process` INLINE.** Execute the skill yourself in
     this same agent. Do NOT spawn a sub-agent (no Agent / Task tool,
     no "general-purpose agent", no background dispatch). The
     scheduler tick IS the processing agent.
     - Rationale: spawning a child causes this agent to poll the
       filesystem, see `.processing.lock` written by its own child,
       and deadlock waiting on a lock it cannot itself release.
     - Do NOT poll `.processing.lock`, `_system/state/`, or
       `git status` to infer skill progress. When `/ztn:process`
       returns control to you, it is done — proceed to step 3.
     - Anything ambiguous, low-confidence, or boundary-case — let
       the skill route it to CLARIFICATIONS as designed. Do NOT
       pause for owner input. CLARIFICATIONS growing is the expected
       steady state.
     - `/ztn:process` finishes maintain inline; do not invoke
       `/ztn:maintain` separately.
     - If `/ztn:process` aborts on lock / repo state — append
       failure note to CLARIFICATIONS as in step 1, then continue to
       step 3 so the note still gets committed.
     - **Manifest emission.** `/ztn:process` Step 5.5 writes both
       `_system/state/batches/{batch_id}.md` (markdown report) and
       `_system/state/batches/{batch_id}.json` (JSON manifest via
       `emit_batch_manifest.py` — Minder consumer contract per
       `minder-project/strategy/ARCHITECTURE.md` §4.5). `/ztn:maintain`
       Step 6.6 writes its own `{batch_id}-maintain.json`. Both
       files commit through `/ztn:save` in step 3 normally.
     - **Concept and audience layer is fully autonomous.** Format
       issues never raise CLARIFICATION; the engine resolves via
       `_common.py` normalisers (`normalize_concept_name`,
       `normalize_audience_tag`, `recompute_hub_trio`) at Step 3.6
       structural verification + Step 4.7 producer guard. Lint Scan
       A.7 is the post-write defence-in-depth. The scheduler tick
       does NOT see new owner-facing items from these classes —
       they're producer-resolved.

3. Save. Run `/ztn:save --auto`.
   - This commits with the auto-proposed message (suffix `[scheduled]`)
     and pushes to `origin`. No prompts.
   - Engine paths are refused as always; if any are dirty, that's an
     owner-only situation and the scheduler must surface it via
     CLARIFICATIONS, not bypass via `--include-engine`.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

4. Cleanup. The tick must leave behind ZERO non-`main` branches.
   - Verify current branch is still `main`: `git rev-parse --abbrev-ref HEAD`
     must print `main`. If not, append CLARIFICATION and exit.
   - If `START_BRANCH` (captured in step 0) is not `main`:
     - Delete the local branch if it exists: `git branch -D "$START_BRANCH" || true`.
     - Delete it on `origin` if the runtime pushed it: `git push origin --delete "$START_BRANCH" || true`.
     - Both deletions are best-effort — failure is logged to CLARIFICATIONS
       under `### Scheduler failures` but does NOT change exit status.
   - Never leave any `claude/*` or other ad-hoc branch on `origin` or
     locally. This repo only has `main`.

5. Forbidden in this run:
   - `/ztn:lint` (has its own nightly schedule)
   - `/ztn:agent-lens` (has its own nightly schedule; lens runs are
     not part of the daytime processing flow)
   - `/ztn:resolve-clarifications` (owner-only interactive; auto-mode
     is dispatched by lint Step 7.5 nightly, not from process)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force` of any kind
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion
   - spawning a sub-agent / Task / "general-purpose agent" for
     `/ztn:process`, `/ztn:save`, `/ztn:sync-data`, or any other step
     in this contract — every skill runs inline in this agent
   - polling `.processing.lock` or any state file to infer progress —
     skills are synchronous; their return IS the completion signal

Output: a single-line status (success / partial / sync-blocked /
save-blocked) plus the commit SHA if a commit landed. No prose.
