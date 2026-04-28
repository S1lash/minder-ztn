---
name: ztn:process
description: >
  Process new voice transcripts from _sources/inbox/ into ZTN three-layer architecture
  (Records + Knowledge + Hubs). Full pipeline: pre-scan with People Resolution Map,
  LLM noise gate, 14-question classification (incl. content potential with type/angle),
  atomization, cross-domain scan, hub detection, per-batch subagent dispatch with self-review, people profile
  enrichment, idea living documents. Emits batch report per run and Evidence Trail
  initial entry in every new knowledge note.
disable-model-invocation: false
---

# /ztn:process — Transcript Processing Pipeline

Process new source files from `_sources/inbox/` into the ZTN three-layer architecture:
- **Records** (`_records/{meetings,observations}/`) — lightweight transcript-grounded logs (meetings = multi-speaker work; observations = solo Plaud reflections/ideas/therapy)
- **Knowledge** (PARA: `1_projects/` through `4_archive/`) — atomic insights
- **Hubs** (`5_meta/mocs/`) — synthesis and evolution tracking

**Philosophy:** Inclusion-biased. Better to over-capture than to miss a fact.
Per-batch full-pipeline subagent (Step 3) + producer self-review (Step 3.7) guarantee trustworthiness.

**Documentation convention:** при любых edits этого SKILL соблюдай `_system/docs/CONVENTIONS.md` — файл описывает current behavior без version/phase/rename-history narratives.

> **Schema expectations.** Skill polagaется на наличие системных файлов: `SOUL.md`,
> `OPEN_THREADS.md`, `CURRENT_CONTEXT.md`, `log_maintenance.md`, `log_process.md`,
> `log_lint.md`, `BATCH_LOG.md`, `batches/`, `batch-format.md`, `registries/SOURCES.md`;
> расширенная схема PEOPLE.md с колонками Tier/Mentions/Last; `## Evidence Trail` секция
> в knowledge notes. Если во время flow обнаруживается несостыковка (missing file,
> unexpected schema, inconsistent references между registries) — **не останавливаться
> и не гадать**: зафиксировать вопрос в `_system/state/CLARIFICATIONS.md` под `## Open Items`
> с type `process-compatibility`, применить conservative default, продолжить обработку.
> User разбирает на ревью.

## Arguments

`$ARGUMENTS` supports:
- `--dry-run` — list new files without processing
- `--file <path>` — process a single specific file (skip PROCESSED.md comparison)
- `--reprocess` — re-process files already in PROCESSED.md
- `--no-sync-check` — skip the data-freshness pre-flight (see below)

---

## Pre-flight: data freshness (non-blocking)

Before any heavy work, check if the owner's `origin` has commits not
yet pulled into this clone. Multi-device setups (phone records into
inbox/ on laptop A, this laptop B is a passive consumer) mean local
inbox/ may be stale.

Skip entirely if `--no-sync-check` is passed.

```bash
if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin --quiet 2>/dev/null || true
  branch=$(git rev-parse --abbrev-ref HEAD)
  remote_ahead=$(git rev-list --count "HEAD..origin/${branch}" 2>/dev/null || echo 0)
fi
```

Cases:
- `origin` not configured, or fetch failed (offline) → silently proceed.
- `remote_ahead == 0` → silently proceed.
- `remote_ahead > 0` → render owner-facing prompt:
  ```
  ⓘ origin/<branch> ahead by <N> commit(s). New transcripts may be
    waiting in inbox/ from another device.

    [s] run /ztn:sync-data first  (recommended — abort current /ztn:process)
    [c] continue with current local state  (safe — won't lose anything)
    [d] show pending commits         (then re-prompt)
  ```
  - `s`: print «owner: run `/ztn:sync-data`, then re-run `/ztn:process`», exit 0.
  - `c`: proceed (`remote_ahead` snapshot logged in batch report for traceability).
  - `d`: `git log HEAD..origin/$branch --oneline`, then re-prompt s/c.

