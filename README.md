# minder-ztn

Personal-knowledge engine: voice transcripts → structured Zettelkasten
+ a Claude Code agent stack that reads, writes, and integrates the
notes for you.

This is the **public skeleton**. Clone it, run bootstrap, review the
clarifications queue, drop voice transcripts, run `/ztn:process`, and
you have a system that:

- Files transcripts into records (meetings/observations) and PARA notes
- Tracks people, projects, tags, hubs, open threads, calendar, tasks
- Captures principles and trade-offs into a personal constitution
- Surfaces outside-view observations via agent-lenses (stalled threads,
  drift between stated values and actual behaviour, cross-domain
  connections you didn't notice, system-meta digest)
- Stays consistent under nightly lint passes
- Survives context resets — Claude reads `_system/` to rebuild state

## What you get

- `integrations/claude-code/` — rules, slash commands, and skills you
  install into `~/.claude/` with one script.
- `zettelkasten/_system/` — system docs, registries, runtime state.
- `zettelkasten/_system/scripts/` — Python pipeline (constitution
  regen, evidence-trail compactor, candidate buffers, concept and
  audience format autofix, batch JSON manifest emission, tests).
- `zettelkasten/{0_constitution,1_projects,…,6_posts}/` — empty PARA
  layout you populate as you go.
- `scripts/sync_engine.sh` — pull engine updates from upstream
  without touching your data.

## Quickstart

```bash
# 1. Create your own ZTN from this template
gh repo create my-ztn --template <maintainer>/minder-ztn --private --clone
cd my-ztn

# 2. Install the Claude Code integration (rules, commands, skills → ~/.claude/)
./integrations/claude-code/install.sh

# 3. Open the repo in Claude Code and run bootstrap:
#    /ztn:bootstrap
#
# 4. Review what bootstrap surfaced for your decision:
#    /ztn:resolve-clarifications
#
# 5. From here on — the daily flow:
#    /ztn:process            (voice transcripts → notes)
#    /ztn:lint               (consistency sweep — autofix + surface non-obvious)
#    /ztn:agent-lens         (outside-view observations on cadence)
#    /ztn:agent-lens-add     (create a new agent-lens via wizard)
#    /ztn:source-add         (register a new input-source type declaratively)
#    /ztn:resolve-clarifications  (walk the owner-decision queue)
#    /ztn:save               (commit + push)
#    /ztn:sync-data          (pull on a second device)
#    /ztn:update             (pull engine updates from upstream)
```

`install.sh` is the only manual shell step. After it, every operation
lives inside Claude Code.

`/ztn:bootstrap` populates SOUL.md / PEOPLE / PROJECTS and seeds the
clarifications queue with anything ambiguous it found in your inputs;
`/ztn:resolve-clarifications` is the canonical owner-facing path to
walk that queue (skill clusters items by theme, pre-forms hypotheses,
applies confirmed resolutions in place).

Full walkthrough with optional steps (drop an existing backlog, write
an identity profile, set up scheduled processing) —
`docs/onboarding.md`.

## Run it on a schedule

Three engine-shipped scheduler prompts in
`integrations/claude-code/scheduler-prompts/` cover the autonomous
surface so you only show up for resolution:

- `process-scheduled.md` — ingest new transcripts (≥ 3× per day)
- `agent-lens-nightly.md` — runs due lenses (skill filters by
  per-lens cadence; lenses may emit `## Action Hints`); 1× nightly
  at 03:00
- `lint-nightly.md` — invariant scans + Step 7.5 dispatches
  `/ztn:resolve-clarifications --auto-mode` inline (consumes fresh
  lens hints + new clarifications, auto-applies safe additive
  proposals, queues residue); 1× nightly at 05:00

Lens production is one scheduler tick, lint+resolve cleanup is
another — the most quality-sensitive split (agent-lens vs resolve)
stays at the scheduler level.

Paste each body into Claude Code `/schedule` (or any cron-like runner
that can launch a `claude` session). Full setup, push-credential
options, and design rationale — `docs/scheduling.md`.

## Sync engine updates

See `docs/upstream-sync.md`. `git remote add upstream …` once, then
`scripts/sync_engine.sh` whenever you want to pull engine improvements.

## Contribute back

Engine improvements (skills, scripts, docs) are welcome.
See `CONTRIBUTING.md`.

## License

MIT — see `LICENSE`.
