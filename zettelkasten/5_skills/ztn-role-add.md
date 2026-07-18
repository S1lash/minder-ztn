---
id: ztn-role-add-skill
title: 'Skill: /ztn:role:add'
type: skill
created: 2026-07-11
modified: '2026-07-12'
tags:
- type/skill
- topic/automation
- topic/roles
---

# /ztn:role:add

Pointer card. The full concierge flow lives in the installed skill, not here.

## Sources of truth

- **Concierge flow:** `~/.claude/skills/ztn-role-add/SKILL.md` (after
  `install.sh`).
- **What roles are:** [[ztn-roles]] + `_system/roles/_frame.md`.
- **Config schema + loader/validator:** `_system/scripts/roles_common.py`
  (`load_role_config`, remit model, cadence semantics).
- **Part-kind plugins:** `_system/scripts/roles_archetype_{kind}.py` —
  each exposes a `CONCIERGE_MANIFEST` (plain purpose / triggers / built)
  the skill reads instead of hardcoding a kind list.
- **Remit resolver (probe):** `_system/scripts/minder_query.py`.
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]].

## What it does (one paragraph)

Expert role-creation concierge. User says what they want a standing role
to steward in plain language («be the PM of my side-project», «hold the
meaning of my research and tell me when the work drifts»); the skill
develops the idea, **composes** it from the built part-kinds (`ledger`,
`narrative`, `registry`, `metrics`, `assessment`, `stance`), fights for the
highest-leverage role FOR the owner
(power-uses grounded in real data, a meeting-aware remit, a
growth-calibrated persona, a mandatory self-review gate), probes the
user's real notes to show what the role would actually find, and
generates a complete, validation-passing role — config + hook bodies —
calibrated to the user's data and intent. Cross-routes a wish that is
really a lens or a metric source to the right skill instead of
force-fitting it. User never sees `config.yml` fields, remit axes,
persona stances, cadence anchors, or part schemas — those are the
skill's responsibility. The write is atomic and validated through
`load_role_config` before success; the skill writes **only config +
hooks**, never a part's state — cold-start (seeding
`parts/{part_id}.json` + `state.md`) is `roles_persist.py`'s job.

## Part-kind honesty (load-bearing)

A role is a **composition of parts**; a wish decomposes into facets, each
mapped to a built kind. All six kinds — `ledger` (discrete items with a
moving status), `narrative` (a versioned prose reading of meaning /
alignment), `registry` (a catalog or an append-only log), `metrics` (a
number tracked toward a target), `assessment` (a keyed on/off-track
verdict), and `stance` (an argued position, grounded in records or in the
constitution) — are built today; most real roles compose two or more. A
facet that needs an unbuilt capability (a part that ACTS on the world, or
reaches into an external tool — the Layer-2 frontier) is named plainly, not
faked: the skill builds the parts that ARE available and notes the
deferred facet for later. A wish that is really a passive observer or a
numeric intake is cross-routed to `/ztn:agent-lens-add` or a metric
source, never force-composed into a role.

## When to use

- Casual idea you want shipped well: «spin up a PM over my open decisions».
- Friend onboarding: non-technical user who wants a standing steward
  without learning the schema.
- Shaping a brand-new role: `--from-existing <id>` to duplicate-and-modify
  an existing role's config, `--from-spec <path>` for a rough written wish.

## When NOT to use

- Changing an existing role's config, hooks, or lifecycle (pause / resume
  / retire) — that's [[ztn-role-edit]]; this skill creates new roles only
  and refuses a duplicate-intent match.
- Running a tick or approving a cold-start draft — that's [[ztn-roles]].
- Asking a role a question — that's [[ztn-role-ask]].
- Schema extension (new config field, part-kind, persona stance, cadence)
  — the skill blocks; engine-maintainer flow.

This card carries no flow detail of its own.
