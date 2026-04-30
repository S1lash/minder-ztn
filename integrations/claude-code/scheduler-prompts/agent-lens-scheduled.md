You are running an autonomous scheduled tick for the agent-lens system.
There is no human in this loop. Your contract:

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

2. Agent-lens. Run `/ztn:agent-lens --all-due` INLINE — execute the
   skill yourself in this same agent. Do NOT spawn a sub-agent (no
   Agent / Task tool, no "general-purpose agent", no background
   dispatch). The scheduler tick IS the agent-lens agent.
   - Rationale: spawning a child causes this agent to poll the
     filesystem, see `.agent-lens.lock` written by its own child, and
     deadlock waiting on a lock it cannot itself release.
   - Do NOT poll `_sources/.agent-lens.lock`, `_system/state/`, or
     `git status` to infer skill progress. When `/ztn:agent-lens`
     returns control to you, it is done — proceed to step 3.
   - The skill reads `_system/registries/AGENT_LENSES.md`, filters
     lenses with `status: active` and that are due per their cadence,
     runs them sequentially (records-input first, lens-outputs-input
     last), writes outputs to `_system/agent-lens/{id}/{date}.md`,
     appends to `_system/state/agent-lens-runs.jsonl`, and logs to
     `_system/state/log_agent_lens.md`.
   - Validator rejections, registry malformations, individual lens
     errors — all surface to `_system/state/log_agent_lens.md` and
     CLARIFICATIONS as the skill designs. Do NOT pause for owner.
   - If `/ztn:agent-lens` aborts on lock / repo state — append failure
     note to CLARIFICATIONS as in step 1, then continue to step 3 so
     the note still ships.
   - Pre-step sanity: before invoking `/ztn:agent-lens`, check for
     leftover locks: `_sources/.processing.lock`, `_sources/.maintain.lock`,
     `_sources/.lint.lock`, `_sources/.agent-lens.lock`. Since this
     contract bans sub-agents and skills delete their lock on exit,
     any lock at tick start is stale by definition. Older than 2h →
     delete and proceed. Younger than 2h → append CLARIFICATION
     «recent lock at tick start, possible concurrent owner session»
     and exit.
   - Do NOT exclude or reorder lenses; the registry IS the policy.

3. Save. Run `/ztn:save --auto`.
   - Commits with auto-proposed message (suffix `[scheduled]`) and
     pushes to `origin`. Engine refusal applies. No force-push.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

4. Cleanup. Leave behind ZERO non-`main` branches.
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

5. Error handling — surface everything, never silent failure.
   Any unexpected condition NOT covered explicitly in steps 0-4
   above (filesystem error, runtime crash, unhandled LLM API
   condition, malformed git state, missing required tool,
   permission error, disk full, anything you didn't plan for) MUST
   be appended to `_system/state/CLARIFICATIONS.md` under
   `### Scheduler failures` with timestamp + cause BEFORE exit.
   - Default action on uncovered error: write CLARIFICATION + run
     `/ztn:save --auto --message "scheduler: agent-lens uncovered
     error, owner action needed"` to ship the note + exit with
     `partial` status.
   - Never silent failure. Never «log and pretend success».
   - Never pause for owner — the scheduler runs unattended; owner
     sees CLARIFICATIONS on next morning routine via
     /ztn:resolve-clarifications.
   - The skill itself ALSO writes CLARIFICATIONS for its own
     internal errors (registry malformed, lens-level failures,
     auto-pause triggers — see SKILL.md «Error handling principle»).
     The scheduler-tick layer adds CLARIFICATIONS only for things
     OUTSIDE the skill's reach (git state, filesystem, runtime).

6. Forbidden in this run:
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:lint` (its own nightly schedule)
   - `/ztn:resolve-clarifications` (owner-only)
   - `/ztn:update` (engine sync is owner-only)
   - `--include-draft` on agent-lens (drafts are owner-driven dry-runs)
   - `--lens <id>` on agent-lens (manual single-lens runs are
     owner-driven; scheduled ticks always run `--all-due`)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion

Output: single-line status (success / partial / sync-blocked /
save-blocked / lens-locked) plus commit SHA if landed. No prose.
