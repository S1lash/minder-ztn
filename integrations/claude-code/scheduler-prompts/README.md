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
| `lint-nightly.md` | `/ztn:sync-data` → `/ztn:lint` → `/ztn:save --auto` | 1× nightly, e.g. cron `0 3 * * *` |
| `agent-lens-nightly.md` | `/ztn:sync-data` → `/ztn:agent-lens --all-due` → `/ztn:save --auto` | 1× nightly, e.g. cron `30 3 * * *` |
| `resolve-auto.md` | `/ztn:sync-data` → `/ztn:resolve-clarifications --auto-mode` → `/ztn:save --auto` | 1× nightly, e.g. cron `0 4 * * *` |

There is no `maintain` prompt — maintain runs inline at the tail of
`/ztn:process`. There is no interactive `resolve-clarifications`
prompt — that flow is owner-only by design.

**Why three nightly entries instead of one chained tick.** The three
nightly skills (`lint`, `agent-lens`, `resolve-clarifications
--auto-mode`) each perform LLM-driven judgement work: lint over
invariant scans, agent-lens over per-lens thinker/structurer pairs,
and resolve over Step A.2 curation + A.3 sweep. Chaining them in one
scheduler tick would accumulate context across all three, with
later steps reading their inputs through whatever reasoning the
earlier steps already laid down — anchoring bias, contextual bleed,
sub-optimal cache utilisation. Splitting into three back-to-back
ticks gives each LLM-judgement step a fresh scheduler-agent context.
The 30-minute spacing is enough for one tick to commit and push
before the next pulls; lens hints written at 03:30 are still fresh
at 04:00 (vs 21h gap if separated by full days). The cost is three
cron entries instead of one — accepted in exchange for materially
better judgement quality on the system's most context-sensitive
LLM calls.

Order matters: lint at 03:00 (cleans up invariant violations first
so agent-lens sees a tidy base), agent-lens at 03:30 (runs due
lenses, may emit `## Action Hints`), resolve-auto at 04:00 (consumes
fresh hints + clarifications, judges against full owner context).

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
  name: ztn-lint
  cron: 0 3 * * *
  prompt: <paste body of lint-nightly.md>
```

```
/schedule
  name: ztn-agent-lens
  cron: 30 3 * * *
  prompt: <paste body of agent-lens-nightly.md>
```

```
/schedule
  name: ztn-resolve-auto
  cron: 0 4 * * *
  prompt: <paste body of resolve-auto.md>
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
- `ztn-lint` (03:00 local), `ztn-agent-lens` (03:30 local),
  `ztn-resolve-auto` (04:00 local) — three back-to-back nightly ticks
  in this order. Each ~5-15 min, each in its own scheduler-agent
  context for clean LLM judgement. Owner sits down to a fresh queue +
  fresh lens outputs + fresh resolve session log all committed before
  morning routine.
