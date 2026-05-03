# People Registry

**Last Updated:** REPLACE_WITH_DATE

All people mentioned in the system. New entries appear automatically when
`/ztn:process` resolves a name during transcript processing.

**Schema:**
- `Tier` — 1 (has profile OR mentions ≥ 8), 2 (3–7 mentions), 3 (1–2), `stale` (0 mentions + no profile)
- `Mentions` — 1-per-file count across `_records/` and PARA. Recomputed by `/ztn:bootstrap` and `/ztn:maintain`
- `Last` — latest `created` date where person appears in frontmatter
- Tier `stale` → row MUST be moved to `## Stale People` (split-table) and populate `Reason` per Archive Contract Form B (`_system/docs/SYSTEM_CONFIG.md`).

---

## People

Sorted by mentions desc within tier.

| ID | Name | Role | Org | Profile | Tier | Mentions | Last |
|---|---|---|---|---|---|---|---|
| _(empty)_ | | | | | | | |

---

## Stale People

People with `Tier: stale`. Per Archive Contract Form B, every row here carries a `Reason` cell — free-form one-sentence rationale. Forward-only: rows that became stale before contract adoption are not backfilled.

| ID | Name | Role | Org | Profile | Tier | Mentions | Last | Reason |
|---|---|---|---|---|---|---|---|---|
| _(empty)_ | | | | | | | | |
