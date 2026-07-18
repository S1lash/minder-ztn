---
id: ztn-role-list-skill
title: 'Skill: /ztn:role:list'
type: skill
created: 2026-07-12
modified: '2026-07-12'
tags:
- type/skill
- topic/automation
- topic/roles
---

# /ztn:role:list

Pointer card. The full pipeline lives in the installed skill, not here.

## Sources of truth

- **Pipeline:** `~/.claude/skills/ztn-role-list/SKILL.md` (after
  `install.sh`).
- **Authoritative id set:** `_system/scripts/roles_common.py`
  (`discover_role_ids`, `load_role_config`, `last_successful_run`).
- **Rendered enrichment (optional):** `_system/views/ROLES.md` (via
  `/ztn:maintain` — a stale/absent registry falls through to a live
  derive, never a reason to omit a role).
- **What roles are:** [[ztn-roles]].
- **Full orientation card:** [[CLAUDE_ZETTELKASTEN]].

## What it does (one paragraph)

Shows the owner their roles, conversationally — read-only, lock-free,
never writes. Always enumerates the AUTHORITATIVE set from
`discover_role_ids()` first (a freshly-created or just-deleted role
would be missing / stale in `ROLES.md`, which only refreshes on a
`/ztn:maintain` tick), then uses `ROLES.md` only to enrich facts
(last-run, counts) for the ids it happens to cover. Translates every raw
config field to plain words — never prints a remit glob, a part `kind`,
a `cadence_anchor`, or `schema_version`. Leads with the conclusion (how
many roles, active vs paused split), then one compact line per role:
what it watches, what it tracks, how often it looks, status, last run
(or «cold-start-pending» when its first look hasn't produced a live
state yet).

## When to use

- «покажи мои роли», «what roles do I have», «is {role} active or
  paused», «when did {role} last run» — enumeration + role metadata.

## When NOT to use

- A question about what a specific role TRACKS (its status, its
  reading) — that's [[ztn-role-ask]]; listing shows metadata, not
  content.
- Changing a role — that's [[ztn-role-edit]].
- Creating a role — that's [[ztn-role-add]].
- The owner explicitly wants raw config — point at [[ztn-role-edit]]
  (which owns config changes) rather than dumping internals here.

This card carries no flow detail of its own.
