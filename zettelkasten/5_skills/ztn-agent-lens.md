---
id: ztn-agent-lens-skill
title: 'Skill: /ztn:agent-lens'
type: skill
created: 2026-04-30
modified: '2026-04-30'
tags:
- type/skill
- topic/automation
- topic/agent-lens
---

# /ztn:agent-lens

Pointer card. The full pipeline lives in the installed skill, not here.

## Sources of truth

- **Pipeline:** `~/.claude/skills/ztn-agent-lens/SKILL.md` (after
  `install.sh`).
- **Lens registry:** `_system/registries/AGENT_LENSES.md` — concept,
  schema, cadence semantics, lens lifecycle.
- **Two-stage frame contract:** `_system/registries/lenses/_frame.md` —
  thinker prompt + structurer prompt + validator rules.
- **Per-lens definitions:** `_system/registries/lenses/{id}/prompt.md`.
- **Scheduler-prompt body:**
  `integrations/claude-code/scheduler-prompts/agent-lens-scheduled.md`.
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]] — three layers,
  routing, all ZTN skills, conventions.

## What it does (one paragraph)

Reads the lens registry, filters lenses that are due per their
per-lens cadence, runs each through a two-stage pipeline (free-form
thinker LLM → structurer LLM → structural validator), writes
observation snapshots to `_system/agent-lens/{id}/{date}.md`. Each
lens runs in isolation: fresh API context per Stage, no cross-lens
carry-over, no subagent dispatch. Meta lenses (input_type=lens-outputs)
read other lenses' outputs and produce a navigator digest of pointers,
never content.

## How to add a lens

Use the wizard: [[ztn-agent-lens-add]].

This card carries no skill detail of its own.
