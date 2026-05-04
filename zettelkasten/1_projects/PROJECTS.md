# Project Registry

**Last Updated:** REPLACE_WITH_DATE

All projects in the system. Add a row when a new project is created.

**Schema:**
- `Scope` — `work` (employer / clients), `personal` (life, health, learning),
  `side` (side business, freelance, public projects), `mixed` (truly cross-context).
  Owner-tagged; `/ztn:bootstrap` seeds with a hint from raw-scan source bias,
  owner edits. Empty `Scope` defaults to `work` for legacy rows.
- `Status` — `active`, `paused`, `candidate` (added by bootstrap, awaiting owner review),
  `completed` (moved to `## Completed Projects`), `archived` (dropped before completion;
  moved to `## Archived Projects` with required `Reason` per Archive Contract Form B
  in `_system/docs/SYSTEM_CONFIG.md`).

---

## Active Projects

| ID | Name | Description | Folder | Scope | Status |
|----|------|-------------|--------|-------|--------|
| _(empty)_ | | | | | |

---

## Completed Projects

| ID | Name | Description | Folder | Scope | Completed |
|----|------|-------------|--------|-------|-----------|
| _(empty)_ | | | | | |

---

## Archived Projects

Projects with `Status: archived` — dropped before completion. Per Archive Contract Form B (`_system/docs/SYSTEM_CONFIG.md`), every row carries a `Reason` cell — free-form one-sentence rationale. Forward-only: projects archived before contract adoption are not backfilled. (Successfully completed projects belong in `## Completed Projects` and do not require Reason.)

| ID | Name | Description | Folder | Scope | Status | Archived | Reason |
|----|------|-------------|--------|-------|--------|----------|--------|
| _(empty)_ | | | | | | | |