The check is a courtesy nudge, not a gate — `c` is always safe (process
operates on local working-tree only; pulled commits won't be lost).

---

## Early Exit Check

**FIRST action — before lock, context, or pre-scan.**

Quick-scan `_sources/inbox/` subdirectories for any transcript files
(`transcript*.md` or `.md` in `crafted/`). Use Glob, not full reads.

- If `--file` or `--reprocess` flag: skip this check (files come from elsewhere).
- If 0 candidate files found: report `"No new transcripts in inbox — nothing to process."` and **exit immediately**. No lock, no context loading, no system file reads.
- If `--dry-run` with 0 files: same — report empty and exit.

This saves ~10 file reads and all pre-scan work on empty runs.

---

## Concurrency Lock

Runs only when Early Exit Check found files to process.

**Cross-skill lock check — read all three lock files first:**
- `_sources/.maintain.lock` — exists → abort «`/ztn:maintain` running, try again later»
- `_sources/.lint.lock` — exists → abort «`/ztn:lint` running, try again later»
- `_sources/.processing.lock` — exists → abort «another `/ztn:process` run in progress»

All three skills mutually exclusive.

1. After cross-skill checks pass, create `_sources/.processing.lock` with content: `{ISO timestamp} — {session info}`
2. On completion (success or failure): **DELETE** `_sources/.processing.lock`

The lock file MUST be deleted in all exit paths — normal completion, errors, and early abort.
If you find a stale lock (>2 hours old), warn the user and offer to delete it.

---

## Step 0.0: Regenerate Constitution Derived Views

Invoke `/ztn:regen-constitution` (or run `python3 _system/scripts/regen_all.py`)
as the very first action. This ensures SOUL.md Values zone,
`_system/views/constitution-core.md`, and `_system/views/CONSTITUTION_INDEX.md`
reflect the current state of `0_constitution/` before any context load.

Consistency rule for the whole platform: every pipeline that reads a derived
view regenerates first. Cost is ~100 ms; the guarantee is that nothing in
Step 1 Context Load is stale relative to source.

Failure of this step is fatal — report the underlying script error and stop.
Partial derived views would poison downstream reasoning.

---

## Step 0: Pre-Scan

Before any processing begins, scan ALL new transcripts to build shared context.

### 0.1 Quick Read

For each new transcript:
- If `transcript_with_summary.md`: read only the summary section
  (after `<transcript_to_summary_delimiter>`)
- If `transcript.md`: read first 50 lines

Extract (quick, no deep analysis):
- Date/timestamp from folder name
- Names of people mentioned
- Main topics / keywords
- Source type (derived from parent folder under `_sources/inbox/`; canonical list in `_system/registries/SOURCES.md`)

### 0.2 Build People Resolution Map

Collect ALL person names/diminutives across ALL new transcripts.
Load `3_resources/people/PEOPLE.md`.
Resolve each name against the registry.

Three tiers:

| Tier | Condition | Action |
|------|-----------|--------|
| RESOLVED | Unambiguous match to existing person in PEOPLE.md (exact name or alias) | Use existing ID. BINDING — all files must use this ID |
| NEW | No match in PEOPLE.md, enough context to create profile | Assign canonical ID in `firstname-lastname` format NOW. If last name unknown — AMBIGUOUS instead. BINDING — all files must use this ID |
| AMBIGUOUS | Could match multiple people, or unclear identity | Note the ambiguity. Defer to full-context resolution in Step 3.3. Recommendation only |

Fuzzy matching rules:
- Russian diminutives: Серёга→sergey-matveev, Ром/Рома→roman-raspadnyuk, Женя→zhenya-tochilkin, etc.
  Always resolve to the FULL ID (firstname-lastname), never to a bare first name.
- Check `aliases` field in PEOPLE.md
- **Check CLARIFICATIONS.md Resolved Archive** for known transcription artifacts
  (e.g., «Нуара»→lara-neprokina, «Трафт»→vanya-kravets, «Сотки»→maxim-andreev).
  These are RESOLVED tier — use the mapped ID directly.
- First-name-only: if only one person with that name exists → RESOLVED;
  if multiple → AMBIGUOUS

**ID format (MANDATORY):** `firstname-lastname` in transliterated lowercase.
Use the name the author uses in conversation (Дима, not Дмитрий; Леха, not Алексей).
NEVER create IDs without a last name (e.g., `vasily`, `dima`, `misha`).
If the last name is unknown from the transcript — mark as AMBIGUOUS and log to CLARIFICATIONS.md.
Exception: people known only by one name (e.g., psychologist "Татьяна") — must be explicitly justified.

The People Resolution Map is LIVE and MUTABLE. New people discovered during
processing (e.g., surfaced by §3.7 self-review or in subagent's classification
pass) are aggregated post-batch by orchestrator at Step 3.8, ensuring subsequent
runs use consistent IDs.

### 0.3 Hub Signal Matching

Load `_system/views/HUB_INDEX.md`.
Match pre-scan topics/people against the hub index.
For each file, note which hubs it likely touches.
This guides context loading in Step 3.3 — load only relevant hubs, not all of them.

---

## Step 1: Load Context

Read these system files (in parallel where possible):

0. `{{MINDER_ZTN_BASE}}/_system/docs/ENGINE_DOCTRINE.md` — operating philosophy (load FIRST; binding frame for every step). Cross-skill rules from §3 govern: surface-don't-decide, inclusion-bias-on-capture / curation-on-promotion, idempotency, the owner-LLM contract.
1. `{{MINDER_ZTN_BASE}}/_system/docs/SYSTEM_CONFIG.md` — note formats, routing rules, naming
2. `{{MINDER_ZTN_BASE}}/5_meta/PROCESSING_PRINCIPLES.md` — 8 principles + values profile
3. `{{MINDER_ZTN_BASE}}/_system/SOUL.md` — identity + current focus + working style (context only)
4. `{{MINDER_ZTN_BASE}}/_system/views/CURRENT_CONTEXT.md` — live state snapshot (context only)
5. `{{MINDER_ZTN_BASE}}/_system/state/OPEN_THREADS.md` — open strategic threads (context only)
6. `{{MINDER_ZTN_BASE}}/3_resources/people/PEOPLE.md` — people registry. Schema: `ID | Name | Role | Org | Profile | Tier | Mentions | Last`. Preserve all columns when writing
7. `{{MINDER_ZTN_BASE}}/1_projects/PROJECTS.md` — project registry
8. `{{MINDER_ZTN_BASE}}/_system/registries/TAGS.md` — tag registry
9. `{{MINDER_ZTN_BASE}}/_system/registries/SOURCES.md` — inbox source whitelist (consumed by Step 2.1)
10. `{{MINDER_ZTN_BASE}}/_system/views/HUB_INDEX.md` — hub index (if not loaded in Step 0)
11. `{{MINDER_ZTN_BASE}}/_system/state/PROCESSED.md` — already processed files
12. `{{MINDER_ZTN_BASE}}/_system/state/CLARIFICATIONS.md` — pending clarifications.
    Also scan **Resolved Archive** table: previously resolved name variants (e.g.,
    «Нуара» = Лара Непрокина, «Трафт» = Кравец). Use these to auto-resolve
    transcription artifacts in new transcripts without re-creating ambiguities.

**CLARIFICATIONS HARD RULE.** При `confidence < threshold` — не принимать решение
молча. Записать вопрос в `_system/state/CLARIFICATIONS.md` под `## Open Items`, использовать
conservative default, продолжить работу. Применяется на всех шагах skill.

**SOUL / CURRENT_CONTEXT / OPEN_THREADS — контекст-only.** Не модифицируются этим
skill. Используются для лучшего понимания priority/focus при классификации нот
и адверсариал-аудите. Их incremental обновление — ответственность `/ztn:maintain`.

---

## Step 2: Find New Files

### 2.1 Scan Directories

Load `_system/registries/SOURCES.md` — the whitelist of inbox source types.
Iterate over rows in the `## Active Sources` and `## Reserved Sources` tables;
for each row, scan the `Inbox Path` directory using the `Format Hint` as a
matching pattern. Reserved sources may be empty — that is expected and NOT an error.

To add a new source: append a row to SOURCES.md and create the corresponding
`_sources/inbox/{id}/` + `_sources/processed/{id}/` folders. No skill code changes.

Everything in `_sources/inbox/` is unprocessed — the filesystem IS the primary filter.
PROCESSED.md serves three roles:
1. **Crash recovery** — files are moved to `processed/` BEFORE processing (Step 2.4).
   If a file is in `processed/` but NOT in PROCESSED.md, it was moved but processing
   failed — needs retry.
2. **`--reprocess` support** — identifies which files to re-process from `processed/`.
3. **Audit log** — historical record of all processing operations.

NOTE: Both `_sources/inbox/crafted/describe-me/` and
`_sources/processed/crafted/describe-me/` are **excluded from processing**.
They contain AI-generated / hand-written reference profiles (PROFILE.md,
policies, identity drafts) consumed by `/ztn:bootstrap` Step 2 as the
primary SOUL source. These are NOT transcripts. The directory glob for
the `crafted` source is `_sources/inbox/crafted/*.md` (flat, top-level
only) — `describe-me/` lives in a subdir and therefore stays out of the
processing queue regardless. Bootstrap moves consumed inbox-side
describe-me/ contents to processed-side after first read.

For each folder, prefer `transcript_with_summary.md` over `transcript.md`.

### 2.2 File Selection

All files in `_sources/inbox/` are candidates for processing.

If `--file <path>`: process only that file (can be in inbox or processed).
If `--reprocess`: also scan `_sources/processed/` and re-process specified files.

### 2.3 Sort Chronologically

Sort new files by timestamp ASCENDING (oldest first).
Extract timestamp from folder name (e.g., `2026-03-31T14:38:00Z` or `2026-03-31_topic`).

Chronological order matters: earlier transcripts provide context for later ones —
within a batch via shared subagent context, across batches via the pre-scan
briefing (see §3.0.1, §3.0.3).

If 0 new files found: report "No new transcripts to process" and exit.
If `--dry-run`: list new files with timestamps, then STOP.

### 2.4 Move to Processed (before processing)

For each file to be processed:
1. Move from `_sources/inbox/{source}/{id}/` to `_sources/processed/{source}/{id}/`
2. This ensures `source:` fields in created notes point to the FINAL file location immediately
3. If processing fails after move, crash recovery detects: file in `processed/` but NOT in PROCESSED.md → needs processing

This "move-first" approach guarantees:
- `source:` fields are always correct (no temporary mismatch)
- New `plaud_insert` deliveries to `inbox/` won't be confused with in-progress files
- PROCESSED.md entry = fully processed; no entry = needs processing or retry

---

## Step 3: Process Files (per-batch full-pipeline subagents)

### Architecture

The orchestrator partitions the chronologically-sorted file list (from §2.3)
into batches and dispatches one full-pipeline subagent per batch. Each
subagent runs Steps 3.1–3.7 (read → classify → produce notes → structural
verify → self-review) for every transcript in its batch, in shared context.

Steps that REMAIN in the orchestrator and run AFTER all subagents complete:
3.7.5 (constitution alignment), 3.8 (people profiles), 3.9 (system updates),
3.10 (source integrity), and Steps 4.x / 5.x.

**Why this topology:** trust unit = «Opus + sufficient context for the work
unit». Per-batch subagent gives every transcript dedicated attention without
batch-saturation pressure on the orchestrator. Cross-transcript context
within a batch is preserved (full prior transcripts are in the same
subagent context, not summaries).

### 3.0.1 Batch Partitioning

- **Order:** chronological, by source timestamp (filename-derived) — never
  reordered. Order is preserved both within and across batches.
- **Token threshold T = 250 000** input tokens per batch (sum of all
  transcript file contents in the batch, before briefing overhead).
- **Transcript cap N = 6** per batch — secondary limit, even if T not
  reached. Caps attention dilution within shared context.
- **Algorithm:** scan files in chronological order. Pack into current batch
  while both (a) cumulative tokens ≤ T AND (b) transcript count < N. When
  either breaks, close current batch, start a new one with the next file.
  Under-filled batches are acceptable — chronological priority over packing
  density.
- **Oversize edge case:** single source > T → solo batch with that source
  alone. No splitting. Opus 1M context handles it.

### 3.0.2 Concurrency

- Max **3 parallel subagents** at any time.
- If batch count > 3, queue remaining FIFO.
- All subagents within a wave dispatched in a single tool-use message
  (multiple parallel `Task` blocks).

### 3.0.3 Subagent Invocation Contract

- Tool: `Task`, `subagent_type: general-purpose` (inherits Opus from
  orchestrator).
- Per-batch input passed in the Task prompt:
  - **Briefing (verbatim):** pre-scan results from Step 0 — PEOPLE.md,
    PROJECTS.md, HUB_INDEX.md, OPEN_THREADS, principle-candidates buffer
    state. Identical across all subagents in the same run.
  - **Batch transcripts:** ordered list of absolute paths to source files
    in `_sources/processed/...`, in chronological order.
  - **Pipeline spec:** instruction to execute Steps 3.1–3.7 for every
    transcript in the batch. The subagent reads the full transcript
    content from each path and processes them sequentially in chronological
    order, sharing context across them within the batch.
- Subagent return value (manifest):
  ```yaml
  batch_id: "{orchestrator-assigned}"
  transcripts_processed:        # one entry per transcript
    - path: "_sources/processed/..."
      records_created: ["_records/meetings/...", "_records/observations/..."]
      knowledge_notes_created: ["1_projects/..."]
      tasks_extracted: [...]
      events_extracted: [...]
      people_mentions: [...]    # raw, unresolved (orchestrator handles 3.8)
      project_mentions: [...]
      coverage_manifest: {...}  # per §3.7 — see below
      fixes_applied: [...]      # what self-review caught and fixed
      processing_log: [...]     # key decisions for debug/audit visibility
  errors: [...]                 # empty if all transcripts processed cleanly
  ```
- Subagents write produced notes to disk directly (records, knowledge notes,
  hub updates inside their scope). Subagents **do NOT** write to global
  registries (PEOPLE.md, PROJECTS.md, TAGS.md, HUB_INDEX.md,
  PROCESSED.md, log_process.md, TASKS.md, CALENDAR.md) — those are
  orchestrator-only at Steps 3.8, 3.9, 4.x.

### 3.0.4 File Completeness Invariant (hard guarantee)

- Before dispatch: orchestrator computes set `S` = all source paths
  enumerated in §2.4 (after move to `_sources/processed/`).
- After all subagents return: union of `transcripts_processed[].path`
  across all manifests must equal `S` exactly.
- Mismatch (any file missing OR any duplicate processing) → **halt**.
  No partial writes to global registries, no batch artifacts written.
  Surface explicit error in report. Counter `sources` checked against
  `len(S)` at Step 5 Completion Gate.
- Any subagent returning a non-empty `errors` list → halt.

### 3.0.5 Equal-Attention Invariant

- Single subagent prompt template applies to every batch. No fast-path for
  short transcripts, no thorough-path for long ones.
- Within a batch, subagent is instructed to give every transcript identical
  processing depth (Steps 3.1–3.7 in full per transcript) and return
  outputs in the same order as input.

### Steps that follow per transcript inside the subagent

For each transcript in the batch (in chronological order, shared context):
execute Steps 3.1 → 3.6 → 3.7 (self-review) sequentially. After each
transcript, the subagent carries forward a brief running context (3–5
sentences: entities, decisions, open threads) to the next transcript in
the same batch — this is now natural shared-context continuation, not an
explicit handoff document.

### 3.1 Read Transcript

Read full file content. Two formats:

- **`transcript_with_summary.md`**: raw transcript + LLM summary separated by
  `<transcript_to_summary_delimiter>`.
  - Part BEFORE delimiter = raw transcript (the SOURCE OF TRUTH)
  - Part AFTER delimiter = LLM summary (use as classification HINT, never as authority)
- **`transcript.md`**: raw transcript only.

### 3.2 LLM Noise Gate

Ask a single binary question about the transcript content:

> "Is this genuine speech content (a real conversation, reflection, or dictation)
> or is it noise (accidental recording, audio artifacts, unintelligible fragments,
> system test output)?"

- **Genuine** → proceed to Step 3.3
- **Noise** → skip this file. Log: `SKIPPED (noise): {path} — {reason}`
  Do NOT add to PROCESSED.md (so it can be re-evaluated if the noise gate
  was wrong — the file stays "new" until genuinely processed).
- **Inclusion-biased:** if in doubt, classify as genuine and process.

### 3.3 Semantic Context Loading

Before classification, load relevant context for THIS specific transcript:

1. **Resolve people** via the People Resolution Map (from Step 0.2):
   - RESOLVED / NEW → use the assigned ID directly
   - AMBIGUOUS → read full transcript context to attempt resolution.
     If still ambiguous: make best guess, log to CLARIFICATIONS.md

2. **Load matching hubs** (from Step 0.3 signals):
   - Read ONLY "Текущее понимание" section (includes subsections: Ключевые выводы,
     Открытые вопросы, Активные риски)
   - Do NOT load full hub files — prevents context window bloat

3. **Grep related notes** for context:
   - **Recent (last 2-3 weeks):** by matched people/projects/topics.
     Read titles and frontmatter only, not full content.
   - **Topic-deep (any age):** if Q10/Q12 will need to check existing knowledge
     on a specific topic (e.g., for hub threshold counting), grep for knowledge
     notes with matching `topic/` or `project/` tags across all time.
     Read frontmatter only — enough to count and detect evolution.
   - Purpose: detect evolution, avoid redundancy, enable accurate hub threshold checks

4. **Resolve projects** against PROJECTS.md registry

5. **Leverage existing ZTN knowledge** (ADR-017):
   For each topic, consider:
   - Is this NEW information?
   - Is this CONFIRMATION of existing knowledge?
   - Is this CONTRADICTION of existing understanding?
   - Is this EVOLUTION of a previous position?

### 3.4 LLM Classification

Answer these 14 questions for each transcript, using the loaded context.
Be specific and cite evidence from the transcript.

**== SOURCE CLASSIFICATION ==**

1. SOURCE TYPE: What kind of source is this?
   Options: work-meeting | personal-reflection | therapy | idea-brainstorm | mixed
   Evidence: [quote from transcript that supports classification]

2. LANGUAGE: What is the primary language of the transcript?
   (Note content will be written in this language. Section headers follow the language.)

**== CONTENT ANALYSIS ==**

3. KEY TOPICS: List 2-5 main topics discussed.
   For each: [topic] — [one-sentence summary]

4. DECISIONS MADE: List any decisions (explicit OR implicit consensus).
   For each decision:
   a) What was decided
   b) What alternatives were considered (even if not explicitly stated — infer from context)
   c) Who made or influenced the decision
   d) Why this choice (reasoning, constraints)
   e) Scope: FINAL (committed) or TENTATIVE (still open to revision)
   f) Supersedes: does this override a previous decision? If yes, which one?
      Check loaded hubs for prior decisions on the same topic.

   Decision markers to scan for: «решили», «договорились», «будем делать», «выбрали»,
   «утвердили», «отложили», «пока так», «по итогу»
   Implicit consensus markers: repeated agreement, lack of objection to a proposal,
   "ну давай так и сделаем", default acceptance

