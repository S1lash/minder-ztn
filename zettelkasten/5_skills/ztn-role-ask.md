---
id: ztn-role-ask-skill
title: 'Skill: /ztn:role:ask'
type: skill
created: 2026-07-12
modified: '2026-07-12'
tags:
- type/skill
- topic/automation
- topic/roles
---

# /ztn:role:ask

Pointer card. The full pipeline lives in the installed skill, not here.

## Sources of truth

- **Pipeline:** `~/.claude/skills/ztn-role-ask/SKILL.md` (after
  `install.sh`).
- **Reference resolution:** `_system/scripts/roles_common.py`
  (`resolve_role_reference`, `discover_role_ids`).
- **Remit-bounded reads:** `_system/scripts/minder_query.py --role {id}`
  (`--list` / `--search` / `--read`, fail-closed to the role's remit).
- **What roles are:** [[ztn-roles]].
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]].

## What it does (one paragraph)

Answers a question addressed to one of the owner's roles — read-only,
lock-free, never persists, never reaches `roles_persist.py` or the tick
pipeline. Resolves a free-text reference (display name / id /
transliteration, STT-tolerant — the owner rarely says the machine id) to
exactly one role, then answers in that role's persona voice via a 3-tier
ladder, escalating only when the current tier can't ground the answer:
**L0** — the role's tracked `state.md` snapshot (composite: every part's
`<!-- AUTO: role-state/{part_id} -->` zone); **L1** — a bounded synthesis
over the remit INDEX (`--list`) when L0 doesn't cover the question,
marked provisional; **L2** — a full remit-bounded investigation
(`--search` + `--read`, following the in-remit link graph) for detail,
history, connections, or «why». The answer is grounded in the role's
remit or it abstains — it never invents.

## Reference resolution (never guess)

`resolve_role_reference` returns match candidates:

| Candidates | Action |
|---|---|
| exactly one exact match | proceed |
| exactly one fuzzy match | **confirm first** — never act unconfirmed |
| two or more | surface a pick-list, let the owner choose |
| none, a name was given | list the owner's roles |
| none, generic reference («спроси у роли») | enumerate roles, ask which |

## When to use

- «спроси у Руди про…», «what's the status of…», «что роль знает про X»
  — any question addressed TO a role about what it tracks.

## When NOT to use

- Enumerating / showing all roles — that's [[ztn-role-list]].
- Changing a role's persona, remit, cadence, or lifecycle — that's
  [[ztn-role-edit]]; this skill never mutates a role.
- Creating a role — that's [[ztn-role-add]].
- Running a tick — that's [[ztn-roles]]; this skill never takes
  `.roles.lock` and never sends a payload to `roles_persist.py`.

This card carries no flow detail of its own.
