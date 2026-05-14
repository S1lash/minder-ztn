# scheduler-prompts/

Copy-paste prompt bodies for the autonomous ZTN loop. Each `.md` file
in this directory contains **only** the prompt — no headers, no meta,
no fences. Open the file, select all, paste into your scheduler.

For full design rationale, cadence, and plug-in instructions see
`docs/scheduling.md`.

## Files

| File | What it runs | Recommended cadence |
|---|---|---|
| `process-scheduled.md` | `/ztn:sync-data` → `/ztn:process` (maintain inline) → `finalize-tick.sh scheduler/process` | ≥ 3× per day, e.g. cron `0 9,14,19 * * *` |
| `agent-lens-nightly.md` | `/ztn:sync-data` → `/ztn:agent-lens --all-due` → `finalize-tick.sh scheduler/agent-lens` | 1× nightly, e.g. cron `0 3 * * *` |
| `lint-nightly.md` | `/ztn:sync-data` → `/ztn:lint` (Step 7.5 dispatches `/ztn:resolve-clarifications --auto-mode` inline) → `finalize-tick.sh scheduler/lint` | 1× nightly, e.g. cron `0 5 * * *` |

## Delivery model — two modes with an MCP fallback

`finalize-tick.sh` auto-detects how to deliver the tick's commit to
`origin/main`:

**LOCAL mode** — start branch is `main` (local cron, launchd, GitHub
Actions running with full push rights). Single `git push origin main`.

**ROUTINES mode** — start branch is a sandbox ref (`claude/...`). Cloud
Routines' git proxy refuses direct push to `main`. The script instead:

1. `git push origin HEAD:<sandbox-branch>` (proxy-allowed)
2. `gh pr create --base main --head <sandbox-branch>`
3. `gh pr merge --squash --delete-branch`

End state: `main` updated with one squash commit on origin, sandbox
branch deleted on origin.

**MCP fallback** — Anthropic Cloud Routines sandboxes don't ship `gh`.
When `finalize-tick.sh` exits 2 with `"gh CLI not found in PATH"`, the
scheduler prompts have an explicit Step 5b that:

1. Pushes the local commit to the sandbox branch via plain `git push`.
2. Calls the `github` MCP `create_pull_request` tool.
3. Calls the `github` MCP `merge_pull_request` tool with squash method.
4. Best-effort sandbox-branch cleanup via three fallbacks.

Step 5b is the **only** authorized non-script git/MCP path in the
prompts. It runs only on the specific «gh missing» exit and only after
`finalize-tick.sh` has produced a local `[scheduled]` commit.

## Sandbox-branch cleanup

The Cloud Routines proxy blocks both `git push origin main` AND
`git push origin --delete <branch>` (both return HTTP 403). The
`github` MCP server typically has create + merge tools but no
`delete_branch`. So in-tick deletion is best-effort.

The **load-bearing cleanup layer is GitHub's repo setting
«Automatically delete head branches»** (Settings → General → Pull
Requests). When enabled, GitHub itself removes the head branch the
moment its PR is merged (squash, merge, or rebase). Owner must enable
this once per repository; the scheduler relies on it.

With the setting on, every tick's flow ends with «PR merged → branch
auto-deleted by GitHub». No script-side recovery is needed and no
scheduler-created branch should ever linger on origin.

## Partial-tick handling

If a tick aborts between push and PR-merge, the sandbox branch on
origin holds the unmerged commit. There is no automatic recovery —
the next tick processes fresh state from `_sources/inbox/` and
produces a new commit. The stranded sandbox branch is harmless (work
content is re-derivable from inputs) and can be removed manually by
the owner if it accumulates: `git push origin --delete <branch>` from
a local clone.

If an agent driving a scheduler tick invents its own retry loop with
direct `git push` or `gh` calls, that is a contract violation — the
prompts forbid it explicitly.

## Single-commit guarantee

Every scheduler tick produces **exactly one commit on `origin/main`**.
This replaces the old `/ztn:save --auto` step which was producing N
commits per tick (one per "phase" the agent felt like grouping).

- `scripts/scheduler/stage.sh` — staging-only helper (idempotent). May
  be called any number of times during a tick; commits nothing.
- `scripts/scheduler/finalize-tick.sh <tag>` — single commit + delivery
  (LOCAL: direct push, ROUTINES: push-to-sandbox + PR + squash-merge).
  Folds any unpushed `[scheduled]` commits from a previous partial tick.
  Refuses to rewrite history if owner has manual non-scheduled commits
  ahead of `origin/main` (no force-push, ever).

`/ztn:save` is **owner-interactive only**. Scheduler prompts must never
invoke it (slash form or otherwise) and must never call `git commit` /
`git push` / `git add` / `gh` directly outside the helper scripts.

There is no `maintain` prompt — maintain runs inline at the tail of
`/ztn:process`. There is no separate `resolve-clarifications` prompt
— `--auto-mode` is dispatched by lint Step 7.5 inline; interactive
mode is owner-only by design.

