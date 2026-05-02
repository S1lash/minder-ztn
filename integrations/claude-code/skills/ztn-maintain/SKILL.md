---
name: ztn:maintain
description: >
  After-batch integrator for ZTN. Reads unprocessed batches from
  `_system/state/batches/` + `_system/state/BATCH_LOG.md`, integrates them into live state:
  thread detection & strategic-grain opening, back-reference writes into
  records/notes frontmatter, hub linkage for new threads, thread closure
  suggestions (suggest-only — never auto-closes), tier promote suggestions
  (suggest-only — never auto-applies), mention consistency sanity check,
  CURRENT_CONTEXT full regen, log_maintenance.md append. Multi-batch iteration,
  per-batch idempotency, concurrency lock, best-effort malformed batch handling.
disable-model-invocation: false
---

# /ztn:maintain — After-Batch Integrator

Consumes `_system/state/batches/{batch-id}.md` produced by `/ztn:process`. Integrates
each unprocessed batch into live state.

**Philosophy:**
- Maintain = integrate, not extract. Never creates knowledge notes, records,
  tasks, events, or increments mention counts. These are `/ztn:process` territory.
- Maintain only modifies: `OPEN_THREADS.md`, hubs, `CURRENT_CONTEXT.md`,
  `CLARIFICATIONS.md`, `log_maintenance.md`, and frontmatter back-refs in
  existing records/notes (`threads:` field). Body of existing notes — never.
- **Suggest, don't apply** for user-facing state changes (thread closure, tier
  promote). Maintain raises CLARIFICATIONS; owner applies manually via edit.
- Best-effort over hard fail. Malformed batch → workaround + CLARIFICATION.
- LLM-first reasoning with rule-based floor.

**Contracts:** `_system/docs/ENGINE_DOCTRINE.md` (operating philosophy
— load first; binding cross-skill rules: surface-don't-decide,
inclusion-bias-on-capture / curation-on-promotion, idempotency,
owner-LLM contract), `_system/docs/batch-format.md`,
`_system/docs/SYSTEM_CONFIG.md` (Data & Processing Rules),
`5_meta/PROCESSING_PRINCIPLES.md` (8 principles — calibrate hub
linkage and tier-promote judgements against principle 3 Connection
Awareness, principle 4 Cross-Domain Permeability, principle 7 People).

**Documentation convention:** при любых edits этого SKILL соблюдай `_system/docs/CONVENTIONS.md` — файл описывает current behavior без version/phase/rename-history narratives.

## Arguments

`$ARGUMENTS` supports:
- `--dry-run` — scan unprocessed batches, report planned actions without writes
- `--batch <id>` — process only a specific batch-id. Must exist as
  `_system/state/batches/{id}.md` (validated in Early Exit). Raises a warning if the
  batch is already recorded in log_maintenance.md and requires `--force` to
  proceed (re-run creates duplicate CLARIFICATIONS and may create duplicate
  thread entries, back-refs are idempotent)
- `--force` — used with `--batch <id>` only. Acknowledge duplicate risk and
  bypass log_maintenance.md idempotency check. No effect without `--batch`
- `--verbose` — include full decision rationale in report
- `--no-sync-check` — skip the data-freshness pre-flight (see below)

---

## Pre-flight: data freshness (non-blocking)

Multi-device safeguard. If `origin` has commits not yet pulled, the
batch under `_system/state/batches/` may have been produced on another
device and already integrated there. Courtesy check, not a gate.

Skip with `--no-sync-check`.

```bash
if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin --quiet 2>/dev/null || true
  branch=$(git rev-parse --abbrev-ref HEAD)
  remote_ahead=$(git rev-list --count "HEAD..origin/${branch}" 2>/dev/null || echo 0)
fi
```

- `origin` absent, fetch failed, or `remote_ahead == 0` → silently proceed.
- `remote_ahead > 0` → prompt:
  ```
  ⓘ origin/<branch> ahead by <N> commit(s). Maintain on stale state
    may double-integrate batches already handled elsewhere.

    [s] run /ztn:sync-data first  (recommended)
    [c] continue with current local state
    [d] show pending commits
  ```
- `s` → exit 0, owner re-runs after sync-data.
- `c` → proceed; `d` → show log, re-prompt.

---

## Early Exit Check

**FIRST action — before lock, before context loading.**

**0. Cross-skill lock check.** Read all three lock files:
- `_sources/.processing.lock` — exists → abort «`/ztn:process` running, try again later»
- `_sources/.lint.lock` — exists → abort «`/ztn:lint` running, try again later»
- `_sources/.maintain.lock` — exists → abort «another `/ztn:maintain` run in progress»

All three skills mutually exclusive. Stale lock (>2 hours) → warn, offer manual removal, do NOT auto-delete.

1. Read `_system/state/BATCH_LOG.md` — all rows.
2. Read `_system/state/log_maintenance.md` — grep for entries matching
   `## ... | maintain | by: ztn:maintain | batch: {id}` AND absence of
   `### Errors / Warnings → Aborted` marker.
3. Compute **unprocessed set** = BATCH_LOG batches \ log_maintenance.md maintain
   batches. Sort oldest-first by `batch_id` (monotonic timestamp string sort).
4. If `--batch <id>` given:
   - Validate `_system/state/batches/{id}.md` file exists — if not, abort with
     `"Error: batch {id} not found in _system/state/batches/"` and exit immediately.
   - Check if `{id}` appears in log_maintenance.md as already processed. If yes:
     - Without `--force`: abort with warning
       `"Batch {id} already integrated (log_maintenance.md entry exists). Re-running will duplicate CLARIFICATIONS and may duplicate thread entries. Pass --force to proceed, or omit --batch to skip."`
     - With `--force`: proceed with unprocessed set = `{id}` and log the force
       flag in log_maintenance.md entry Errors/Warnings section.
   - If not in log_maintenance.md: unprocessed set = `{id}`.
5. If unprocessed set is empty (and not `--batch`): report
   `"No unprocessed batches — nothing to integrate."` and **exit immediately**.
   No lock, no further reads.

---

## Concurrency Lock

Runs only when unprocessed set is non-empty.

1. Check `_sources/.maintain.lock`. If exists → report to user and abort.
   If stale (>2 hours old), warn user and offer manual deletion; do not
   auto-delete.