5. ACTION ITEMS: List any tasks, to-dos, commitments.
   For each: [task] — [who is responsible] — [deadline if mentioned]
   Classify each as ACTION / WAITING / DELEGATE per the rules in SYSTEM_CONFIG.md
   (section "Task Format → Правила классификации"). This classification feeds
   TASKS.md aggregation in Step 4.1 and lets Waiting/Delegate items inherit the
   `@person-id` prefix in the aggregate file.

6. INSIGHTS: List any non-obvious realizations, connections, or understanding shifts.
   For each: [insight] — [what changed in understanding]

7. PEOPLE: List ALL people mentioned with their role/context.
   Scan the ENTIRE transcript for names, diminutives, and references.
   Mark as: [participant] (was in the meeting) or [mentioned] (talked about)
   For new people not in registry: [name] — [role] — [org] — [context]

**== STRUCTURAL DECISIONS ==**

8. SPLITTING: How many distinct knowledge streams exist in this transcript?
   A "knowledge stream" = self-contained topic that deserves its own note.
   Consider: Can this topic be understood WITHOUT the other topics in this transcript?
   - If yes → separate note
   - If no → part of the same note

   For each stream: [topic] — [type: decision/insight/reflection/idea/technical]

9. RECORD: What kind of record fits this transcript?
   Records are MANDATORY for every transcript-grounded source so that knowledge
   notes always anchor to a record-id (wikilink), never to a raw transcript path.

   - SOURCE TYPE = work-meeting → **meeting record** in `_records/meetings/`
     Filename: `YYYYMMDD-meeting-{main-participant}-{topic-slug}.md`
     Body: summary (2-3 sentences), key points (ALL significant — Principle 1),
     decisions, action items, participants, source link.

   - SOURCE TYPE ∈ {personal-reflection, idea-brainstorm, therapy} (solo speaker,
     no meeting context) → **observation record** in `_records/observations/`
     Filename: `YYYYMMDD-observation-{topic-slug}.md`
     Body: speaker, summary (2-3 sentences), key points, mood/context if salient,
     source link. NO decisions / action items sections (those live in knowledge
     notes that link back via `extracted_from:`).

   - SOURCE TYPE = mixed → split into the dominant kind by majority of content,
     or create both a meeting record AND an observation record if two distinct
     transcript segments warrant it. Document the choice in Q9 evidence.

   Output: proposed filename(s), kind, speaker (for observation), summary, key points.

10. KNOWLEDGE EXTRACTION: For each knowledge stream from Q8:
    - Should this become a standalone Knowledge Note?
    - Threshold: Does it have VALUE beyond the meeting context?
      (A status update = no. An architectural decision = yes. A career insight = yes.)
    - If yes: proposed filename, folder, types, domains
    - EXISTING KNOWLEDGE CHECK (use Step 3.3 topic-deep grep results):
      Does a note on this exact topic already exist?
      If yes: is this NEW, CONFIRMATION, CONTRADICTION, or EVOLUTION?

11. HUB CONTINUITY: Does this transcript continue/update any existing hub?
    Check loaded hubs. For each match:
    - Hub ID
    - What new information does this transcript add?
    - How does "Текущее понимание" need to change?
    - New entry for Хронологическая карта: [date] [note-ref] [type] [what happened]
    - New entry for Changelog: [date] [what shifted]

12. NEW HUB: Does any topic now reach the 3+ knowledge notes threshold?
    Count existing KNOWLEDGE notes touching this topic (use Step 3.3 topic-deep
    grep results + notes created earlier in this batch). If 3+ including
    this one → propose new hub.
    (Records do NOT count toward the threshold — only knowledge notes.)
    - Proposed hub ID: hub-{topic}
    - Initial "Текущее понимание" draft
    - Backfill хронологическая карта from existing notes

13. CROSS-DOMAIN: Is there anything here that changes understanding in ANOTHER domain?
    Threshold: ~30% confidence. If it MIGHT be relevant → capture the link.
    - [insight from domain A] → [relevance to domain B]
    - Proposed wikilink or hub update

14. CONTENT POTENTIAL: Assess each knowledge stream from Q8 for public sharing value.

    Three fields (all OPTIONAL — omit entirely if no public value):

    #### content_potential: high|medium

    `high` — at least ONE is true:
    - Author shares personal experience/story illustrating a professional principle
    - Specific technical insight, approach, or architectural decision
    - Opinion/position on a topic discussed in the industry (AI, fintech, management, etc.)
    - Career, leadership, or management reflection with concrete examples
    - Business or product idea with an original angle
    - Workflow, process, or tool usage pattern useful to others
    - Personal reflection or life insight with universal resonance

    `medium` — at least ONE is true:
    - Kernel of interesting thought, not yet fully developed
    - Topic is potentially public, but current context is too personal/company-specific — needs rework
    - Fragment that could become part of a larger post when combined with other notes

    #### content_type: expert|reflection|story|insight|observation

    Set when `content_potential` is set. Determines the NATURE of the note (single value):

    | Type | What it is | Example |
    |------|-----------|---------|
    | `expert` | Professional/technical knowledge, architectural decisions, domain expertise | "DBA alias vs merchant profiles" |
    | `reflection` | Personal introspection, psychology, self-analysis, therapy insights | "Валидация и отвержение комплиментов" |
    | `story` | Narrative arc — career journey, personal experience, travel, life event | "From Java Dev to TPM: 9-year journey" |
    | `insight` | Non-obvious connection, counter-intuitive observation, pattern recognition | "AI adoption в QA: творческое сопротивление — не страх замены" |
    | `observation` | Lightweight seed thought, casual noticing, not yet developed | "Music's role in creative thinking" |

    `content_type` is the dominant type of the NOTE, not the post. A therapy reflection
    that can be reframed as a management insight for LinkedIn is still `reflection` —
    the reframing is `/ztn:check-content`'s job when generating drafts.

    #### content_angle: string OR array of strings

    Each angle = one sentence hook — the "why would someone read this?" framing.

    **Single angle** (most notes):
    ```yaml
    content_angle: "Почему делегирование — это не про контроль, а про детский перфекционизм"
    ```

    **Multiple angles** (when a note can produce posts with different framings):
    ```yaml
    content_angle:
      - "Childhood perfectionism → adult control patterns: a therapy insight"
      - "Why delegation is hard for tech leads — it's not about trust"
    ```

    Multiple angles typically arise when a note sits at the intersection of domains
    (personal + professional, technical + management). Each angle may target a different
    audience or platform — `/ztn:check-content` uses angles to cluster the note into
    multiple theme groups and generate distinct drafts.

    **Default: one angle.** Only add multiple when genuinely distinct framings exist.
    Don't force it — one good angle is better than two weak ones.

    #### Bias and filtering

    **Bias: inclusion.** When in doubt, mark `medium`. Do NOT skip.
    Filtering is `/ztn:check-content`'s job, not this step's.
    False positives are cheap; false negatives lose content opportunities.

