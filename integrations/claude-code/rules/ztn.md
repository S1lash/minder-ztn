# Zettelkasten (ZTN) — Personal Knowledge Base

## What is ZTN

The owner's structured personal knowledge base — meeting notes, reflections,
decisions, people context, ideas, recaps. Three layers: Records (`_records/`),
Knowledge (PARA: `1_projects/` `2_areas/` `3_resources/` `4_archive/`), Hubs
(`5_meta/mocs/`). The values layer (`0_constitution/`) is loaded separately
as a directive via `constitution-core.md`, not searched here.

**ZTN base:** `{{MINDER_ZTN_BASE}}/`

The owner may refer to this system as `ztn`, `зтн`, `zettelkasten`, `minder`,
`minder-ztn`, `моя база`, `мои заметки`, `вторая память`, `база знаний` —
all aliases resolve to the same ZTN.

## Trigger — when to search ZTN

### Reactive (owner asks)
When the owner asks to find, recall, or reference something from their notes,
ZTN, or any alias above — **search automatically**, no slash command needed.

### Proactive (Claude initiates) — narrow signals only

Search ZTN **without being asked** only when one of these holds:

- The owner explicitly signals recurrence: "я уже думал…", "в прошлый раз…",
  "где-то записывал…", "I've thought about this before", "we discussed this".
- The owner re-derives reasoning that sounds like recovering captured material
  (working through a question that almost certainly lives in a hub).

When searching proactively, surface it: "Проверил твои заметки — нашёл
релевантное: …"

**Do NOT trigger** for: general code work, web search, git history, generic
mentions of a person without recall context, hypothetical decisions, pros/cons
discussions without explicit recall signal.

## How to search

1. **Resolve entities** when searching by person/project:
   - `_system/registries/PEOPLE.md` — name → ID
   - `_system/registries/PROJECTS.md` — project → ID
   - `_system/registries/TAGS.md` — available tags

2. **Search** (Grep/Glob, parallel):
   - **Records:** `_records/meetings/`, `_records/observations/`
   - **Knowledge:** PARA folders (`1_projects/` … `4_archive/`)
   - **Hubs:** `5_meta/mocs/`; `_system/HUB_INDEX.md` for topic overview
   - **Sources:** `_sources/` for full-text on raw transcripts when ZTN notes
     lack detail
   - Frontmatter grep: person ID, project ID, tags, types
   - System indexes: `_system/TASKS.md` (todos), `_system/CALENDAR.md` (events)

3. **Return synthesised results.** For each match: title, date, excerpt, tags.
   If the owner asked a question — synthesise an answer from multiple notes,
   not a raw list.

## Session recap — `/ztn-recap`

Saves the current session as a transcript under
`{{MINDER_ZTN_BASE}}/_sources/inbox/claude-sessions/` for later processing by
`/ztn:process`. Suggest after sessions with important decisions or context
worth preserving.

## Decision check — `/ztn:check-decision` (suggest, do NOT auto-invoke)

Surface this skill when the owner explicitly frames a decision in **values
terms**:
- "is this aligned with my principles?", "am I being consistent?"
- explicit trade-off framing between two values
- owner asks for a formal / recorded check, not just an opinion

The skill loads the **full** active constitution tree (not only the loaded
`constitution-core.md`), emits a structured verdict, and persists an Evidence
Trail citation on cited principles. That persistence is its unique value vs
inline reasoning over the loaded axioms.

**Do NOT** suggest for: generic pros/cons, architecture choices without
values content, task routing. Inline reasoning over the loaded axioms covers
those without skill overhead.
