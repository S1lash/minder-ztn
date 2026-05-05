# Scheduling — autonomous ZTN ticks

ZTN is designed to run **multiple times a day, every day**, without you
in the loop for the routine path. This doc describes the canonical
scheduling setup, the assumptions baked into it, and how to plug it in.

## The canonical loop

Three scheduled jobs. No more.

| Job | Cadence | Skill chain | Prompt source |
|---|---|---|---|
| `ztn-process` | ≥ 3× per day | `/ztn:sync-data` → `/ztn:process` (maintain inline) → `/ztn:save --auto` | `integrations/claude-code/scheduler-prompts/process-scheduled.md` |
| `ztn-lint` | 1× nightly (03:00) | `/ztn:sync-data` → `/ztn:lint` → `/ztn:save --auto` | `integrations/claude-code/scheduler-prompts/lint-nightly.md` |
| `ztn-agent-lens` | 1× nightly (03:30) | `/ztn:sync-data` → `/ztn:agent-lens --all-due` → `/ztn:save --auto` | `integrations/claude-code/scheduler-prompts/agent-lens-nightly.md` |
| `ztn-resolve-auto` | 1× nightly (04:00) | `/ztn:sync-data` → `/ztn:resolve-clarifications --auto-mode` → `/ztn:save --auto` | `integrations/claude-code/scheduler-prompts/resolve-auto.md` |

The three nightly ticks run back-to-back at 03:00 / 03:30 / 04:00 in
order so that lint cleans up invariant violations first, agent-lens
runs against a tidy base, and resolve-auto consumes fresh lens hints
~30 min after they land. Each tick uses its own scheduler-agent
context — separate sessions, no accumulated reasoning across the
three quality-critical LLM-judgement skills. The agent-lens step
fires nightly but the skill itself filters lenses by per-lens
cadence; most nights agent-lens runs zero or one lens; on
weekly/biweekly anchors it runs the due ones.

There is no `ztn-maintain` schedule — maintain runs inline as the tail
of `/ztn:process`. There is no `ztn-resolve-clarifications` schedule —
the owner reviews the queue manually; that is the human-in-loop hinge
of the whole system. There is no `ztn-agent-lens-add` schedule — lens
creation is owner-driven (wizard-style); see
`integrations/claude-code/skills/ztn-agent-lens-add/SKILL.md`.

## Opinionated assumptions

These are not configurable. If you need a different model, the
scheduler prompts are not for you yet.

- **Process at least daily, usually multiple times.** ZTN's value
  comes from cadence. Less than once a day means transcripts pile up
  and the macro picture lags reality.
- **Lint at night, after the day's last process tick.** Lint reads the
  day's accumulated state. Running it before processing is wasteful;
  running it concurrently with processing risks lock contention.
- **Every scheduled run autocommits and pushes.** Without push,
  multi-device use breaks. Without autocommit, the working tree
  accumulates uncommitted scheduler output and the next manual
  `/ztn:save` becomes ambiguous.
- **Ambiguity goes to CLARIFICATIONS, not to you.** The whole
  CLARIFICATIONS mechanism exists for this exact case. A scheduled
  run that pauses on a question is broken — it just hangs the agent
  until timeout. CLARIFICATIONS is the async hand-off.
- **Engine drift is never resolved by the scheduler.** `--auto` on
  `/ztn:save` refuses engine paths. If you edited engine files locally,
  the scheduler will leave them dirty and surface a CLARIFICATIONS
  note. Run `/ztn:update` (or revert) yourself.

## What the scheduler will NEVER do

| Operation | Why not |
|---|---|
| `git push --force` | Data-loss risk. Push rejection means «sync next tick», not «overwrite remote». |
| `--include-engine` on save | Engine is owned upstream. Local edits to engine paths are an owner concern. |
| `/ztn:resolve-clarifications` | Resolution is the human-in-loop step by design. Auto-resolution defeats the purpose. |
| `/ztn:update` | Engine sync needs owner attention (VERSION delta, migrations, divergence resolution). |
| Pause and ask the owner | No human in this loop. Anything that would be a question becomes a CLARIFICATIONS row. |
| Skip commit on «small» changes | Every tick commits, even routine state-only churn. Predictability beats minimalism. |

## Plug-in — Claude Code `/schedule`

The recommended path. Three routines:

```
/schedule
  name: ztn-process
  cron: 0 9,14,19 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/process-scheduled.md>
```

```
/schedule
  name: ztn-lint
  cron: 0 3 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/lint-nightly.md>
```

```
/schedule
  name: ztn-agent-lens
  cron: 30 3 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/agent-lens-nightly.md>
```

```
/schedule
  name: ztn-resolve-auto
  cron: 0 4 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/resolve-auto.md>
```

The prompt bodies are self-contained — fresh agent per run, no extra
context loaded. They are engine-shipped, so `/ztn:update` keeps your
prompts current as the engine evolves. After a `/ztn:update` that
changed either prompt file, re-paste the updated body into `/schedule`
(detection of «schedule prompts changed» is on the `/ztn:update`
follow-up checklist).

## Plug-in — non-Claude-Code schedulers

cron + `claude --print`, launchd, GitHub Actions on a private fork:
same prompt bodies. Ensure:

- Filesystem access to the ZTN repo working tree.
- Configured git identity for autonomous push.
- Authentication to `origin` (SSH key in the runner / token in env).
  Concrete setup options (passphrase-less SSH, PAT-baked remote URL,
  platform-managed credentials) — see `docs/onboarding.md` §9.
- A way to surface non-zero exit (logs, email, pager) — the prompt
  bodies exit non-zero on sync-blocked / save-blocked.

## Owner morning routine

The other half of the loop. Whatever happened overnight + during the
day lands in CLARIFICATIONS by morning.

1. `/ztn:resolve-clarifications` — pre-syncs against `origin`, walks
   you through the queue one theme at a time, refreshes derived views
   (`/ztn:regen-constitution`, `/ztn:maintain`) when your resolutions
   touched constitution / registries, and reminds you to save.
2. `/ztn:save` (interactive, not `--auto`) — commit + push your
   resolutions when the skill prompts you.

That's it. The scheduler covers ingestion + slop-catching; you cover
judgement + resolution.

## Why this shape (instead of N tiny jobs or one big one)

- **One big nightly job.** Tried mentally: would mean transcripts
  dropped at 10am don't surface until 03:00 the next day. ZTN is a
  thinking aid; latency >12h kills the feedback loop.
- **Per-skill schedules (process, maintain, lint, resolve, agent-lens,
  agent-lens-add).** Tried mentally: maintain has no independent
  cadence (it tails process); resolve and agent-lens-add must not be
  autonomous (owner judgement / wizard interview); process / lint /
  agent-lens cover the autonomous surface area entirely. Three jobs
  is the right minimum.
- **Process every hour.** Wasteful for typical input rates and burns
  Claude Code budget; revisit only if you start dropping transcripts
  faster than the recommended 3× cadence drains them.
