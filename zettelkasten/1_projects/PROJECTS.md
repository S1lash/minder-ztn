# Project Registry

**Last Updated:** REPLACE_WITH_DATE

All projects in the system. Add a row when a new project is created.

**Schema:**
- `Scope` — `work` (employer / clients), `personal` (life, health, learning),
  `side` (side business, freelance, public projects), `mixed` (truly cross-context).
  Owner-tagged; `/ztn:bootstrap` seeds with a hint from raw-scan source bias,
  owner edits. Empty `Scope` defaults to `work` for legacy rows.
- `Status` — `active`, `paused`, `candidate` (added by bootstrap, awaiting owner review),
  `completed` (moved to second table).

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
