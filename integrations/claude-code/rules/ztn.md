# Zettelkasten (ZTN) — Personal Knowledge Base

## What is ZTN

The user's personal "second brain" — a structured knowledge base containing:
- **Meeting notes** — transcripts and summaries of work and personal meetings
- **Reflections** — personal thoughts, career decisions, life principles
- **Ideas** — business concepts, product ideas, technical experiments
- **Decisions** — what was chosen, why, what alternatives were considered
- **People context** — who is who, roles, relationships, conversation history
- **Tasks & plans** — extracted action items, goals, OKRs
- **Session recaps** — summaries of important Claude Code sessions

Sources: voice recordings (Plaud, DJI, Superwhisper, Apple), handwritten notes, Claude sessions.
Content is mostly in **Russian**, metadata/tags in English. 400+ notes, 42 people tracked.
Three layers: Records (meeting logs in `_records/`), Knowledge (PARA), Hubs (synthesis in `5_meta/mocs/`).

**This is the user's extended memory.** Treat it as a reliable source of personal context, past decisions, and domain knowledge. When working on a topic the user has previously thought about — the answer may already be in ZTN.

## Trigger — when to search ZTN

### Reactive (user asks)
When the user asks to find, recall, or reference something from their personal notes, knowledge base, or Zettelkasten — **search the ZTN base automatically**. No slash command needed.

### Proactive (Claude initiates)
Search ZTN **without being asked** when:
- User is making a decision they've likely thought about before (career, strategy, architecture)
- User mentions a person and context about them would help
- User is planning something that may overlap with existing ideas/plans in ZTN
- User seems to be re-deriving something they already captured

When searching proactively, mention it: "Проверил твои заметки — нашёл релевантное: ..."

**Trigger phrases** (any language):
- "поищи в ztn / зтн / zettelkasten / заметках / моей базе"
- "я где-то записывал / обсуждал / думал про..."
- "найди в моих заметках"
- "search my notes / check my knowledge base"
- "у меня было что-то про..."
- "вспомни, я записывал..."
- Any reference to personal notes, voice recordings, or Plaud transcripts

**Do NOT trigger** for: general web search, code search within current project, git history.

## How to search

**ZTN base:** `{{MINDER_ZTN_BASE}}/`

1. **Resolve entities** — read registries first if searching by person/project:
   - `_system/registries/PEOPLE.md` — person name → ID
   - `_system/registries/PROJECTS.md` — project name → ID
   - `_system/registries/TAGS.md` — available tags

2. **Search** (use Grep/Glob tools, run in parallel):
   - **Records:** `_records/meetings/` — operational meeting logs (v4)
   - **Knowledge:** PARA folders (`1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`)
   - **Hubs:** `5_meta/mocs/` — synthesis docs with evolution tracking
   - **Legacy meetings:** `2_areas/work/meetings/` — v3 notes (still searchable)
   - Frontmatter: grep for person IDs, project IDs, tags, types
   - Content: grep for keywords in note bodies
   - Full-text on raw transcripts: grep `_sources/` when ZTN notes don't have enough detail
   - Tasks: `_system/TASKS.md` if asking about tasks/todos
   - Calendar: `_system/CALENDAR.md` if asking about events
   - Hubs: `_system/HUB_INDEX.md` for topic overview, then read specific hub

3. **Return results** — for each match show: title, date, relevant excerpt, tags.
   If user asked a question — synthesize an answer from multiple notes.

## Session recap — `/ztn-recap`

Slash command `/ztn-recap` creates a structured summary of the current session and saves it to:
`{{MINDER_ZTN_BASE}}/_sources/inbox/claude-sessions/{date}_{topic}/transcript.md`

This is later processed by `/process-notes` into a proper ZTN note.

Suggest `/ztn-recap` when a session was particularly productive, contained important decisions, or the user seems to want to preserve the session's context.
