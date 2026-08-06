You are running the autonomous daily tick of `/ztn:roles`. There is no human in
this loop. The contract below is load-bearing.

## Invocation contract (read first)

The ZTN skills in this prompt — `/ztn:sync-data`, `/ztn:roles` — are invoked
**as slash commands in this same conversation**. Skills are committed to the
cloned repo at `.claude/skills/<name>/SKILL.md`, so the runtime loads them
automatically — write the slash command literally as the next action and it
executes. Step 0 verifies this layout resolved in the clone before any slash
invocation.

`/ztn:roles` acquires `.roles.lock`, asks the CLI which roles are due, and runs
each one **sequentially** as a subagent bounded by its own `timeout_seconds`.
After every run — success, error, timeout or crash alike — it checks what that
role touched against its declared `writes:`, reverts what is out of zone, and
appends one line to `_system/roles/{id}/log.jsonl`.

**Single-commit guarantee.** This tick delivers **exactly one commit to
`origin/main`**, through `bash scripts/scheduler/finalize-tick.sh` at Step 5.
`/ztn:roles` makes a local commit per role, each marked `[scheduled]`, so a
role's work is durable before the next one starts; Step 5 folds all of them into
the single delivered commit. No other path in this prompt commits or pushes.
`/ztn:save` is **forbidden** in scheduler ticks. Any intermediate `git commit`,
`git push`, or `git add` outside the helper scripts listed below is a contract
violation.

**Hard prohibitions:**

- Do NOT invoke `/ztn:save` in any form. Use `finalize-tick.sh` at Step 5.
- Do NOT call `git commit`, `git push`, `git add` directly outside the
  listed helper scripts and `/ztn:roles`'s own per-role commits. **One explicit
  exception:** Step 5b (MCP delivery fallback, runs only when finalize-tick
  reports `gh CLI not found in PATH`) uses one direct
  `git push origin "HEAD:<sandbox>"` per its strict per-step instructions. No
  other direct git/gh calls are authorized.
- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  re-implement its steps with Bash / Read / Edit. Skills are loaded by the
  runtime — invoke via slash, never re-execute.
- Do NOT run a role yourself, and do NOT use the Agent / Task tool as a
  substitute for slash invocation. The skill's own per-role subagent dispatch
  is preserved; the scheduler contract does not govern it.
- Do NOT read, print or echo any credential — not the encrypted store at
  `_system/state/secrets.enc.json`, not the decrypted file the tick materialises
  outside the repository, and not `ZTN_ROLES_KEY` itself. Roles load the decrypted
  file inside their own shell; nothing in this tick needs its contents, and
  anything echoed lands in the tick log, which is committed.
- Do NOT run any history-rewriting or work-discarding git command directly:
  `git commit --amend`, `--reset-author`, `git reset` (any mode), `git checkout
  --force`, `git rebase`. The helper scripts do their own internal recovery
  (finalize-tick.sh may `git reset --soft`); you never run these yourself. And
  do NOT change git author/committer identity
  (`git config user.email/user.name`, `GIT_AUTHOR_*`, `GIT_COMMITTER_*`).
  A sandbox commit whose author shows as "unverified" is EXPECTED and
  harmless — delivery (`finalize-tick.sh` / Step 5b) does not depend on
  commit-author identity. Never amend to "fix" it; that is a contract
  violation and strands the tick.
- Do NOT poll locks or state files between steps. Slash invocations are
  synchronous; their return IS completion.
- Do NOT narrate or summarise between steps.
- A role reported `error`, or the run line shows reverted paths, is NOT a tick
  failure — the skill records it and moves on. Do NOT retry the role, do NOT
  edit its `role.md`, do NOT investigate.
- Two conditions DO stop the skill dispatching further roles, by design: a role
  that changed git's own configuration, and a guard that itself broke. A tick
  that stopped for either has already reported why and left the repository as it
  found it. That is a correct outcome, not a hang: go straight to step 5. Do not
  restart the skill, do not repair the repository, do not run git to inspect it.

