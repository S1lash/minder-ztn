You are running an autonomous nightly tick for /ztn:lint. There is no
human in this loop. Your contract:

## Invocation contract (read this first, it is load-bearing)

Every skill in this contract — `/ztn:sync-data`, `/ztn:lint`,
`/ztn:save` — is invoked **as a slash command in this same conversation**,
exactly once per skill. Write the slash command literally as the next
action; the harness routes it through whichever execution mechanism
the runtime supports (Skill tool, plugin handler, built-in command):

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
skill registry, and cloud-runner registries do not always include
`~/.claude/skills/` entries (documented failure modes 2026-05-06T19:10Z
and 2026-05-07T01:06Z). The slash command above is the stable,
runner-agnostic surface.

**Hard prohibitions, no exceptions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  execute its steps yourself with Bash / Read / Edit / Grep / Glob /
  Write. The skill machinery already exists; your job is to INVOKE
  it via the slash command, not RE-IMPLEMENT it. Manual
  re-implementation is the documented 2026-05-06T05:00Z lint-tick
  failure mode (70+ tool calls, agent budget exhausted before save,
  zero commits, zero pushes).
- Do NOT use the Agent / Task tool as a SUBSTITUTE for the slash
  invocation. The scheduler tick MUST enter each skill through its
  slash form in this same conversation, not by delegating
  «execute /ztn:<name> for me» to a child agent. The deadlock
  prohibition (parent holds `.lint.lock`, child polls for it,
  deadlock) is enforced by entering through the slash command, not
  by banning the skill's internal architecture. `/ztn:lint` itself
  does not dispatch internal subagents; its Step 7.5 invokes
  `/ztn:resolve-clarifications --auto-mode` via the same slash-
  invocation pattern.
- Do NOT poll `_sources/.lint.lock`, `_system/state/`, `git status`,
  or any other file to infer skill progress. Skill invocations are
  synchronous; their return IS the completion signal.
- Do NOT narrate, summarise, or analyse between skill invocations.
  After each skill returns, the next action MUST be the next step's
  skill / Bash call with no intermediate text.

**Bash is permitted only for:**

1. Git plumbing in step 0 and step 5 (branch capture, fetch,
   checkout, rebase, branch deletion, current-branch verification).
2. Lock-mtime check in step 2 (`stat`, `find -mmin`, `rm` of stale
   locks).
3. The procedures `SHIP_FAILURE_NOTE` and `CLEANUP_SANDBOX_BRANCH`
   defined below — copy-paste verbatim, including the script
   invocation. Do NOT improvise alternatives.

Bash for any other purpose is a contract violation.

---

## Procedures (referenced from steps)

### Procedure SHIP_FAILURE_NOTE(cause)

Append a one-line failure note under `### Scheduler failures` in
CLARIFICATIONS.md (idempotent on the section header), then attempt
to ship via `/ztn:save`, then fall back to the bash script if save
itself failed (skill not found / Unknown skill / save errored).

Replace `<CAUSE>` with a one-line cause string (no leading `-`,
no newlines).

```bash
CLAR=zettelkasten/_system/state/CLARIFICATIONS.md
grep -q '^### Scheduler failures$' "$CLAR" \
  || printf '\n### Scheduler failures\n' >> "$CLAR"
printf -- '- %s scheduler-lint: %s\n' \
  "$(date -u +%Y-%m-%dT%H:%MZ)" "<CAUSE>" >> "$CLAR"
```

Then run:

```
/ztn:save --auto --message "scheduler: <CAUSE>"
```

**If `/ztn:save` returns «Unknown skill» / skill-not-found / any
error**, immediately run the fallback (do not retry the slash):

```bash
bash scripts/scheduler-fallback-save.sh "scheduler: <CAUSE>"
```

The fallback script mirrors `/ztn:save --auto`: stages all dirty
owner-data, refuses engine paths (logs them as additional drift
note), commits with `[scheduled, save-fallback]` suffix, pushes to
`origin/main`. Exit 0 = shipped or no-op; exit 2 = git error
(report to stderr, exit `partial`).

### Procedure CLEANUP_SANDBOX_BRANCH

Always run before exiting the tick (success OR failure path).
Removes the sandbox branch the runtime started us on, if any.

```bash
if [ -n "${START_BRANCH:-}" ] && [ "$START_BRANCH" != "main" ]; then
  git branch -D "$START_BRANCH" 2>/dev/null || true
  git push origin --delete "$START_BRANCH" 2>/dev/null || true
fi
```

Best-effort; failures here are silent.

---

## Steps