**Why two nightly entries (lens separate from lint+resolve).** The
most quality-sensitive isolation is between agent-lens and resolve:
agent-lens stages produce `## Action Hints`, and resolve A.2/A.3
judges them. If both ran in the same scheduler-agent context, the
agent that produced lens bodies would also vote on its own proposals
— maximum confirmation bias. So agent-lens is its own tick.

Lint and resolve, by contrast, do ortogonal reasoning: lint pattern-
matches invariant violations (people-bare-name, archive-note-missing,
manifest-schema), resolve judges «would the experienced owner
approve this NOW». Chaining them in one tick accumulates context
but the bleed is small. The operational simplicity of one tick (lint
runs invariant cleanup → immediately consumes the resulting
CLARIFICATIONS + fresh lens hints in resolve A.2/A.3) outweighs the
marginal quality dip.

Order matters: agent-lens at 03:00 (runs due lenses, may emit
`## Action Hints`); lint at 05:00 — lint cleans invariants, then
Step 7.5 dispatches resolve to consume hints + new CLARIFICATIONS
+ existing queue, and either auto-applies safe additive proposals
or queues residue for owner.

**Manifest emission per tick.** `/ztn:process` Step 5.5 writes both
`{batch_id}.md` (markdown report) and `{batch_id}.json` (machine-
parseable JSON manifest for the Minder consumer; schema in
`minder-project/strategy/ARCHITECTURE.md` §4.5). `/ztn:maintain`
Step 6.6 writes its own `{batch_id}-maintain.json`. Both files commit
through `finalize-tick.sh` at the tail of the scheduler tick.

**Concept and audience layer is fully autonomous.** Format issues
never reach the CLARIFICATIONs queue from these layers — engine
resolves via `_common.py` normalisers + lint Scan A.7 autofix. The
scheduler tick should NOT see new owner-facing items from these
classes (records / notes / hubs / profile concept-name and audience-
tag format). If owner sees one, that's a bug in the producer-side
guard, not a normal autonomy boundary.

## Plug-in — Claude Code `/schedule`

The path of least friction. Two routines:

```
/schedule
  name: ztn-process
  cron: 0 9,14,19 * * *
  prompt: <paste body of process-scheduled.md>
```

```
/schedule
  name: ztn-agent-lens
  cron: 0 3 * * *
  prompt: <paste body of agent-lens-nightly.md>
```

```
/schedule
  name: ztn-lint
  cron: 0 5 * * *
  prompt: <paste body of lint-nightly.md>
```

Each routine runs in a fresh agent — the prompt body is fully
self-contained, no extra context required.

## Plug-in — non-Claude-Code schedulers

cron + `claude --print`, launchd, GitHub Actions on a private fork:
same prompt bodies. Ensure the agent has:

- filesystem access to the ZTN repo working tree
- configured git identity for autonomous push
- authentication to `origin` (SSH key in the runner / token in env)
- a way to surface non-zero exit (logs, email, pager) — the prompts
  exit non-zero on sync-blocked / save-blocked

## After `/ztn:update`

These prompt bodies are engine-shipped, so `/ztn:update` keeps the
files current as the engine evolves. Claude Code's `/schedule`,
however, holds the prompt verbatim — engine updates do **not**
propagate to running schedules automatically. After any `/ztn:update`
that touched files in this directory:

1. Open the changed prompt file.
2. Re-paste its body into the corresponding `/schedule` routine.

`/ztn:update` already includes a follow-up reminder when this
directory changes.

## Contract guarantees

What the scheduler will NEVER do, regardless of which prompt is run:

- `git push --force` (of any kind, including `--force-with-lease`)
- direct `git commit`, `git push`, `git add` outside helper scripts
- `/ztn:save` in any form (owner-interactive only)
- staging engine paths (scripts/, integrations/, docs/, `_system/docs/`,
  `_system/scripts/`, `.engine-manifest.yml`, etc.) — `finalize-tick.sh`
  filters them and logs to CLARIFICATIONS
- `/ztn:resolve-clarifications` (owner-only)
- `/ztn:update` (owner-only)
- pause and ask the human

Anything that would be a question becomes a row in
`_system/state/CLARIFICATIONS.md` (under `### Scheduler failures` for
terminal errors). Owner reviews via `/ztn:resolve-clarifications` on
the next morning routine.

## Cadence guidance

Recommended:

- `ztn-process` — minimum 3× per day (09/14/19 local). Higher
  frequency is fine; `/ztn:process` is a no-op when
  `_sources/inbox/` is empty. Back-to-back ticks <5 min apart are
  wasteful (Claude Code rate / token budget).
- `ztn-agent-lens` (03:00 local) and `ztn-lint` (05:00 local) —
  two nightly ticks. Agent-lens runs first in its own scheduler-
  agent context (lens production isolated from resolve consumption,
  no confirmation bias). Lint runs ~2 h later, dispatches
  `/ztn:resolve-clarifications --auto-mode` via Step 7.5 inline so
  the same tick that cleans invariants also consumes fresh hints +
  CLARIFICATIONS. Owner wakes up to fully committed queue + lens
  outputs + resolve session log.