2. Create `_sources/.maintain.lock` with content:
   `{ISO timestamp} — maintain run, PID {pid}, batches: {ids comma-separated}`.
3. **Finally semantics:** lock MUST be deleted in ALL exit paths — normal
   completion, skip, malformed abort, exception. Implementation: wrap Steps 1–9
   in try/finally, delete in finally.

---

## Step 0.0: Regenerate Constitution Derived Views

Invoke `/ztn:regen-constitution` (or run `python3 _system/scripts/regen_all.py`)
as the very first action of the run, before the per-batch loop opens.

The pattern-detect sub-step (§Step 7.5) queries the active constitution tree
to dedupe new candidates against existing principles; SOUL.Values lands in
Step 7 CURRENT_CONTEXT via its auto-zone. Both rely on derived views being
fresh relative to `0_constitution/`.

Consistency rule for the whole platform: every pipeline that reads a derived
view regenerates first. Cost is ~100 ms. Failure is fatal — report the
underlying script error and abort the run.

---

## Per-Batch Loop — Steps 1–6 + per-batch log_maintenance.md write

Iterate unprocessed batches **oldest-first**. Each iteration runs Steps 1–6
for that single batch, then writes its log_maintenance.md entry **before**
moving to the next batch. This protects idempotency across crashes: if the
run dies mid-loop, already-written entries mark their batches as processed
and a retry skips them.

After the loop exits, Step 7 (CURRENT_CONTEXT regen) runs once per run.
Step 7 does not produce its own log_maintenance.md entry — the last batch's
entry (written at end of its iteration) records the final
`CURRENT_CONTEXT.md: regenerated` note retrospectively, updated via edit
after Step 7 completes.

---

## Step 1: Load & Parse Batch

1. Load `_system/state/batches/{batch_id}.md`. Read entire file.
2. Parse YAML frontmatter. Required keys: `batch_id`, `timestamp`, `processor`,
   `batch_format_version`, `sources`, `records`, `notes`, `tasks`, `events`,
   `threads_opened`, `threads_resolved`, `clarifications_raised`,
   `people_candidates_appended` (added 2026-04-24; batches produced before
   that date do not carry this key — treat missing as 0, no warning, no
   `batch-version-unknown` escalation).
3. Parse body sections by `## Heading` markers (per `_system/docs/batch-format.md` §Sections).

### Malformed handling (best-effort, never hard-fail)

For each anomaly: apply workaround, raise CLARIFICATION with the concrete
reason code below, continue processing.

| Anomaly | Workaround | Reason code |
|---|---|---|
| Missing / invalid frontmatter | Extract what parses; use section bodies as fallback metadata (batch_id from filename) | `batch-malformed-frontmatter` |
| Unknown `batch_format_version` | Assume current spec semantics per `_system/docs/batch-format.md` | `batch-version-unknown` |
| Required section missing entirely | Treat as empty | `batch-missing-section` |
| Header count ≠ actual list length | Use actual list count; flag header | `batch-counts-inconsistent` |
| Count negative / non-numeric | Use list-based count | `batch-counts-anomaly` |
| `[[note-id]]` reference to non-existent file | Skip linkage for that ref | `batch-dangling-reference` |
| People Update references unknown person id (not in PEOPLE.md) | Skip tier check for that person | `batch-unknown-person` |

CLARIFICATIONS written in Step 8 (aggregated with run-level items).

---

## Step 2: Thread Detection (open new threads)

### Input

- Current batch: `## Records Created`, `## Knowledge Notes Created`,
  `## Tasks Extracted` (task descriptions, `deadline:`, and `From:` links)
- Live: `_system/TASKS.md ## Waiting` (existing waiting tasks)
- Live: `_system/state/OPEN_THREADS.md ## Active` (to avoid duplicates)

### Pipeline

**2.1 Collect candidates.** For each new record and each new decision-type
knowledge note, apply LLM reasoning:

> Is this starting a new **strategic expectation** that spans multiple tasks
> and takes time to resolve (waiting-for-response, needs-decision, needs-research,
> blocked)? Or is it operational detail (single task, fact captured, no blocking
> expectation)?

Strategic candidate = umbrella ожидание. Operational = single action, already
covered by TASKS.md.

**2.2 Dedup against existing active threads.** For each candidate, scan
`OPEN_THREADS.md ## Active`:
- People overlap: candidate.People ∩ thread.People ≠ ∅
- Topic overlap: LLM semantic match over titles + Context fields

If strong match (same umbrella) → DO NOT open new thread. Instead:

**(a) Merge into Source field.** Add `[[{batch-record-id}]]` into the existing
thread's `Source:` field. Source field comes in two live formats — normalize
before append:

- **Single-link form** (current bootstrap output):
  `- Source: [[{existing-id}]]`

  Convert to multi-link inline form:
  `- Source: [[{existing-id}]], [[{batch-record-id}]]`

- **Multi-link inline form** (comma-separated on one line):
  `- Source: [[{id1}]], [[{id2}]]`

  Append: `- Source: [[{id1}]], [[{id2}]], [[{batch-record-id}]]`

Dedup: if `{batch-record-id}` already present in Source — skip the Source
append, continue to (b).

**(b) Track for back-ref write.** Record this `(batch-record-id, existing-thread-id)`
pair in the run's back-ref worklist. Step 3 will write the `threads:` back-ref
into the record's frontmatter — same treatment as newly-created threads. This
ensures existing threads benefit from structural matching in future Step 5
Signal 2 runs.

Skip to next candidate.

**2.3 Strategic grain filter.** Per SYSTEM_CONFIG Data & Processing Rules:
- Thread ≥ 2 related tasks OR 1 waiting-for-response expectation that doesn't
  resolve in single-call action
- Thread < 2 weeks to resolve expected (heuristic, not strict)
- Reject single-task candidates: log in internal state for Step 8 report,
  no CLARIFICATION needed (operational-by-design is not ambiguous)

**2.4 Ambiguity gate.** LLM confidence about «new strategic thread?»
< 90% → CLARIFICATION `thread-detection-ambiguous` with:
- Candidate source record id + batch-id
- Arguments for (strategic signals)
- Arguments against (operational signals)
- **Suggested action:** `open-thread` | `skip` | `merge-into-existing-thread-X`