### 3.5 Create Outputs

Based on the 14-question classification, create outputs. Fully automatic, no confirmation needed.

#### A) Records → RECORD in `_records/{kind}/`

Create exactly one record per transcript. Two kinds:

##### A1) Work meetings → `_records/meetings/`

Filename: `YYYYMMDD-meeting-{main-participant}-{topic-slug}.md`
Template: `{{MINDER_ZTN_BASE}}/5_meta/templates/record-template.md`

Frontmatter: `layer: record`, `kind: meeting` (omit `kind` for backward compat —
absence implies meeting; new records SHOULD include it explicitly).

Record contains:
- Summary (2-3 sentences)
- Ключевые пункты (bullets — ALL significant points, not just "important" ones.
  Principle 1: Capture First. Even a one-line mention of Georgian clients goes in.)
- Решения (with rationale — from Q4 enhanced format)
- Action Items (with `- [ ]`, person link `[[person-id]]`, `^task-{slug}`)
- Упоминания людей (with context: role in this meeting, participant vs mentioned)
- `## Source` section with relative path to raw transcript

NO `<details>` blocks. NO raw transcript duplication. The `## Source` section
links to `_sources/processed/` for full-text access.

##### A2) Solo transcripts → `_records/observations/`

Use for personal-reflection / idea-brainstorm / therapy / any single-speaker
Plaud capture where there is no meeting to log. The observation record is the
canonical anchor for any knowledge notes extracted from this transcript — it
is what their `extracted_from:` and `## Evidence Trail` wikilink points to.

Filename: `YYYYMMDD-observation-{topic-slug}.md`
Template: `{{MINDER_ZTN_BASE}}/5_meta/templates/observation-record-template.md`

Frontmatter:
```yaml
---
id: YYYYMMDD-observation-{topic-slug}
title: "Наблюдение: {topic on transcript language}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript_with_summary.md
recorded_at: {ISO timestamp from transcript folder name, when known}

layer: record
kind: observation
speaker: {person-id of the owner from SOUL.md Identity; "unknown" if ambiguous}
people:
  - {anyone mentioned by name}
projects:
  - {projects touched if any}
tags:
  - record/observation
  - person/{speaker}
  - topic/{key-topic}
---
```

Body:
- `## Summary` — 2-3 sentences capturing what the recording was about
- `## Ключевые пункты` — bullets covering ALL significant points (same Principle 1)
- `## Контекст / настроение` — optional: where/when/mood if salient (e.g., «в машине после встречи с Димой», «после терапии»)
- `## Упоминания людей` — only if names came up (otherwise omit)
- `## Source` — transcript path, recorded timestamp

NO `## Решения` / `## Action Items` sections. Decisions and tasks belong in
knowledge notes, where they earn their own structure and link back via
`extracted_from: {observation-record-id}`.

##### Routing summary

| SOURCE TYPE (Q1)                                | Record kind | Folder                  |
|-------------------------------------------------|-------------|-------------------------|
| work-meeting                                    | meeting     | `_records/meetings/`    |
| personal-reflection / idea-brainstorm / therapy | observation | `_records/observations/`|
| mixed                                           | both kinds  | split per dominant segment |

#### B) Knowledge streams → KNOWLEDGE NOTE in PARA folders

For each knowledge stream identified in Q8/Q10:

Filename mapping by primary type:
- decision → `YYYYMMDD-decision-{topic}.md`
- insight → `YYYYMMDD-insight-{topic}.md`
- reflection → `YYYYMMDD-reflection-{topic}.md`
- idea → `YYYYMMDD-idea-{topic}.md`
- technical → `YYYYMMDD-technical-{topic}.md`

Folder: use routing logic from SYSTEM_CONFIG.md (Folder Routing Logic section).
Template: `{{MINDER_ZTN_BASE}}/5_meta/templates/note-template.md`

Frontmatter MUST include `layer: knowledge`.
If extracted from a record: add `extracted_from: {record-id}` to frontmatter.
`contains:` block is OPTIONAL — include only if note has tasks or ideas.

If Q14 determined content_potential for this knowledge stream:
  - Add `content_potential: high` or `content_potential: medium` to frontmatter (after `priority:`)
  - Add `content_type: {type}` — one of: expert, reflection, story, insight, observation
  - Add `content_angle:` — string (one angle) or array (multiple distinct framings)
  - All three fields are OPTIONAL — omit entirely if Q14 found no public value

Decision notes (ADR-013 enhanced):
- Body includes: what was decided, alternatives considered, reasoning, who decided, scope
- If superseding a previous decision: add `supersedes: {previous-note-id}` to frontmatter
- The superseded note is NOT modified — both versions persist (Principle 5: Evolution Tracking)

#### Idea Notes — Living Document Pattern

When a knowledge stream's primary type is `idea`:

1. **SEARCH** existing ideas before creating a new file:
   - Grep `3_resources/ideas/business/` and `3_resources/ideas/products/` frontmatter
   - Match signals (all contribute to confidence):
     a) Tag overlap: compare `topic/*` and `project/*` tags (weight: 40%)
     b) Title/keyword overlap: extract 2-4 key words from new idea title,
        compare against existing titles and aliases (weight: 35%)
     c) Subfolder match: same subfolder (business/ or products/) adds base score (weight: 25%)

2. **Decision thresholds:**
   - **≥ 80% confidence — MATCH:** Update the existing idea note:
     - READ existing note
     - APPEND section: `## Update YYYY-MM-DD` with: source link, new context, what changed/evolved
     - Update `modified:` date in frontmatter
     - Increment `mentions:` count (add field if missing, default to 1 for existing notes)
     - Add additional source to `## Source` section
     - Do NOT create a new file
   - **50-79% confidence — AMBIGUOUS:** Create new note (safe default).
     Add `mentions: 1`. Log to CLARIFICATIONS.md:
     "New idea [{title}] may be related to existing [[{existing-id}]]. Consider merging."
   - **< 50% confidence — NO MATCH:** Create new idea note as before.
     Add `mentions: 1` to frontmatter.

3. **Edge cases:**
   - Multiple matches ≥ 80%: pick highest confidence, log runner-ups to CLARIFICATIONS
   - Cross-subfolder match (business↔products): treat as AMBIGUOUS regardless of score

Body structure for knowledge notes:
- ## Контекст — where/when this came up
- ## Ключевая мысль — the core insight/decision/idea (with `^insight-{slug}` anchor if needed)
- ## Применение / Следствие — so what? how does this change things?
- ## Связи — `[[wikilinks]]` to related notes, hubs, people
- ## Evidence Trail — append-only audit trail of knowledge (see below)
- ## Source — link to raw transcript

#### Evidence Trail (mandatory for new knowledge notes)

Every new knowledge note (`layer: knowledge`, any type: decision / insight / reflection /
idea / technical) MUST include a `## Evidence Trail` section placed **before** `## Source`.
Records (`layer: record`) and people profiles do NOT get Evidence Trail.

Format:

```markdown
## Evidence Trail

- **YYYY-MM-DD** | [[{source-record-or-note-id}]] — {≤1-2 sentences: what was extracted / confirmed / contradicted / raised}
```

Rules:
1. **Initial entry (N ≥ 1)** on creation:
   - Typically 1 entry — the source record/transcript this note was extracted from.
   - 2+ entries when the note has multiple origins (e.g., `extracted_from:` + explicit `related_to:` references that point at other source records in the same batch).
2. **Ordering:** newest-first. New entries prepended at the top of the list.
3. **Append-only:** never delete or rewrite entries. Corrections land as new entries noting the previous one was inaccurate.
4. **Matching is limited to `type: idea` Living Document pattern.** For other types, a new transcript that touches the same topic produces a new note (linked via `supersedes:` / `related_to:`) with its own initial Evidence Trail — NOT an append to the existing note's Trail. Rich matching for decision / insight / reflection / technical is `/ztn:lint` territory.
5. **Legacy notes without Evidence Trail are valid.** Never backfill existing notes via `/ztn:process` — that is `/ztn:lint` territory through CLARIFICATIONS suggestions.
6. **Multiple `## Evidence Trail` sections in one file** (anomaly, e.g., human edit): append to the first section encountered. Do NOT merge or delete the others. Raise an item in `_system/state/CLARIFICATIONS.md` `## Open Items` with type `evidence-trail-anomaly` (and this increments `clarifications_raised`).

#### Idea Living Document — Evidence Trail append + dedup

