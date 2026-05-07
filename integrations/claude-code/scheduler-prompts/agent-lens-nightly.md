You are running the autonomous nightly tick of `/ztn:agent-lens`. There
is no human in this loop. The contract below is load-bearing.

## Invocation contract (read first)

Every ZTN skill in this prompt — `/ztn:sync-data`, `/ztn:agent-lens`,
`/ztn:save` — is invoked **as a slash command in this same conversation**.
Skills are committed to the cloned repo at `.claude/skills/<name>/SKILL.md`
(symlinks into `integrations/claude-code/skills/<name>/`), so the runtime
loads them automatically — write the slash command literally as the next
action and it executes.

`/ztn:agent-lens --all-due` iterates all lenses whose cadence has elapsed
and runs each through its two-stage thinker→structurer pipeline as the
skill's own architecture. Outputs land in `_system/agent-lens/{id}/{date}.md`
plus the runs index `_system/state/agent-lens-runs.jsonl`.

**Hard prohibitions:**

- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  re-implement its steps with Bash / Read / Edit. Skills are loaded by
  the runtime — invoke via slash, never re-execute.
- Do NOT use the Agent / Task tool as a substitute for slash invocation.
  The skill's own internal sub-agent dispatch (per-lens thinker /
  structurer) is preserved; the scheduler contract does not govern it.
- Do NOT poll locks or state files between steps. Slash invocations are
  synchronous; their return IS completion.
- Do NOT narrate or summarise between steps.

**Bash is permitted only for the helper invocations explicitly listed
in the steps below.** Anything else is a contract violation.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" agent-lens-nightly
bash scripts/scheduler/cleanup-sandbox.sh
```

Then exit `partial` immediately.

## Steps

1. `bash scripts/scheduler/pin-main.sh` — get on fresh `origin/main` and
   capture the starting sandbox branch for cleanup.

2. `bash scripts/scheduler/lock-check.sh` — abort if any pipeline lock
   (process / maintain / lint / agent-lens / resolve) is recent (<2h).
   Stale locks (>2h) are removed automatically.

3. `/ztn:sync-data` — safe `git pull --rebase` with conflict-refuse
   semantics.
   - Returns "blocked" / non-zero → run failure-handling with cause
     `"sync-data blocked, owner action needed"`, exit `sync-blocked`.

4. `/ztn:agent-lens --all-due` — exactly ONE invocation. Iterates all
   due lenses sequentially, writes outputs + machine index. Lens-level
   failures degrade to clarifications and do not abort the whole run.
   - On skill-level error (registry unreadable, etc.) → run
     failure-handling, exit `partial`.
   - When the skill returns, the immediate next action is step 5.

5. `/ztn:save --auto --tag scheduler/agent-lens` — engine-aware commit +
   push to `origin/main` with `[scheduled]` suffix and
   `scheduler/agent-lens:` tag prefix on the commit message.
   - On "Unknown skill" / skill error → fall back to:
     `bash scripts/scheduler/save.sh "scheduler/agent-lens: nightly save"`.
     Exit code 0 → continue to step 6.
     Exit code 2 → run failure-handling with cause `"save fallback failed"`,
     continue to step 6 anyway.

6. `bash scripts/scheduler/cleanup-sandbox.sh` — best-effort delete of the
   starting sandbox branch.

## Forbidden in this tick

- `/ztn:process`, `/ztn:lint` — separate schedules
- `/ztn:resolve-clarifications` — owner-only interactive; auto-mode is
  dispatched only by lint Step 7.5, never from agent-lens
- `/ztn:update` — engine sync is owner-only
- `--include-engine` on save
- `git push --force` of any kind
- creating a feature branch, worktree, or PR
- leaving any non-`main` branch behind on completion

## Output

Single-line status: `success` / `partial` / `sync-blocked`. If a commit
landed, append the SHA. No prose.
