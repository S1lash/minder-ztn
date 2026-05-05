# scheduler-prompts/

Copy-paste prompt bodies for the autonomous ZTN loop. Each `.md` file
in this directory contains **only** the prompt — no headers, no meta,
no fences. Open the file, select all, paste into your scheduler.

For full design rationale, cadence, and plug-in instructions see
`docs/scheduling.md`.

## Files

| File | What it runs | Recommended cadence |
|---|---|---|
| `process-scheduled.md` | `/ztn:sync-data` → `/ztn:process` (maintain inline) → `/ztn:save --auto` | ≥ 3× per day, e.g. cron `0 9,14,19 * * *` |
| `nightly-combined.md` | `/ztn:sync-data` → `/ztn:agent-lens --all-due` → `/ztn:lint` → `/ztn:save --auto` | 1× nightly, e.g. cron `0 3 * * *` |

There is no `maintain` prompt — maintain runs inline at the tail of
`/ztn:process`. There is no separate `agent-lens` or `lint` prompt —
they run as steps 3 and 4 of the nightly chain so lens Action Hints
written by step 3 are consumed immediately by step 4's lint-dispatched
`/ztn:resolve-clarifications --auto-mode` (no 24h gap). There is no
interactive `resolve-clarifications` prompt — that flow is owner-only
by design. The `agent-lens` step runs nightly because the skill itself
filters lenses by per-lens cadence — nightly ≠ nightly lens runs.

**Manifest emission per tick.** `/ztn:process` Step 5.5 writes both
`{batch_id}.md` (markdown report) and `{batch_id}.json` (machine-
parseable JSON manifest for the Minder consumer; schema in
`minder-project/strategy/ARCHITECTURE.md` §4.5). `/ztn:maintain`
Step 6.6 writes its own `{batch_id}-maintain.json`. Both files commit
through `/ztn:save --auto` normally.

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
  name: ztn-nightly
  cron: 0 3 * * *
  prompt: <paste body of nightly-combined.md>
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

- `git push --force`
- `--include-engine` on `/ztn:save`
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
- `ztn-nightly` — once per night, after the day's last process tick.
  03:00 local recommended — far enough from evening processing to
  avoid lock contention, far enough from morning that the
  CLARIFICATIONS queue + lens outputs + resolve session log are
  fresh when owner sits down. The nightly chain takes ~30-45 min
  end-to-end (agent-lens 5-15 min + lint Pass 1 ~3 min + resolve
  --auto-mode dispatch ~30-90s LLM + save ~5s).