Extension of the Living Document pattern above (≥ 80% match branch):

- After reading the existing idea note and before writing, **prepend** a new entry to its `## Evidence Trail` section:
  `- **{today}** | [[{new-source-id}]] — {1-2 sentence summary of what this transcript adds}`
- **Dedup by (date + source-id):** if the existing Trail already contains an entry with the same date AND same `[[source-id]]`, **skip the prepend** (do NOT create a duplicate). This makes `--reprocess` idempotent and protects against re-run dirt.
- All other Living Document side effects (Update section, `modified:`, `mentions:`, additional Source link) remain as before.

#### `--reprocess` semantics for Evidence Trail

- **Decision / insight / reflection / technical / initial idea:** the note is fully rewritten by the reprocess run → the Evidence Trail is **reset** → write exactly one fresh initial entry with the reprocess date and the source link. Prior Trail history is discarded (it reflected a classification we are deliberately revising).
- **Idea via Living Document update during `--reprocess`:** apply the same (date + source-id) dedup described above. If the source is already present in the Trail → skip the prepend. This makes `--reprocess` idempotent at the Trail level.
- **Legacy notes without Evidence Trail** that the skill did NOT create: untouched. Backfill is `/ztn:lint` territory.

For personal content (reflections, therapy, ideas):
- Write in the language of the original transcript
- Preserve texture: direct quotes with `> "цитата"`, emotional context, narrative arc
- No record created — only knowledge notes

Primary note: When N knowledge notes come from one transcript, all reference
the source via `source:` in frontmatter. The primary note (closest to the main
topic) is first. Others include `related_to: {primary-note-id}` in frontmatter
(analogous to `extracted_from` and `supersedes` — relationship metadata belongs
in frontmatter, not content).

#### C) Hub updates → UPDATE existing hub in `5_meta/mocs/`

For each matching hub (from Q11):
1. Read current hub file
2. REWRITE "Текущее понимание" — integrate new information with existing understanding.
   This is a FULL REWRITE of the section, reflecting the latest synthesized state.
   Written in first person, as a summary for future self.
3. ADD row to "Хронологическая карта" — date, `[[note-ref|title]]`, type, what happened
4. ADD entries to "Связанные знания" — decisions, insights, cross-domain links
5. ADD entry to "Changelog" (newest first) — date + what shifted in understanding
6. Update `modified` date in frontmatter
7. Update `people`, `projects` lists if new entries

#### D) New hub creation → CREATE in `5_meta/mocs/`

When a topic reaches 3+ KNOWLEDGE notes (Q12):
1. Use template: `{{MINDER_ZTN_BASE}}/5_meta/templates/hub-template.md`
2. Fill "Текущее понимание" — synthesize from all related notes
3. BACKFILL "Хронологическая карта" — rows for ALL existing related notes
4. Fill "Связанные знания" — decisions, insights, questions
5. Fill "Changelog" — initial entry
6. Add to `_system/views/HUB_INDEX.md`

Hub ID format: `hub-{topic-slug}` (e.g., `hub-api2-p2p`, `hub-delegation-pattern`)

#### E) Cross-domain insights

If significant enough (from Q13):
- Create standalone knowledge note in the TARGET domain
- Link back to source note and source domain hub
- Update target domain hub if it exists

If minor:
- Add `[[wikilink]]` in source note's "Связи" section
- Mention in hub's "Связанные знания → Cross-Domain" section

### 3.6 Structural Verification

After creating EACH note (record or knowledge), verify:

- [ ] Frontmatter is valid YAML — no syntax errors, all required fields present
- [ ] `layer:` field is correct — `record` for records, `knowledge` for knowledge notes
- [ ] People IDs in `people:` exist in PEOPLE.md OR will be created in Step 3.8
- [ ] Project IDs in `projects:` exist in PROJECTS.md
- [ ] Tags follow conventions from TAGS.md (format: `type/xxx`, `domain/xxx`, etc.)
- [ ] File placed in correct PARA folder per SYSTEM_CONFIG.md routing rules
- [ ] `source:` points to a real file path in `_sources/processed/`
- [ ] `extracted_from:` (if present) references an existing or just-created record ID
- [ ] `supersedes:` (if present) references an existing note ID
- [ ] ID matches filename (without `.md` extension)

If any check fails, fix immediately before proceeding.

### 3.7 Self-Review (subagent-internal coverage check)

**Runs inside the subagent**, per transcript, **after** §3.6 structural
verification, **before** the subagent moves to the next transcript or
returns its manifest. NON-OPTIONAL. Every transcript must produce a
coverage manifest.

**Purpose:** producer-side completion ritual. The subagent has just
processed a transcript and produced notes — before declaring done, it
re-anchors itself to the source one more time through the four scan
lenses, generates an explicit coverage manifest, and reconciles the
manifest against its own produced notes. Mismatches are fixed in place.

**Trust model:** this is producer-trust under «Opus + full context», not
external verifier-redundancy. The subagent is the authority on its own
output; self-review is the explicit finishing step that ensures every
transcript got the four-lens treatment uniformly. Limitation acknowledged:
shared blind spots between the main pass and the self-review pass cannot
be caught here — that is the cost of the producer-trust model.

#### 3.7.1 Generate coverage manifest

For the current transcript, anchor back to the **raw transcript content**
(skip any LLM-generated summary section in `transcript_with_summary.md`)
and produce four lenses:

a) PEOPLE SCAN: every person name, diminutive, or contextual reference
   («мой техлид», «тот парень из QA»). For each: participant or mentioned?

b) TOPIC SCAN: every topic shift or subject change. For each: one-sentence
   summary of what was discussed.

c) DECISION SCAN: every decision marker.
   Explicit: «решили», «договорились», «будем делать», «выбрали», «утвердили»,
   «отложили», «пока так», «по итогу».
   Implicit: agreement without objection, «ну давай так», default acceptance.
   For each: what was decided, by whom, with what reasoning?

d) ACTION SCAN: every commitment marker.
   «сделаю», «до пятницы», «надо будет», «я возьму», «запланирую».
   For each: who committed, to what, by when?

Quote literally where quotes matter. Be exhaustive — completeness here is
the entire value of the step.

#### 3.7.2 Reconcile against produced notes

For each item in the manifest:
- PRESENT in produced note(s) → MATCHED. Verify meaning preserved.
- ABSENT from produced notes → MISSED.

For each claim in the produced notes:
- Anchored to a manifest item or to a clear inference from one → OK.
- No basis in source → HALLUCINATED.

Failure types and fixes (apply in place, before returning):
- **MISSED** — fact in source, absent from note. Add to the note.
- **DISTORTED** — fact in note, meaning changed from source. Correct.
- **HALLUCINATED** — fact in note, no source basis. Remove.
- **THIN DECISION** — decision captured but lacks alternatives/reasoning/scope. Enrich.
- **UNLINKED REVISION** — decision updates a prior one without `supersedes:`. Add link.

#### 3.7.3 Manifest output

Subagent attaches per-transcript to its return manifest:
- `coverage_manifest`: the four scan lists.
- `fixes_applied`: list of `{type, target_note_id, brief}` for every fix.
- If no fixes were needed, `fixes_applied: []` — explicit empty, not omitted.

### 3.7.5 Constitution Alignment Check

For every record produced in this run with `types:` array containing
`decision`, run an alignment check against the active constitution tree.
Records carrying heavy `fixes_applied` from §3.7 self-review (≥ 3 fixes,
or any HALLUCINATED fix) are deferred — content reliability borderline,
do not generate drift clarifications until reviewed.

This step runs in the **orchestrator**, after all subagents complete and
their manifests are aggregated.

**How:** invoke `/ztn:check-decision` per decision record. Pass:

- `situation` = one-sentence distillation of the decision (context + chosen
  path + stated rationale from the record)
- `record_ref` = wiki-link to the record (meeting or observation), e.g. `[[YYYYMMDD-meeting-...]]` or `[[YYYYMMDD-observation-...]]`
- `dry_run: false` (Evidence Trail append on cited principles is desired)

**Verdict handling:**

| Verdict | Action |
|---|---|
| `aligned` | No CLARIFICATION. `/ztn:check-decision` already appends `citation-aligned` to cited principles' Evidence Trail and bumps their `last_applied`. |
| `violated` with per-decision confidence ≥ 0.8 | Raise CLARIFICATION of type `principle-drift`. Include: quote from the record, the violated principle id, short "why this looks like drift" rationale, options to resolve (confirm deviation → refine principle; reconsider decision; mark exception). |
| `tradeoff` | Raise CLARIFICATION of type `principle-tradeoff` (info-level). Include: the two principles in tension, the direction the record chose, invitation to log explicit reasoning back into the record. |
| `no-match` | No CLARIFICATION. Not every decision touches the constitution. |

**CLARIFICATION item format** — same schema as other items under `## Open Items`:

```markdown
### YYYY-MM-DD — principle-drift: {principle.title}

**Type:** principle-drift
**Subject:** {principle.id}
**Source:** _records/{path}
**Action taken:** raised by /ztn:process Step 3.7.5 after /ztn:check-decision verdict violated (confidence 0.85)
**Quote:** > «{1–3 verbatim sentences from the record context}»
**Uncertainty:** Decision `{record.chosen}` appears to contradict `{principle.statement}`.
**To resolve:** confirm drift is intentional (refine principle or add exception note), reconsider the decision, or mark as a one-off exception with rationale.
```

`principle-tradeoff` uses the same shape with two principle refs in **Subject:**.

**Invariants for this sub-step:**

- Do not edit principle body. `/ztn:check-decision` handles L1 writes
  (Evidence Trail + `last_applied`); this step only raises CLARIFICATIONS.
