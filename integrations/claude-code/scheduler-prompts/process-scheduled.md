You are running an autonomous scheduled tick of `/ztn:process`. There is
no human in this loop. The contract below is load-bearing.

## Invocation contract (read first)

Every ZTN skill in this prompt — `/ztn:sync-data`, `/ztn:process`,
`/ztn:save` — is invoked **as a slash command in this same conversation**.
Skills are committed to the cloned repo at `.claude/skills/<name>/SKILL.md`
(symlinks into `integrations/claude-code/skills/<name>/`), so the runtime
loads them automatically — write the slash command literally as the next
action and it executes.

**Hard prohibitions:**

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

**Bash is permitted only for the helper invocations explicitly listed
in the steps below.** Anything else is a contract violation.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" process-scheduled
bash scripts/scheduler/cleanup-sandbox.sh
```

Then exit `partial` immediately. Do not retry.

## Steps

1. `bash scripts/scheduler/pin-main.sh` — get on fresh `origin/main` and
   capture the starting sandbox branch for cleanup.

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

5. `/ztn:save --auto --tag scheduler/process` — engine-aware commit +
   push to `origin/main` with `[scheduled]` suffix and `scheduler/process:`
   tag prefix on the commit message.
   - On "Unknown skill" / skill error → fall back to:
     `bash scripts/scheduler/save.sh "scheduler/process: routine save"`.
     Exit code 0 from the script → continue to step 6.
     Exit code 2 → run failure-handling with cause `"save fallback failed"`,
     continue to step 6 anyway.

6. `bash scripts/scheduler/cleanup-sandbox.sh` — best-effort delete of the
   starting sandbox branch (local + remote). Errors here are silent.

## Forbidden in this tick

- `/ztn:lint`, `/ztn:agent-lens` — separate nightly schedules
- `/ztn:resolve-clarifications` — owner-only interactive; auto-mode is
  dispatched by lint Step 7.5, not from process
- `/ztn:update` — engine sync is owner-only
- `--include-engine` on save
- `git push --force` of any kind
- creating a feature branch, worktree, or PR
- leaving any non-`main` branch behind on completion

## Output

Single-line status: `success` / `partial` / `sync-blocked`. If a commit
landed, append the SHA. No prose.
