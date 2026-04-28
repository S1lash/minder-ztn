# Sources Registry

**Last Updated:** REPLACE_WITH_DATE

Whitelist of inbox source directories scanned by `/ztn:process`. Each row describes
one source type. To add a new source: append one row here, create
`_sources/inbox/{id}/` and `_sources/processed/{id}/` (with `.gitkeep`), done —
no skill code changes required.

**Schema:**
- `ID` — canonical source identifier (matches folder name under `_sources/inbox/` and `_sources/processed/`)
- `Inbox Path` — relative path scanned by `/ztn:process` Step 2.1
- `Format Hint` — expected file name(s) inside each per-source folder
- `Description` — what kind of content lives in this source
- `Status` — `active` | `reserved` | `deprecated`

---

## Active Sources

| ID | Inbox Path | Format Hint | Description | Status |
|---|---|---|---|---|
| plaud | `_sources/inbox/plaud/` | `{ISO-timestamp}/transcript_with_summary.md` (preferred) or `transcript.md` | Plaud voice recorder transcripts | active |
| dji-recorder | `_sources/inbox/dji-recorder/` | `{date}_{topic}/transcript_with_summary.md` or `transcript.md` | DJI mic recorder transcripts | active |
| superwhisper | `_sources/inbox/superwhisper/` | `{date}_{topic}/transcript_with_summary.md` or `transcript.md` | Superwhisper dictations | active |
| apple-recording | `_sources/inbox/apple-recording/` | `{date}_{topic}/transcript_with_summary.md` or `transcript.md` | Apple Voice Memos exports | active |
| claude-sessions | `_sources/inbox/claude-sessions/` | `{date}_{topic}/transcript.md` | Claude Code session recaps via `/ztn-recap` | active |
| notes | `_sources/inbox/notes/` | `*.md` | Textual notes dropped manually | active |
| voice-notes | `_sources/inbox/voice-notes/` | `{date}_{topic}/transcript.md` | Miscellaneous voice note transcripts | active |
| crafted | `_sources/inbox/crafted/` | `*.md` (flat — top level only; `crafted/describe-me/` subdir is excluded as bootstrap reference) | Hand-written documents processed through the same pipeline | active |

---

## Reserved Sources

| ID | Inbox Path | Format Hint | Description | Status |
|---|---|---|---|---|
| openclaw | `_sources/inbox/openclaw/` | `{ISO-timestamp}/transcript.md` | OpenClaw session_end recaps | reserved — inbox empty by default; recognized by skill so no code change required when activated |

---

## Notes

- Skill scans directories in the order they appear in the Active Sources table; chronological sort of files is applied afterwards (Step 2.3 of `/ztn:process`).
- Deprecation protocol: to retire a source, move its row to a `## Deprecated Sources` section. Do not delete rows — preserves audit trail.