- Do not create new principles. Pattern extraction into candidates is
  `/ztn:maintain`'s job, not `/ztn:process`.
- If `/ztn:check-decision` returns with an error (e.g. empty visible tree),
  log the failure in the processing record but do not block the batch —
  continue to Step 3.8. Constitution checking is additive, not a gate.

**Cost / latency note.** Each decision invokes `/ztn:check-decision`, which
runs Opus. On a Max subscription this is not a cost concern, but batches
with many decision records will add noticeable latency. If a batch starts
producing > 10 decision records per run, consider a single LLM call that
classifies the whole batch against the tree (one prompt, multi-record
reasoning) — that optimisation is not implemented today because current
batch sizes sit below that threshold and the per-record contract is
simpler to audit in `log_process.md`.

### 3.8 People Profiles

**This step APPLIES the canonical rules from `_system/docs/SYSTEM_CONFIG.md` → "Data & Processing Rules".
Those rules are the single source of truth. If a rule changes, update SYSTEM_CONFIG, not this step.**

Applicable rules (all mandatory, no silent compromise):

1. **People inclusion — `inclusion-biased`.**
   - Every person with tier RESOLVED or NEW from the People Resolution Map (Step 0.2) who is mentioned in the transcript content (not noise) → include in the note's `people:` frontmatter array.
   - Do NOT apply "central to note" heuristic — it is subjective and a source of gaps.
   - **Bare first name** (AMBIGUOUS and cannot be resolved to a `firstname-lastname` ID) → do NOT add to `people:`. Default path: **append to `_system/state/people-candidates.jsonl`** via `python3 _system/scripts/append_person_candidate.py` (one entry per distinct mention — if the same bare name appears in N different transcripts in a batch, that's N appends). The buffer is aggregated weekly by `/ztn:lint` Scan C.5, which promotes recurring / information-rich candidates to CLARIFICATIONS. This keeps one-off mentions out of the user's resolution queue.

     **High-importance escape hatch.** Bypass the buffer and raise a CLARIFICATION immediately (the pre-2026-04-24 behaviour) ONLY when ANY of these signals are present:
     - Bare name belongs to an external/client meeting (transcript contains `meeting` + `external` markers, or the session is clearly a 1:1 with an outside party).
     - Full surname is present elsewhere in the same transcript but wasn't matched due to STT artifacts (you have enough info to resolve NOW).
     - Explicit user tagging `@resolve-now` in transcript or inbox override file.
     - Role + context are fully specified in a single mention (e.g. "новый Head of X", "CEO of {company}") — promoting later adds no info.

     In all other cases: buffer append, no CLARIFICATION, `clarifications_raised` counter NOT incremented for this mention (buffer appends are reported separately as `people_candidates_appended`).

     **Invocation:**
     ```bash
     python3 _system/scripts/append_person_candidate.py \
       --name "Антон" \
       --date {record.created} \
       --source {source-path-excerpt} \
       --note-id {produced-note-id} \
       --quote "{1–3 verbatim sentences around the mention}" \
       [--role-hint "{role inferred from context}"] \
       [--related-people id1,id2] \
       [--suggested-id {id if fuzzy-match suggests one}] \
       [--high-importance]  # only if escape-hatch triggered — but in that case ALSO raise a CLARIFICATION; the buffer line serves as audit trail
     ```

     Quote + role_hint + related_people are optional but strongly encouraged — they make weekly aggregation + promotion decisions deterministic (lint reads the buffer, never re-reads transcripts).

**CLARIFICATION item formatting requirement (person-identity / people-bare-name / people-identity).**

> Applies ONLY when the high-importance escape hatch (above) triggers. For routine one-off bare names — append to the candidates buffer instead; `/ztn:lint` Scan C.5 will emit the CLARIFICATION on aggregation if promotion rules fire.

The item body MUST include:

1. **`**Quote:**` field** — verbatim transcript fragment (≥1 full sentence, ideally 2–3) around the mention. User resolves без opening source transcript.
2. **`**Context:**` field** (mandatory) — 2–4 sentence paragraph self-contained для LLM review session. Includes: what ambiguity is about, why uncertain, related entities inline (wikilinks/ids), relevant Focus/People context, 1–2 candidate resolutions с brief pros/cons.

Also include nearby topic/project markers when they help disambiguate (often more useful than role heuristic alone).

**Distinction Quote vs Context:**
- `Quote` = verbatim fragment из транскрипта (deterministic, source-grounded)
- `Context` = LLM-synthesized surrounding understanding (what item is *about*, not what was said verbatim)

Template:

```markdown
### YYYY-MM-DD — «{name-as-transcribed}» в T{N} ({timestamp}) — {one-line hint}

**Type:** people-bare-name | person-identity
**Subject:** {bare-name string OR candidate person-id}
**Source:** _sources/processed/{path}
**Suggested action:** resolve-bare-name | create-profile | dismiss
**Confidence tier:** surfaced (process always surfaces — never auto-applies identity)
**Action taken:** {what the pipeline did}

**Quote:** > «{1–3 verbatim sentences around the mention from the transcript}»

**Context:** {2–4 sentence paragraph: what ambiguity is about, PEOPLE.md candidates if any, related hub/project context, 1–2 candidate resolutions с brief rationale}

**Uncertainty:** {what is unclear and why}
**To resolve:** {what the user needs to do}
```

2. **Mention counting — `1-per-file`.**
   - When a person first appears in this file (in `people:` frontmatter OR as subject of the record/note), `Mentions` in PEOPLE.md += **1**.
   - Repeated occurrences of the SAME person within the SAME file do NOT increment further. Monotonic.
   - Decrements only happen on manual deletion or `/ztn:lint` dedup (out of scope here).

3. **PEOPLE.md 8-column schema preservation.**
   - Any write to PEOPLE.md (insert OR update) preserves all 8 columns: `ID | Name | Role | Org | Profile | Tier | Mentions | Last`.
   - On update of an existing row: change only the columns that changed (typically `Mentions`, `Last`, sometimes `Role`/`Org`). Never drop or reorder columns.

4. **Tier assignment — only on insert of a NEW person.**
   - If a profile was created in `3_resources/people/{id}.md` during this step → `Tier = 1`.
   - Otherwise → `Tier = 3` (default for newly added entries without profile).
   - **Existing persons are NEVER re-tiered by this skill.** Tier promotion (3 → 2, 2 → 1) is `/ztn:maintain` responsibility. Demotion requires human-in-the-loop via CLARIFICATION (never automatic).

For each person mentioned in the transcript (using the People Resolution Map):

1. **If exists in PEOPLE.md:**
   a) **New context check** — does the transcript reveal any of:
      - New role, title, or responsibility?
      - Organizational change (team move, promotion, new project)?
      - New relationship context with the author or other people?
      - Expressed opinion, skill, or competency not previously captured?
      - Key quote or characterization?
   b) If yes to ANY: READ current profile (`3_resources/people/{id}.md`)
      → APPEND new information to `## Контекст` section (don't overwrite existing text)
      → Update `## Ключевые темы` if new topic areas emerged
   c) **ALWAYS** add backlink to `## Упоминания`:
      `- [[{note-id}|{brief context}]] — YYYY-MM-DD`
      This is NOT optional — every mention in every processed transcript gets a backlink.
   d) Update row in PEOPLE.md:
      - `Mentions` += 1 (increment; dedup rule: 1 per file per person, не per-utterance)
      - `Last` = note's `created` date (YYYY-MM-DD)
      - `Tier` — не пересчитывать здесь (это задача `/ztn:maintain`). Оставить текущее значение

2. **If NEW (from People Resolution Map or discovered during audit):**
   - Create profile in `3_resources/people/{id}.md` using
     `{{MINDER_ZTN_BASE}}/5_meta/templates/person-template.md`
   - Add row to `3_resources/people/PEOPLE.md`. Все 8 колонок обязательны:
     - `ID`, `Name`, `Role`, `Org` — из extracted context
     - `Profile` — `[[{id}]]` (wikilink)
     - `Tier` — `1` если профиль создан (auto-Tier-1 правило SDD); иначе `3`
     - `Mentions` — `1`
     - `Last` — note's `created` date
   - Add `person/{id}` tag to `_system/registries/TAGS.md`
   - Add person to the People Resolution Map (for subsequent files)

3. **If identity uncertain:**
   - Make best guess and create the profile (inclusion-biased)
   - Log uncertainty in `_system/state/CLARIFICATIONS.md` **Open Items** section
     with enough context for the user to resolve quickly
   - When user resolves: move item from Open Items to **Resolved Archive** table
     (one-line summary: date, item, resolution). This keeps Open Items clean
     while preserving audit trail for future transcription artifact matching.

Within a batch: if the same new person appears in multiple transcripts,
consolidate information BEFORE creating the profile. Collect all mentions
first, then create one comprehensive profile.

### 3.9 System Updates

**Runs in orchestrator, post-aggregate.** Subagents do NOT touch
PROCESSED.md or log_process.md — those updates are batched here from
aggregated subagent manifests.

For each processed source path (collected from all subagent manifests):

1. **PROCESSED.md** — add entry to the existing table (header: `| Source | Main Note | Date |`):
   `| _sources/processed/{source}/{timestamp}/transcript*.md | zettelkasten/{path-to-main-note}.md | YYYY-MM-DD |`
   Source path points to the FINAL location in `processed/` (file was moved there in Step 2.4).
   Duplicate check: if source path already in table, skip (unless `--reprocess`).

