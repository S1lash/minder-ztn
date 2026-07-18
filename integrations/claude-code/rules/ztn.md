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

1. **Resolve entities** when searching by person/project/concept:
   - `3_resources/people/PEOPLE.md` — name → ID
   - `1_projects/PROJECTS.md` — project → ID
   - `_system/registries/TAGS.md` — available tags (`tags:` axis)
   - `_system/registries/CONCEPT_NAMING.md` — concept-name format
     (`concepts:` axis: snake_case ASCII, English-only). Concepts are
     a separate axis from tags.
   - `_system/registries/AUDIENCES.md` — `audience_tags` whitelist
     (canonical 5 + active extensions)

2. **Search** (Grep/Glob, parallel):
   - **Records:** `_records/meetings/`, `_records/observations/`
   - **Knowledge:** PARA folders (`1_projects/` … `4_archive/`)
   - **Hubs:** `5_meta/mocs/`; `_system/HUB_INDEX.md` for topic overview
   - **Sources:** `_sources/` for full-text on raw transcripts when ZTN notes
     lack detail
   - Frontmatter grep: person ID, project ID, tags, types, concepts,
     audience_tags, is_sensitive, origin
   - System indexes: `_system/TASKS.md` (todos), `_system/CALENDAR.md` (events)

3. **Return synthesised results.** For each match: title, date, excerpt, tags.
   If the owner asked a question — synthesise an answer from multiple notes,
   not a raw list.

## Session recap — `/ztn-recap`

Saves the current session as a transcript under
`{{MINDER_ZTN_BASE}}/_sources/inbox/claude-sessions/` for later processing by
`/ztn:process`. Suggest after sessions with important decisions or context
worth preserving.

Adaptive: when a session produced a **verbatim artifact** the owner will reuse
as-is (toast, speech, letter, post, proposal, spec), the skill can also save it
exactly to `_sources/inbox/crafted/` — on request (`--crafted` / `--crafted-only`)
or proactively, with a bidirectional link to the recap. Crafted-only (no recap)
is valid when only the original matters.

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

## Roles — the owner's standing ZTN stewards

The owner may keep **roles**: standing agents (a project PM, a diet coach, an
observer) that watch one zone of the ZTN and track what's happening there — each
with its own name (which may be non-ASCII, e.g. «Руди»). You don't hold a list of
them; the engine resolves references at call time.

Route role-talk to the right skill — don't answer for a role from memory:

- **"спроси у Руди про…", "узнай у роли…", "ask my PM role about…", "что роль
  знает про X"** → `/ztn:role:ask` (read-only, resolves the name/id even from
  garbled STT, answers from the role's own remit). A generic "узнай у роли" with no
  name → the skill enumerates the owner's roles and asks which.
- **"давай улучшим Руди", "переучи роль", "поставь на паузу"** → `/ztn:role:edit`.
- **"заведи роль, которая…", "мне нужна роль-PM"** → `/ztn:role:add`.
- **"покажи мои роли", "какие у меня роли"** → `/ztn:role:list`.

This is a pointer, not a role registry — the skills read the live roles under the
ZTN base. Do not invent a role or its answer; if unsure a role exists, `/ztn:role:list`.
