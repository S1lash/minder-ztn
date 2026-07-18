---
name: ztn:role:list
description: >
  Show the owner their ZTN roles, conversationally — read-only, lock-free, never
  writes. Enumerates every role and presents each in plain language: what it
  watches, what it tracks, how often it looks, whether it's active or paused, and
  when it last ran. Groups active vs paused; if there are no roles, says so and
  offers to create one. This is ENUMERATION + role metadata (which roles exist and
  their config-level status) — NOT a question about what a role tracks (that is
  `ztn:role:ask`). Triggers: «покажи мои роли», «какие у меня роли», «список
  ролей», «сколько у меня ролей», «Kitchen Reno активна или на паузе», «когда роль
  последний раз запускалась», «list my roles», «what roles do I have», «show me my
  roles», «is Kitchen Reno active or paused», «when did Kitchen Reno last run», «which of my roles
  are paused». For a QUESTION to a role about what it tracks («status of my
  project», «спроси у Kitchen Reno про X») use `ztn:role:ask`; to change one use
  `ztn:role:edit`; to create one use `ztn:role:add`.
disable-model-invocation: false
---

# /ztn:role:list — show the owner their roles (read-only)

Answer «what roles do I have and how are they doing» in plain language. It is
**read-only**: no lock, no write, it never reaches `roles_persist.py` or the tick
pipeline, and it mutates no `parts/*.json`, `state.md`, run log, registry, or
CLARIFICATIONS queue. It reports what's there and stops.

The owner is a human who wants the shape of their roles at a glance — not config.
Lead with the conclusion (how many roles, active vs paused), then one compact line
per role. Never surface `config.yml` fields, remit globs, part kinds, cadence
anchors, or any internal mechanic as jargon — translate all of it to plain words.

## Step 1 — Load context

Load `ENGINE_DOCTRINE.md` (auto-loaded). Answer in the owner's language: detect it
from their request; if unclear, fall back to the body language of `_system/SOUL.md`,
then the most recent records, then English. Calibrate wording to the presentation
floor in `_system/docs/communication-baseline.md` (conclusion first, plain
language, high signal, no filler, no flattery) — read it if present, skip silently
if not.

## Step 2 — Source of truth (authoritative id set, enriched by the registry)

**Always enumerate the AUTHORITATIVE set of roles from `discover_role_ids()`** —
never from `ROLES.md` alone. `ROLES.md` is a rendered projection refreshed only on a
`/ztn:maintain` tick, so a freshly-created role (or a just-deleted one) can be missing
from it or stale; trusting it as the source of truth would silently omit a role the
owner just made. So: get the live id set from `discover_role_ids()` first, then use
`ROLES.md` ONLY to enrich the facts (last-run, counts) for the ids it happens to cover.

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "_system/scripts")
from roles_common import discover_role_ids, load_role_config, RoleConfigError, last_successful_run
for rid in discover_role_ids():                     # the authoritative, live set
    try:
        cfg = load_role_config(rid)
    except RoleConfigError as exc:
        print(f"SKIP\t{rid}\t{exc}")                # setup problem — reported, never dropped
        continue
    parts = ",".join(f"{p.id}:{p.kind}" for p in cfg.parts)
    run = last_successful_run(rid)
    last = run["run_at"][:10] if run else ""
    print(f"OK\t{cfg.id}\t{cfg.name}\t{parts}\t{cfg.cadence}\t{cfg.cadence_anchor}\t{cfg.status}\t{last}")
