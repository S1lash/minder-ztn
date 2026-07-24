You are running the autonomous nightly tick of `/ztn:roles`. There
is no human in this loop. The contract below is load-bearing.

## Invocation contract (read first)

The ZTN skills in this prompt — `/ztn:sync-data`, `/ztn:roles` —
are invoked **as slash commands in this same conversation**. Skills are
committed to the cloned repo at `.claude/skills/<name>/SKILL.md`, so the
runtime loads them automatically — write the slash command literally as
the next action and it executes. Step 0 verifies this layout resolved in
the clone before any slash invocation.

`/ztn:roles --all-due` iterates all roles whose cadence has elapsed
and runs each through its tick→persist pipeline as the
skill's own architecture. Outputs land in `_system/roles/{id}/state.md`
plus the runs index `_system/state/roles-runs.jsonl`.

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
- Do NOT open `integrations/claude-code/skills/ztn-*/SKILL.md` and
  re-implement its steps with Bash / Read / Edit. Skills are loaded by
  the runtime — invoke via slash, never re-execute.
- Do NOT use the Agent / Task tool as a substitute for slash invocation.
  The skill's own internal sub-agent dispatch (per-lens thinker /
  structurer) is preserved; the scheduler contract does not govern it.
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
- If the working tree looks "dirty across many lens outputs" after Step
  4, that is NORMAL. Do NOT try to "group by lens" or "save progress" —
  Step 5's `finalize-tick.sh` collapses every dirty owner path into one
  commit.

**Bash is permitted only for the helper invocations explicitly listed
in the steps below** — plus the `/ztn:roles` skill's own `_system/...` script
steps and the `cd zettelkasten && …` prefix they run under (see «Working
directory»). Anything else is a contract violation.

## Working directory (read first)

Two roots are in play — keep them straight so no step wastes effort locating
files. The layout is FIXED; do not go discovering it.

- **Repo root** — the routine's starting directory. Holds `scripts/scheduler/*.sh`
  and `.claude/skills/`. Run every `bash scripts/scheduler/...` helper (Steps 0–2
  and 5) and every slash invocation from here.
- **ZTN base** = `zettelkasten/` under the repo root. Holds `_system/`, the role
  dirs, and the pipeline Python. The `/ztn:roles` skill resolves its `_system/...`
  script paths relative to THIS base, so run its script steps from the base —
  prefix each with `cd zettelkasten && …`. The shell CWD resets to the repo root
  between commands, so the prefix goes on EACH script step, not once. The base is
  ALWAYS `zettelkasten/`; never spend a step searching for `_system/scripts`.

`/ztn:sync-data` (Step 3) operates on git from the repo root — no `cd` needed.

## Secrets — the master key (fill per-instance; needed only for acting / auth roles)

A role that reaches an AUTHENTICATED external system (an act tool, or any tool with a
`secret://` credential) resolves its token from the encrypted blob using the secrets
master key. That key must be in this routine's **environment** as
`ZTN_SECRET_MASTER_KEY` for the autonomous tick to resolve it — the tick STAGES acts
(a baseline read) and PROBES external state, both of which need the credential.

Set it **once, per-instance**, out of band from git (never commit a real key). The key
the concierge printed when you wired your first secret must be in this routine's
**environment** — put it in the **routine's own env / secret config** as
`ZTN_SECRET_MASTER_KEY`. That is the ONLY reliable carrier: the `/ztn:roles` skill runs
its Python in separate subprocesses, and a shell `export` does NOT persist across them —
so the durable routine-env var is what every helper + subprocess actually inherits.

Fill these in your routine's env / secret config (per-instance, NEVER committed). Both
are OFF until you set them, so a missing key never acts by accident:

```
# --- roles routine env / secret config (per-instance, never committed) ---
# 1. Master key — needed for a role that reads/acts on an AUTHENTICATED system.
#    Paste the key the concierge printed when you wired your first secret:
ZTN_SECRET_MASTER_KEY=<paste your master key here>

# 2. Autonomous acting — set to 1 ONLY if you want acting roles to make their board
#    changes on their own on schedule (no per-act approval). Leave UNSET to keep every
#    act owner-confirmed. This is your explicit consent: an autonomous role acts in the
#    un-caged runtime on YOUR say-so (a prompt-injection in content it reads could steer
#    an act, bounded to the mandate's surface). Only a role you DIALED `autonomy:
#    autonomous` is affected; advisory roles still stage regardless.
ZTN_ROLES_AUTONOMOUS_ACK=1
```

(An in-prompt `export ZTN_SECRET_MASTER_KEY="…"` only helps a runtime where all of a
tick's steps share ONE shell — it is not a substitute for the routine-env var.)
**If you run no acting / secret-bearing roles, leave BOTH unset:** secret resolution
honest-degrades (the tool is skipped, its refusal is surfaced, the tick still completes)
and every act stays owner-confirmed — the routine is never blocked by a missing key.

## Failure handling

Any non-zero exit from a bash helper, or any skill error / "Unknown skill"
response, triggers this exit path:

```
bash scripts/scheduler/ship-failure-note.sh "<one-line cause>" roles-nightly
```

Then exit `partial` immediately.

## Steps

0. **Secrets key (acting / auth roles only).** `ZTN_SECRET_MASTER_KEY` must live in the
   routine's env/secret config (see «Secrets» above) — that is what the skill's
   subprocesses inherit; a shell `export` here does not reach them. Nothing to do in this
   step if it is set there (or unset by design — the tick honest-degrades). Then:
   `bash scripts/scheduler/ensure-skills.sh` — verify the project-level
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
   (process / maintain / lint / agent-lens / content / resolve / roles) is recent (<2h).
   Stale locks (>2h) are removed automatically.

3. `/ztn:sync-data` — safe `git pull --rebase` with conflict-refuse
   semantics.
   - Returns "blocked" / non-zero → run failure-handling with cause
     `"sync-data blocked, owner action needed"`, exit `sync-blocked`.

4. `/ztn:roles --all-due` — exactly ONE invocation. Iterates all
   due roles sequentially, writes outputs + machine index. Its `_system/...`
   script steps run from the `zettelkasten/` base (prefix `cd zettelkasten && …` —
   see «Working directory»); the base is fixed, do not search for it. Role-level
   failures degrade to clarifications and do not abort the whole run.
   - On skill-level error (registry unreadable, etc.) → run
     failure-handling, exit `partial`.
   - When the skill returns, the immediate next action is step 5.

5. `bash scripts/scheduler/finalize-tick.sh scheduler/roles` — the
   single commit + delivery for this tick. Auto-detects mode:
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

- `/ztn:process`, `/ztn:lint`, `/ztn:agent-lens` — separate schedules
- `/ztn:resolve-clarifications` — owner-only interactive; auto-mode is
  dispatched only by lint Step 7.5, never from agent-lens
- `/ztn:save` in any form (owner-interactive only — scheduler uses
  `finalize-tick.sh`)
- `/ztn:update` — engine sync is owner-only
- direct `git commit`, `git push`, `git add` outside helper scripts
- `git push --force` of any kind
- creating a feature branch, worktree, or PR
- leaving any non-`main` branch behind on completion

## Output

Single-line status: `success` / `partial` / `sync-blocked`. If a commit
landed, append the SHA. If the tick staged owner-approval work — a
`role-act-confirm` or `role-cold-start` in the run summary — append
`(N awaiting approval)` so a friend scanning the routine log sees the queue is
waiting on them (the acts/drafts are staged, not lost; approve via the morning
routine). No other prose.