Do NOT create the thread. Owner resolves.

**2.5 Create new thread** for candidates that pass filters AND ambiguity gate.

Thread id: `thread-{YYYYMMDD}-{semantic-slug}` where date = batch timestamp
(UTC date part). Slug: 3–5 kebab-case keywords from title. Uniqueness check
against OPEN_THREADS.md — if collision, append `-2`, `-3`.

Entry format in `OPEN_THREADS.md ## Active` — use `###` heading to match
existing bootstrap-generated threads:

```markdown
### {thread-id}: {thread title — strategic umbrella в одну строку}

- Status: {waiting-for-response | needs-decision | needs-research | blocked}
- Since: {YYYY-MM-DD — batch timestamp UTC date}
- People: {person-id1, person-id2, ...} (from related records' `people:`)
- Source: [[{record-id1}]], [[{note-id1}]], [[{note-id2}]]
- Context: {2–4 sentence summary from LLM: what we're waiting for, why it matters, what blocks what}
- Related Tasks: {task-id1, task-id2, ...} (from batch `## Tasks Extracted` + any matching TASKS.md Waiting items)
- hub: [[{hub-id}]]   # populated in Step 4; omit line if no hub match
```

Append new thread block after the last existing `### thread-...` in `## Active`
(preserving existing order), before the `---` separator or `## Resolved` section.

### Update OPEN_THREADS.md header (precise operation)

Parse existing header:

```
**Last Updated:** {YYYY-MM-DD}
**Active:** {A} | **Resolved:** {R}
```

Regex: `\*\*Active:\*\* (\d+) \| \*\*Resolved:\*\* (\d+)`.

Update:
- `{A}` → `{A + N_new_threads_opened_this_batch}`
- `{R}` → unchanged (maintain does not apply closures)
- `**Last Updated:** {YYYY-MM-DD}` → today's date (UTC date part of run start)

Preserve all other lines. Rewrite entire file with the header swap.

Also update frontmatter `modified:` to today's date if present.

---

## Step 3: Back-Reference Write

Back-ref worklist = union of:

- **(A) New threads** created in Step 2.5 — each thread's Source list pairs
  with that thread-id
- **(B) Merged records** from Step 2.2.(b) — each `(batch-record-id, existing-thread-id)`
  pair recorded there

Both groups follow identical write logic:

1. For each `(record-or-note-id, thread-id)` pair in the worklist:
   - Locate file: scan `_records/meetings/` + `_records/observations/` for record ids, PARA folders
     (`1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`) for knowledge
     note ids. If not found → skip, raise `batch-dangling-reference`.
   - Open file, parse frontmatter.
   - If `threads:` key exists → append `{thread-id}` if not already present in
     the list. Preserve other entries.
   - If `threads:` key absent → add it as YAML list: `threads:` with single
     `- {thread-id}` entry.
   - Write file back. **Body untouched.**
2. Track count `back_refs_written` for Step 8 report. Report split:
   - `N_backrefs_new_threads` (from worklist group A)
   - `N_backrefs_merged_threads` (from worklist group B)

### Idempotency

Back-ref write is idempotent by design (check-before-append). Safe on retry.
Both new-thread and merged-thread writes use the same check-append logic.

### Why

- Structural (not fuzzy) match for Step 5 Signal 2 in future batches — works
  equally for new AND existing threads once first record with that topic
  lands
- Navigation: from a record/note file, owner can jump to the linked strategic
  thread via frontmatter `threads:` list

---

## Step 4: Hub Linkage

For each thread created in Step 2:

**4.1 Hub search.** Glob `5_meta/mocs/*.md`. For each hub:

- **Primary:** people overlap — hub frontmatter `people:` ∩ thread.People.
  If hub has no `people:` frontmatter, skip primary criterion for this hub.
- **Secondary:** keyword/topic overlap — LLM semantic match over hub title +
  `## Ключевые выводы` top bullets (or `## Текущее понимание` if first is absent)
  vs thread title + Context.