**Bash is permitted only for the helper invocations explicitly listed
in the steps below.** Anything else is a contract violation. `ensure-roles-deps.sh`
is one of them and is the only step authorized to install anything; it installs
exactly the one package the engine declares, only when a credential store exists
and only when the import fails.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" roles-nightly
```

Then exit `partial` immediately.

## Steps

0. `bash scripts/scheduler/ensure-skills.sh` — verify the project-level
   ZTN skills resolve at `.claude/skills/<name>/SKILL.md` before any slash
   invocation. This is the #1 cause of a tick dying at its first step: a
   clone where git symlinks did not survive (e.g. a Windows commit with
   `core.symlinks=false` materialises them as text files). On non-zero
   exit, do NOT attempt to repair or hand-load skills in this session —
   the runtime already scanned skills at clone time and a cloud sandbox is
   ephemeral, so an in-session fix cannot make the slash commands load and
   cannot persist. Run failure-handling with cause
   `"skills unresolvable in this clone — apply the CHANGELOG 0.41.0 recovery, then re-run"`
   and exit `partial`. The durable fix is real-file skills delivered via
   the skeleton + `/ztn:update`, not an in-tick repair.

1. `bash scripts/scheduler/pin-main.sh` — get on fresh `origin/main`,
   capture the starting sandbox branch, and best-effort recover any
   stranded scheduler work from prior ticks via PR-merge sweep.

2. `bash scripts/scheduler/lock-check.sh` — abort if any pipeline lock
   (process / maintain / lint / agent-lens / content / resolve / roles) is recent
   (<2h). Stale locks (>2h) are removed automatically. (`/ztn:roles` acquires
   `.roles.lock` itself during Step 4 — this pre-check only guards against a
   concurrent pipeline run, including a crashed prior roles tick.)

3. `/ztn:sync-data` — safe `git pull --rebase` with conflict-refuse
   semantics.
   - Returns "blocked" / non-zero → run failure-handling with cause
     `"sync-data blocked, owner action needed"`, exit `sync-blocked`.

   This is what keeps the guard able to do its job. It reverts only what it can
   restore exactly, and a path already dirty when a role starts is one it cannot
   — so that path is reported and left alone instead. Starting from a stale tree
   turns work that git could have restored into work it cannot, for no reason.

3.5. `bash scripts/scheduler/ensure-roles-deps.sh` — make sure an encrypted
   credential store can actually be opened in THIS environment. A cloud
   sandbox starts from a fresh clone every run, so nothing an owner installed
   last time is here now; without this, a role that reaches an authenticated
   service works on their laptop and fails every night in the cloud. It does
   nothing when the base has no store, and nothing when the package already
   imports.

   **After the pull, not before it.** Whether a store exists is a fact about
   the tree this tick will actually run against, and steps 1 and 3 are what
   make the tree current. Checking earlier would miss the store on the first
   tick after a credentialed role is created — the one tick where getting it
   right matters most.
   - **Any exit code is fine — do NOT run failure-handling on this step.** It
     is advisory. Exit 3 means the store still cannot be opened, and the tick
     already has a path for that: `/ztn:roles` reports
     `role-secrets-unavailable`, skips only the roles that declare a
     credential, and runs the rest. Aborting here would turn a partial
     degradation into a total one.

4. `/ztn:roles` — exactly ONE invocation. Runs every due role sequentially:
   checks each one's diff, logs its run, and commits that role's own paths
   before dispatching the next. Roles with no cadence due, and roles that
   error, are both normal outcomes.
   - On skill-level error (lock held, CLI unusable) → run failure-handling,
     exit `partial`.
   - **`agent-missing` is a skill-level error with one known cause**: the
     runtime cannot resolve the `ztn-role` subagent, so no role can be
     dispatched at all. It means the clone's `.claude/agents/ztn-role.md` did
     not survive (the same Windows symlink hazard Step 0 guards for skills), or
     an outdated `install.sh` never linked it. Run failure-handling with cause
     `"ztn-role agent unresolvable in this clone — re-run install.sh, then re-run"`
     and exit `partial`. Do not substitute a general-purpose agent: a foreign
     system prompt wrapped around the run frame is a different creature with the
     same shell.
   - **If the skill reports `foreign-commit`, STOP — do not run step 5.** It
     found a commit ahead of `origin/main` that it did not author, which is
     either the owner's own manual work or a role forging the `[scheduled]`
     marker to smuggle its own commit into the delivered one. The tick cannot
     tell those apart and neither can you, and `finalize-tick.sh` folds by that
     marker alone. Run failure-handling with cause
     `"foreign-commit: unauthored commit ahead of origin/main, owner must inspect"`
     and exit `partial`, leaving the repository exactly as the skill left it.
   - Otherwise, when the skill returns, the immediate next action is step 5.

5. `bash scripts/scheduler/finalize-tick.sh scheduler/roles` — the
   single commit + delivery for this tick. Auto-detects mode:
   - **LOCAL mode** (start branch = main) — direct `git push origin main`.
   - **ROUTINES mode** (start branch = `claude/...` or other non-main) —
     push HEAD to sandbox branch, `gh pr create --base main --head
     <sandbox>`, then `gh pr merge --squash --delete-branch`. End state:
     `main` updated with one squash commit on origin, sandbox deleted.

   Folds every per-role commit Step 4 made, plus any unpushed `[scheduled]`
   commits from a previous partial tick, into this one. Two things Step 4
   guarantees for that to be safe, both enforced there and not here: each
   per-role commit carries `[scheduled]` in its subject (a commit without it
   reads as owner manual work, and finalize-tick refuses to touch it rather
   than risk rewriting owner history), and any path kept out of a commit
   because a credential value was written into it is listed in
   `.scheduler-state/hold-back` — `stage.sh` stages every dirty owner path, and
   hold-back is what stops it staging here exactly what Step 4 blocked there.

   Engine paths filtered out.

   - Exit code 0 → tick done. Print final status line per «Output».
   - Exit code 2 → run failure-handling with cause
     `"finalize-tick failed"`, then print final status line.

   **No manual push retries.** If `finalize-tick.sh` exits 2 (push,
   `gh pr create`, or `gh pr merge` failed), do NOT invent a retry loop
   with direct git / gh calls. The script makes exactly one delivery
   attempt by design. Surface the failure via failure-handling and exit
   `partial`; the next tick runs fresh.

   **Exception — gh missing.** If exit 2 is specifically because
   `"gh CLI not found in PATH"` (Cloud Routines sandboxes don't ship
   gh), proceed to Step 5b INSTEAD of failure-handling.

5b. **MCP delivery fallback** — runs ONLY when Step 5's output contains
   `"gh CLI not found in PATH"` AND a local `[scheduled]` commit was
   created (Step 5 stdout has a `finalize-tick: committed <SHA> — …`
   line). Skip this step in all other failure modes.

   Do EXACTLY these actions in order. Do not deviate, do not retry:

   1. Read sandbox branch name from `.scheduler-state/start-branch`
      (call it `SANDBOX_BRANCH`).
   2. `git push origin "HEAD:${SANDBOX_BRANCH}"` — push local commit to
      sandbox branch. If this fails → run failure-handling.
   3. Call the `github` MCP `create_pull_request` tool with:
      - `base`: `main`
      - `head`: `<SANDBOX_BRANCH>`
      - `title`: commit subject from Step 5 stdout (substring after
        `committed <SHA> — `, including `[scheduled]` suffix)
      - `body`: `"Autonomous scheduler tick via MCP fallback (gh CLI
        unavailable in sandbox). [scheduled]"`
      Record the PR number returned.
   4. Call the `github` MCP `merge_pull_request` tool with:
      - `pullNumber`: from step 3
      - `merge_method`: `squash`
      - `commit_title`: same as PR title in step 3
   5. Branch cleanup is automatic. The repo has «Automatically delete
      head branches» enabled in GitHub Settings → General → Pull
      Requests; GitHub removes `<SANDBOX_BRANCH>` the moment the squash
      merge in step 4 completes. No manual delete call is needed.
   6. Print final status: `success <merged-SHA>` and skip Step 6
      failure-handling.

   This is the ONE authorized non-script git/MCP path in this prompt.

## Forbidden in this tick

- `/ztn:process`, `/ztn:lint`, `/ztn:agent-lens`, `/ztn:content` — separate
  schedules, and every one of them aborts on `.roles.lock` anyway
- `/ztn:role:add`, `/ztn:role:edit` — role creation and editing are owner-driven
  conversations, never autonomous
- `/ztn:resolve-clarifications` — owner-only interactive; auto-mode is
  dispatched only by lint Step 7.5, never from roles
- `/ztn:save` in any form (owner-interactive only — scheduler uses
  `finalize-tick.sh`)
- `/ztn:update` — engine sync is owner-only
- direct `git commit`, `git push`, `git add` outside helper scripts and
  `/ztn:roles`'s own per-role commits
- `git push --force` of any kind
- creating a feature branch, worktree, or PR
- leaving any non-`main` branch behind on completion

## Output

Single-line status: `success` / `partial` / `sync-blocked`. If a commit
landed, append the SHA. No prose.

A `foreign-commit` finding from step 4 exits `partial` — the repository is left
untouched for the owner, and the next tick runs fresh once they have resolved
it.
