---
name: ztn:source-add
description: >
  Register a new source-type with the ZTN engine. Validates the proposed
  ID, appends a row to _system/registries/SOURCES.md, and creates the
  paired _sources/inbox/{id}/ and _sources/processed/{id}/ folders with
  .gitkeep markers. Idempotent — re-running with the same ID is a no-op.
  Pure declarative: no SKILL.md edits required for /ztn:process or
  /ztn:bootstrap to pick up the new source.
disable-model-invocation: false
---

# /ztn:source-add — Register a New Source

Single-purpose skill that adds a source-type to the engine's whitelist.
After this skill returns, the next `/ztn:process` run will scan the new
inbox folder automatically — no further configuration required.

**Documentation convention:** при любых edits этого SKILL соблюдай
`_system/docs/CONVENTIONS.md` — файл описывает current behavior без
version/phase/rename-history narratives.

## When to invoke

- The owner wants to track a new source of input (a new voice recorder,
  a new export pipeline, a new manual-notes folder, etc.).
- The owner is bootstrapping the system and wants to add their own
  hardware/software sources beyond the universal starter set.

Do **not** invoke for:
- One-off file drops — drop the file into an existing source folder
  (`notes` or `crafted` are usually right).
- Renaming an existing source — that is a manual edit (rename folder
  + edit SOURCES.md row + grep referrers); intentionally not automated.
- Retiring a source — manual: move the row to `## Deprecated Sources` and populate the `Reason` cell per Archive Contract Form B (`_system/docs/SYSTEM_CONFIG.md`). Empty `Reason` on a deprecated row surfaces as `archive-reason-missing` CLARIFICATION on next `/ztn:lint` Scan G.2.

## Arguments (all optional — skill prompts when missing)

| Flag | Meaning | Default |
|---|---|---|
| `--id <kebab-case>` | Source ID. Becomes the folder name and the registry key. | prompt |
| `--description <text>` | One-line human description for the registry row. | prompt |
| `--layout <type>` | One of: `flat-md`, `dir-per-item`, `dir-with-summary`. | prompt |
| `--default-domain <hint>` | One of: `personal`, `work`, `mixed`, `auto`. | `auto` |
| `--skip-subdirs <csv>` | Comma-separated subdirectory names to exclude from processing. Empty = scan everything. | empty |
| `--status <state>` | `active` or `reserved`. `reserved` = whitelisted with empty inbox by design. | `active` |
| `--dry-run` | Print the row that would be appended and the folders that would be created. Make no changes. | off |

## Step 1: Load Context

Read in parallel:

1. `{{MINDER_ZTN_BASE}}/_system/registries/SOURCES.md` — the live registry. Check for ID collisions and table structure.
2. `{{MINDER_ZTN_BASE}}/_system/registries/SOURCES.template.md` — the schema spec. Use it to validate Layout / Default Domain / Status values and to mirror the column order used in the live registry.

If either file is missing, abort with a clear error pointing the owner at `/ztn:bootstrap` (the registries are bootstrap-seeded).

## Step 2: Resolve Arguments

For each argument that was not passed via flag, prompt the owner with one focused question. Each prompt MUST surface the legal values and explain what the field changes downstream.

**Validation rules (apply to every argument source — flags and prompts alike):**

- **ID** — kebab-case (`^[a-z][a-z0-9-]*[a-z0-9]$`), 3–32 chars. Reject if:
  - already present (case-insensitive) in any of `## Active Sources`, `## Reserved Sources`, `## Deprecated Sources`
  - matches a reserved system name: `inbox`, `processed`, `crafted/describe-me` segment, `.gitkeep`, `.lint.lock`, `.maintain.lock`, `.processing.lock`, `.resolve.lock`
- **Layout** — must be one of the three documented types. No free-form input.
- **Default Domain** — must be one of `personal`, `work`, `mixed`, `auto`. Free-form rejected.
- **Skip Subdirs** — each entry is kebab-case or simple filename; reject `..`, absolute paths, glob characters (`*`, `?`, `[`).
- **Status** — must be `active` or `reserved`. `deprecated` is intentionally NOT a creation state — deprecating happens by hand on an existing row.
- **Description** — non-empty, no pipe characters (table delimiter). If a pipe is needed, escape with HTML entity `&#124;` and warn.

If any validation fails, surface the failure and re-prompt for that single field. Never silently coerce.

## Step 3: Confirm

Render a preview block and ask for confirmation:

