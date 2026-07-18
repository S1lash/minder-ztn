---
id: ztn-role-edit-skill
title: 'Skill: /ztn:role:edit'
type: skill
created: 2026-07-12
modified: '2026-07-12'
tags:
- type/skill
- topic/automation
- topic/roles
---

# /ztn:role:edit

Pointer card. The full concierge flow lives in the installed skill, not here.

## Sources of truth

- **Concierge flow:** `~/.claude/skills/ztn-role-edit/SKILL.md` (after
  `install.sh`).
- **Config schema + loader/validator:** `_system/scripts/roles_common.py`
  (`load_role_config_file`, `resolve_role_reference`,
  `emit_clarification`).
- **Remit resolver (probe):** `_system/scripts/minder_query.py`.
- **What roles are:** [[ztn-roles]] + `_system/roles/_frame.md`.
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]].

## What it does (one paragraph)

The expert counterpart to [[ztn-role-add]], over a role that already has
**history**. Resolves a free-text role reference the same way
[[ztn-role-ask]] does (confirm on fuzzy, never guess), then reads the
role's `decisions.jsonl` + run log + tracked part state to propose
GROUNDED improvements — a staleness instruction it never had, a stale
narrative reframed, a meeting-blind remit widened — before applying the
owner-confirmed change **validate-before-write**: a new config is
generated in memory, validated against a temp copy, and swapped in only
on success. Ordinary edits (persona / cadence / activation / name / hook
/ adding a new part / brief) just validate and write, preserving every
part's tracked state (`parts/*.json`, `state.md`, `decisions.jsonl`)
untouched.

## Edit classes (decide the class FIRST)

| Ask | Class | Result |
|---|---|---|
| sound / cadence / activation / name / hook / brief | ordinary edit | validate-before-write |
| add a new part to the composite | add-part | appends to `parts[]`; cold-starts on the next tick |
| WHAT ZONE it watches | remit change | writes the new remit + emits `role-remit-changed` — **never** a silent churn |
| remove / replace a part, or change its kind | parts-shape change | **DISALLOWED** on a live role — offer [[ztn-role-add]] for a new role instead |
| new config field / cadence / stance / part-kind | schema extension | **BLOCKED** — routes to the engine maintainer |
| pause / resume / retire / hard-delete | lifecycle | flip `status` / archive with an Archive-Contract reason / typed-confirm delete |

A remit change stages a re-baseline because the tracked state (ledger
keys, narrative evidence) was built against the OLD zone — letting the
next tick reconcile it silently would orphan keys or trip the
churn-guard. A parts-shape change on a live role is refused because it
would strand that part's accumulated state; **adding** a part is fine —
it cold-starts clean, like a fresh role's part.

## When to use

- «улучши / retune / rename / widen this role», «pause / resume / retire
  {role}» — any change to an EXISTING role's identity, instructions, or
  lifecycle.

## When NOT to use

- Creating a role — that's [[ztn-role-add]] (this skill never creates
  one).
- Asking a role a question — that's [[ztn-role-ask]].
- Reshaping parts in a way that would strand state — refused here,
  points to [[ztn-role-add]] for a fresh role instead.
- Running a tick — that's [[ztn-roles]]; this skill only acquires
  `.roles.lock` for its own atomic config swap, never for a tick.

This card carries no flow detail of its own.
