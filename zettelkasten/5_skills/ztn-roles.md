---
id: ztn-roles-skill
title: 'Skill: /ztn:roles'
type: skill
created: 2026-07-11
modified: '2026-07-12'
tags:
- type/skill
- topic/automation
- topic/roles
---

# /ztn:roles

Pointer card. The full pipeline lives in the installed skill, not here.

## Sources of truth

- **Pipeline:** `~/.claude/skills/ztn-roles/SKILL.md` (after `install.sh`).
- **Shared frame contract:** `_system/roles/_frame.md` — the three-stage
  frame (thinker → structurer → writer) every role tick runs inside.
- **Sole writer + control boundary:** `_system/scripts/roles_persist.py` —
  runs the archetype validator for each addressed part FIRST, then
  persists; the only thing that writes role state.
- **Scoped remit resolver:** `_system/scripts/minder_query.py` — remit →
  zone index / `--search` / `--read`; the body's navigation tool.
- **Per-role definitions:** `_system/roles/{id}/{config.yml,
  parts/{part_id}.json, state.md, decisions.jsonl, hooks/tick.md,
  hooks/ask.md, brief.md (optional)}` — this skill reads `hooks/tick.md`;
  `hooks/ask.md` is read by [[ztn-role-ask]].
- **Scheduler-prompt body:**
  `integrations/claude-code/scheduler-prompts/roles-nightly.md` (daily
  tick; per-role cadence enforced inside via `is_due` — a daily tick is
  not a daily role run).
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]].

## What it does (one paragraph)

A **role** is a standing agent that watches ONE zone (remit) of the base
and keeps a composition of working **parts** current about what's
happening there — each part a built kind (e.g. **ledger**: a keyed status
registry; **narrative**: a versioned prose reading of meaning /
alignment; also **registry**, **metrics**, **assessment**, **stance**) —
plus its own persona and cadence. This skill runs the
**tick**: for every due role it updates all of its parts from what
changed. Per-role isolation: each role's frame stages run in fresh
context, no cross-role carry-over, no subagent dispatch; one role's
error never aborts the sweep. Reading is honor-system and agentic
(lens-style): the thinker is handed the zone INDEX plus scoped
`minder_query --list/--search/--read` tools bounded to its remit, and
decides what to open — nothing out of remit is reachable.

## The control boundary (read first)

The tick BODY (the LLM) only *proposes* a structured, part-addressed
delta payload — it **never writes state**. The sole writer is
`roles_persist.py`, which runs the archetype validator FIRST per
addressed part (grounding: citations ⊆ the engine-authored read-records
oracle; append-not-replace; churn-guard) and only then persists. An
ungrounded, invalid, or churny delta is rejected regardless of what the
body intended. This seam is the whole safety model.

## Modes

- **tick** (`--all-due` default, or `--role <id>`) — update the due
  roles' parts; takes `.roles.lock`, gated by cadence (`is_due`) then
  activation (`by_change` / `by_elapsed_time`).
- **cold-start** — the first tick over an empty part mints a *frozen*
  `staging` draft (not live) and surfaces `role-cold-start`; the same
  draft re-surfaces until the owner runs `--approve-coldstart <role-id>`.
- **Tick-only.** Asking a role a question is a separate read-only skill —
  [[ztn-role-ask]] — not a mode here.

Seven-lock matrix (`.processing .maintain .lint .agent-lens .content
.resolve .roles`) — mutually exclusive per doctrine §3.4.
`roles_persist.py` emits deterministic `role-*` CLARIFICATION types
(cold-start, new-key, churn-guard, auto-paused, schema-version,
identity-suggest, unroutable, and the proactive `role-nudge`); a remit
change instead emits `role-remit-changed` directly from [[ztn-role-edit]].

## Family

A role has one tick runner and four owner-facing skills, all colon-named
(`ztn:role:*`):

- [[ztn-role-add]] — create (`/ztn:role:add`)
- [[ztn-role-ask]] — ask a question (`/ztn:role:ask`, read-only)
- [[ztn-role-edit]] — change + lifecycle (`/ztn:role:edit`)
- [[ztn-role-list]] — show (`/ztn:role:list`)

This card carries no skill detail of its own.