2. **log_process.md** — add one entry per run at TOP (newest first), aggregating across all batches:

   ```markdown
   ## YYYY-MM-DD — Processing: {run-summary}

   **Sources:** {N total, list grouped by batch}
   **Records created:** {N} — {list of record IDs}
   **Knowledge notes created:** {N} — {list of note IDs}
   **Knowledge notes extracted:** {N} — {list, with "from {record-id}"}
   **Hubs updated:** {N} — {list of hub IDs with brief change description}
   **Hubs created:** {N} — {list of new hub IDs}
   **People created:** {N} — {list}
   **People updated:** {N} — {list}
   **Self-review fixes:** {N total} — {distribution by type: MISSED / DISTORTED / HALLUCINATED / THIN DECISION / UNLINKED REVISION}
   **Batches:** {batch_count} — {token totals, transcript counts per batch}
   ```

(Context handoff between transcripts now happens implicitly within shared
subagent context per batch; no per-file handoff document needed.)

### 3.10 Verify Source Integrity

**Runs in orchestrator, post-aggregate.** Cross-cuts the file completeness
invariant from §3.0.4 with note-level path checks.

For every source path in `S` (enumerated set from §3.0.4):
- Confirm file exists in `_sources/processed/{source}/{id}/` (moved in Step 2.4).
- Confirm at least one note in subagent manifests carries this path in its
  `source:` field (or in any `source:` of its produced notes).
- Confirm PROCESSED.md entry was written for it (Step 3.9).

If any check fails — halt at Completion Gate (Step 5). Do NOT proceed to
batch artifacts. The mismatch implies either a subagent silently dropped
a transcript or a write-step failed; both require investigation, not
continuation.

---

## Step 4: Post-Processing

After ALL files in the batch are processed:

### 4.1 Update TASKS.md

**Canonical structure & format: see `_system/docs/SYSTEM_CONFIG.md` → "Task Format" section.**
Source of truth for section names, classification rules, header format, and stream grouping.

**Regeneration algorithm:**

1. **Read existing TASKS.md first** — extract the set of `^task-id` values currently
   in the `## Stale` section. These IDs MUST be preserved in Stale, never moved back
   to active sections, even if the source note still has them as `- [ ]`.
   Stale = result of user's manual review; pipeline doesn't override it.

2. **Scan ALL notes** (records + knowledge) for `- [ ]` items. Extract task description,
   linked note, `^task-id`, and any `→ [[person-id]]` reference.

3. **Classify each task** using the table in SYSTEM_CONFIG (Action / Waiting / Delegate).
   Key distinctions:
   - **Action**: «{owner-first-name from SOUL.md Identity}: ...», first-person speech (`I:`/`я:`), or task clearly for owner to execute
   - **Waiting**: «@person: ...» AND owner is the recipient of the output (blocker for owner)
   - **Delegate**: owner assigned/escalated, owns tracking, but output goes to team/process
   - **Someday** / **Personal**: separate sections (low priority; non-work)
   - **Unclear**: → Action (safe default)

4. **Apply Stale preservation** — any task whose `^task-id` was in old Stale section →
   new Stale section. All other tasks → appropriate active section.

5. **Group within each section by stream** (`### Stream Name`). Use existing streams
   from the current TASKS.md; create new stream when a clear topic cluster emerges
   (≥3 related tasks). Stream list is organic and evolves.

6. **Semantic dedup** — if two tasks express the same work from different notes,
   merge into one entry with both `[[note-link]]` references and a single `^task-id`
   (keep the more descriptive ID). Log merges in the report.

7. **Update header** — recompute `Last Updated`, per-section counts, `Total unique`.

NOTE: At 500+ notes, switch to incremental update (scan only new/modified notes,
merge into existing TASKS.md structure). For now, regenerate from all notes
while preserving Stale.

### 4.2 Update CALENDAR.md

**Canonical structure & format: see `_system/docs/SYSTEM_CONFIG.md` → "Event/Meeting Format" section.**

Scan ALL notes for dated events (`📅` items) and future meetings.

