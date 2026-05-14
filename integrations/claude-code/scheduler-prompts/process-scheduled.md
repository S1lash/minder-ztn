You are running an autonomous scheduled tick of `/ztn:process`. There is
no human in this loop. The contract below is load-bearing.

## Invocation contract (read first)

The ZTN skills in this prompt — `/ztn:sync-data`, `/ztn:process` — are
invoked **as slash commands in this same conversation**. Skills are
committed to the cloned repo at `.claude/skills/<name>/SKILL.md` (symlinks
into `integrations/claude-code/skills/<name>/`), so the runtime loads them
automatically — write the slash command literally as the next action and
it executes.

**Single-commit guarantee.** This tick produces **exactly one git commit
+ one git push**, both from `bash scripts/scheduler/finalize-tick.sh` at
Step 5. No other path in this prompt commits or pushes. `/ztn:save` is
**forbidden** in scheduler ticks — it is an owner-interactive tool. Any
intermediate `git commit`, `git push`, or `git add` outside the helper
scripts listed below is a contract violation.

**Hard prohibitions:**

- Do NOT invoke `/ztn:save` in any form. Use `finalize-tick.sh` at Step 5.
- Do NOT call `git commit`, `git push`, `git add` directly. The only
  allowed git mutations come from the helper scripts listed in the
  steps, with one explicit exception: Step 5b (MCP delivery fallback,
  runs only when finalize-tick reports `gh CLI not found in PATH`) uses
  one direct `git push origin "HEAD:<sandbox>"` per its strict per-step
  instructions. No other direct git/gh calls are authorized.
- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  re-implement its steps yourself with Bash / Read / Edit. Skills are
  loaded by the runtime — invoke via slash, never re-execute.
- Do NOT use the Agent / Task tool as a substitute for slash invocation.
  Each ZTN skill must enter through its slash form in this same
  conversation. (The skill's own internal Task dispatch — specifically
  `/ztn:process` Step 3 per-batch sub-agents — IS preserved; that fires
  inside the skill invocation as the skill's own architecture.)
- Do NOT poll locks, `git status`, or any state file to infer skill
  progress. Slash invocations are synchronous; their return IS completion.
- Do NOT narrate or summarise between steps. After each step returns, the
  next action is the next step's command with no intermediate prose.
- If the working tree looks "dirty across many categories" after Step 4,
  that is NORMAL output of `/ztn:process` + inline `/ztn:maintain`. Do
  NOT try to "group by theme" or "save progress" — Step 5's
  `finalize-tick.sh` collapses every dirty owner path into one commit.

**Bash is permitted only for the helper invocations explicitly listed
in the steps below.** Anything else is a contract violation.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" process-scheduled
```

Then exit `partial` immediately. Do not retry.

## Steps

1. `bash scripts/scheduler/pin-main.sh` — get on fresh `origin/main`,
   capture the starting sandbox branch, and best-effort recover any
   stranded scheduler work from prior ticks via PR-merge sweep.

2. `bash scripts/scheduler/lock-check.sh` — abort if any pipeline lock
   (process / maintain / lint / agent-lens / resolve) is recent (<2h).
   Stale locks (>2h) are removed automatically.

3. `/ztn:sync-data` — safe `git pull --rebase` with conflict-refuse
   semantics, ensures the local clone has the latest owner data from
   any other device that pushed since this Routine started.
   - Returns "blocked" / non-zero on uncommitted local changes or
     unresolvable conflict → run failure-handling above with cause
     `"sync-data blocked, owner action needed"`, exit `sync-blocked`.

4. `/ztn:process` — exactly ONE invocation. The skill runs the full
   pipeline including the inline `/ztn:maintain` tail. Per-batch
   sub-agent dispatch fires inside the skill (Step 3) — that is the
   skill's own architecture and IS preserved.
   - On skill error → run failure-handling, exit `partial`.
   - When the skill returns, the immediate next action is step 5 with
     no intermediate text.

5. `bash scripts/scheduler/finalize-tick.sh scheduler/process` — the
   single commit + delivery for this tick. The script auto-detects mode:
   - **LOCAL mode** (start branch = main) — single direct
     `git push origin main`.
   - **ROUTINES mode** (start branch = `claude/...` or other non-main) —
     push HEAD to the sandbox branch, `gh pr create --base main --head
     <sandbox>`, then `gh pr merge --squash --delete-branch`. End state:
     `main` updated with one squash commit on origin, sandbox branch
     deleted.

   Folds any unpushed `[scheduled]` commits from a previous partial tick
   into one commit with the current working-tree changes. Engine paths
   are filtered out (logged to CLARIFICATIONS). Refuses to touch
   non-scheduled commits if owner has manual work ahead of `origin/main`.

   - Exit code 0 → tick done. The next action is to print the final
     status line per «Output» below.
   - Exit code 2 → run failure-handling with cause
     `"finalize-tick failed"`, then print the final status line.

   **No manual push retries.** If `finalize-tick.sh` exits 2 because
   `git push`, `gh pr create`, or `gh pr merge` failed (HTTP 403,
   network, anything), do NOT invent a retry loop with direct git / gh
   calls. The script makes exactly one delivery attempt by design. If
   work could not be delivered, surface the failure via failure-handling
   and exit `partial`; the next tick processes fresh inbox state.

   **Exception — gh missing.** If exit 2 is specifically because
   `"gh CLI not found in PATH"` (Cloud Routines sandboxes don't ship
   gh), proceed to Step 5b INSTEAD of failure-handling.

5b. **MCP delivery fallback** — runs ONLY when Step 5's output contains
   `"gh CLI not found in PATH"` AND a local `[scheduled]` commit was
   created (Step 5 stdout has a `finalize-tick: committed <SHA> — …`
   line). Skip this step in all other failure modes.

   Do EXACTLY these actions in order. Do not deviate, do not retry on
   transient errors (let Step 5b's first failure trip failure-handling):

   1. Read sandbox branch name from `.scheduler-state/start-branch`
      (call it `SANDBOX_BRANCH`).
   2. `git push origin "HEAD:${SANDBOX_BRANCH}"` — push the local commit
      to the sandbox branch. If this fails → run failure-handling.
   3. Call the `github` MCP `create_pull_request` tool with:
      - `base`: `main`
      - `head`: `<SANDBOX_BRANCH>`
      - `title`: the commit subject from Step 5 stdout (the substring
        after `committed <SHA> — `, including the `[scheduled]` suffix)
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
   It exists because `finalize-tick.sh`'s gh-based delivery cannot run
   when gh is missing. Outside of «`gh CLI not found in PATH`» exit, do
   NOT invoke any github MCP tool from this prompt — failure-handling
   covers other failure modes.

## Forbidden in this tick

- `/ztn:lint`, `/ztn:agent-lens` — separate nightly schedules
- `/ztn:resolve-clarifications` — owner-only interactive; auto-mode is
  dispatched by lint Step 7.5, not from process
- `/ztn:save` in any form (owner-interactive only — scheduler uses
  `finalize-tick.sh`)
- `/ztn:update` — engine sync is owner-only
- direct `git commit`, `git push`, `git add` outside helper scripts
- `git push --force` of any kind
- creating a feature branch, worktree, or PR
- leaving any non-`main` branch behind on completion

## Output

Single-line status: `success` / `partial` / `sync-blocked`. If a commit
landed, append the SHA. No prose.
