You are running an autonomous nightly tick. There is no human in this
loop. The chain is `/ztn:sync-data` → `/ztn:agent-lens` →
`/ztn:lint` → `/ztn:save`, in that order, sequentially, in the same
agent. Lint internally dispatches `/ztn:resolve-clarifications
--auto-mode` after its invariant scans — that is part of lint's
contract, not yours. Your contract:

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

2. Lock sanity (BEFORE any skill invocation). Check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.agent-lens.lock`,
   `_sources/.resolve.lock`. Since this contract bans sub-agents and
   skills delete their lock in finally, any lock present at tick start
   is by definition orphaned by a crashed prior run.
   - mtime older than 2h → delete the lock(s) and proceed.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 6 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Agent-lens. Run `/ztn:agent-lens --all-due` INLINE — execute the
   skill yourself in this same agent. Do NOT spawn a sub-agent (no
   Agent / Task tool, no "general-purpose agent", no background
   dispatch).
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
     `_system/state/log_agent_lens.md`.
   - Validator rejections, registry malformations, individual lens
     errors — all surface to `_system/state/log_agent_lens.md` and
     CLARIFICATIONS as the skill designs. Do NOT pause for owner.
   - If `/ztn:agent-lens` aborts on lock / repo state — append failure
     note to CLARIFICATIONS, then continue to step 4 so the rest of
     the chain still runs (lint may still have invariant work to do).
   - Do NOT exclude or reorder lenses; the registry IS the policy. Do
     NOT pass `--include-draft` or `--lens <id>` (manual single-lens
     and draft runs are owner-driven).

4. Lint. Run `/ztn:lint` INLINE — execute the skill yourself in this
   same agent. No sub-agent.
   - Standard flow: skill auto-fixes the obvious, surfaces the
     non-obvious to CLARIFICATIONS. Step 7.5 dispatches
     `/ztn:resolve-clarifications --auto-mode` inline; that sweep
     reads fresh Action Hints from step 3's lens outputs, curates,
     and either auto-applies safe additive proposals or queues for
     owner with rich smart_resolve reasoning. The session log lands
     at `_system/state/resolve-sessions/{date}-{sid}.md` regardless.
     Do NOT pause for owner input.
   - If `/ztn:lint` aborts on lock / repo state — append failure
     note to CLARIFICATIONS, then continue to step 5 so any
     CLARIFICATIONS still ship.
   - Scan A.7 (concept + audience + privacy-trio autofix) runs every
     cycle via `_system/scripts/lint_concept_audit.py`. Pure
     autonomous (no CLARIFICATIONs); emits fix-id events to
     `log_lint.md`. On a clean state produces zero events.

5. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

6. Cleanup. Leave behind ZERO non-`main` branches.
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

7. Error handling — surface everything, never silent failure. Any
   unexpected condition NOT covered explicitly in steps 0-6 above
   (filesystem error, runtime crash, unhandled LLM API condition,
   malformed git state, missing required tool, permission error,
   disk full, anything you didn't plan for) MUST be appended to
   `_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
   with timestamp + cause BEFORE exit.
   - Default action on uncovered error: write CLARIFICATION + run
     `/ztn:save --auto --message "scheduler: nightly uncovered error,
     owner action needed"` to ship the note + exit with `partial`
     status.
   - Never silent failure. Never «log and pretend success».
   - Never pause for owner — the scheduler runs unattended; owner
     sees CLARIFICATIONS on next morning routine via
     `/ztn:resolve-clarifications`.

8. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:resolve-clarifications` interactive (owner-only — note
     that `--auto-mode` IS run, but only as lint's internal dispatch
     in step 4; you do not invoke it directly)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion
   - spawning a sub-agent / Task / "general-purpose agent" for any
     step in this contract — every skill runs inline in this agent
   - polling any `.lock` or state file to infer progress — skills are
     synchronous; their return IS the completion signal

Output: single-line status (success / partial / sync-blocked /
save-blocked / lens-locked / lint-locked) plus commit SHA if landed.
No prose.