**Regeneration algorithm:**
1. Extract all `📅 **YYYY-MM-DD**` items with descriptions and note links.
2. Separate Recurring (explicit regular meetings in note content) from one-off events.
3. Identify Deadlines — events framed as «@person должен сделать X к дате» — move to Deadlines section.
4. Split one-off events by date vs today:
   - Future → Upcoming
   - Past but within 2 weeks → Past
   - Older than 2 weeks → DROP (don't carry forward)
5. Update `Last Updated` in header.

### 4.3 Update HUB_INDEX.md

Rebuild the hub index table from all hub files in `5_meta/mocs/`.

### 4.4 Content Potential Verification

Verify that all newly created knowledge notes with content potential have
complete frontmatter: `content_potential`, `content_type`, and `content_angle`.
If any field is missing — add it now based on Q14 assessment.

NOTE: There is no separate CONTENT_PIPELINE registry. Content candidates live
in note frontmatter and are discovered dynamically by `/ztn:check-content`.
POSTS.md tracks only published posts.

### 4.5 Batch Verification

Run these checks over the ENTIRE processing run's output:

- [ ] Count match: every transcript-grounded source produced exactly one record (kind = meeting | observation per Q9 routing)
- [ ] No orphan path-link Evidence Trails: every new knowledge note's `## Evidence Trail` wikilink points at a record-id or note-id, never at `_sources/...`
- [ ] No orphan extracted_from: every `extracted_from:` reference points to an existing record
- [ ] All hubs exist: every hub referenced in notes exists as a file in `5_meta/mocs/`
- [ ] Bidirectional cross-references: if note A links to note B, note B's hub/relations should reference note A
- [ ] No duplicate notes: no two notes cover the same topic from the same source
- [ ] PROCESSED.md complete: every processed source file has an entry
- [ ] People registry consistent: every person ID in any note's frontmatter exists in PEOPLE.md

### 4.6 Content Proportionality Check + Coverage Fix Rate

#### Proportionality

Compare source length vs output density:

| Source type | Expected key points per ~10 minutes |
|---|---|
| Work meeting (tactical) | 5-8 bullets |
| Work meeting (strategic) | 3-5 bullets + 1-2 knowledge notes |
| Therapy / reflection | 2-4 knowledge notes |
| Idea brainstorm | 1-3 knowledge notes |

If output is significantly thinner than expected, flag in the report.

#### Coverage Fix Rate

Aggregate `fixes_applied` from all subagent manifests. Calculate: what %
of notes had any fix during §3.7 self-review?

- < 20%: Normal. Producer pass and self-review well-aligned.
- 20-50%: Elevated. Subagent's main pass leaving gaps the self-review is
  catching — review classification prompt or context budget per batch.
- > 50%: Systemic issue. Flag in report with recommendation (likely
  T threshold too high or N cap too high — subagent attention diluted).

Also report: distribution of fix types (MISSED / DISTORTED / HALLUCINATED /
THIN DECISION / UNLINKED REVISION) — concentration in one type points to
a specific failure mode in the pipeline.

### 4.7 Batch Data Accumulation (in-memory, before Completion Gate)

Assemble the full dataset required for the batch artifacts — **in memory only**, no disk
writes yet. Disk writes happen at Step 5.5, strictly after the Completion Gate.

Accumulate:

- **`batch_id`** = UTC timestamp of run start, format `YYYYMMDD-HHmmss`. Fixed at the moment the concurrency lock was acquired and stable for the rest of the run. On collision (theoretical, due to concurrency lock this should not happen) — append suffix `-1`, `-2`.
- **`timestamp`** = ISO 8601 UTC with trailing `Z` (run start).
- **`processor`** = `ztn:process`.
- **`batch_format_version`** = per `_system/docs/batch-format.md` current spec version.
- **Counts:** `sources`, `records`, `notes`, `tasks`, `events`, `threads_opened = 0`, `threads_resolved = 0`, `clarifications_raised`, `people_candidates_appended` (see counter mechanics below).
- **Lists for each section of the batch report:** Sources Processed (with source type ID), Records Created (id + title + people + projects), Knowledge Notes Created (id + title + types + domains + Evidence Trail status), Tasks Extracted (task-id + description + deadline + priority + from-note), Events Extracted (datetime + description + participants + from-note), People Updates (id + change type + mentions delta + tier note), Hubs Updated (id list), CLARIFICATIONS Raised (type + summary per item).

**`clarifications_raised` counter mechanics:**

- The skill maintains an in-memory integer counter across the entire run. Reset to **0** at run start.
- Every time the skill appends an item under `## Open Items` in `_system/state/CLARIFICATIONS.md` — regardless of type (`process-compatibility`, `people-bare-name`, `people-identity`, `idea-ambiguous-match`, `evidence-trail-anomaly`, etc.) — the counter increments by exactly **1**.
- The final counter value is recorded in batch frontmatter as `clarifications_raised:`.
- The counter is **not** persisted between runs.

**`people_candidates_appended` counter mechanics:**

- Parallel in-memory counter reset to **0** at run start.
- Increments by 1 for every successful `append_person_candidate.py` invocation (one per bare-name mention routed to the buffer).
- Does NOT double-count high-importance escape-hatch cases: in that path, a CLARIFICATION is raised (increments `clarifications_raised`) AND a buffer line is written as audit trail (increments `people_candidates_appended`). Both counters are independent.
- The final value is recorded in batch frontmatter as `people_candidates_appended:`.
- Report it separately from `clarifications_raised` in the batch report — these are two distinct user-visible states (inbox for lint aggregation vs immediate resolution queue).

**Thread counts are zero.** `/ztn:process` does NOT open or resolve threads — that is `/ztn:maintain` responsibility. This is a hard invariant and is checked at the Completion Gate.

---

## Step 5: Completion Gate

**MANDATORY. Do NOT produce the report until ALL items are verified.**

If any item is incomplete, go back and complete it. No deferring as "follow-up."

- [ ] All transcripts processed (records + knowledge notes written to disk)
- [ ] **File completeness invariant** (§3.0.4): union of `transcripts_processed[].path` across all subagent manifests equals enumerated source set `S` exactly — no missing, no duplicates
- [ ] Self-review (Step 3.7) coverage manifest returned for EVERY transcript; `fixes_applied` populated (empty list explicit if no fixes)
- [ ] No subagent returned a non-empty `errors` list (halt-on-error invariant)
- [ ] Per-note structural verification passed (Step 3.6, inside subagent)
- [ ] People profiles: new people added to PEOPLE.md + profile files created in `3_resources/people/`
- [ ] People profiles: existing people's `## Упоминания` updated with new mentions
- [ ] Tags: new `person/{id}` tags added to TAGS.md for new people
- [ ] Hubs: existing hubs updated (rewrite "Текущее понимание", add to chronological map, changelog)
- [ ] Hubs: new hubs CREATED for topics reaching 3+ knowledge notes threshold
- [ ] HUB_INDEX.md rebuilt
- [ ] PROCESSED.md updated for all processed source paths
- [ ] log_process.md entry added (newest first)
- [ ] TASKS.md updated (header counts refreshed; Stale section preserved from previous TASKS.md; classification Action/Waiting/Delegate applied per SYSTEM_CONFIG rules)
- [ ] CALENDAR.md updated (Past section pruned to last 2 weeks; Deadlines have `@person-id` prefix)
- [ ] Content potential fields verified (content_potential + content_type + content_angle)
- [ ] Knowledge notes placed in correct PARA folder (NOT in deprecated `2_areas/work/meetings/`)
- [ ] New records in `_records/{meetings,observations}/` per Q9 routing (NOT in `2_areas/work/meetings/`); every transcript anchored to exactly one record
- [ ] Batch verification passed (Step 4.5)
- [ ] CLARIFICATIONS.md reviewed — new items noted for report
- [ ] content_potential assessed for all new knowledge notes (Q14)
- [ ] Every new knowledge note (`layer: knowledge`, not record, not profile) in this batch contains `## Evidence Trail` with ≥ 1 initial entry placed BEFORE `## Source`
- [ ] PEOPLE.md — 8 columns (`ID | Name | Role | Org | Profile | Tier | Mentions | Last`) preserved in every row touched this run; new rows have all 8 populated
- [ ] In-memory batch data accumulated (Step 4.7): `batch_id` fixed; count fields reconcile with actually created artifacts; `clarifications_raised` matches the in-memory counter value
- [ ] `threads_opened = 0` AND `threads_resolved = 0` (process does not touch threads)
- [ ] `people_candidates_appended` matches both (a) the in-memory counter and (b) actual line-count delta in `_system/state/people-candidates.jsonl` since run start. If mismatch — do NOT write batch; investigate the gap (typically missed append invocation or double-count on escape-hatch path)

**Note on batch artifacts:** the files `_system/state/batches/{batch-id}.md` and the new row in
`_system/state/BATCH_LOG.md` are NOT yet on disk at this point, and therefore are NOT checked in
this gate. Their write happens at Step 5.5 — strictly POST-Gate. If this gate fails, Step 5.5
does not run and no batch file appears on disk. Absence of batch = absence of contract.
Crash recovery via PROCESSED.md handles partial filesystem state on the next run.

**No deferring.** Every item above is part of the pipeline, not follow-up.
If context window is tight, use subagents for parallel work
(hub creation, view regeneration) — but verify their output.

---

## Step 5.5: Batch Artifacts Write (post-Gate)

**Runs ONLY if Step 5 Completion Gate passed fully.** If the gate failed, stop here —
no batch artifacts on disk.

### 5.5.1 Write `_system/state/batches/{batch-id}.md`

Create the per-batch report file according to the contract in
`_system/docs/batch-format.md`.

**Frontmatter (all keys required):**

```yaml
---
batch_id: {YYYYMMDD-HHmmss}
timestamp: {ISO 8601 UTC with trailing Z}
processor: ztn:process
batch_format_version: {current spec version from batch-format.md}
sources: N
records: N
notes: N
tasks: N
events: N
threads_opened: 0
threads_resolved: 0
clarifications_raised: N
people_candidates_appended: N
---
```

**Sections (in this exact order, never skipped — use `(none)` when empty):**

1. `## Sources Processed` — one bullet per transcript: `- {path} ({source-type-id})`
2. `## Records Created` — per record: `- [[{id}]] | {title}` + child bullets `People:` and `Projects:`
3. `## Knowledge Notes Created` — per note: `- [[{id}]] | {title}` + child bullets `Types:` + `Domains:` + `Evidence Trail: started|appended`
4. `## Tasks Extracted` — per task: `- {task-id} | {description} | deadline: {date or —} | priority: {low|normal|high}` + child bullet `From: [[{note-id}]]`
5. `## Events Extracted` — per event: `- {datetime} | {description} | participants: {ids}` + child bullet `From: [[{note-id}]]`
6. `## People Updates` — per person touched: `- {id} | {change-type} | mentions: {before}→{after} | tier: {value} (no change | promoted via maintain later)`
7. `## Threads` with sub-sections `### Opened` and `### Resolved` — both `(none)` for `/ztn:process` (process never touches threads)
8. `## Hubs Updated` — `- [[{hub-id}]]` per hub touched
9. `## CLARIFICATIONS Raised` — per item: `- {type} | {one-line summary}` — count MUST equal `clarifications_raised` in frontmatter
10. `## People Candidates Appended` — per entry: `- {candidate_id} | {name_as_transcribed} | {note-id} | {role_hint or —}` — count MUST equal `people_candidates_appended` in frontmatter. Use `(none)` if empty.

### 5.5.2 Append row to `_system/state/BATCH_LOG.md`

Append ONE new markdown table row to the Batch Log, matching the schema defined
in `_system/docs/batch-format.md` (9 columns):

```
| {batch_id} | {timestamp} | {sources} | {records} | {notes} | {tasks} | {events} | 0 | 0 |
```

**Strict rules:**
- Append-only. Never rewrite, reorder, or delete existing rows.
- Exactly ONE new row per successful run.
- The `threads_open` and `threads_close` columns are always `0` for `/ztn:process` output.

### 5.5.3 Failure semantics

If Step 5.5 itself fails mid-way (e.g., filesystem error while writing `batches/{id}.md`):
- If the batch file was partially written → best-effort delete it to avoid a claim of successful completion that isn't backed by a full file.
- Do NOT append to BATCH_LOG.md unless `batches/{id}.md` wrote completely.
- Log the error, surface it in the Step 6 report under a `### Errors` subsection, and exit non-zero.

---

## Step 6: Report

Output to user:

```
## ZTN Processing Report — YYYY-MM-DD

### Files Processed: N

| # | Source | Record | Knowledge Notes | Hubs |
|---|--------|--------|-----------------|------|
| 1 | {timestamp} — {topic} | {record-id or "—"} | {note-ids or "—"} | {hub updates/creates} |

### Summary
- Records created: N
- Knowledge notes created: N (of which N extracted from records)
- Hubs updated: N
- Hubs created: N
- People created: N ({list})
- People updated: N ({list})

### Self-Review Stats
- Notes self-reviewed: N
- Fixes applied: N (coverage fix rate: X%)
- MISSED items caught: N
- DISTORTED items corrected: N
- HALLUCINATED items removed: N
- THIN DECISIONS enriched: N
- UNLINKED REVISIONS resolved: N

### Batch Stats
- Batches dispatched: N (each ≤ 250k tokens, ≤ 6 transcripts)
- Max parallel subagents: N (cap = 3)
- File completeness: PASSED ({len(S)} sources enumerated, {len(S)} processed)

### New Entities
- Tags: {list of new tags}
- People: {list of new people with roles}
- Projects: {list of new projects}
- Hubs: {list of new hubs}

### Clarifications Needed: N
{list items from CLARIFICATIONS.md added during this run, if any}

{if N > 0:} Run `/ztn:resolve-clarifications` to review interactively when ready.

### Completion Gate
- [x] All transcripts processed
- [x] File completeness invariant passed (all enumerated sources in subagent manifests)
- [x] Self-review (Step 3.7) coverage manifests returned for every transcript
- [x] People profiles created/updated
- [x] Hubs created/updated
- [x] System views regenerated (TASKS, CALENDAR, HUB_INDEX)
- [x] PROCESSED.md + log_process.md updated
- [x] Batch verification passed
- [x] Evidence Trail present in every new knowledge note
- [x] PEOPLE.md 8-column schema preserved
- [x] Batch artifacts written (batches/{id}.md + BATCH_LOG row)

### Batch Artifact
- **batch_id:** {YYYYMMDD-HHmmss}
- **Report:** `_system/state/batches/{batch-id}.md`
- **BATCH_LOG:** +1 row (threads_open/close = 0)
- **clarifications_raised:** {N}

### Health Indicators
- Open tasks: {N} (oldest: {date}, {age} ago)
  {if age > 60 days}: ⚠️ Consider running `/ztn:sweep-tasks` (future skill)
- Content candidates: {N} notes with content_potential (high: {N}, medium: {N})
  {if high > 3 and no published in last 30 days}: 💡 Run `/ztn:check-content` to review and draft
- People profiles: {N} total, {N} with empty Контекст section
  {if empty > 5}: 📋 Consider one-time people enrichment pass
```

## Example Usage

```
/ztn:process
/ztn:process --dry-run
/ztn:process --file _sources/inbox/plaud/2026-01-25_meeting/transcript_with_summary.md
/ztn:process --reprocess
```
