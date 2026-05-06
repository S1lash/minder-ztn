You are running an autonomous nightly tick for /ztn:lint. There is no
human in this loop. Your contract:

## Invocation contract (read this first, it is load-bearing)

Every skill in this contract — `/ztn:sync-data`, `/ztn:lint`,
`/ztn:save` — is invoked **exclusively via the Skill tool**, exactly
once per skill, e.g.:

```
Skill(skill="ztn-lint")
Skill(skill="ztn-save", args="--auto")
```

**Skill-tool name format — DASH, not COLON.** The Skill-tool registry
keys skills by their installed directory name (`ztn-lint`,
`ztn-save`, `ztn-sync-data`), not by the slash-command form
(`/ztn:lint`). Calling `Skill(skill="ztn:lint")` returns «Unknown
skill» and aborts the tick (failure mode documented
2026-05-06T19:10Z). Always use `ztn-<name>` with a dash.

That IS what «inline» means in this prompt: the Skill tool runs the
skill in this same conversation, same context, no sub-agent. NOT
that you re-implement the skill yourself.

**Hard prohibitions, no exceptions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  execute its steps yourself with Bash / Read / Edit / Grep / Glob /
  Write. The skill machinery already exists; your job is to INVOKE
  it, not RE-IMPLEMENT it. Manual re-implementation is the
  documented 2026-05-06 lint-tick failure mode (70+ tool calls,
  agent budget exhausted before step 4 save, zero commits, zero
  pushes). This rewrite exists to prevent that failure from
  recurring.
- Do NOT use the Agent / Task tool as a SUBSTITUTE for invoking the
  skill via the Skill tool. The scheduler tick MUST enter each skill
  through `Skill(skill="ztn-<name>", ...)`, not by delegating
  «execute /ztn:<name> for me» to a child agent. The deadlock
  prohibition (parent holds `.lint.lock`, child polls for it,
  deadlock) is enforced by entering through Skill, not by banning
  the skill's internal architecture. `/ztn:lint` itself does not
  dispatch internal subagents; its Step 7.5 invokes
  `/ztn:resolve-clarifications --auto-mode` via the same Skill tool
  pattern, not via Agent / Task.
- Do NOT poll `_sources/.lint.lock`, `_system/state/`, `git status`,
  or any other file to infer skill progress. Skill calls are
  synchronous; their return IS the completion signal.
- Do NOT narrate, summarise, or analyse between Skill calls. After
  each Skill call returns, the next action MUST be the next step's
  Skill / Bash call with no intermediate text.

**Bash is permitted only for** the git plumbing in step 0 and
step 5 (branch capture, fetch, checkout, rebase, branch deletion),
and for the one-line `printf >> CLARIFICATIONS.md` writes that
ship scheduler-failure notes ahead of save.

**If a Skill call returns an error**, append a one-line note to
`_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
(timestamp + skill + error), then proceed to step 4 save so the note
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
     `Skill(skill="ztn-save", args='--auto --message "scheduler: cannot reach main, owner action needed"')`,
     exit.
   - From here on, the working branch is `main`.

1. Pre-flight sync. Invoke `Skill(skill="ztn-sync-data")`.
   - Up-to-date or no `origin` → continue to step 2.
   - Conflict / non-fast-forward (skill returns blocked status) → STOP.
     Append one-line note to `_system/state/CLARIFICATIONS.md` under
     `### Scheduler failures` (timestamp + cause), then invoke
     `Skill(skill="ztn-save", args='--auto --message "scheduler: sync conflict, owner action needed"')`.
     Exit.
   - Skill-tool error → CLARIFICATION + step 4 + exit `partial`.

2. Lock sanity (BEFORE invoking the lint skill). Use Bash to check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.resolve.lock`,
   `_sources/.agent-lens.lock`. Since this contract bans sub-agents and
   skills delete their lock in finally, any lock present at tick start
   is by definition orphaned by a crashed prior run.
   - mtime older than 2h → delete the lock(s) and proceed to step 3.
   - mtime younger than 2h → assume a concurrent owner session may be
     active. Append CLARIFICATION «recent lock at tick start, possible
     concurrent owner session» under `### Scheduler failures`, then
     jump to step 4 (commit the CLARIFICATION) and exit cleanly. Do
     NOT touch the lock.

3. Lint. Invoke `Skill(skill="ztn-lint")` — exactly ONE Skill-tool
   call. The Invocation contract at the top of this file applies in
   full: no SKILL.md reading, no manual scan execution, no
   Agent/Task substitute for the Skill call, no polling, no
   narration between this and step 4.
   - The skill internally auto-fixes the obvious, surfaces the non-
     obvious to CLARIFICATIONS, runs Step 7.5 dispatch of
     `/ztn:resolve-clarifications --auto-mode` inline, generates Lint
     Context Store summaries, writes `log_lint.md`, runs Scan A.7
     (concept + audience + privacy-trio autofix). All of that is the
     skill's responsibility, not yours.
   - Queue size is irrelevant to whether this tick continues — owner
     reviews CLARIFICATIONS tomorrow via `/ztn:resolve-clarifications`.
   - When the Skill call returns, your IMMEDIATE next action is the
     step-4 Skill call. No summary, no analysis, no «let me check what
     happened» Bash calls.
   - If the Skill call errors / aborts / reports lock-blocked — append
     one-line note to CLARIFICATIONS, continue to step 4 unconditionally
     so the note ships.

4. Save. Invoke `Skill(skill="ztn-save", args="--auto")`.
   - This step runs UNCONDITIONALLY after step 3 returns, regardless
     of step 3's outcome. Steps 0 and 2 have their own embedded save
     calls; this is the save call for the normal lint path.
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

6. Forbidden in this run (in addition to the Invocation-contract
   prohibitions at the top):
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:agent-lens` (separate scheduler tick earlier in the
     night — its lens hints are READ here via lint Step 7.5
     dispatch, not produced here)
   - `/ztn:resolve-clarifications` interactive (owner-only — note
     that `--auto-mode` IS run, but only as lint's internal dispatch
     in step 3; you do not invoke it directly)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion

Output: single-line status (success / partial / sync-blocked /
save-blocked / lint-locked) plus commit SHA if landed. No prose.