```
About to register source:

  ID:              {id}
  Inbox Path:      _sources/inbox/{id}/
  Layout:          {layout}
  Default Domain:  {default-domain}
  Skip Subdirs:    {skip-subdirs or "—"}
  Description:     {description}
  Status:          {status}

Will:
  + append row to _system/registries/SOURCES.md (under ## {Active|Reserved} Sources)
  + create  _sources/inbox/{id}/.gitkeep
  + create  _sources/processed/{id}/.gitkeep

Proceed? [y/N]
```

If `--dry-run` was passed, print the preview and exit with code 0 — never touch the filesystem.

If the owner declines, exit cleanly with no changes.

## Step 4: Apply

In order:

1. **Create folders.**
   - `_sources/inbox/{id}/` with a `.gitkeep` file.
   - `_sources/processed/{id}/` with a `.gitkeep` file.
   - If a folder already exists, leave its contents alone; only ensure `.gitkeep` is present.

2. **Append SOURCES.md row.** Locate the target table heading (`## Active Sources` or `## Reserved Sources`). If the heading is missing — create it just above `## Notes` (or at end-of-file if `## Notes` absent). Append the new row to the table preserving column order from SOURCES.template.md:

   ```
   | {id} | `_sources/inbox/{id}/` | {layout} | {default-domain} | {skip-subdirs or "—"} | {description} | {status} |
   ```

3. **Update `Last Updated`** field at the top of SOURCES.md to today's ISO date (`YYYY-MM-DD`).

All three writes happen as separate filesystem operations — there is no transaction. If step 2 fails after step 1 already created folders, the next invocation must detect the orphan folders and continue from where it left off (idempotency, see Step 5).

## Step 5: Idempotency Contract

Re-invocations with the same `--id` MUST be safe:

- If the row exists in any section of SOURCES.md → report «source `{id}` already registered (status: {state})» and exit 0 without changes.
- If the row exists but folders are missing → recreate the folders + `.gitkeep`, report «registry row found, repaired missing folders», exit 0.
- If folders exist but row is missing → propose adding the row using current arguments. Owner must confirm explicitly — never silently materialise a row from filesystem state alone.

## Step 6: Report

Print a short summary:

```
Registered source: {id}
  Row appended:   _system/registries/SOURCES.md (## {section} Sources)
  Inbox:          _sources/inbox/{id}/
  Processed:      _sources/processed/{id}/

Next: drop input files into _sources/inbox/{id}/ and run /ztn:process.
```

## What this skill does NOT do

- **Never edits any other SKILL.md** — the engine is decoupled from per-source IDs by design (Phase B refactor). If a downstream skill needs source-specific behaviour, that behaviour lives as a column on SOURCES.md, not as code.
- **Never edits CONCEPT.md / SYSTEM_CONFIG.md / FOLDERS.md** — those describe the layout in source-agnostic terms.
- **Never moves or processes files** — input handling is `/ztn:process`'s job.
- **Never deprecates or removes sources** — deprecation is manual to enforce a deliberate audit-trail entry.
- **Never modifies the deny-by-default `.engine-manifest.yml`** — owner data layer (`_sources/inbox/`, `_sources/processed/`) stays in the manifest's `exclude:` list, and the skeleton's `.gitkeep` provisioning is handled by `release_engine.py` from SOURCES.template.md.

## Cross-skill interactions

- **`/ztn:process`** — picks up the new source on its next run, no configuration. Reads SOURCES.md Step 2.1.
- **`/ztn:bootstrap`** — source-agnostic raw scan globs `_sources/inbox/**/*.md`, so the new source is included automatically once its row is active.
- **`/ztn:sync-data`** — counts new files in `_sources/inbox/**` for its «pending /ztn:process» nudge; no awareness of source IDs.
- **`/ztn:lint`** — does not look at SOURCES.md directly. Lint checks the registry mechanically only when the owner requests a registry audit (out of scope here).

## Locks

This skill writes only to a registry row + two `.gitkeep` files. It is **not** in the cross-skill mutex set with `/ztn:process` / `/ztn:maintain` / `/ztn:lint` / `/ztn:agent-lens`, because:

- It does not scan inbox content.
- It does not touch system state files (`_system/state/*`, logs, batches).
- It writes only paths that the running skills do not concurrently mutate (registry table append + new folders).

If the owner runs `/ztn:source-add` while `/ztn:process` is running, the worst case is that `/ztn:process` Step 2.1 already loaded SOURCES.md before the row was appended — the new source becomes visible on the next run. No corruption is possible.
