You are running an autonomous nightly tick for /ztn:agent-lens. There
is no human in this loop. Your contract:

## Invocation contract (read this first, it is load-bearing)

Every skill in this contract — `/ztn:sync-data`, `/ztn:agent-lens`,
`/ztn:save` — is invoked **exclusively via the Skill tool**, exactly
once per skill, e.g.:

```
Skill(skill="ztn:agent-lens", args="--all-due")
Skill(skill="ztn:save", args="--auto")
```

That IS what «inline» means in this prompt: the Skill tool runs the
skill in this same conversation, same context, no sub-agent. NOT
that you re-implement the skill yourself.

**Hard prohibitions, no exceptions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  execute its steps yourself with Bash / Read / Edit / Grep / Glob /
  Write. The skill machinery already exists; your job is to INVOKE
  it, not RE-IMPLEMENT it. Manual re-implementation exhausts the
  agent turn budget before the save step (lint-tick failure mode
  documented 2026-05-06).
- Do NOT use the Agent / Task tool as a SUBSTITUTE for invoking the
  skill via the Skill tool. The scheduler tick MUST enter each skill
  through `Skill(skill="ztn:<name>", ...)`, not by delegating
  «execute /ztn:<name> for me» to a child agent. The deadlock
  prohibition (parent holds `.agent-lens.lock`, child polls for it,
  deadlock) is enforced by entering through Skill, not by banning
  the skill's internal architecture. `/ztn:agent-lens` itself
  forbids subagent dispatch by its own SKILL.md Step 4.5.3 (direct
  LLM API only); this scheduler contract does not relax that.
- Do NOT poll `_sources/.agent-lens.lock`, `_system/state/`,
  `git status`, or any other file to infer skill progress. Skill
  calls are synchronous; their return IS the completion signal.
- Do NOT narrate, summarise, or analyse between Skill calls. After
  each Skill call returns, the next action MUST be the next step's
  Skill / Bash call with no intermediate text.

**Bash is permitted only for** the git plumbing in step 0 and
step 5 (branch capture, fetch, checkout, rebase, branch deletion),
the lock-mtime check in step 2, and the one-line `printf >>
CLARIFICATIONS.md` writes that ship scheduler-failure notes ahead
of save.

**If a Skill call returns an error**, append a one-line note to
`_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
(timestamp + skill + error), proceed to step 4 save so the note
ships, then exit `partial`. Never fall back to manual execution.

---

## Steps

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
     `### Scheduler failures` with timestamp and cause, invoke
     `Skill(skill="ztn:save", args='--auto --message "scheduler: cannot reach main, owner action needed"')`,
     exit.
   - From here on, the working branch is `main`.

1. Pre-flight sync. Invoke `Skill(skill="ztn:sync-data")`.
   - Up-to-date or no `origin` → continue to step 2.
   - Conflict / non-fast-forward (skill returns blocked status) → STOP.
     Append a one-line note to `_system/state/CLARIFICATIONS.md` under
     `### Scheduler failures` with timestamp + cause, then invoke
     `Skill(skill="ztn:save", args='--auto --message "scheduler: sync conflict, owner action needed"')`.
     Exit.
   - Skill-tool error → CLARIFICATION + step 4 + exit `partial`.

2. Lock sanity (BEFORE invoking the skill). Use Bash to check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.resolve.lock`,
   `_sources/.agent-lens.lock`. Any lock present at tick start is by
   definition orphaned by a crashed prior run (this contract bans sub-
   agents; skills delete their lock in finally).
   - mtime older than 2h → delete the lock(s) and proceed to step 3.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 4 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Agent-lens. Invoke `Skill(skill="ztn:agent-lens", args="--all-due")`
   — exactly ONE Skill-tool call. The Invocation contract at the top
   of this file applies in full: no SKILL.md reading, no manual lens
   execution, no Agent/Task substitute for the Skill call (the skill
   itself forbids subagent dispatch by Step 4.5.3 — that's the
   skill's internal contract, separate from this scheduler one), no
   polling, no narration between this and step 4.
   - The skill internally reads `_system/registries/AGENT_LENSES.md`,
     filters lenses with `status: active` and that are due per their
     cadence, runs them sequentially (base-input first, lens-outputs-
     input last), writes outputs to `_system/agent-lens/{id}/{date}.md`
     — including any optional `## Action Hints` trailers — appends to
     `_system/state/agent-lens-runs.jsonl`, and logs to
     `_system/state/log_agent_lens.md`. Each observation entity
     carries the privacy trio per SKILL Step 5.9 (`origin: personal`,
     `audience_tags: []`, `is_sensitive: false`). All of that is the
     skill's responsibility, not yours.
   - Validator rejections, registry malformations, individual lens
     errors — all surface to `log_agent_lens.md` and CLARIFICATIONS
     as the skill designs. Do NOT pause for owner.
   - When the Skill call returns, your IMMEDIATE next action is the
     step-4 Skill call. No summary, no analysis, no «let me check
     git status» Bash calls.
   - If the Skill call errors / aborts on lock / repo state — append
     failure note to CLARIFICATIONS, then continue to step 4
     unconditionally so the note still ships.
   - Action Hints written by lenses here will be consumed by
     `/ztn:resolve-clarifications --auto-mode` later in the night
     (lint nightly tick dispatches it inline via Step 7.5). Lens
     production and resolve consumption sit in separate scheduler-
     agent contexts on purpose: the agent that judges proposals in
     Step A.2/A.3 has not just produced lens body output, which
     prevents confirmation bias on its own emissions.
   - Do NOT pass `--include-draft` or `--lens <id>` (manual single-
     lens and draft runs are owner-driven). The scheduled tick always
     runs `--all-due` only.

4. Save. Invoke `Skill(skill="ztn:save", args="--auto")`.
   - This step runs UNCONDITIONALLY after step 3 returns, regardless
     of step 3's outcome. Steps 0 and 2 have their own embedded save
     calls; this is the save call for the normal lens path.
   - Auto-proposed message lands with suffix `[scheduled]`. Engine
     refusal applies. No prompts, no force-push.
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
   - Default action on uncovered error: write CLARIFICATION + invoke
     `Skill(skill="ztn:save", args='--auto --message "scheduler: agent-lens uncovered error, owner action needed"')`
     to ship the note + exit with `partial` status.
   - Never silent failure. Never «log and pretend success».
   - Never pause for owner — the scheduler runs unattended; owner
     sees CLARIFICATIONS on next morning routine.

7. Forbidden in this run (in addition to the Invocation-contract
   prohibitions at the top):
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

Output: single-line status (success / partial / sync-blocked /
save-blocked / lens-locked) plus commit SHA if landed. No prose.
