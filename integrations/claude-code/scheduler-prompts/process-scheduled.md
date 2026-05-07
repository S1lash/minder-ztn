You are running an autonomous scheduled tick. There is no human in this
loop. Your contract:

## Invocation contract (read this first, it is load-bearing)

Every skill in this contract — `/ztn:sync-data`, `/ztn:process`,
`/ztn:save` — is invoked **as a slash command in this same conversation**,
exactly once per skill. Write the slash command literally as the next
action, the harness routes it through the appropriate execution
mechanism (Skill tool, plugin handler, or built-in command — the
runtime decides):

```
/ztn:sync-data
/ztn:process
/ztn:save --auto
```

That IS what «inline» means in this prompt: the skill runs in this
same conversation, same context, no sub-agent. NOT that you
re-implement the skill yourself by reading SKILL.md and executing
its steps with Bash / Read / Edit.

**Do not invent your own invocation syntax.** Do not write
`Skill(skill="ztn-process")` or `Skill(skill="ztn:process")` as a
literal call — those are runtime-internal forms that depend on the
session's skill registry (cloud-runner registries do not always
include `~/.claude/skills/` entries; this is the documented
2026-05-06T19:10Z and 2026-05-07T01:06Z failure mode). The slash
command above is the stable, runner-agnostic surface.

**Hard prohibitions, no exceptions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  execute its steps yourself with Bash / Read / Edit / Grep / Glob /
  Write. The skill machinery already exists; your job is to INVOKE
  it via the slash command, not RE-IMPLEMENT it. Manual
  re-implementation exhausts the agent turn budget before the save
  step (lint-tick failure mode documented 2026-05-06T05:00Z).
- Do NOT use the Agent / Task tool as a SUBSTITUTE for the slash
  invocation. The scheduler tick MUST enter each skill through its
  slash form in this same conversation, not by delegating
  «execute /ztn:<name> for me» to a child agent. The deadlock
  prohibition (parent holds `.processing.lock`, child polls for it,
  deadlock) is enforced by entering through the slash command, not
  by banning the skill's internal architecture.
- The skill's own internal sub-agent dispatch — specifically
  `/ztn:process` Step 3 per-batch full-pipeline subagents — is
  load-bearing for quality (trust unit = Opus + sufficient context
  per batch) and IS preserved. That dispatch fires inside the skill
  invocation as the skill's own architecture; this scheduler contract
  does not govern it.
- Do NOT poll `_sources/.processing.lock`, `_system/state/`,
  `git status`, or any other file to infer skill progress. Skill
  invocations are synchronous; their return IS the completion signal.
- Do NOT narrate, summarise, or analyse between skill invocations.
  After each skill returns, the next action MUST be the next step's
  skill / Bash call with no intermediate text.

**Bash is permitted only for** the git plumbing in step 0 and
step 4 (branch capture, fetch, checkout, rebase, branch deletion),
the lock-mtime check in step 2a, and the one-line `printf >>
CLARIFICATIONS.md` writes that ship scheduler-failure notes ahead
of save.

**If a slash invocation returns an error** (skill not found,
abort, etc.), append a one-line note to
`_system/state/CLARIFICATIONS.md` under `### Scheduler failures`
(timestamp + skill + error), proceed to step 3 save so the note
ships, then exit `partial`. If save itself errors too, fall back
to a direct `git add + commit + push` of the CLARIFICATIONS file
only — that is the ONLY allowed manual fallback, and only for
shipping the failure note. Never fall back to manual execution of
the failed skill itself.

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
     note to `_system/state/CLARIFICATIONS.md` under a
     `### Scheduler failures` section with timestamp and cause, run
     `/ztn:save --auto --message "scheduler: cannot reach main, owner action needed"`
     (this commits + pushes on whatever branch we're on so the note
     still ships), then exit.
   - From here on, the working branch is `main`. All subsequent steps
     operate on `main` only.

1. Pre-flight sync. Run `/ztn:sync-data`.
   - Up-to-date or no `origin` → continue to step 2.
   - Conflict / non-fast-forward (skill returns blocked status) → STOP.
     Append a one-line note to `_system/state/CLARIFICATIONS.md` under
     a `### Scheduler failures` section with timestamp + short cause,
     then run `/ztn:save --auto --message "scheduler: sync conflict, owner action needed"`
     so the note itself ships to remote. Exit.
   - Skill invocation error → CLARIFICATION + step 3 + exit `partial`.

2. Process.
   - **2a. Lock sanity (BEFORE invoking the skill).** Use Bash to check
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
   - **2b. Run `/ztn:process`** — exactly ONE slash invocation. The
     Invocation contract at the top of this file applies in full:
     no SKILL.md reading, no manual step execution, no Agent/Task
     substitute (the skill's internal Step 3 per-batch subagent
     dispatch is preserved and fires inside the skill invocation),
     no polling, no narration between this and step 3.
     - Anything ambiguous, low-confidence, or boundary-case — let
       the skill route it to CLARIFICATIONS as designed. Do NOT
       pause for owner input. CLARIFICATIONS growing is the expected
       steady state.
     - `/ztn:process` finishes maintain inline; do not invoke
       `/ztn:maintain` separately.
     - When the skill returns, your IMMEDIATE next action is
       the step-3 invocation. No summary, no analysis, no «let me
       check git status» Bash calls.
     - If the skill errors / aborts on lock / repo state —
       append failure note to CLARIFICATIONS as in step 1, then
       continue to step 3 unconditionally so the note still gets
       committed.
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
   - This step runs UNCONDITIONALLY after step 2 returns, regardless
     of step 2's outcome. Steps 0 and 2a have their own embedded save
     calls; this is the save call for the normal process path.
   - Commits with the auto-proposed message (suffix `[scheduled]`)
     and pushes to `origin`. No prompts.
   - Engine paths are refused as always; if any are dirty, that's an
     owner-only situation and the scheduler must surface it via
     CLARIFICATIONS, not bypass via `--include-engine`.
   - If push rejects (someone pushed first) — commit stays local; the
     next scheduled tick pre-syncs and resolves. Do NOT force-push.
   - **Save-skill unavailable fallback (last resort, only for shipping
     CLARIFICATIONS).** If `/ztn:save` itself errors with «skill not
     found» or similar registry failure, AND the only dirty file is
     `zettelkasten/_system/state/CLARIFICATIONS.md`, you MAY do a
     direct `git add zettelkasten/_system/state/CLARIFICATIONS.md &&
     git commit -m "scheduler: <one-line cause> [scheduled]" && git
     push origin main`. This is the ONLY case where direct git is
     allowed. Do not extend this fallback to other dirty files —
     route those through the next tick.

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

5. Forbidden in this run (in addition to the Invocation-contract
   prohibitions at the top):
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

Output: a single-line status (success / partial / sync-blocked /
save-blocked) plus the commit SHA if a commit landed. No prose.
