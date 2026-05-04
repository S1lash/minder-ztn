# Sources Registry

**Last Updated:** REPLACE_WITH_DATE

Whitelist of inbox source directories scanned by `/ztn:process`. Each row
describes one source type. Adding a source is a **declarative** operation:
either invoke `/ztn:source-add` or append a row here + create the
`_sources/inbox/{id}/` and `_sources/processed/{id}/` folders. No SKILL
code changes required — every per-source behaviour is encoded as a column
on this row.

---

## Schema

| Column | Required | Meaning |
|---|---|---|
| `ID` | yes | Canonical source identifier. Kebab-case. Matches the folder name under `_sources/inbox/` and `_sources/processed/`. |
| `Inbox Path` | yes | Relative path scanned by `/ztn:process` Step 2.1. Always `_sources/inbox/{id}/`. |
| `Layout` | yes | One of: `flat-md`, `dir-per-item`, `dir-with-summary`. See **Layout types** below. |
| `Default Domain` | yes | Hint for cross-domain classification when content is ambiguous. One of: `personal`, `work`, `mixed`, `auto`. `auto` = let the LLM decide per-file. |
| `Skip Subdirs` | optional | Comma-separated list of subdirectory names (relative to `Inbox Path`) that the processor MUST ignore. Empty / `—` = scan everything. Used for reference material that lives alongside transcripts (e.g. `describe-me/` under `crafted`). |
| `Description` | yes | One-line human description of what lives in this source. |
| `Status` | yes | `active` / `reserved` / `deprecated`. Reserved = whitelisted but inbox empty by design (no error if no files). Deprecated = retain row for audit, skip during scan. |
| `Reason` | required when `Status: deprecated` | Free-form one-sentence rationale per Archive Contract Form B (`SYSTEM_CONFIG.md`). Empty cell on a row in `## Deprecated Sources` is a contract violation — surfaces as `archive-reason-missing` CLARIFICATION on next `/ztn:lint`. |

### Layout types

- **`flat-md`** — files live directly at `inbox/{id}/*.md`. One file = one item. The file's mtime or filename is the chronological key. Example: hand-written notes.
- **`dir-per-item`** — each item is its own folder: `inbox/{id}/{folder}/transcript.md`. The folder name carries the timestamp / topic. Example: voice-note exports without summary.
- **`dir-with-summary`** — same shape as `dir-per-item`, but the source MAY also produce `transcript_with_summary.md` next to `transcript.md`. The processor prefers the `_with_summary` variant when present and falls back to plain `transcript.md` otherwise. Example: Plaud, DJI mic, any AI-summarising recorder.

### Per-item folder naming (dir-per-item / dir-with-summary)

The processor parses the leading timestamp from the folder name. Three forms are supported and may coexist within a single source:

1. **Pure ISO** — `2026-04-29T14:09:30Z`
2. **ISO + topic suffix** — `2026-04-29T14:09:30Z_short topic`
3. **Date + topic** — `2026-04-29_short-topic` or legacy `04-29 short topic` (short form falls back to current year, last seen, owner-warned via CLARIFICATION when ambiguous).

If no timestamp can be parsed, the processor falls back to file mtime and surfaces a CLARIFICATION asking the owner to rename. **Never** silently drops the file.

---

## Active Sources

| ID | Inbox Path | Layout | Default Domain | Skip Subdirs | Description | Status |
|---|---|---|---|---|---|---|
| plaud | `_sources/inbox/plaud/` | dir-with-summary | auto | — | Plaud voice-recorder transcripts (popular AI-summarising hardware recorder). | active |
| voice-notes | `_sources/inbox/voice-notes/` | dir-per-item | auto | — | Generic voice-note transcripts from any recorder/app. Catch-all for users without a brand-specific source. | active |
| claude-sessions | `_sources/inbox/claude-sessions/` | dir-per-item | work | — | Claude Code session recaps captured via `/ztn-recap`. Almost always work-context. | active |
| notes | `_sources/inbox/notes/` | flat-md | auto | — | Plain Markdown notes dropped manually into the folder. | active |
| crafted | `_sources/inbox/crafted/` | flat-md | auto | describe-me | Hand-written long-form documents processed through the same pipeline. The `describe-me/` subdir holds reference profile material consumed only by `/ztn:bootstrap` — never by `/ztn:process`. | active |

---

## Reserved Sources

_(Empty by default. Add rows here when whitelisting a source whose inbox stays empty until a future integration is enabled.)_

---

## Deprecated Sources

_(Empty by default. To retire a source, MOVE its row here — do not delete it. Audit trail matters more than table tidiness. The deprecated table carries an additional `Reason` column per Archive Contract Form B.)_

| ID | Inbox Path | Layout | Default Domain | Skip Subdirs | Description | Status | Reason |
|---|---|---|---|---|---|---|---|
| _(empty)_ | | | | | | | |

---

## Adding a new source

**Recommended:** invoke `/ztn:source-add` and answer the prompts. The skill validates the ID, appends a correctly-formed row, and creates both inbox/processed folders with `.gitkeep`.

**Manual fallback:** append a row to the table above using the schema, then create:

```
_sources/inbox/{id}/.gitkeep
_sources/processed/{id}/.gitkeep
```

After either route, `/ztn:process` picks up the new source on the next run. No SKILL.md edits required.

---

## Notes

- `/ztn:process` Step 2.1 iterates rows in declaration order, then sorts the resulting file list chronologically (Step 2.3) — declaration order is **not** processing order.
- Reserved sources may have empty inbox folders. That is expected and never reported as an error.
- Deprecation protocol: retire a source by moving its row to `## Deprecated Sources` and populate the `Reason` cell. Do not delete rows. (Archive Contract Form B — `SYSTEM_CONFIG.md`.)
- The `crafted/describe-me/` exclusion is encoded declaratively via `Skip Subdirs: describe-me`. Bootstrap reads the same path through its own contract; `/ztn:process` simply skips it.
