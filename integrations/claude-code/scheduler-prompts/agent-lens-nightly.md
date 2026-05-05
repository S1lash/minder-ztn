You are running an autonomous nightly tick for /ztn:agent-lens. There
is no human in this loop. Your contract:

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
     note to `_system/state/CLARIFICATIONS.md` under
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
   `_sources/.agent-lens.lock`. Any lock present at tick start is by
   definition orphaned by a crashed prior run (this contract bans sub-
   agents; skills delete their lock in finally).
   - mtime older than 2h → delete the lock(s) and proceed.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 4 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Agent-lens. Run `/ztn:agent-lens --all-due` INLINE in this same
   agent. Do NOT spawn a sub-agent (no Agent / Task tool, no "general-
   purpose agent", no background dispatch).
   - Rationale: spawning a child causes this agent to poll the
     filesystem, see `.agent-lens.lock` written by its own child, and
     deadlock waiting on a lock it cannot itself release.
   - Do NOT poll `_sources/.agent-lens.lock` or any state file to
     infer skill progress. When `/ztn:agent-lens` returns control to
     you, it is done — proceed to step 4.
   - The skill reads `_system/registries/AGENT_LENSES.md`, filters
     lenses with `status: active` and that are due per their cadence,
     runs them sequentially (base-input first, lens-outputs-input
     last), writes outputs to `_system/agent-lens/{id}/{date}.md` —
     including any optional `## Action Hints` trailers — appends to
     `_system/state/agent-lens-runs.jsonl`, and logs to
     `_system/state/log_agent_lens.md`. Each observation entity
     carries the privacy trio per SKILL Step 5.9 (`origin: personal`,
     `audience_tags: []`, `is_sensitive: false` — owner-only by
     construction; engine never auto-widens).
   - Validator rejections, registry malformations, individual lens
     errors — all surface to `log_agent_lens.md` and CLARIFICATIONS
     as the skill designs. Do NOT pause for owner.
   - If `/ztn:agent-lens` aborts on lock / repo state — append failure
     note to CLARIFICATIONS, then continue to step 4 so the note
     still ships.
   - Action Hints written by lenses here will be consumed by
     `/ztn:resolve-clarifications --auto-mode` later in the night
     (lint nightly tick dispatches it inline via Step 7.5). Lens
     production and resolve consumption sit in separate scheduler-
     agent contexts on purpose: the agent that judges proposals in
     Step A.2/A.3 has not just produced lens body output, which
     prevents confirmation bias on its own emissions.
   - Do NOT exclude or reorder lenses; the registry IS the policy.
     Do NOT pass `--include-draft` or `--lens <id>` (manual single-
     lens and draft runs are owner-driven).

4. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

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
     `/ztn:save --auto --message "scheduler: agent-lens uncovered
     error, owner action needed"` to ship the note + exit with
     `partial` status.
   - Never silent failure. Never «log and pretend success».
   - Never pause for owner — the scheduler runs unattended; owner
     sees CLARIFICATIONS on next morning routine.

7. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:lint` (separate scheduler tick at 03:00)
   - `/ztn:resolve-clarifications` (auto-mode is dispatched by the
     later lint nightly tick via lint Step 7.5; not here — lens
     emission and resolve consumption are kept in separate
     scheduler-agent contexts on purpose)
   - `/ztn:update` (engine sync is owner-only)
   - `--include-draft` on agent-lens (drafts are owner-driven dry-runs)
   - `--lens <id>` on agent-lens (manual single-lens runs are
     owner-driven; scheduled ticks always run `--all-due`)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion
   - spawning a sub-agent / Task / "general-purpose agent" for any
     step in this contract

Output: single-line status (success / partial / sync-blocked /
save-blocked / lens-locked) plus commit SHA if landed. No prose.
