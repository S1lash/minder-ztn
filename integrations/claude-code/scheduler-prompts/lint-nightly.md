You are running the autonomous nightly tick of `/ztn:lint`. There is no
human in this loop. The contract below is load-bearing.

## Invocation contract (read first)

The ZTN skills in this prompt — `/ztn:sync-data`, `/ztn:lint` — are
invoked **as slash commands in this same conversation**. Skills are
committed to the cloned repo at `.claude/skills/<name>/SKILL.md`, so the
runtime loads them automatically — write the slash command literally as
the next action and it executes. Step 0 verifies this layout resolved in
the clone before any slash invocation.

`/ztn:lint` Step 7.5 dispatches `/ztn:resolve-clarifications --auto-mode`
inline as part of its own pipeline; the resolve session in turn may
escalate ambiguous candidates to `/ztn:check-decision`. Both fire inside
the lint slash invocation as the skill's own architecture and ARE
preserved — your job is to invoke `/ztn:lint` once and let it run.

**Single-commit guarantee.** This tick produces **exactly one git commit
+ one git push**, both from `bash scripts/scheduler/finalize-tick.sh` at
Step 5. No other path in this prompt commits or pushes. `/ztn:save` is
**forbidden** in scheduler ticks. Any intermediate `git commit`,
`git push`, or `git add` outside the helper scripts listed below is a
contract violation.

**Hard prohibitions:**

- Do NOT invoke `/ztn:save` in any form. Use `finalize-tick.sh` at Step 5.
- Do NOT call `git commit`, `git push`, `git add` directly outside the
  listed helper scripts. **One explicit exception:** Step 5b (MCP
  delivery fallback, runs only when finalize-tick reports `gh CLI not
  found in PATH`) uses one direct `git push origin "HEAD:<sandbox>"`
  per its strict per-step instructions. No other direct git/gh calls
  are authorized.
- Do NOT open any `integrations/claude-code/skills/ztn-*/SKILL.md` and
  re-implement its steps with Bash / Read / Edit. Skills are loaded by
  the runtime — invoke via slash, never re-execute.
- Do NOT use the Agent / Task tool as a substitute for slash invocation.
  The skill's own internal sub-agent dispatch is preserved; the scheduler
  contract does not govern it.
- Do NOT `git commit --amend`, `--reset-author`, or otherwise rewrite an
  existing commit, and do NOT change git author/committer identity
  (`git config user.email/user.name`, `GIT_AUTHOR_*`, `GIT_COMMITTER_*`).
  A sandbox commit whose author shows as "unverified" is EXPECTED and
  harmless — delivery (`finalize-tick.sh` / Step 5b) does not depend on
  commit-author identity. Never amend to "fix" it; that is a contract
  violation and strands the tick.
- Do NOT poll locks or state files between steps. Slash invocations are
  synchronous; their return IS completion.
- Do NOT narrate or summarise between steps.
- If the working tree looks "dirty across many categories" after Step 4,
  that is NORMAL output of `/ztn:lint` + inline resolve dispatch. Do NOT
  try to "group by theme" or "save progress" — Step 5's `finalize-tick.sh`
  collapses every dirty owner path into one commit.

**Bash is permitted only for the helper invocations explicitly listed
in the steps below.** Anything else is a contract violation.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" lint-nightly
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
   (process / maintain / lint / agent-lens / resolve) is recent (<2h).
   Stale locks (>2h) are removed automatically.

3. `/ztn:sync-data` — safe `git pull --rebase` with conflict-refuse
   semantics.
   - Returns "blocked" / non-zero → run failure-handling with cause
     `"sync-data blocked, owner action needed"`, exit `sync-blocked`.

4. `/ztn:lint` — exactly ONE invocation. Runs the full pipeline:
   migration check → context load → Scans A–H → worklist apply → context
   store generation → Step 7.5 resolve-clarifications --auto-mode dispatch
   (which may cascade into /ztn:check-decision for ambiguous proposals).
   - On skill error → run failure-handling, exit `partial`.
   - When the skill returns, the immediate next action is step 5.

5. `bash scripts/scheduler/finalize-tick.sh scheduler/lint` — the single
   commit + delivery for this tick. Auto-detects mode:
   - **LOCAL mode** (start branch = main) — direct `git push origin main`.
   - **ROUTINES mode** (start branch = `claude/...` or other non-main) —
     push HEAD to sandbox branch, `gh pr create --base main --head
     <sandbox>`, then `gh pr merge --squash --delete-branch`. End state:
     `main` updated with one squash commit on origin, sandbox deleted.

   Folds any unpushed `[scheduled]` commits from a previous partial tick.
   Engine paths filtered out. Refuses to touch non-scheduled commits if
   owner has manual work ahead of `origin/main`.

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

- `/ztn:process`, `/ztn:agent-lens` — separate schedules
- `/ztn:resolve-clarifications` invoked DIRECTLY — only via lint Step 7.5
  dispatch (the lint skill handles it inline)
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