0. Force operation on `main`. The runtime may have started this run on a
   sandbox branch (e.g. `claude/<random>`). All work in this tick MUST
   land on `main` directly — no feature branches, no PRs, no leftover
   branches anywhere.
   - Capture the starting branch:
     `START_BRANCH=$(git rev-parse --abbrev-ref HEAD)`.
   - `git fetch origin main`.
   - `git checkout main` (create-or-track if needed:
     `git checkout -B main origin/main`).
   - `git pull --rebase origin main` — rebase variant on purpose:
     sandbox-local commits on `main` (e.g. an unpushed commit from a
     previous failed tick) get replayed on top of `origin/main`
     instead of blocking on non-fast-forward. Force-push remains
     forbidden; rebase only re-orders local-only commits.
   - **If checkout fails on a dirty working tree, or rebase encounters
     conflicts:**
     - `git rebase --abort 2>/dev/null || true`
     - Run procedure `SHIP_FAILURE_NOTE("cannot reach main: <short cause>")`.
     - Run procedure `CLEANUP_SANDBOX_BRANCH`.
     - Exit `partial`.
   - From here on, the working branch is `main`.

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` configured → continue to step 2.
   - **Conflict / non-fast-forward (skill returns blocked status):**
     - Run procedure `SHIP_FAILURE_NOTE("sync conflict, owner action needed")`.
     - Run procedure `CLEANUP_SANDBOX_BRANCH`.
     - Exit `sync-blocked`.
   - **Skill invocation error (Unknown skill / abort):**
     - Run procedure `SHIP_FAILURE_NOTE("ztn:sync-data: <error short form>")`.
     - Run procedure `CLEANUP_SANDBOX_BRANCH`.
     - Exit `partial`.

2. Lock sanity (BEFORE invoking the lint skill). Use Bash to check
   `_sources/.processing.lock`, `_sources/.maintain.lock`,
   `_sources/.lint.lock`, `_sources/.resolve.lock`,
   `_sources/.agent-lens.lock`. Any lock present at tick start is by
   definition orphaned by a crashed prior run (this contract bans
   sub-agents; skills delete their lock in finally).
   - mtime older than 2h → `rm` the lock(s) and proceed to step 3.
   - mtime younger than 2h → assume a concurrent owner session may
     be active. Do NOT touch the lock.
     - Run procedure `SHIP_FAILURE_NOTE("recent lock at tick start, possible concurrent owner session: <which lock>")`.
     - Run procedure `CLEANUP_SANDBOX_BRANCH`.
     - Exit `partial`.

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
     step-4 invocation. No summary, no analysis, no «let me check
     what happened» Bash calls.
   - **If the skill errors / aborts / reports lock-blocked:**
     - Run procedure `SHIP_FAILURE_NOTE("ztn:lint error: <short>")`.
     - Run procedure `CLEANUP_SANDBOX_BRANCH`.
     - Exit `partial`.

4. Save. Run `/ztn:save --auto`.
   - This step runs UNCONDITIONALLY after step 3 returns successfully.
     (Failure paths in steps 0/1/2/3 already shipped via
     SHIP_FAILURE_NOTE and exited.)
   - Auto-proposed message lands with suffix `[scheduled]`. Engine
     refusal applies. No prompts, no force-push.
   - **If `/ztn:save` errors with «Unknown skill» / skill-not-found
     / abort:**
     - Run `bash scripts/scheduler-fallback-save.sh "scheduler: lint tick auto-save"`.
     - Exit code 0 from the script → continue to step 5.
     - Exit code 2 → run procedure `SHIP_FAILURE_NOTE("save fallback failed: git error, owner action needed")`.
     - Continue to step 5 regardless.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.

5. Cleanup.
   - Verify current branch is still `main`:
     `[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ]` — if not,
     run `SHIP_FAILURE_NOTE("post-save not on main, branch=<X>")`
     and continue to CLEANUP_SANDBOX_BRANCH anyway.
   - Run procedure `CLEANUP_SANDBOX_BRANCH`.
   - Never leave any `claude/*` or other ad-hoc branch on `origin` or
     locally.

6. Forbidden in this run (in addition to the Invocation-contract
   prohibitions at the top):
   - `/ztn:process` (its own daytime schedule handles this)
   - `/ztn:maintain` (runs inline inside process; not relevant here)
   - `/ztn:agent-lens` (separate scheduler tick at 03:00 — its lens
     hints are READ here via lint Step 7.5 dispatch, not produced here)
   - `/ztn:resolve-clarifications` interactive (owner-only — note
     that `--auto-mode` IS run, but only as lint's internal dispatch
     in step 3; you do not invoke it directly)
   - `/ztn:update` (engine sync is owner-only)
   - any interactive prompt to the human
   - `--include-engine` on save
   - `git push --force`
   - creating a feature branch, worktree, or PR for the work
   - leaving any non-`main` branch behind on completion

Output: single-line status (success / partial / sync-blocked) plus
commit SHA if landed. No prose.
