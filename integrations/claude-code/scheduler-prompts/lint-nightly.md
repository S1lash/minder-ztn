You are running an autonomous nightly tick for /ztn:lint. There is no
human in this loop. Your contract:

## Invocation contract (read this first, it is load-bearing)

Every skill in this contract — `/ztn:sync-data`, `/ztn:lint`,
`/ztn:save` — is invoked **as a slash command in this same conversation**,
exactly once per skill. Write the slash command literally as the next
action, the harness routes it through the appropriate execution
mechanism (Skill tool, plugin handler, or built-in command — the
runtime decides):

```
/ztn:sync-data
/ztn:lint
/ztn:save --auto
```

That IS what «inline» means in this prompt: the skill runs in this
same conversation, same context, no sub-agent. NOT that you
re-implement the skill yourself by reading SKILL.md and executing
its steps with Bash / Read / Edit.

**Do not invent your own invocation syntax.** Do not write
`Skill(skill="ztn-lint")` or `Skill(skill="ztn:lint")` as a literal
call — those are runtime-internal forms that depend on the session's
skill registry (cloud-runner registries do not always include
`~/.claude/skills/` entries; this is the documented 2026-05-06T19:10Z
and 2026-05-07T01:06Z failure mode). The slash command above is the
stable, runner-agnostic surface.

**Hard prohibitions, no exceptions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  execute its steps yourself with Bash / Read / Edit / Grep / Glob /
  Write. The skill machinery already exists; your job is to INVOKE
  it via the slash command, not RE-IMPLEMENT it. Manual
  re-implementation is the documented 2026-05-06T05:00Z lint-tick
  failure mode (70+ tool calls, agent budget exhausted before step 4
  save, zero commits, zero pushes).
- Do NOT use the Agent / Task tool as a SUBSTITUTE for the slash
  invocation. The scheduler tick MUST enter each skill through its
  slash form in this same conversation, not by delegating
  «execute /ztn:<name> for me» to a child agent. The deadlock
  prohibition (parent holds `.lint.lock`, child polls for it,
  deadlock) is enforced by entering through the slash command, not
  by banning the skill's internal architecture. `/ztn:lint` itself
  does not dispatch internal subagents; its Step 7.5 invokes
  `/ztn:resolve-clarifications --auto-mode` via the same slash-
  invocation pattern, not via Agent / Task.
- Do NOT poll `_sources/.lint.lock`, `_system/state/`, `git status`,
  or any other file to infer skill progress. Skill invocations are
  synchronous; their return IS the completion signal.
- Do NOT narrate, summarise, or analyse between skill invocations.
  After each skill returns, the next action MUST be the next step's
  skill / Bash call with no intermediate text.

**Bash is permitted only for** the git plumbing in step 0 and
step 5 (branch capture, fetch, checkout, rebase, branch deletion),
and for the one-line `printf >> CLARIFICATIONS.md` writes that
ship scheduler-failure notes ahead of save.

**If a slash invocation returns an error** (skill not found, abort,
etc.), append a one-line note to `_system/state/CLARIFICATIONS.md`
under `### Scheduler failures` (timestamp + skill + error), then
proceed to step 4 save so the note ships, then exit `partial`. If
save itself errors too, fall back to a direct `git add + commit +
push` of the CLARIFICATIONS file only — that is the ONLY allowed
manual fallback, and only for shipping the failure note. Never fall
back to manual execution of the failed skill itself.

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
     `### Scheduler failures` with timestamp and cause, run
     `/ztn:save --auto --message "scheduler: cannot reach main, owner action needed"`,
     exit.
   - From here on, the working branch is `main`.

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue to step 2.
   - Conflict / non-fast-forward (skill returns blocked status) → STOP.
     Append one-line note to `_system/state/CLARIFICATIONS.md` under
     `### Scheduler failures` (timestamp + cause), then run
     `/ztn:save --auto --message "scheduler: sync conflict, owner action needed"`.
     Exit.
   - Skill invocation error → CLARIFICATION + step 4 + exit `partial`.

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

3. Lint. Run `/ztn:lint` — exactly ONE slash invocation. The Invocation
   contract at the top of this file applies in full: no SKILL.md
   reading, no manual scan execution, no Agent/Task substitute, no
   polling, no narration between this and step 4.
   - The skill internally auto-fixes the obvious, surfaces the non-
     obvious to CLARIFICATIONS, runs Step 7.5 dispatch of
     `/ztn:resolve-clarifications --auto-mode` inline, generates Lint
     Context Store summaries, writes `log_lint.md`, runs Scan A.7
     (concept + audience + privacy-trio autofix). All of that is the
     skill's responsibility, not yours.
   - Queue size is irrelevant to whether this tick continues — owner
     reviews CLARIFICATIONS tomorrow via `/ztn:resolve-clarifications`.
   - When the skill returns, your IMMEDIATE next action is the
     step-4 invocation. No summary, no analysis, no «let me check what
     happened» Bash calls.
   - If the skill errors / aborts / reports lock-blocked — append
     one-line note to CLARIFICATIONS, continue to step 4 unconditionally
     so the note ships.

4. Save. Run `/ztn:save --auto`.
   - This step runs UNCONDITIONALLY after step 3 returns, regardless
     of step 3's outcome. Steps 0 and 2 have their own embedded save
     calls; this is the save call for the normal lint path.
   - Auto-proposed message lands with suffix `[scheduled]`. Engine
     refusal applies. No prompts, no force-push.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.
   - **Save-skill unavailable fallback (last resort, only for shipping
     CLARIFICATIONS).** If `/ztn:save` itself errors with «skill not
     found» or similar registry failure, AND the only dirty file is
     `zettelkasten/_system/state/CLARIFICATIONS.md`, you MAY do a
     direct `git add zettelkasten/_system/state/CLARIFICATIONS.md &&
     git commit -m "scheduler: <one-line cause> [scheduled]" && git
     push origin main`. This is the ONLY case where direct git is
     allowed. Do not extend this fallback to other dirty files.

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