Score each hub: `(people_overlap_count * 2) + topic_relevance_score`.
Topic relevance — LLM judgment 0–3:
- 0 = unrelated (hub's topic domain differs from thread's core topic)
- 1 = tangentially related (shared person but different problem domain)
- 2 = clearly related (thread's topic is a subtopic of hub)
- 3 = core match (thread is central expectation within hub's current focus)

**4.2 Ambiguity gate:**

**HARD RULE:** `topic_relevance ≥ 1` is **required** for any linkage. A hub with
only people overlap and `topic_relevance = 0` is NEVER linked regardless of
score — prevents hub bloat from incidental people overlap. This overrides the
score threshold below.

After topic filter applied:

| Match result (topic_relevance ≥ 1 candidates only) | Action |
|---|---|
| 0 hubs pass topic filter | Skip linkage. Thread stays with empty `hub:` field. This is OK — not every thread maps to a hub. If thread clearly needs hub but none exists — consider suggesting new hub creation (`/ztn:lint` territory) |
| 1 hub passes topic filter with score ≥ 2 | Apply linkage (4.3) |
| 2+ hubs pass topic filter with score ≥ 2 | CLARIFICATION `thread-hub-ambiguous` with candidate hubs + scoring + topic_relevance for each. Skip until resolved |
| 1+ hubs pass topic filter but all with score < 2 | Skip linkage (people signal too weak + mediocre topic) |

**4.3 Apply linkage** (when exactly one hub matches):

1. In `OPEN_THREADS.md`: set `hub: [[{hub-id}]]` field in thread entry.
2. In `5_meta/mocs/{hub-id}.md`:
   - Append bullet to `## Открытые вопросы` section:
     `- [[{thread-id}]] — {thread title} (since {YYYY-MM-DD})`
   - If section doesn't exist — create it using this placement priority:
     1. **Before `## Ключевые выводы`** if that section exists
     2. Else **before `## Changelog`** if that section exists
     3. Else **at end of body** (append after last content line)
   - Update frontmatter: `modified: {today}`. Do NOT touch `last_mention` —
     that's updated by `/ztn:process` when notes are added. Maintain only
     adds structural metadata (thread linkage), not new mentions.

No hub Changelog entry added by maintain — that's semantic evolution, not
structural link. `/ztn:lint` handles semantic drift if it becomes visible.

**Hub frontmatter — concept and privacy fields are NEVER written by
maintain.** Hubs do not carry a `concepts:` field (member_concepts is
manifest-only, derived at emission time from member-note frontmatter).
Privacy trio (`origin`, `audience_tags`, `is_sensitive`) on hubs is
owner-curated; maintain inherits the existing values when writing
`modified:` and never auto-flips them. A drift signal (e.g. dominant
member origin shifted) surfaces a CLARIFICATION
(`hub-origin-drift` / `hub-sensitivity-drift`) rather than mutation.

**Hub manifest emission for this batch.** When this maintain run
emits its batch manifest (`_system/state/batches/{ts}-maintain.json`),
each hub touched in this run gets a `hubs.updated[]` entry with:

- `path`, `checksum_sha256`, `domains` (existing fields)
- `member_concepts[]` — union of `concepts:` from all member knowledge
  notes that exist on disk at the moment of manifest emission. Every
  entry MUST conform to `_system/registries/CONCEPT_NAMING.md`. A
  non-conformant member-note `concepts:` value is NOT silently
  filtered; surface CLARIFICATION `concept-format-mismatch` (member
  note path + raw value) and emit the entry verbatim into
  `member_concepts[]` so `/ztn:lint` Scan A.7 catches it on the
  manifest path too. The downstream Minder consumer is responsible
  for failing closed on its side; ZTN does not silently sanitise.
- `origin`, `audience_tags`, `is_sensitive` — read from hub
  frontmatter as-is. No inference; owner is authoritative for hub
  privacy.

---

## Step 5: Thread Closure Suggestion (suggest-only)

**Applies to ALL active threads** — existing + freshly created in Step 2.

For each thread, evaluate 4 signals. **Graceful field handling:** older
bootstrap-generated threads may not have `Related Tasks` or `hub:` fields.
A missing field means the corresponding signal cannot fire (neither positive
nor negative) — it's excluded from scoring, not counted as a failed signal.
Note this in CLARIFICATION if the thread scores closure from only 2–3
available signals.

### Signal 1 — Tasks

**Prerequisite:** thread has `Related Tasks` field. If absent → **signal
excluded from scoring** (not fired, not counted). Log as «signal-1-unavailable»
in CLARIFICATION evidence if this thread reaches closure threshold.

If `Related Tasks` present, check each task id against `TASKS.md`:
- task in `## Done` (or marked `cancelled` / `stale`) → task counts as done
- task in `## Waiting` or `## Actions` → not-done
- task id not found in TASKS.md → unknown; raise `thread-dangling-task-ref`;
  count as not-done for scoring (conservative)

**Signal fires** if ALL related tasks are done/cancelled/stale AND
`Related Tasks` list is non-empty.

### Signal 2 — Explicit closure

Scan batch records + notes for closure references to this thread:

- **Structural match (priority):** open each record/note body-or-frontmatter.
  If frontmatter `threads:` list contains this thread-id AND record/note
  contains closure-marker language → fire signal. Closure markers (LLM
  semantic match, not regex):
  - «закрыли», «решили», «решение принято», «получили ответ», «больше не ждём»
  - «выкатили», «задача закрыта», «done», «resolved», «вопрос снят»
- **Fuzzy fallback:** no `threads:` in batch records — LLM judgment over
  people+topic overlap + closure-marker presence. Must have ≥2 of: person
  overlap, topic overlap, closure-marker. Lower confidence than structural.

**Signal fires** if structural match found, or fuzzy fallback confidence
≥ 70%.

### Signal 3 — Staleness

- Thread `Since` > 4 weeks from batch timestamp
- AND no mentions of thread.People in batch's records/notes

**Signal fires** if both conditions hold.

### Signal 4 — Hub resolution

**Prerequisite:** thread has `hub: [[{hub-id}]]` field. If absent or empty →
**signal excluded from scoring** (same semantics as Signal 1).

If present:
- Read hub's `## Ключевые выводы` section
- Check for bullet referencing this thread's title/topic (LLM semantic match)

**Signal fires** if hub already captured a resolution for this thread.

### Scoring & CLARIFICATION

- **≥ 2 signals fire** → CLARIFICATION `thread-closure-suggested`
- **< 2 signals** → keep open, no action

Excluded signals (missing field) are neither positive nor negative for
scoring. Example: thread with no `Related Tasks` and no `hub:` (Signals 1
and 4 unavailable) closes only via Signals 2+3 together.

CLARIFICATION content — parsable fields + rich free-form:

```markdown
### {YYYY-MM-DD} — thread-closure-suggested: {thread-id}

**Type:** thread-closure-suggested
**Subject:** {thread-id}
**Source:** batch-{batch_id}
**Suggested action:** close-thread | close-partial | keep-thread-open
**Confidence tier:** surfaced (HARD RULE — closure never auto-applied)
**Signals fired:** {N}/4
  - Signal 1 (tasks): {fired | not-fired} — {evidence: task-ids + статусы}
  - Signal 2 (explicit closure): {fired | not-fired} — {evidence: record-id + Quote если fuzzy}
  - Signal 3 (staleness): {fired | not-fired} — {evidence: since {date}, age {N} weeks}
  - Signal 4 (hub resolution): {fired | not-fired} — {evidence: hub-id + bullet}

**Quote:** > «{verbatim if Signal 2 via closure-marker}»   # optional

**Context:** {2–4 sentence paragraph: что за тема thread, кто participants, какие signals сошлись и почему, текущий hub state если linked, candidate resolution rationale. Self-contained для LLM review.}

**Suggested resolution text:** {1–2 sentences готовые для вставки в hub's `## Ключевые выводы`}

**Uncertainty:** {what LLM was unsure about — edge cases, remaining tasks, partial closure nuances}

**To resolve:** Run `/ztn:resolve-clarifications` — the skill diffs OPEN_THREADS.md (move entry to `## Resolved` + add `Resolved:` + `Resolution:` fields) and hub edits (`## Открытые вопросы` remove bullet, `## Ключевые выводы` append resolution) on owner confirm.
```

**Maintain NEVER moves thread to Resolved.** Owner does this manually.

---

## Step 6: Tier Promote & Mention Consistency

### Input

Batch `## People Updates` section — one row per person:
`- {person-id} | {change-type} | mentions: {X}→{Y} | tier: {T} ({note})`

### 6.1 Mention consistency check

For each row:
1. Read `3_resources/people/PEOPLE.md` row for `{person-id}`.
2. Compare PEOPLE.md `Mentions` column with batch-reported `Y`.
3. If not equal → CLARIFICATION `mention-count-drift` with:
   - person-id, batch-expected Y, PEOPLE.md actual Z, diff
   - Note: may indicate lost write or concurrent edit in `/ztn:process`

**Maintain does NOT edit PEOPLE.md counts.** Only logs anomaly.

### 6.2 Tier promote check

For each row (assuming PEOPLE.md has person — if not, raise `batch-unknown-person`):

1. Compute **expected tier** per SYSTEM_CONFIG rules:
   - Profile exists in `3_resources/people/{id}.md` OR mentions ≥ 8 → **Tier 1**
   - mentions 3–7 (no profile) → **Tier 2**
   - mentions 1–2 (no profile) → **Tier 3**
2. Read **current tier** from PEOPLE.md `Tier` column.
3. Compare:
   - current == expected → no action
   - expected > current (promote: 3→2 or 2→1) → CLARIFICATION
     `tier-promote-suggested` (see format below)
   - expected < current (demote direction) → skip. Demote is `/ztn:lint`
     territory — never maintain.

CLARIFICATION format:

```markdown
### {YYYY-MM-DD} — tier-promote-suggested: {person-id}

**Type:** tier-promote-suggested
**Subject:** {person-id}
**Source:** batch-{batch_id}
**Suggested action:** promote-tier | keep-thread-open (keep current)
**Confidence tier:** surfaced (HARD RULE — PEOPLE.md Tier column never auto-applied)
**Mentions:** {old}→{new}
**Current tier:** {T_current}
**Expected tier:** {T_expected} (per SYSTEM_CONFIG thresholds)
**Recent contexts:** {3–5 most recent record/note titles referencing this person}

**Context:** {2–4 sentence paragraph: кто этот person (role, org from PEOPLE.md), recent activity pattern (last N records/topics), relationship density signal (coordinator / implementer / external stakeholder), candidate action rationale.}

**To resolve:** Edit `3_resources/people/PEOPLE.md` — change `Tier` column for {person-id} to {T_expected}. Profile generation for Tier 1 without existing profile — handled by `/ztn:lint` weekly.

**Uncertainty:** {if LLM sees signals suggesting relationship density doesn't match raw count, note here}
```

**Maintain does NOT edit PEOPLE.md Tier column.** Owner applies manually.

---

## Step 6.5: Write log_maintenance.md entry for this batch (IN-LOOP)

Append ONE entry to `_system/state/log_maintenance.md` for the current batch,
newest first (prepend to the entries block after `<!-- Entries append BELOW this line, newest first -->`).

Format:

```markdown
## {ISO UTC timestamp of this batch iteration} | maintain | by: ztn:maintain | batch: {batch_id}

### Updates
- Threads: +{N_opened_this_batch} opened, {N_merged_this_batch} existing threads received new batch-records (via Source+back-ref merge), 0 closed (closure is manual — see Suggestions)
- Back-references: +{N_backrefs_this_batch} records/notes enriched with `threads:` frontmatter ({N_backrefs_new} for new threads + {N_backrefs_merged} for merged into existing)
- Hubs: +{N_hubs_linked_this_batch} threads linked
- Mention consistency: {N_checked_this_batch} checked, {M_drifts_this_batch} drifts flagged
- Tier: 0 applied (suggest-only, see Suggestions for pending promotes)
- CURRENT_CONTEXT.md: pending (regenerated post-loop; see last-batch entry for confirmation)
- INDEX.md: pending (regenerated post-loop; see last-batch entry for confirmation)

### Auto-Fixes
- (none — maintain does not auto-fix, suggest-only)

### Suggestions → CLARIFICATIONS
- {total_items_this_batch} items raised: {breakdown}

### Errors / Warnings
- {batch anomalies specific to this batch, or `(none)`}
- {if `--force` used on already-processed batch: "Re-run via --force, duplicate risk acknowledged"}
```

After this write, a crash before the next batch iteration leaves the system
in a recoverable state: retry picks up from the next unprocessed batch.

Proceed to next batch or, if this was the last, exit the loop.

---

## Post-Loop — Steps 7–9

Run **once** after the per-batch loop completes.

---

## Step 7: CURRENT_CONTEXT Full Regen

Overwrite `_system/views/CURRENT_CONTEXT.md` entirely. Regenerate from source-of-truth:

### Input sources

| Source | Used for |
|---|---|
| `_system/SOUL.md` | `## Focus` — copy Work + Personal streams from SOUL.md |
| `_system/TASKS.md` | Waiting tasks with deadline ≤ (today + 2 days) |
| `_system/CALENDAR.md` | Events in (today, today + 7 days] |
| `_system/state/OPEN_THREADS.md` | Top 3 oldest active threads |
| Last processed batch (highest batch_id in this run) | `## Last Activity` counts |

Use **today** = date part of `generated` timestamp (UTC) written in frontmatter.

### Output format

```markdown
---
id: current-context
layer: system
generated: {ISO UTC timestamp with Z suffix}
generated_by: ztn:maintain
batch_id: {last processed batch_id in this run}
---

# Current Context

> Live state для thin orientation. Регенерируется `/ztn:maintain` после каждого batch
> и `/ztn:lint` nightly. Не редактируется вручную.

## Focus (from SOUL.md)

**Work:**
- {copy from SOUL.md Focus → Work}

**Personal:**
- {copy from SOUL.md Focus → Personal}

## Tasks Due by {today + 2d} (as of {today})

- [ ] {task description} — **до {date}** — [[{source-note-id}]]
- ...

(empty → `(none — no tasks due in this window)`)

## Meetings through {today + 7d} (as of {today})

- 📅 **{YYYY-MM-DD}** — {event description}
- ...

(empty → `(none)`)

## Open Threads ({N} active)

Top 3 по давности:

- **{thread-id}** — {title} ({status}, since {date})
- **{thread-id}** — {title} ({status}, since {date})
- **{thread-id}** — {title} ({status}, since {date})

Полный список — `_system/state/OPEN_THREADS.md`.

## Last Activity

- Last batch: {last_batch_id} at {last_batch_timestamp} — {notes_last} notes, {tasks_last} tasks, {events_last} events
- This maintain run: processed {N_batches} batches (first {first_batch_id} → last {last_batch_id}), +{total_threads_opened_across_run} threads opened, +{total_backrefs_across_run} back-refs, +{total_clarifications_across_run} CLARIFICATIONS raised
```

Aggregated counts (`total_*_across_run`) sum over all batches processed this
run. Empty-run case (0 batches in unprocessed set) does not reach Step 7 —
Early Exit handles it. Single-batch case writes `{N_batches} = 1`.

Use explicit absolute dates in section headers (not "Today/Tomorrow") to
eliminate ambiguity when user reads file later.

---

## Step 7.5: Pattern → Candidate Detection (once per run, post-loop)

Scan recent decision records for recurring rationale that looks like an
unstated principle. Runs once per `/ztn:maintain` run, after all batches
are integrated and after Step 7 has refreshed the live context. Output is
append-only into `_system/state/principle-candidates.jsonl`; no constitution
files are modified.

### Input

- All files under `_records/meetings/` and `_records/observations/` with
  `types:` including `decision`, created within the last 30 days (use
  the record's `created:` frontmatter or file mtime fallback).
- The active constitution tree, via
  `python3 _system/scripts/query_constitution.py --compact`
  (filtered to the current context; `personal` by default).
- The current candidate buffer `_system/state/principle-candidates.jsonl`
  for dedupe.

### Pipeline

1. **Group by rationale.** Extract `rationale` (from the decision
   record's prose or the `## Rationale` section). Use LLM clustering
   to group records whose rationale expresses the same operating
   logic (semantic match; stylistic differences do not split groups).

2. **Filter.** Keep only groups where:
   - `|group| ≥ 2` records (two or more independent occurrences in the
     last 30 days)
   - No active principle statement semantically covers the group's
     rationale. Use the principle `statement` + first paragraph of
     body from `query_constitution.py` output for the comparison.

3. **Dedupe against buffer.** For each surviving group, scan
   `principle-candidates.jsonl`. Skip if an entry within the last 30
   days has an `observation` or `hypothesis` that already covers the
   same operating logic. Comparison is LLM semantic, not string match.

4. **Append candidates.** For each non-duplicate group, invoke:

   ```bash
   python3 _system/scripts/append_candidate.py \
       --situation "Recurring decision rationale across N records" \
       --observation "<short verbatim fragment if one is representative, else empty>" \
       --hypothesis "<one-line inferred principle from the group>" \
       --suggested-type principle \
       --suggested-domain <inferred-domain-or-unknown> \
       --origin personal \
       --session-id "maintain-$(date -u +%Y-%m-%d)" \
       --record-ref "[[<most-recent-record-id-of-group>]]"  # any record kind: meeting or observation
   ```

   `suggested_type: principle` is the default — recurring rationale
   rarely qualifies as `axiom` (too fundamental) or `rule` (too
   binary). Pick `unknown` over guessing wrong.

### Invariants for this step

- Do not modify any file under `0_constitution/`. Candidate surfacing
  is append-only into the buffer; promotion is `/ztn:lint` F.3 +
  human review territory.
- Do not reason about verdicts (aligned / violated) — that is
  `/ztn:process` Step 3.7.5's job. Maintain only spots *new* patterns.
- Running on an empty tree (no active principles) is valid: every
  recurring rationale becomes a candidate. Expected in early bootstrap.
- Output count feeds Step 8 log patch (see below) so each run's
  contribution is visible in `log_maintenance.md`.

### Output

A list of `{candidate_count, session_id}` consumed by Step 8.
Console trace lists each appended candidate for the run report.

---

## Step 7.6: INDEX.md Full Regen

Overwrite `_system/views/INDEX.md` entirely. Content-oriented catalog
of every knowledge note and hub, faceted by PARA + `domains:`. This is
the «navigation surface» Karpathy-style: read INDEX → drill into pages,
no embedding-RAG required at moderate scale.

Runs **once** post-loop, after Step 7 (CURRENT_CONTEXT regen) and Step
7.5 (pattern detect). Cost is one frontmatter pass over knowledge layer
+ hubs (~500 files at current scale, sub-second).

### Input sources

| Source | Used for |
|---|---|
| `1_projects/**/*.md` (excluding README, PROJECTS.md) | Knowledge notes — Projects facet |
| `2_areas/**/*.md` (excluding README) | Knowledge notes — Areas facet |
| `3_resources/**/*.md` (excluding README, PEOPLE.md) | Knowledge notes — Resources facet |
| `5_meta/mocs/*.md` | Hubs facet |

**Exclusions:** `_records/` (operational provenance, not catalog
content), `_sources/`, `_system/`, `0_constitution/` (own
`CONSTITUTION_INDEX.md`), `4_archive/` (dead material — out of scope
for current iteration), `6_posts/` (own pipeline), `5_meta/CONCEPT.md`
+ `5_meta/PROCESSING_PRINCIPLES.md` (engine docs, not knowledge),
`5_meta/templates/`, `5_meta/starter-pack/`.

### Per-entry rendering

For each knowledge note, extract:
- `id` (frontmatter `id:`; fallback to filename stem)
- `title` (frontmatter `title:`)
- `description` (frontmatter `description:` if present)
- `domains` (frontmatter `domains:`; default `[]`)
- `modified` (frontmatter `modified:`; fallback to `created:`)

**Summary fallback chain** (first non-empty wins):
1. `description:` from frontmatter
2. `title:` from frontmatter
3. First non-empty prose line after frontmatter, trimmed to 100 chars
4. Literal `_(no description)_` — explicit signal to owner to add one

For each hub, additionally extract:
- `inbound_count` — count of `[[hub-id]]` references across the base
  (grep `[[id]]` in all `.md` excluding the hub itself, the index
  files in `_system/views/`, and `_system/state/log_*.md`)

### Output format

```markdown
---
id: index
layer: system
generated: {ISO UTC timestamp with Z suffix}
generator: ztn:maintain
note_count: {N}
hub_count: {M}
domain_count: {D}
---

# Wiki Index

Auto-generated by `/ztn:maintain`. Do not edit by hand — changes are
overwritten on next regen. Content-oriented catalog of all knowledge
notes and hubs in the base, with a one-line summary per entry.

This view answers «what's in the wiki» without `grep`. Faceted by PARA
(structural) and `domains:` (semantic). The cross-domain facet is the
quickest way to spot work↔personal bridges already crystallised in the
knowledge layer.

For the synthesis layer (hubs only) see `HUB_INDEX.md`. For values /
identity see `CONSTITUTION_INDEX.md`. For the live focus snapshot see
`CURRENT_CONTEXT.md`.

---

## By PARA

### Projects (`1_projects/`) — {N_proj}

- [[note-id]] — {summary} · `[domain1, domain2]` · {YYYY-MM-DD}
- ...

(empty → `_(empty)_`)

### Areas (`2_areas/`) — {N_areas}

- [[note-id]] — {summary} · `[domain1]` · {YYYY-MM-DD}
- ...

### Resources (`3_resources/`) — {N_res}

- [[note-id]] — {summary} · `[domain1]` · {YYYY-MM-DD}
- ...

---

## By Domain

### work ({N_work})
- [[note-id]] — {summary}
- ...

### identity ({N_identity})
- ...

### {other domain} ({N})
- ...

(Domains rendered in descending count order. Notes with no `domains:`
field appear under `### unscoped ({N_unscoped})` last.)

---

## Cross-domain (≥ 2 domains, {N_cross})

Notes whose `domains:` list contains 2+ values. The highest-leverage
class per engine doctrine §1.4. Observation lens
`cross-domain-bridge` discovers latent bridges; this section
inventories the explicit ones.

- [[note-id]] — {summary} · `[work, identity]` · {YYYY-MM-DD}
- ...

(empty → `_(no cross-domain notes yet)_`)

---

## Hubs (`5_meta/mocs/`) — {M}

- [[hub-id]] — {summary} · `[domains]` · {inbound_count} inbound · upd {YYYY-MM-DD}
- ...

(Sorted by `inbound_count` descending — the centrality signal.)
```

### Sort order within sections

- **By PARA / Cross-domain**: `modified` descending (freshest first)
- **By Domain**: same — `modified` descending within each domain
- **Hubs**: `inbound_count` descending (centrality first), tie-break
  by `modified` descending

### Counts in frontmatter

- `note_count` = total knowledge notes (sum across PARA folders)
- `hub_count` = `len(5_meta/mocs/*.md)`
- `domain_count` = `len(set(union of all domains values))` excluding
  the synthetic `unscoped` bucket

### Atomicity

Write to `_system/views/INDEX.md.tmp` first, then atomic `mv` over
`INDEX.md`. This prevents readers from seeing a half-written file if a
concurrent skill (lens, lint) reads during regen.

### Failure mode

If frontmatter parsing fails for ≥ 1 file: continue with that file
under «unparseable» surfaced in the run report; do not abort INDEX
write. The note is rendered as `[[note-id]] — _(frontmatter parse
error)_` and surfaces to the run report. Lint Scan A.2 already handles
schema normalisation, so this is a transient state.

---

## Step 8: Patch last-batch log_maintenance.md entry with regen + pattern-detect confirmation

The per-batch entries were written in Step 6.5 with
`CURRENT_CONTEXT.md: pending` and `INDEX.md: pending`. After Step 7,
Step 7.5, and Step 7.6 complete successfully:

1. Locate the log_maintenance.md entry for the **last batch** of this run
   (highest batch_id processed).
2. Replace `CURRENT_CONTEXT.md: pending (regenerated post-loop; see last-batch entry for confirmation)`
   with `CURRENT_CONTEXT.md: regenerated (generated: {timestamp}, covers batches {first_id}..{last_id})`.
3. Replace `INDEX.md: pending (regenerated post-loop; see last-batch entry for confirmation)`
   with `INDEX.md: regenerated (generated: {timestamp}, note_count: {N}, hub_count: {M}, domain_count: {D})`.
4. Append a line immediately below noting the Step 7.5 pattern-detect
   result: `principle-candidates.jsonl: +{candidate_count} new candidates
   (session_id: {session_id})`. If Step 7.5 produced zero new candidates,
   write `+0 (no recurring rationale patterns)` to keep the trace explicit.

Earlier batches in the run retain their `pending` notes — readable as
«covered by the last batch's regen», consistent with invariant that regen
runs once per run, not once per batch.

If Step 7 / 7.6 were skipped (e.g. `--dry-run`), leave `pending` in
place and also skip the pattern-detect confirmation — no patch needed.

---

## Step 9: Release Lock

Delete `_sources/.maintain.lock`. Must execute on every path — use finally
semantics.

---

## CLARIFICATIONS Format

Append new items under a single dated header at the END of `## Open Items`
section, BEFORE the HTML comment block:

```markdown
## maintain {YYYY-MM-DD} batch-{batch_id}

### {individual item 1}
...

### {individual item 2}
...
```

If a maintain run processes multiple batches, use multiple headers (one per
batch) for cleaner grouping.

### Item format (parsable fields + free-form body)

All items use the structured body from the step that raised them
(see Step 2.4, 4.2, 5, 6). Common fields:

- `**Type:**` — one of reason codes below
- `**Subject:**` — the primary entity id
- `**Source:**` — `batch-{id}` always (maintain never cites raw `_sources/*`)
- `**Suggested action:**` — parsable verb from the Resolution-action canonical vocabulary (close-thread / keep-thread-open / promote-tier / pursue-or-close / fix-process / dismiss / etc. — see `_system/docs/SYSTEM_CONFIG.md`)
- `**Confidence tier:**` — surfaced (maintain never auto-applies thread closure / tier promote; HARD RULE)
- `**To resolve:**` — imperative instruction for the owner
- `**Quote:**` — verbatim fragment when applicable (closure fuzzy match,
  transcript quotes for person-ambiguity items)
- `**Context:**` — **mandatory** — 2–4 sentence paragraph self-contained для LLM review session. Includes: what ambiguity is about, why uncertain, related entities inline (wikilinks/ids), relevant live-state context (OPEN_THREADS state, PEOPLE.md row, hub content if applicable), 1–2 candidate resolutions с brief rationale. Owner не открывает source files для resolve.

**Distinction Quote vs Context:**
- `Quote` = verbatim fragment из batch artifact or source (deterministic, grounded)
- `Context` = LLM-synthesized surrounding understanding (what item is *about*, not what was said verbatim)

### Reason codes

- `thread-detection-ambiguous` — new-thread candidate with LLM confidence < 90%
- `thread-closure-suggested` — ≥2/4 closure signals, manual apply needed
- `thread-hub-ambiguous` — 2+ hub candidates for linkage
- `thread-dangling-task-ref` — thread.Related Tasks references missing task
- `tier-promote-suggested` — mentions crossed threshold, manual apply needed
- `mention-count-drift` — PEOPLE.md count vs batch report mismatch
- `batch-malformed-frontmatter`, `batch-version-unknown`,
  `batch-missing-section`, `batch-counts-inconsistent`, `batch-counts-anomaly`,
  `batch-dangling-reference`, `batch-unknown-person` — batch anomalies

Parsable fields are stable across codes to enable automated reader (`/ztn:resolve-clarifications`).
Do not reorder or rename — append-only evolution.

---

## Output Report

Write to user (stdout) at end of run:

```
## ZTN Maintain Report — YYYY-MM-DD

### Batches Processed: N
{For each batch, one line:}
- {batch_id}: +{threads_opened} threads, +{backrefs} back-refs, +{hubs_linked} hubs, {suggestions_raised} CLARIFICATIONS

### Aggregated Summary
- Threads opened: N
- Back-references written: N (across M records/notes)
- Hubs linked: N (across K unique hubs)
- Closure suggestions raised: N
- Tier promote suggestions raised: N
- Mention drifts flagged: N
- Batch anomalies flagged: N

### CLARIFICATIONS Raised: N
{list with Type + Subject + Suggested action for each, grouped by reason code}

### State Updates
- OPEN_THREADS.md: {Active N→M}
- CURRENT_CONTEXT.md: regenerated (batch_id: {last})
- INDEX.md: regenerated (note_count: {N}, hub_count: {M}, domain_count: {D})
- log_maintenance.md: +{N} entries

### Completion Gate
- [x] All unprocessed batches iterated (N processed)
- [x] Lock released
- [x] CURRENT_CONTEXT regenerated
- [x] INDEX regenerated
- [x] log_maintenance.md entries written (one per batch)
- [x] No silent closures — maintain never moves threads to Resolved, suggest-only
- [x] No silent tier changes — maintain never edits PEOPLE.md Tier column
- [x] Back-refs only modified frontmatter of records/notes (body untouched)
- [x] No writes to TASKS.md / CALENDAR.md / _records/ body / PARA body / PEOPLE.md counts or tier

### Next Actions for Owner
{if any CLARIFICATIONS were raised:}
Run `/ztn:resolve-clarifications` to review the queue interactively. Specifically pending:
- {N} thread closures suggested — skill renders signals + hypothesis, applies move to OPEN_THREADS.md `## Resolved` on confirm
- {N} tier promotes suggested — skill proposes PEOPLE.md Tier edit with diff
- {N} batch anomalies — surfaced for review; root cause may need `/ztn:process` re-run
```

---

## Example Usage

```
/ztn:maintain
/ztn:maintain --dry-run
/ztn:maintain --batch 20260417-211522
/ztn:maintain --verbose
```

---

## Invariants

These are structural invariants maintain guarantees:

1. **Zero writes** to: `_records/meetings/*` + `_records/observations/*` body, PARA notes body, `_system/TASKS.md`,
   `_system/CALENDAR.md`, `_system/state/BATCH_LOG.md`, `_system/state/batches/*`,
   `_system/state/PROCESSED.md`, `_system/SOUL.md`, `3_resources/people/PEOPLE.md`
   (mention counts AND tier column).
2. **Only frontmatter writes** allowed on records/notes — specifically the
   `threads:` back-reference field. No body modifications, no other frontmatter
   fields touched.
3. **Idempotent retry** — running `/ztn:maintain` twice on the same unprocessed
   set must yield identical state on second run. Guaranteed by:
   - Per-batch log_maintenance.md write in Step 6.5 (inside loop) — a crash
     mid-loop leaves already-processed batches marked, retry skips them.
   - Back-ref writes are append-if-missing (check before append).
   - Header counter updates are parsed + incremented from live state, not
     cumulative across runs.
4. **No silent apply** — thread closures and tier promotions never executed
   by maintain. Only CLARIFICATIONS raised.
5. **Lock always released** — finally semantics mandatory.
6. **CURRENT_CONTEXT + INDEX regenerated when batches were processed** —
   if at least one batch reached Step 6.5, Step 7 (CURRENT_CONTEXT) and
   Step 7.6 (INDEX) each run once post-loop. Exceptions: `--dry-run` (no
   regen), empty unprocessed set (never reaches post-loop — Early Exit
   handles it). INDEX regen failure does NOT abort the run — surface in
   report, continue to Step 8 with `INDEX.md: regen-failed ({error})` in
   the log patch.
7. **Best-effort on malformed batch** — hard fail is forbidden. Every anomaly
   must have a workaround + CLARIFICATION.
8. **Empty batch safe** — a batch with 0 records, 0 notes, 0 tasks still
   passes through cleanly: 0 threads opened, 0 back-refs, 0 hubs linked,
   log_maintenance.md entry written with zeroed counters. CURRENT_CONTEXT
   and INDEX regen still run post-loop (fresh timestamp even if state
   didn't change).
9. **Existing threads (pre-Phase-3 format) handled gracefully** — threads
   created by bootstrap without `Related Tasks` or `hub:` fields do not cause
   errors. Corresponding closure signals are excluded from scoring (Step 5).

---

## Contract dependencies

Maintain consumes artifacts produced by `/ztn:process`:
- `_system/docs/batch-format.md` frontmatter schema
- Inline Mentions increment in PEOPLE.md (1-per-file rule)
- Structured batch sections per `_system/docs/batch-format.md`

If a batch is malformed or written by an unknown processor version — treat
per Step 1 malformed-handling table, raise `batch-version-unknown` or
`batch-malformed-frontmatter` CLARIFICATION, continue best-effort.
