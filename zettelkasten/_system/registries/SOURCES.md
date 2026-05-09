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
| `Family` | yes | Processing family — drives which `/ztn:process` branch consumes files. One of: `transcript`, `metric-day`, `recap`. See **Family routing** below. Default `transcript` for backwards compatibility (older registries lacking the column are treated as transcript). |
| `Layout` | yes | One of: `flat-md`, `dir-per-item`, `dir-with-summary`. See **Layout types** below. |
| `Default Domain` | yes | Hint for cross-domain classification when content is ambiguous. Free-form (`personal`, `work`, `mixed`, `auto`, `health`, …). `auto` = let the LLM decide per-file; concrete values short-circuit classification. |
| `Skip Subdirs` | optional | Comma-separated list of subdirectory names (relative to `Inbox Path`) that the processor MUST ignore. Empty / `—` = scan everything. Used for reference material that lives alongside transcripts (e.g. `describe-me/` under `crafted`, `raw/` under `garmin`). |
| `Description` | yes | One-line human description of what lives in this source. |
| `Status` | yes | `active` / `reserved` / `deprecated`. Reserved = whitelisted but inbox empty by design (no error if no files). Deprecated = retain row for audit, skip during scan. |
| `Reason` | required when `Status: deprecated` | Free-form one-sentence rationale per Archive Contract Form B (`SYSTEM_CONFIG.md`). Empty cell on a row in `## Deprecated Sources` is a contract violation — surfaces as `archive-reason-missing` CLARIFICATION on next `/ztn:lint`. |

### Family routing

| Family | Branch | Pipeline shape |
|---|---|---|
| `transcript` | Default LLM pipeline (Step 3 onward) | Subagent dispatch, classification, knowledge-note extraction, multi-domain routing. Files become record + knowledge notes. |
| `metric-day` | Inline deterministic Python (Step 2.5, no LLM) | One file → one biometric record under `_records/biometric/{date}.md`. Rolling baselines + σ-deviation flags + streak detection. See `_system/scripts/process_metric_day.py`. Privacy trio hard-set: `is_sensitive: true`, `audience_tags: []`, `origin: personal`. |
| `recap` | Reserved | Future short-form session-recap branch; falls back to `transcript` for now. |

A single `/ztn:process` invocation may mix families; the metric-day
phase runs first inline, transcript phase runs second via existing
subagent dispatch. Manifest carries one batch_id with multiple
sections (e.g. `records`, `records.biometric`).

### Layout types

- **`flat-md`** — files live directly at `inbox/{id}/*.md`. One file = one item. The file's mtime or filename is the chronological key. Example: hand-written notes, daily Garmin snapshots.
- **`dir-per-item`** — each item is its own folder: `inbox/{id}/{folder}/transcript.md`. The folder name carries the timestamp / topic. Example: voice-note exports without summary.
- **`dir-with-summary`** — same shape as `dir-per-item`, but the source MAY also produce `transcript_with_summary.md` next to `transcript.md`. The processor prefers the `_with_summary` variant when present and falls back to plain `transcript.md` otherwise. Example: Plaud, DJI mic, any AI-summarising recorder.

### Per-item folder naming (dir-per-item / dir-with-summary)

The processor parses the leading timestamp from the folder name. Three forms are supported and may coexist within a single source:

1. **Pure ISO** — `2026-04-29T14:09:30Z`
2. **ISO + topic suffix** — `2026-04-29T14:09:30Z_short topic`
3. **Date + topic** — `2026-04-29_short-topic` or legacy `04-29 short topic` (short form falls back to current year, last seen, owner-warned via CLARIFICATION when ambiguous).

If no timestamp can be parsed, the processor falls back to file mtime and surfaces a CLARIFICATION asking the owner to rename. **Never** silently drops the file.

For metric-day family the filename is canonical `YYYY-MM-DD.md` — one file per calendar day.

---

## Active Sources

| ID | Inbox Path | Family | Layout | Default Domain | Skip Subdirs | Description | Status |
|---|---|---|---|---|---|---|---|
| plaud | `_sources/inbox/plaud/` | transcript | dir-with-summary | auto | — | Plaud voice-recorder transcripts (popular AI-summarising hardware recorder). | active |
| voice-notes | `_sources/inbox/voice-notes/` | transcript | dir-per-item | auto | — | Generic voice-note transcripts from any recorder/app. Catch-all for users without a brand-specific source. | active |
| claude-sessions | `_sources/inbox/claude-sessions/` | transcript | dir-per-item | work | — | Claude Code session recaps captured via `/ztn-recap`. Almost always work-context. | active |
| notes | `_sources/inbox/notes/` | transcript | flat-md | auto | — | Plain Markdown notes dropped manually into the folder. | active |
| crafted | `_sources/inbox/crafted/` | transcript | flat-md | auto | describe-me | Hand-written long-form documents processed through the same pipeline. The `describe-me/` subdir holds reference profile material consumed only by `/ztn:bootstrap` — never by `/ztn:process`. | active |
| garmin | `_sources/inbox/garmin/` | metric-day | flat-md | health | raw | Garmin daily biometric snapshots. One file per calendar day; `raw/` holds full minute-level JSON payloads (skipped by /ztn:process; available as escape hatch for biometric lenses). Inactive until owner wires a Garmin collector — pipeline lies dormant otherwise. | active |

---

## Reserved Sources

_(Empty by default. Add rows here when whitelisting a source whose inbox stays empty until a future integration is enabled.)_

---

## Deprecated Sources

_(Empty by default. To retire a source, MOVE its row here — do not delete it. Audit trail matters more than table tidiness. The deprecated table carries an additional `Reason` column per Archive Contract Form B.)_

| ID | Inbox Path | Family | Layout | Default Domain | Skip Subdirs | Description | Status | Reason |
|---|---|---|---|---|---|---|---|---|
| _(empty)_ | | | | | | | | |

---

## Adding a new source

**Recommended:** invoke `/ztn:source-add` and answer the prompts. The skill validates the ID, appends a correctly-formed row, and creates both inbox/processed folders with `.gitkeep`. Pass `--family <transcript|metric-day|recap>` (default `transcript`).

**Manual fallback:** append a row to the table above using the schema, then create:

```
_sources/inbox/{id}/.gitkeep
_sources/processed/{id}/.gitkeep
```

After either route, `/ztn:process` picks up the new source on the next run. No SKILL.md edits required.

---

## Notes

- `/ztn:process` Step 2.1 iterates rows in declaration order, then sorts the resulting file list chronologically (Step 2.3) — declaration order is **not** processing order.
- `Family` column drives processing branch (see Family routing above). Default `transcript` if column absent (migration `002-sources-family-column.sh` populates).
- Reserved sources may have empty inbox folders. That is expected and never reported as an error.
- Deprecation protocol: retire a source by moving its row to `## Deprecated Sources` and populate the `Reason` cell. Do not delete rows. (Archive Contract Form B — `SYSTEM_CONFIG.md`.)
- The `crafted/describe-me/` exclusion is encoded declaratively via `Skip Subdirs: describe-me`. Bootstrap reads the same path through its own contract; `/ztn:process` simply skips it. Same pattern for `garmin/raw/`.