PY
```

This gives the complete current set with plain facts. When `_system/views/ROLES.md`
exists, you MAY additionally read it to enrich tabular extras (item counts,
cold-start-pending flags) for the ids it covers — but an id present in
`discover_role_ids()` yet absent from `ROLES.md` is a NEW role, shown live from its
config, not omitted. A role that fails to load is reported by id as a setup problem
(«`{id}` couldn't be read — its setup has a problem; `/ztn:role:edit {id}` to look»),
never silently dropped.

**Last-run enrichment (cheap only).** When it's cheap — the live path already
returns it, and `roles-runs.jsonl` is a small append-only log — note when each role
last ran, or that it's **cold-start-pending** (created but its first look hasn't
produced a live state yet: no successful run in `roles-runs.jsonl`). If reading the
run log would cost real work, skip it — it is a nice-to-have, not required.

## Step 3 — Plain-language projection (never show config as jargon)

For each role, translate the raw config into plain words. **Never** print an axis,
a glob, a part `kind`, `cadence_anchor`, or `schema_version`. Show:

| Show the owner… | Derived from… | In plain words |
|---|---|---|
| **name** | `config.name` (display, MAY be non-ASCII, e.g. «Kitchen Reno») | as-is — it's what the owner calls it |
| **what it watches** | the remit — which project / area / folder / hub / tag / decisions it's scoped to | «your kitchen renovation project — its folder and hub», «your kitchen-reno folder», «anything tagged travel». Describe the ZONE, never the globs |
| **what it tracks** | its `parts` (each a built kind) | a **ledger** part → «the workstreams / what's in flight»; a **narrative** part → «the project's meaning and whether the work still serves it». A composite → join them: «the workstreams + the project's meaning». Never say «ledger» / «narrative» / «part» |
| **how often it looks** | `cadence` + `cadence_anchor` | «once a week, Monday», «every day», «monthly». Never «weekly / monday» as raw tokens |
| **status** | `config.status` | active / paused (in the owner's language) |
| **last run** | `roles-runs.jsonl` (cheap) | «last looked {date}», or «hasn't run yet — its first look is still pending» for cold-start |

**Grouping and shape.** Open with the conclusion — how many roles, and the split.
Then group **active** first, **paused** below. Keep each role to ~2 lines:

> You have 2 roles — 1 active, 1 paused.
>
> **Active**
> - **Kitchen Reno** — watches your kitchen renovation project (its folder and
>   hub); tracks the workstreams + the project's meaning. Looks once a week,
>   Monday. Last looked 2026-07-11.
>
> **Paused**
> - **Book Club** — watches your book club notes; tracks what's in flight.
>   Monthly, paused since you stopped it.

If a role is cold-start-pending, say so in its second clause instead of a date
(«created, but its first look is still pending — `/ztn:roles --role {id}` to run
it»).

## Step 4 — Offer the natural next actions

Close with the family's inline entry points, in the owner's language:

> Ask one → `/ztn:role:ask {name}` «…» · change one → `/ztn:role:edit {name}` ·
> new one → `/ztn:role:add`.

Use a real role name in the examples (the owner's most-recently-run or first
active role), so the next step is copy-ready.

## Empty state

If `discover_role_ids()` returns nothing (and `ROLES.md` lists no roles), say so
plainly and offer creation — don't dress up an empty list:

> You don't have any roles yet. A role is a standing steward that watches one zone
> of your notes and keeps an honest, current picture of it — a PM over a project, a
> keeper of your open decisions. Want to set one up? → `/ztn:role:add`

## Read-only invariants (the whole safety model)

- **No lock, no write, never persists.** Takes no `.roles.lock`, sends no payload
  to `roles_persist.py`, never reaches the tick pipeline, mutates no role file,
  registry, run log, or CLARIFICATION. It only reads.
- **Never renders the registry.** `ROLES.md` is owned by `render_roles_registry.py`
  via `/ztn:maintain`. This skill READS it (or derives live when it's absent); it
  never writes it, and a stale/absent registry is a fall-through to live derive, not
  a reason to regenerate.
- **Plain projection only.** Never expose `config.yml` fields, remit globs, part
  kinds, or cadence anchors as jargon. If the owner explicitly asks for the raw
  config of a role, point them at `/ztn:role:edit {name}` (which owns config
  changes) rather than dumping internals here.
- **Owner-facing prose only.** No structured output, no state change. Exit status:
  `list-shown`.

## Files read / written

Read: `_system/views/ROLES.md` (preferred registry, when present);
`_system/roles/{*}/config.yml` (per-role name / remit / parts / cadence / status —
for the plain-language projection); `_system/state/roles-runs.jsonl` (cheap
last-run / cold-start-pending enrichment); `_system/SOUL.md` +
`_system/docs/communication-baseline.md` (language + presentation calibration).
Reads no role's `state.md` and no remit corpus — listing is a registry-level
glance, not a per-role investigation.

**Written: nothing.** This skill is read-only by contract.

## Relationship to the rest of the family

- `ztn:role:ask` — ask one role a question (read-only, remit-bounded ladder).
- `ztn:role:edit` — change / retune a role + pause / resume / retire.
- `ztn:role:add` — create a role (expert concierge).
- `ztn:roles` — the mechanical tick runner (scheduler-facing); no `list` mode.

«Show my roles» routes here. A question TO a role routes to `ask`; «улучшим Kitchen Reno» /
«pause Book Club» to `edit`; «заведи роль» to `add`. When a request is really one of
those, hand off rather than answering here — this skill only enumerates.
