---
name: ztn:lint
description: >
  Nightly slop catcher for ZTN. Reads the whole base, autonomously fixes
  the obvious, surfaces the non-obvious as CLARIFICATIONS with rich Context
  paragraphs (self-contained для LLM review session), generates Lint Context
  Store (30-day rolling daily + forever monthly summaries = system memory beyond
  lint). Confidence tier routing (silent/noted/reviewed/surfaced/hidden) via
  rule-floor × LLM-verdict. Dedup = content-merging (not destructive).
  Cross-skill lock awareness symmetric. Best-effort, idempotent, rollback via git.
disable-model-invocation: false
---

# /ztn:lint — Nightly Slop Catcher

Autonomous ночной ревизор базы.

**Philosophy:**
- Autonomy-first with audit — lint действует как owner сам бы рефакторил базу
  ночью, но каждое действие логируется с fix-id + rollback via git
- Unified format non-negotiable — все profiles + CLARIFICATIONS в canonical schema
- Dedup = content-merging, not destructive — worst-case wrong merge = related-topic
  content landed в primary, reversible via git revert
- CLARIFICATIONS self-contained — mandatory `**Context:**` paragraph
- Lint Context Store = system memory beyond lint (owner, future agents)
- Best-effort over hard fail — never abort run due to single file anomaly

**Contracts:** `_system/docs/ENGINE_DOCTRINE.md` (operating philosophy
— load first; binding cross-skill rules — F.5 non-personal-origin
guard implements §3.6 owner-LLM contract; lint as «curation-on-promotion»
gate per §3.2),
`_system/docs/SYSTEM_CONFIG.md` (Data & Processing Rules, Profile
template, Log file ownership, Cross-skill exclusion, CLARIFICATIONS
format), `5_meta/PROCESSING_PRINCIPLES.md` (8 principles — slop
detection calibrated against principle 1 Capture First, principle 5
Evolution Tracking, principle 8 Texture).

**Documentation convention:** при любых edits этого SKILL соблюдай `_system/docs/CONVENTIONS.md` — файл описывает current behavior без version/phase/rename-history narratives.

## Arguments

`$ARGUMENTS` supports:
- `--dry-run` — scan all, report planned actions + diffs for auto-fixes, NO writes
- `--dry-run --verbose` — full diff for every would-be action (auto-fixes + CLARIFICATIONS appends + Lint Context Store generation)
- `--scope fast` — skip expensive scans (dedup + Evidence Trail backfill); use for ad-hoc day-time runs. Default = full
- `--verbose` — include reasoning traces in stdout report (doesn't change scan scope)
- `--force` — bypass «lint ran recently (<6h)» warning
- `--weekly` — force weekly scan triggers (content pipeline reminder, etc.) even if not first run of UTC week
- `--no-sync-check` — skip the data-freshness pre-flight (see below)

---

## Pre-flight: data freshness (non-blocking)

Multi-device safeguard. If `origin` has commits not yet pulled, lint
on a stale snapshot may produce CLARIFICATIONS that another device
already resolved. Courtesy check, not a gate.

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
  ⓘ origin/<branch> ahead by <N> commit(s). Lint on stale data may
    re-surface already-resolved items.

    [s] run /ztn:sync-data first  (recommended)
    [c] continue with current local state
    [d] show pending commits
  ```
- `s` → exit 0 with «owner: run `/ztn:sync-data`, then re-run `/ztn:lint`».
- `c` → proceed; `d` → show log, re-prompt.

---

## Step 0 — Early Exit Check + Cross-Skill Lock Awareness

**FIRST action.** No context load, no work until passed.

### 0.1 Cross-skill lock check (HARD contract — symmetric mutual exclusion)

Read all three lock files в order:
1. `_sources/.processing.lock` — exists → abort с `"/ztn:process running, try again later"`
2. `_sources/.maintain.lock` — exists → abort с `"/ztn:maintain running, try again later"`
3. `_sources/.lint.lock` — exists → abort с `"another /ztn:lint run in progress"` (unless `--force`)

Stale lock (>2 hours old, parse ISO timestamp from file content) → warn, report PID if present, **offer manual removal, do NOT auto-delete.**

### 0.2 Recent-run check

Read `_system/state/log_lint.md` — last entry timestamp. If < 6 hours ago, report:
```
Lint ran {N} hours ago (last entry: {timestamp}). Pass --force to proceed anyway.
```
Exit unless `--force`.

---

## Step 0.3 — Regenerate Constitution Derived Views

Invoke `/ztn:regen-constitution` (or run `python3 _system/scripts/regen_all.py`).
Runs after Early Exit / Recent-run checks so skipped runs do not regenerate,
and before the concurrency lock so a fatal regen failure does not leave a
stray lock file.

Scan F reads the active constitution tree plus the candidate buffer;
Step 2 Context Load reads SOUL.md (which contains the auto-rendered Values
zone). Both require derived views to be fresh relative to `0_constitution/`.

Platform consistency: every pipeline that reads a derived view regenerates
first. Failure is fatal — report the underlying script error and abort the
run before acquiring the lock.

---

## Step 0.5 — Concurrency Lock

Create `_sources/.lint.lock` with content:
```
{ISO UTC timestamp} — lint run, PID {pid}, mode: {full|fast}, args: {$ARGUMENTS}
```

**Finally semantics mandatory:** lock release in every exit path (normal, skip, exception, malformed abort). Wrap Steps 1–9 в try/finally; delete lock in finally. If crashed mid-run, next run detects stale lock + PID absent → safe to remove manually.

---

## Step 1 — Migration Check (one-time)

Before main context load.

### 1.0 Check if migration already done (frontmatter flag)

**Primary detection:** parse `_system/state/log_lint.md` YAML frontmatter. Read `migration_completed` map. Per migration step:
- If `migration_completed.resolved_archive` present → skip §1.A (Resolved Archive migration done)
- If `migration_completed.profile_schema` present → skip §1.B (Profile normalization done)
- If both present → skip Step 1 entirely, proceed к Step 2

**Why frontmatter (not string grep of body):**
- Immune к copy-paste body poisoning (body text never queried for migration detection)
- Survives log rotation (frontmatter migrates к new quarterly file atomically)
- YAML-parseable — type-safe boolean/date values, не brittle regex
- Explicit key naming prevents accidental collision with prose content

**Migration completion protocol (post-success):**
After §1.A + §1.B successfully complete, write/update `log_lint.md` frontmatter:
```yaml
migration_completed:
  resolved_archive: YYYY-MM-DD
  profile_schema: YYYY-MM-DD
```
Fallback к atomic write: full file rewrite with updated frontmatter + existing body preserved. Never partial-write.

**Idempotency guarantee:** Migration steps use **frontmatter-flag post-completion** — flag set ТОЛЬКО после successful completion ВСЕХ подсекций. If crash mid-migration (e.g. 16/32 items migrated + crash before flag write):
- Retry reads frontmatter, sees no `migration_completed.resolved_archive` → re-executes migration
- **Duplicate-prevention safeguard:** before creating new entry в §1.A, grep `## Resolved Items` для match with same `Original-type + Original-subject + Resolution-date` — skip if match exists (idempotent append)
- Profile schema normalization (§1.B) naturally idempotent (checks section presence before inserting)

This ensures single crash mid-migration followed by retry produces same final state as clean single run. Body `### Migration (one-time...)` subsection still written к log entry for audit readability, but NOT used for detection.

### 1.A — Legacy CLARIFICATIONS Resolved Archive migration

Source: `_system/state/CLARIFICATIONS.md` → find section `## Resolved Archive` (legacy table format `| Date | Item | Resolution |`).

For each row in table:

1. Extract `Date`, `Item`, `Resolution` prose.
2. LLM transformation prompt:
   ```
   Given legacy resolved CLARIFICATION:
   - Date: {date}
   - Item: {item text}
   - Resolution: {resolution text}
   
   Infer and produce structured fields:
   - Original-type: {one of: person-identity | people-bare-name | idea-ambiguous-match |
     topic-classification | cross-domain-link | project-identity | 
     evidence-trail-anomaly | process-compatibility | (unknown)}
   - Original-subject: {primary entity — person-id, note-id, batch-id, or subject string}
   - Resolution-action: {canonical verb — close-thread | keep-thread-open | close-partial |
     promote-tier | demote-tier | merge-notes | dismiss-duplicate | 
     backfill-evidence-trail | resolve-bare-name | create-profile | 
     fix-process | dismiss | defer | (needs-review)}
   - Resolution-target: {machine-readable id if derivable, else (none)}
   - Resolution-payload: {YAML block с deriveable structured data, or empty if unclear}
   - Confidence: high | medium | low
   ```
3. Write structured item под `## Resolved Items` section (create section if absent):
   ```markdown
   ### {resolution-date} — resolved: {original-type}: {original-subject}
   
   **Status:** resolved
   **Original-type:** {type or (unknown)}
   **Original-subject:** {subject}
   **Original-raised:** (unknown — migrated from legacy table)
   **Resolution-date:** {date from legacy}
   **Resolution-action:** {canonical verb or (needs-review) if LLM uncertain}
   **Resolution-target:** {target or (none)}
   **Resolution-payload:**
     ```yaml
     {inferred YAML block or {} if empty}
     ```
   **Applied:** yes (pre-Phase-4, legacy) 
   **Rationale:** {original Resolution prose verbatim — preserves owner's reasoning}
   
   _(Migrated from legacy Resolved Archive table on {YYYY-MM-DD} by ztn:lint; LLM confidence: {high|medium|low})_
   ```
4. If LLM confidence = low OR `Resolution-action: (needs-review)` → flag in migration low-confidence list.
5. After all items written, **delete legacy `## Resolved Archive` table entirely** from CLARIFICATIONS.md.

Raise CLARIFICATION `migration-item-needs-review` for each low-confidence item (surfaced tier — owner validates manually):

```markdown
### {YYYY-MM-DD} — migration-item-needs-review: {subject}

**Type:** migration-item-needs-review
**Subject:** {subject from legacy item}
**Source:** lint-{run-id} (migration step)
**Confidence tier:** surfaced
**Suggested action:** validate-migration

**Context:** Legacy Resolved Archive item migrated with low LLM confidence — Resolution-action unclear или Subject ambiguous. Original legacy text: «{Item}» resolved as «{Resolution}». LLM couldn't confidently map to canonical vocabulary. Owner validates manually, corrects Resolution-action field if needed.

**To resolve:** Read migrated item в CLARIFICATIONS.md `## Resolved Items`, correct `Resolution-action` / `Resolution-target` / `Resolution-payload` fields; remove `(needs-review)` marker. Mark this migration-item-needs-review CLARIFICATION as resolved.

**Uncertainty:** {LLM's specific doubt — что именно unclear}
```

### 1.B — Profile schema normalization

Iterate `3_resources/people/*.md`:

1. Parse frontmatter — ensure keys: `id`, `name`, `role`, `org`, `tags`. If missing any — flag for reviewed tier (ambiguous content), skip auto-fix.
2. Parse body structure. Verify sections present в canonical order:
   - `# {Name cyrillic}` (heading with name)
   - `**Role:** {line}` (one-line role)
   - `## Контекст`
   - `## Мои наблюдения`
   - `## Упоминания`
3. For each missing section:
   - `## Мои наблюдения` missing → insert placeholder: `## Мои наблюдения\n\n_(заполняется вручную)_\n\n` before `## Упоминания` (or at end if Упоминания also missing). **Silent tier** (structural schema fix, never generates private content).
   - `## Упоминания` missing AND inbound references exist (grep record/note frontmatter for person-id in `people:`) → insert section with top 10 wikilinks chronologically. **Silent tier** (deterministic from data).
   - `## Упоминания` missing AND no inbound references → insert empty section placeholder: `## Упоминания\n\n_(нет упоминаний)_\n`. **Silent tier**.
   - `## Контекст` missing → do NOT auto-insert (content decision). Raise CLARIFICATION `profile-context-missing` (surfaced tier).
   - `**Role:**` line missing but `role` in frontmatter → add line from frontmatter. **Silent tier**.
   - `# {Name}` heading missing → derive from `name` frontmatter. **Silent tier**.
4. Preserve existing content of any sections present — never overwrite.
5. Record fix-id в log_lint.md Auto-Fixes entry (NO inline marker — single-source-of-truth, Step 4).

Idempotent — re-running finds no missing sections → no writes.

### 1.C — Write Migration log entry

Structured subsection для Step 7 log_lint.md entry:

```markdown
### Migration (one-time, completed {YYYY-MM-DD})

- **Resolved Archive:** {N_migrated} items migrated to structured format
  - High confidence: {N_high}
  - Medium confidence: {N_med}
  - Low confidence (flagged migration-item-needs-review): {N_low}
  - Legacy table deleted: yes
- **Profiles normalized:** {N_profiles_updated} / 61 profiles
  - Missing `## Мои наблюдения` added: {N_moi}
  - Missing `## Упоминания` added: {N_mentions}
  - Missing `## Контекст` flagged (profile-context-missing): {N_context}
  - Missing heading/role restored: {N_meta}
- **Unified format achieved:** ✓ (all profiles match canonical schema; all resolved CLARIFICATIONS in structured format)
```

---

## Step 2 — Context Load

Load into memory (streamed on-demand where noted):

**Core live state:**
- `_system/SOUL.md` (Focus + Values + Working Style — used by Scan E + monthly SOUL advice)
- `_system/docs/SYSTEM_CONFIG.md` (Data & Processing Rules, Tier thresholds, Profile template, CLARIFICATIONS format contract)
- `3_resources/people/PEOPLE.md` (all persons, Tier/Mentions/Last — used by Scan C)
- `_system/state/OPEN_THREADS.md` (Active + recent Resolved — used by Scan B)
- `_system/TASKS.md` (Waiting/Action/Delegate sections — thread activity detection)
- `_system/CALENDAR.md` (next 7 + past 7 days)
- `_system/state/CLARIFICATIONS.md` (Open Items + Resolved Items structured — post-migration)
- `_system/state/BATCH_LOG.md` (last 30 days)

**Log files (read-only для activity):**
- `_system/state/log_lint.md` (previous runs, own history)
- `_system/state/log_maintenance.md` (maintain activity signals)
- `_system/state/log_process.md` (process chronological, recent entries)

**Lint Context Store:**
- `_system/state/lint-context/daily/*.md` — last 30 if exist (empty on first run post-bootstrap)
- `_system/state/lint-context/monthly/*.md` — last 3 if exist

**Hubs:**
- `_system/views/HUB_INDEX.md`
- `5_meta/mocs/*.md` (frontmatter + `## Ключевые выводы` + `## Открытые вопросы` sections — on-demand streamed via glob)

**Streamed on-demand during scans:**
- `_records/meetings/*.md` + `_records/observations/*.md` (Scan A, B, D — both record kinds)
- PARA: `1_projects/**/*.md`, `2_areas/**/*.md`, `3_resources/**/*.md`, `4_archive/**/*.md` (Scan A, D, E)
- `3_resources/people/*.md` profile bodies (Scan C)
- `_sources/processed/**/transcript*.md` (Scan C.4 mention drift — sampled, not full)
- `_system/state/PROCESSED.md` (Scan C.4 baseline)
- `_system/views/CONTENT_OVERVIEW.md` (if exists, Scan E.2)

---

## Step 3 — Scan Pipeline (Scans A–E)

Scans run sequentially (some feed each other: A-fixed links used by B; C-normalized people used by D). Each scan:
1. Collects raw candidates
2. For each candidate → compute rule-floor + run LLM verdict prompt (§Step 3 Confidence Routing below)
3. Route per tier table → add to run worklist (apply-or-clarification)

### Suppression pre-check (applies к all scans before candidate-to-worklist routing)

**Before** adding candidate к worklist as CLARIFICATION, run suppression check (§Principles §5):

1. Compute candidate's «suppression key» — deterministic signature:
   - Dedup pair: `dedup:{sorted([primary_id, secondary_id])}`
   - Thread: `thread:{thread-id}`
   - Orphan note: `orphan:{note-id}`
   - Tier demote: `tier-demote:{person-id}`
   - Profile extensions: `profile-extensions:{person-id}`
   - Content pipeline: `content-pipeline` (global key)
   - etc.
2. Scan `_system/state/CLARIFICATIONS.md` `## Resolved Items` for matching `Original-subject` × `Resolution-action` ∈ canonical suppression set (defined in `_system/docs/SYSTEM_CONFIG.md` Data & Processing Rules).
3. If match AND within active suppression window → do NOT add к CLARIFICATIONS worklist. Instead log к `log_lint.md` `### Hidden (verbose audit)` с reason `suppressed-via-resolved` + Resolved Item's `Resolution-date` + suppression window end date.
4. **Semantic-change exception:** if candidate's underlying evidence materially changed post-resolution (dedup similarity Δ >10%, thread gained new back-refs, orphan got inbound link), bypass suppression — re-surface CLARIFICATION с explicit prefix в Context: «⚠ Re-surfaced after `{resolution-action}` on `{date}` — material evidence change: {delta description}».

Suppression applies к ALL scans (A–F) producing surfaced-tier CLARIFICATIONS. Reviewed-tier (apply + validate) CLARIFICATIONS are NOT suppressed — they represent actual changes executed, always reported.

### Scan A — Consistency & Structural

**A.1 Broken wikilinks:**
- Grep all `.md` files for `[[...]]` patterns
- For each link target, check if file exists в expected paths (records, PARA, hubs, people)
- If exact match → OK
- If unique case/whitespace variant exists → `strong` floor, auto-fix candidate (normalize to correct case)
- If 2+ candidates → `weak` floor, CLARIFICATION `link-broken-2plus-candidates`
- If 0 candidates → `weak` floor, CLARIFICATION `link-broken-unresolvable`

**A.2 Frontmatter schema normalization:**
- Iterate all notes/records/hubs/profiles
- Check required keys per layer (record/knowledge/hub/person)
- Missing `modified:` → copy `created:` (`strong` → silent)
- Missing `layer:` → infer from folder path (`strong` → silent)
- Missing `tags:` → empty list `tags: []` (`strong` → silent)
- `tags:` string not list → wrap in list (`strong` → silent)
- Frontmatter invalid YAML → `weak`, CLARIFICATION `frontmatter-unfixable-schema`

**A.3 Duplicate hub bullets:**
- For each hub в `5_meta/mocs/`, scan `## Открытые вопросы` for exact-duplicate bullets (same wikilink + same text)
- Remove duplicates (keep first occurrence), `strong` → silent

**A.4 Duplicate back-refs in frontmatter `threads:` lists:**
- Iterate records/notes, check frontmatter `threads:` list for duplicates
- Remove duplicates, `strong` → silent

**A.5 Orphan files:**
- For each note/record, check if inbound references exist:
  - Mentioned in any hub bullet
  - Mentioned в any thread's Source field
  - Mentioned в any other note's wikilinks
  - Referenced in PROCESSED.md
- Zero inbound → `weak`, CLARIFICATION `orphan-file`

### Scan B — Thread Lifecycle

**B.1 Stale thread detection per-status:**

Per-status thresholds (warn → escalate):
- `waiting-for-response`: 2 weeks → 5 weeks
- `needs-decision`: 3 weeks → 6 weeks
- `needs-research`: 4 weeks → 8 weeks
- `blocked`: 6 weeks → 10 weeks

Activity detection (reset counter if ANY):
- Thread-id mentioned в last N daily summaries (N = warn-threshold weeks) in Lint Context Store
- Related task moved Done/Cancelled since thread's `Since`
- Back-ref added to record/note with this thread-id (from `log_maintenance.md` entries since last lint run)
- Hub bullet about thread updated
- LLM semantic match — last 7 days records mention thread's topic/people (even without structural back-ref)

If past warn → CLARIFICATION `thread-stale-warn` (**surfaced tier** — no apply per HARD RULE, thread closure manual only).
If past escalate → CLARIFICATION `thread-stale-escalate` (**surfaced tier** — explicit decision required, no apply per HARD RULE).

**Tier note:** thread closure всегда HARD RULE (no auto-apply regardless of signal strength). Surfaced tier matches реальное apply behavior (no apply, user decides). Signal strength передаётся через Context paragraph (prose), не через tier label.

**B.2 Thread-hub linkage backfill:**
- For each Active thread без `hub:` field, search hubs for semantic match:
  - People overlap + topic overlap (LLM semantic judgment)
- If strong match (1 hub, people + topic clear) → `strong` floor, reviewed tier (creates linkage, owner validates)
- If weak match → `weak` floor, surfaced tier `thread-hub-linkage-backfill-surfaced`

**B.3 Orphan CLARIFICATIONS escalation:**
- For each Open Item > 3 weeks old → CLARIFICATION `orphan-clarification-escalate` (surfaced tier)
- For each Resolved Item with `Applied: no` > 2 weeks old → CLARIFICATION `applied-pending` (surfaced tier)

### Scan C — People Lifecycle

**C.1 Auto Tier 2→1 profile generation** — dual-apply semantics:
- Iterate PEOPLE.md — find persons с mentions ≥ 8 AND no existing profile file в `3_resources/people/`
- For each crossing candidate:
  - Recent records где person в `people:` frontmatter (top 3–5)
  - LLM infer: role, org, tags
  - Generate canonical profile (reviewed tier apply):
    - Frontmatter: id, name, role, org, tags
    - `# {Name}` heading
    - `**Role:** {role summary}`
    - `## Контекст` — LLM 2–3 sentences from recent records
    - `## Мои наблюдения` — placeholder `_(заполняется вручную)_`
    - `## Упоминания` — top 10 wikilinks chronological
  - PEOPLE.md Tier column update — **HARD RULE blocks auto-apply** (via `/ztn:resolve-clarifications`)

**Dual-apply CLARIFICATION format `tier-promote-auto-profile`:**

```markdown
**Applied sub-actions:**
- profile-file-created: yes (fix-id: lint-{id}-profile-create-{seq})
- people-md-tier-updated: no (HARD RULE — via `/ztn:resolve-clarifications`)
```

One CLARIFICATION carries both sub-actions с explicit status. Reader parses sub-action table for exact apply state per component.

Floor `strong` (threshold deterministically crossed) + LLM high verdict → profile creation tier `reviewed` (file created, validate requested) + tier column update `surfaced` (blocked by HARD RULE).

**C.2 Tier demote candidates:**
- Find persons с current Tier 1 BUT no profile AND mentions dropped < threshold OR no activity в last 60 days
- `strong` floor (deterministic condition) + LLM verdict → always surfaced tier (never apply tier changes per HARD RULE)
- CLARIFICATION `tier-demote-candidate`

**C.3 Orphan bare-name resolution — three-surface scan:**

Bare names can appear at three levels in notes; ALL three must be fixed together for consistency (partial fix creates broken state):

1. **Frontmatter `people:` array entries** matching bare-name pattern (no `-lastname`)
2. **Frontmatter `tags:` array entries** matching `person/{bare-name}` pattern
3. **Body inline wikilinks** `[[{bare-name}]]` — these point к non-existent files (broken wikilinks) until fixed

For each bare name encountered:
- Grep all three surfaces across entire ZTN base
- LLM semantic resolution: bare name → candidate person-id using SOUL + PEOPLE + recent records
- If unambiguous (single `{bare}-*` candidate in PEOPLE.md) + LLM high verdict → `reviewed` tier (apply ALL three surfaces + validate via CLARIFICATION)
- If multiple candidates → surfaced tier `orphan-bare-name-surfaced` с per-file disambiguation

**Three-surface apply logic:**
- For each file containing bare name at any surface:
  - Frontmatter `people:` → replace bare с full-id
  - Frontmatter `tags:` person/{bare} → person/{full-id}
  - Body `[[{bare}]]` → `[[{full-id}]]`
- Each surface = separate fix-id with qualifier `bare-name-resolve-frontmatter` / `bare-name-resolve-tag` / `bare-name-resolve-wikilink`
- **Completion Gate check:** per resolved name, grep all three surfaces → 0 residual bare references. If grep returns non-zero → abort fix (surface) + raise surfaced CLARIFICATION for remaining occurrences.

**CLARIFICATION for reviewed-tier apply:**
Aggregated per resolved name с explicit sub-surface counts:

```markdown
**Applied sub-actions:**
- frontmatter-people: {N} refs (fix-ids {range})
- frontmatter-tags: {N} refs (fix-ids {range})
- body-wikilinks: {N} refs (fix-ids {range})
- total: {T} fixes across {F} files
```

User validates via `git diff` + `grep "operation:bare-name-resolve" _system/state/log_lint.md`.

**C.4 Mention count drift:**
- For each person в PEOPLE.md, recount mentions by scanning all notes/records frontmatter `people:` lists
- If counted != PEOPLE.md `Mentions` column → drift detected
- If drift direction makes semantic sense (note deletion for decrement) → `strong` floor + LLM high → silent tier auto-fix (update Mentions column)
- NOTE: this is exception to «never write PEOPLE.md Mentions» — Mentions column is derived data; silent correction of drift is integrity fix, not process territory. BUT: if ambiguous direction, surfaced tier `mention-count-drift-surfaced`

**C.5 People candidates aggregation (weekly — first lint run of UTC week).**

Gate: current UTC weekday = Monday AND no previous `log_lint.md` entry this week fired C.5. Mirrors the F.3 cadence for `principle-candidates`.

Purpose: reduce friction from one-off bare-name mentions. `/ztn:process` Step 3.8 routes AMBIGUOUS bare names to `_system/state/people-candidates.jsonl` instead of raising a CLARIFICATION per mention. This sub-scan aggregates the buffer weekly and promotes only recurring / information-rich candidates to the resolution queue.

Pipeline:

1. **Read buffer.** Load all entries from `_system/state/people-candidates.jsonl`. If empty → skip (no CLARIFICATION, no archive).

2. **Aggregate by name.** Group entries by `slugify(name_as_transcribed)` (Cyrillic transliteration + lowercase). For each group, compute:
   - `mention_count` = number of distinct `(date, note_id)` pairs in group (double-mentions in same transcript collapse — 1-per-file consistent with PEOPLE.md rule)
   - `first_seen` = earliest `date`; `last_seen` = latest `date`
   - `sources` = deduplicated list of `source` paths
   - `notes` = deduplicated list of `note_id`
   - `role_hints` = deduplicated non-null `role_hint` values
   - `suggested_ids` = deduplicated non-null `suggested_id` values
   - `any_high_importance` = logical OR of `high_importance_hint` across group
   - `age_days` = today - first_seen

3. **Promotion rules (evaluate per group, first match wins).**
   - **R1 — High importance.** If `any_high_importance` AND no CLARIFICATION was already raised at process-time for this group → promote.
   - **R2 — Recurrence.** If `mention_count ≥ 2` → promote.
   - **R3 — Strong context.** If `mention_count == 1` AND (at least one `role_hint` is non-empty AND at least one `related_people` array is non-empty AND `len(quote) ≥ 120` chars) → promote. Rationale: single mention with full role + contextual anchor + substantial quote has enough info for the user to decide without re-reading the transcript.
   - **R4 — Stale dismiss.** If `mention_count < 2` AND `age_days ≥ 90` → auto-dismiss. Move all entries of this group to `_system/state/lint-context/weekly/{YYYY-WW}-people-candidates-dismissed.jsonl` with an appended `dismissal_reason: "stale-single-mention-90d"` field. Do NOT emit a CLARIFICATION — the archive line is the audit trail.
   - **R5 — Hold.** Otherwise, leave in buffer for future weeks.

4. **Emit aggregated CLARIFICATION (one per promoted group).**

   ```markdown
   ### YYYY-MM-DD — people-candidate-promoted: «{name_as_transcribed}» ({mention_count}× mentions, first {first_seen} → last {last_seen})

   **Type:** people-bare-name
   **Subject:** {name_as_transcribed}
   **Source:** aggregated from {N} mentions in buffer (see archive path below)
   **Suggested action:** resolve-bare-name | create-profile | dismiss
   **Confidence tier:** surfaced

   **Promotion rule:** R{1|2|3}

   **Aggregated quotes:**
   {for each entry in group, rendered inline:}
   - {date} — [[{note_id}]] — > «{quote}»
     - role_hint: {role_hint or —}
     - related: {related_people joined or —}
     - suggested_id: {suggested_id or —}

   **Candidates in PEOPLE.md (fuzzy match on name_as_transcribed prefix):** {list or «none»}

   **To resolve:** pick one of:
     (a) create profile `{id}` in `3_resources/people/` + add PEOPLE.md row + update backlinks in each listed note_id;
     (b) map to existing `{id}` (add alias) + backfill `people:` frontmatter in each note_id;
     (c) dismiss (external/one-off) — confirm no profile needed.

   **Archive reference:** `_system/state/lint-context/weekly/{YYYY-WW}-people-candidates-archived.jsonl`
   ```

   Include `high_importance_hint: true` inline on the CLARIFICATION when R1 fires so the reader knows process flagged it but deferred the full CLARIFICATION to this aggregation.

5. **Archive + verify + clear (atomic).** After ALL promoted CLARIFICATIONS are rendered AND all dismissed entries written:
   ```bash
   python3 _system/scripts/archive_buffer.py \
     --buffer _system/state/people-candidates.jsonl \
     --archive-dir _system/state/lint-context/weekly
   ```
   The script needs to support per-buffer archive naming. If the current `archive_buffer.py` hardcodes `principle-candidates`, extend it to use the buffer filename stem as archive prefix (`people-candidates.jsonl` → `{YYYY-WW}-people-candidates-archived.jsonl`). **R5 (held) entries** must be preserved — re-write them back to the buffer after archive (the hold-subset write is the final step).

6. **Exit code 2 from archive → `lint-archive-failure` CLARIFICATION** with stderr message; buffer is NOT cleared so data persists for next week's retry.

**Invariants:**
- Never silent-delete a candidate. Dismissals go to the weekly dismissed archive with explicit `dismissal_reason`.
- Buffer line count before run == Promoted + Dismissed + Held + Archive-failed (conservation law; checked at Completion Gate).
- `mention_count` aggregation is deterministic (unique `(date, note_id)` pairs) — same buffer produces same promotions across re-runs, idempotent if buffer unchanged.
- Fuzzy-match на Cyrillic-variants (e.g. «Антон» ≠ «Антоша» ≠ «Антоха» but same person) is OUT OF SCOPE for this version — each variant is its own group. If the user resolves a group and knows it's an alias of another, they record the alias manually in PEOPLE.md and the next week's R4 cleanup handles stale variants.

### Scan D — Note Lifecycle

**D.1 Dedup scan (content-merging, not destructive):**

Pairs similarity check (expensive — N² for ~400 notes = 80K pairs; sample pre-filter by frontmatter overlap first):
1. **Pre-filter:** pairs с ≥ 2 common `tags` + same `layer` + similar `type` → candidate pool
2. **Similarity scoring** per candidate pair:
   - Title similarity (normalized Levenshtein) × 20%
   - Body semantic similarity (LLM judgment 0–100) × 40%
   - Frontmatter overlap (tags, people, projects union count / total) × 40%
3. Combined score ≥ 90% → strong floor; 75–90% → weak floor; < 75% → skip
4. For tier-routed candidates:
   - **Primary selection** — completeness score:
     - Frontmatter fields filled: +1 each (id, created, modified, tags, people, projects)
     - Evidence Trail present: +3
     - Hub linkage: +2
     - Content length: +1 per 100 words capped at 5
     - Age (oldest): +1
     - Tie-breaker: oldest `created:` → alphabetical id ascending
   - **Unique content extraction** — LLM reads secondary body, identifies content NOT in primary
   - **Merge:**
     - Frontmatter union (tags/people/projects)
     - `modified: {today}`
     - Body: append unique bullets в matching primary sections; add new sections если secondary имеет не-existing
     - `## Evidence Trail`: prepend entry `{today}: merged content from deduplicated note [[secondary-id]]`
   - **Secondary treatment:**
     - `silent` / `noted`: delete secondary file + update PROCESSED.md source pointers → primary + **backlink redirect** (see below)
     - `reviewed`: keep secondary, frontmatter `status: merged-into, merged_into: {primary-id}, modified: today`, CLARIFICATION `dedup-reviewed`
     - `surfaced`: no changes, CLARIFICATION `dedup-surfaced`

5. **Backlink redirect (mandatory for silent/noted merge with delete):**
   - Grep all `.md` files for `[[{secondary-id}]]` content wikilinks
   - Skip audit files: `_system/state/log_lint.md`, `_system/state/CLARIFICATIONS.md ## Resolved Items`, primary note's `## Evidence Trail`
   - Rewrite elsewhere `[[{secondary-id}]]` → `[[{primary-id}]]`, silent tier per-fix
   - Also grep tags `person/{secondary-id}` (rare — applies only if dedup target was profile)
   - Log each as fix-id с qualifier `dedup-backlink-redirect`
   - **Completion Gate check:** post-merge grep `[[{deleted-id}]]` in non-audit files → must return 0

**D.2 Evidence Trail backfill** — two modes:

**Mode A: Template-only backfill (silent tier):**
Conditions (all must hold):
- Knowledge note has `source:` frontmatter pointing к valid transcript path
- Note missing `## Evidence Trail` section
- Task = insert 1-line shell entry: `{created date}: original insight captured — source: \`{source basename}\` (backfilled retroactively)`

This is **deterministic schema completion** — no LLM semantic reasoning, just known-data template. Strong floor + trivial verdict → **silent tier OK**. Treat identical to frontmatter schema normalization (Scan A).

**Mode B: Semantic reconstruction (reviewed floor):**
Conditions (used when Mode A insufficient, e.g. Owner wants richer trail):
- LLM reads source transcript + current note body → reconstructs nuanced trail entries pointing к specific insights derived
- Creates narrative evidence chain, not just template pointer
- Floor `weak` (semantic reasoning carries burden) → **reviewed tier minimum**
- CLARIFICATION `evidence-trail-backfill-surfaced` для cases где source не accessible или LLM uncertain

Initial bulk backfill для legacy notes uses **Mode A** (template pointers). Mode B reserved для opt-in deep enrichment runs.

**D.3 Orphan notes:**
- For each knowledge note, check inbound references (hubs, records, threads, other notes' wikilinks)
- Zero inbound → surfaced tier `orphan-note` (archive candidate)

### Scan E — Focus

**E.1 SOUL focus drift (daily scan):**
- Load SOUL.md Focus (Work + Personal)
- Aggregate themes from last 7–14 days daily summaries (or records if Lint Context Store thin)
- LLM rubric: identify themes в activity absent from Focus, Focus items с 0 activity, emerging patterns
- Output: prose assessment (3–5 sentences) + specific observations
- Always surfaced tier `soul-focus-drift` (SOUL never auto-edit — HARD RULE)

**E.2 Weekly content pipeline reminder:**

**Weekly gate check:** Determine if this is first lint run of UTC week (Monday = weekday 0).

```
today_utc = current UTC date
# Check if any prior lint entry this week
this_week_start = today_utc - timedelta(days=today_utc.weekday())  # Monday
read log_lint.md entries with timestamp >= this_week_start
if any entry found:
  skip content pipeline reminder scan (already fired this week, even if on different day)
else:
  run trigger logic below
```

Exception: `--weekly` flag bypass — force weekly gate check to fire regardless of cadence (for manual validation or non-Monday schedules).

Trigger logic (only if weekly gate allows):
1. If `_system/views/CONTENT_OVERVIEW.md` doesn't exist AND ≥ 5 high-content_potential notes present → raise reminder
2. If exists AND frontmatter `generated:` > 7 days ago AND ≥ 5 new high-content_potential notes added since → raise reminder
3. If exists AND generated ≤ 7 days → skip

CLARIFICATION `content-pipeline-reminder` (surfaced tier, aggregated, not per-note).

**Edge case — first-ever lint run:** no log_lint.md entries previously → weekly gate treats as eligible (first run fires reminder regardless of weekday; subsequent runs этой недели skip).

---

### Scan F — Constitution Alignment

Health + maintenance of the `0_constitution/` layer. Seven sub-scans with
explicit cadences; daily scans run every invocation, weekly and monthly
scans gate on first lint run of the UTC week / month. Scan F never edits
principle body content (L1 write limit — see `0_constitution/CONSTITUTION.md`
§8); it only appends to Evidence Trail (on F.5 auto-merge) and surfaces
CLARIFICATIONS.

Input across the whole scan: walk `0_constitution/`, load
`_system/state/principle-candidates.jsonl`, consult recent `_records/` for drift
context.

#### F.1 — Stale principles (daily)

For each principle where `last_reviewed` is older than 180 days: raise a
CLARIFICATION `principle-stale` with subject=principle.title,
Quote=principle.statement, Uncertainty="Last reviewed {date}; > 180 days
old", To resolve="confirm still applicable / rephrase / deprecate".

#### F.2 — Historical drift re-scan (manual only, `--rescan-drift`)

Not on daily cadence. Triggered by explicit `/ztn:lint --rescan-drift --days N`
(default N=30). Purpose: after a retroactive principle edit, walk recent
decision records and re-check alignment against the updated tree.

Per-record logic mirrors `/ztn:process` Step 3.7.5 but emits CLARIFICATIONS
of type `principle-drift-retro` (distinct from daily `principle-drift`) so
the user can tell historical rescans apart from live checks.

#### F.3 — Candidate aggregation (weekly — first lint run of UTC week)

Gate: current UTC weekday = Monday AND no previous log_lint.md entry this
week fired F.3.

Pipeline:
1. Read `_system/state/principle-candidates.jsonl`. If empty → skip.
2. Render ONE CLARIFICATION `principle-candidate-batch` with **all
   candidates inline** (not by reference to the jsonl — entries must stay
   readable if the file rotates). Per candidate: situation, observation,
   hypothesis, suggested_type, suggested_domain, origin, session_id,
   record_ref, date captured.
3. **Archive + verify + clear** — invoke:
   ```bash
   python3 _system/scripts/archive_buffer.py
   ```
   The script copies the buffer to
   `_system/state/lint-context/weekly/{YYYY-WW}-principle-candidates-archived.jsonl`,
   re-reads the archive, verifies line count matches, then clears the
   buffer. Exit code 2 = verify failed → raise CLARIFICATION
   `lint-archive-failure` with stderr message as body; **buffer is not
   cleared** on failure so candidates persist for next week's retry.
4. The aggregate CLARIFICATION references the archive path
   (`_system/state/lint-context/weekly/{YYYY-WW}-principle-candidates-archived.jsonl`)
   so the user can trace each candidate from the CLARIFICATION back to
   the raw buffer entry.

Never silent-delete a candidate. If owner rejects one on review, he writes
the rejection outcome inline in the resolved CLARIFICATION — the
archived jsonl stays forever as audit trail.

#### F.4 — Health metrics (monthly — first lint run of UTC month)

Gate: current UTC day = 1 AND no previous log_lint.md entry this month
fired F.4.

Append a block to `_system/state/lint-context/monthly/{YYYY-MM}.md` under a
dedicated `## Constitution` section:

```
## Constitution ({YYYY-MM})
- Active principles: {N}
  - axioms: {N} · principles: {N} · rules: {N}
- Core (core=true, non-placeholder): {N} (watch: surfaces F.6 if > 10)
- Archived this month: {N}
- Stale surfaced this month (F.1): {N}
- Candidates surfaced: {N_total} → accepted {N_accepted} / rejected {N_rejected} / deferred {N_deferred}
- Auto-merges performed (F.5): {exact: N, llm: N}
- Evidence Trail compactions (F.7 approved): {N}
- Most-cited principles (top 3 by Evidence Trail length): {id1}, {id2}, {id3}
- Most-contradicted (top 3 by citation-violated count, if any): ...
```

Numbers come from this month's log_lint.md entries + a tree walk at
write time. This is information for owner's review, not a trigger for
automation.

#### F.5 — LLM-judge merge (daily, L2 write)

Input: `principle-candidates.jsonl` + visible active principles (via
`query_constitution.py`).

**Level 1 — exact match (no LLM).** For each candidate, normalise its
`hypothesis` + `observation` (lowercase, strip punctuation, collapse
whitespace). Compare against each active principle's normalised
`statement`. On equality: append Evidence Trail entry to the active
principle (`automerge-exact` event type, reference the candidate record),
remove the candidate from the buffer, raise CLARIFICATION
`principle-automerge-exact` (info-only).

**Level 2 — Opus LLM-judge (for everything not resolved by Level 1).**
Invoke reasoning LLM with prompt:

> Candidate: `{content}`
> Active principles in overlapping domains: `{list}`
> Is the candidate:
>   (a) a semantic duplicate of one of the principles (same meaning,
>       different wording)?
>   (b) an edge-case / extension of one principle (adds context without
>       contradicting)?
>   (c) a new independent principle?
>   (d) noise / non-principle (stylistic / emotional reaction without
>       rule-content)?
> Return JSON `{verdict, target_principle_id, confidence, reasoning}`.

- `(a) confidence > 0.8` → automerge as in Level 1, CLARIFICATION
  `principle-automerge-llm` (info, with LLM reasoning preserved).
- `(b) confidence > 0.8` → add candidate to the target principle's
  `## Related` section as an edge-case reference. CLARIFICATION
  `principle-extended-llm` (info, owner may override).
- `(c)` or low-confidence → candidate stays in buffer for F.3 weekly
  aggregate.
- `(d) confidence > 0.9` → tag candidate as suggested-noise in the
  buffer (add `"suggested_noise": true` to the jsonl entry); F.3 surfaces
  these in a distinct section for explicit owner confirmation. Never
  silent-discard.

**Scope-mismatch guard.** If a candidate and a matching active principle
differ in `scope` (e.g. candidate is `personal`, principle is `shared`),
do not automerge. Raise CLARIFICATION `principle-automerge-scope-mismatch`
so owner resolves the scope before merge.

**Non-personal-origin guard.** Candidates whose `origin` is anything
other than `personal` (e.g. `work`, `external`, `bootstrap-raw-scan`,
`bootstrap-profile`) never qualify for automatic Level 2 merge —
always surface as CLARIFICATION (info tier) and let owner confirm
whether the pattern belongs in the personal tree. Rationale: these
origins represent inferred / batch-extracted / cross-context signals
where high recall is expected at the cost of precision; auto-merge
would erode constitution signal density. Only `origin: personal`
(in-the-moment owner-attended capture) is precise enough to qualify.

#### F.6 — Core bloat watch (daily)

Count principles where `core: true` AND `status != placeholder`.

- ≤ 8: silent.
- 9 or 10: append a line to the monthly summary (F.4), no CLARIFICATION.
- \> 10: raise CLARIFICATION `core-bloat` with subject="Core grew to {N}",
  body="compression discipline is eroding — revisit which of the core
  entries are truly irreducible vs derivable from another core".

#### F.7 — Evidence Trail compaction (weekly — first lint run of UTC week)

For every principle whose `## Evidence Trail` has > 50 entries: raise a
CLARIFICATION `evidence-trail-compact` with inline options:

1. **LLM-compact.** Summarise all entries older than 6 months into one
   `[compacted]` line of the form
   `{YYYY-MM}..{YYYY-MM} — cited N times across M decisions; pattern:
   {one-line synthesis}`. Owner approves / edits / rejects inline.
2. **Keep as-is.** If the history is chronologically valuable.
3. **Selective.** Owner lists specific dates / refs to remove.

On owner approval of option 1 or 3, invoke
`python3 _system/scripts/compact_evidence_trail.py --file {path}
--cutoff {YYYY-MM-DD} --summary "{approved text}"`. The script enforces
the protected-window rule (no compaction newer than 365 days).

#### Scan F output contract

All Scan F output is additive to the existing worklist — Step 4 Apply
Worklist routes CLARIFICATIONS identically to Scan A-E items via the
confidence-tier table.

New CLARIFICATION types introduced by Scan F (vocabulary):
`principle-stale`, `principle-drift`, `principle-drift-retro`,
`principle-tradeoff`, `principle-candidate-batch`,
`principle-automerge-exact`, `principle-automerge-llm`,
`principle-extended-llm`, `principle-automerge-scope-mismatch`,
`core-bloat`, `evidence-trail-compact`, `lint-archive-failure`,
`soul-manual-edit-to-auto-zone` (emitted by `render_soul_values.py`;
Scan F consumes / reports on existence).

All types follow the standard CLARIFICATION schema (Type, Subject,
Source, Action taken, Quote where applicable, Context, Uncertainty,
To resolve).

---

## Step 4 — Apply Worklist

Iterate worklist в deterministic order (Scan A → F → within scan by candidate id).

### Confidence tier routing

Each worklist item has:
- Rule-based floor: `strong` | `weak`
- LLM verdict (4-point rubric с explicit evidence): `high` | `confident` | `probable` | `unsure` | `skip`

LLM verdict prompt (template):
```
Proposed fix: {operation} on {target}.
Context: {SOUL + PEOPLE + Lint Context Store relevant + related notes/hub}.

Answer each (y/n + one-sentence evidence):
1. Is structural match sufficient to apply without further review?
2. Does surrounding context corroborate?
3. Is there an analogous resolved case in CLARIFICATIONS archive?
4. Is there clean counter-evidence suggesting this fix is wrong?

Provide verdict: high | confident | probable | unsure | skip
Provide 2-sentence reasoning.
```

Positives − Negatives → verdict:
- 3–4 pos, 0 neg → `high`
- 2–3 pos, 0 neg → `confident`
- 1–2 pos OR 1 neg → `probable`
- 0 pos OR 2+ neg → `unsure`
- Clean counter-evidence present → `skip`

### Tier combined table → action

| Floor | LLM verdict | Tier | Action |
|---|---|---|---|
| strong | high | `silent` | Apply, log_lint.md Auto-Fixes entry (no CLARIFICATION) |
| strong | confident | `noted` | Apply, log_lint.md Auto-Fixes entry with confidence note (no CLARIFICATION) |
| strong | probable | `reviewed` | Apply + CLARIFICATION «validate» (cross-referenced by fix-id) + log_lint.md Auto-Fixes entry |
| weak | high | `reviewed` | Apply + CLARIFICATION (semantic-only match — always validate) + log_lint.md Auto-Fixes entry |
| weak | confident | `surfaced` | No apply, CLARIFICATION only |
| strong | unsure | `surfaced` | No apply, CLARIFICATION only |
| any | unsure (2+ neg) OR skip | `hidden` | No apply, no CLARIFICATION, log_lint.md Hidden subsection only |

**NO inline markers** in target files regardless of tier — see §«No inline markers в target files» below. `log_lint.md` is the single source of truth for audit trail; notes остаются clean reading state.

### HARD RULES override (§1 Принципы, non-negotiable)

Regardless of tier routing:
- Thread closure (move OPEN_THREADS Active → Resolved + hub coordination) → NEVER apply, max tier `surfaced`
- Tier change в PEOPLE.md Tier column (promote OR demote) → NEVER apply, max tier `surfaced`
- SOUL.md edits → NEVER apply
- Record/note body edits вне dedup-merge → NEVER
- PEOPLE.md Mentions column increment (non-drift-correction) → NEVER

**Profile generation** (C.1) — max tier capped at `reviewed` (creates new file, always validate first iteration).

### Conflict handling (same file, multiple ops)

Sequential mutation — each op re-reads target file immediately before write (catches earlier mutations). All auto-fix ops idempotent (check-before-apply) → re-reads safe.

### No inline markers в target files

**`log_lint.md` = single source of truth** для all fix audit trail. NO HTML-comment markers inserted в target notes. Rationale:
- Notes остаются clean для reading/reference use — not polluted debug info
- No marker accumulation across multiple lint runs (avoid N markers per file after N runs)
- Centralized history in one file simplifies grep + audit + rollback
- git commit + fix-id combination уникально locates any change

**Forensic workflow:**
- Странное изменение в файле X → `grep "target:{X}" _system/state/log_lint.md` → full fix record (fix-id + operation + before/after + reasoning + rollback hint)
- «Find all dedup operations» → `grep "operation:dedup" _system/state/log_lint.md`
- «Find all Evidence Trail backfills» → `grep "operation:evidence-trail" _system/state/log_lint.md`
- Rollback → `git log` + fix-id lookup → `git revert` or manual

### fix-id format (mandatory extended)

**Normal run:**
```
lint-{YYYYMMDD}-{run-seq}-{operation-qualifier}-{op-seq}
```

**`--force` run (lock-bypass):**
```
lint-{YYYYMMDD}-{run-seq}-p{PID}-{operation-qualifier}-{op-seq}
```

Components:
- `YYYYMMDD` — UTC date of lint run start (no dashes)
- `run-seq` — 3-digit counter per day (`001`, `002`, ...)
- `p{PID}` — **only when `--force` flag active** — OS process ID prevents collision between parallel `--force` runs bypassing lock
- `operation-qualifier` — **mandatory** — operation class identifier (kebab-case). Examples: `scan-a`, `scan-b`, `scan-c`, `scan-d-trail`, `dedup`, `dedup-backlink-redirect`, `profile-schema`, `migration-profile`, `migration-resolved`, `bare-name-resolve-frontmatter`, `bare-name-resolve-tag`, `bare-name-resolve-wikilink`
- `op-seq` — sequential counter per qualifier within run

Examples:
- `lint-20260420-001-evidence-trail-42` — 42nd Evidence Trail backfill в run 001 on 2026-04-20 (normal)
- `lint-20260420-001-dedup-1` — 1st dedup merge (normal)
- `lint-20260420-001-bare-name-resolve-wikilink-3` — 3rd body-wikilink substitution (normal)
- `lint-20260420-002-p54321-scan-a-7` — Scan A fix #7 in `--force` run (PID 54321)

**Qualifier обязателен** — enables greppable operation-level analysis directly в `log_lint.md` без lookup tables.

**Rationale for PID-on-force:** `--force` bypasses cross-skill lock. Two parallel `--force` runs same day = counter collision risk. PID inclusion guarantees uniqueness без complicating normal id format.

### Applied CLARIFICATION format (mandatory Context field)

```markdown
### {YYYY-MM-DD} — {reason-code}: {subject-short-title}

**Type:** {reason-code}
**Subject:** {entity-id}
**Source:** lint-{run-id}
**Suggested action:** {canonical Resolution-action verb — see `_system/docs/SYSTEM_CONFIG.md`}
**Confidence tier:** {silent|noted|reviewed|surfaced}
**Applied:** {no — if surfaced, yes/fix-{id} — if reviewed}
**Fix-id:** lint-{run-id}-{seq} (cross-reference to log_lint.md Auto-Fixes entry, если applied)

**Quote:** > «{verbatim fragment, 1-3 sentences, when applicable (transcript source)}»

**Context:** {2-4 sentence paragraph — what ambiguity is about, why uncertain, related entities inline with wikilinks, relevant facts from Lint Context Store / SOUL / related hub, 1-2 candidate resolutions with pros/cons}

**Recent contexts:**
- [[{note-id-1}]] — {1-line hint, date}
- [[{note-id-2}]] — {...}

**To resolve:** {imperative — what unblocks system}

**Uncertainty:** {LLM doubt — edge cases, counter-signals}
```

---

## Step 5 — Lint Context Store — Daily Generation (gap-aware catch-up)

After worklist applied, generate all missing daily summaries between `latest_daily_file.date + 1` and yesterday (inclusive).

### Bootstrap mode

If `_system/state/lint-context/daily/` empty → generate last 30 days only (not all-time; cost без value for ancient days). Older days remain un-generated; monthly catch-up uses whatever dailies available.

### Per-day generation

For each target date:
1. Skip if `_system/state/lint-context/daily/{date}.md` already exists.
2. Collect source data:
   - `BATCH_LOG.md` entries dated this day
   - `PROCESSED.md` entries with `created:=this day`
   - `log_maintenance.md` entries dated this day
   - `log_process.md` entries dated this day
   - OPEN_THREADS.md, TASKS.md state diffs (если snapshot possible vs previous day)
3. **Quiet day detection:** if all source data empty → quiet day template with thread-state snapshot + weekday context + pattern from last 7 days.

### Daily format

```markdown
---
id: lint-daily-{YYYY-MM-DD}
layer: system
generated_by: ztn:lint
generated: {ISO UTC timestamp}
covers: {YYYY-MM-DD}
quiet_day: {true|false}
---

# Daily Summary — {date}

## Activity
- Batches processed: {N} ({ids}) | Records: {N} | Notes: {N} | Tasks added: {N} / done: {M}
- Threads: opened {N}, closed {M}, merged {K}
- People: {N} mention events across {M} persons
- Hubs touched: {ids with bullet/content counts}

## Hotspots
- Most-mentioned people (top 3): {ids + counts}
- Most-active threads: {ids}
- Hub of the day (if notable): {id + activity}

## Auto-Fixes (lint previous run)
- {brief summary if lint ran this day — per-tier count}
- (none) — on quiet day or if lint didn't run

## CLARIFICATIONS
- Raised: {count + reason codes breakdown}
- Resolved: {count}

## Notable (LLM-synthesized, 2-4 sentences)
{prose observations — what mattered, why, what drifted; quiet day — contextual commentary from recent patterns + weekday}
```

### Retention purge

After all daily writes, scan `_system/state/lint-context/daily/`, delete files с `{date}.md` date < today − 30 days.

---

## Step 6 — Lint Context Store — Monthly Generation (gap-aware catch-up)

Check for missing monthlies:
1. Read `_system/state/lint-context/monthly/` — find latest sealed month.
2. For each month between `latest_monthly + 1` and `current_month - 1` (inclusive) — generate missing monthly.

### Per-month generation

1. Load daily files from target month (whatever present — gap tolerance).
2. Load live-state snapshots (OPEN_THREADS, PEOPLE, CLARIFICATIONS Resolved archive, content pipeline):
   - For immediately previous month: use current state as snapshot (fresh).
   - For deeper backfill: snapshot `_system/` current state, mark в frontmatter `snapshot_at: {current-date}` (honest limitation).
3. LLM prompt generates summary per template below.
4. **SOUL advice trigger:** if generating monthly AND this month is immediately previous (not deep backfill) → raise `soul-update-advice` CLARIFICATION. Deeper backfill skips SOUL advice (stale recommendations = noise).
5. Write `_system/state/lint-context/monthly/{YYYY-MM}.md`.

### Monthly format («нормальный документ» per Owner)

```markdown
---
id: lint-monthly-{YYYY-MM}
layer: system
generated_by: ztn:lint
generated: {ISO UTC timestamp}
covers: {YYYY-MM-01}..{YYYY-MM-LAST}
daily_coverage: {N}/{days_in_month}
snapshot_at: {generated_date | "fresh" if immediately previous month}
---

# Monthly Summary — {Month Name YYYY}

## TL;DR

{IF `daily_coverage / days_in_month < 0.5` → prepend one-line banner:
 `> ⚠ Reconstructed retroactively on {snapshot_at} from {N} dailies + git history + static file scan. Confidence: medium. Treat as imperfect recall.`
ELSE omit banner.}

- {3-5 bullets — executive summary}

## Structured activity roll-up
- Batches: {N} | Records: {N} | Notes: {N} | Tasks added: {N} / closed: {M} / stale: {K}
- Threads: opened {N}, closed {M}, carried-over {K} → current {total}
- People: new profiles {N}, tier changes (promote/demote) {breakdown}
- Hubs: active {N}, new {M}, top-growing {id}

## Narrative highlights
{1-2 paragraphs — LLM prose. «What mattered this month» with substantive detail for recall}

## Patterns & trends
{1-2 paragraphs — LLM observations: recurring themes, focus drift vs SOUL, emerging topics, counter-patterns}

## Decisions made this month
- {extracted from decision-type notes + resolved threads}

## People focus
- **Top 10 mentioned:** {ids + counts}
- **New additions:** {ids}
- **Relationship-density shifts:** {notable jumps}

## Content pipeline
- High-potential notes accumulated: {N}
- Content types breakdown: expert {N} / reflection {M} / story {K} / insight / observation

## Carrying into {next month}
- **Unresolved threads:** {count + top 3 titles}
- **Pending CLARIFICATIONS:** {count per reason code}
- **Forward-looking from SOUL Focus:** {carry-over priorities}

## Analysis
{1 paragraph — LLM honest reflection. «This month felt X». Soft artifact — owner may edit manually}
```

### soul-update-advice CLARIFICATION (when applicable)

LLM prompt inputs:
- Current SOUL.md content
- 30 daily summaries from generated month
- Resolved threads during month
- Decisions extracted
- People dynamics (new profiles, tier changes)

LLM rubric:
1. Which Focus items received meaningful activity?
2. Which Focus items received 0 activity?
3. Which themes were present in activity but absent from Focus?
4. Has priority shifted observably?
5. Have Values shown strain / reinforcement?
6. Any new emerging patterns warranting Focus addition?

Output CLARIFICATION:

```markdown
### {YYYY-MM-01} — soul-update-advice (monthly)

**Type:** soul-update-advice
**Subject:** _system/SOUL.md
**Source:** lint-monthly-{YYYY-MM}
**Confidence tier:** surfaced (SOUL never auto-edit)
**Suggested action:** review-soul

**Context:** {3-5 sentence LLM summary — how past month's activity aligns/diverges with SOUL Focus. Highlight: (a) themes present but absent from Focus, (b) Focus items receiving 0 activity, (c) emerging patterns}

**Specific recommendations:**

*Focus Work:*
- {Add: theme X — evidence}
- {Revise: Focus item Y — reason}
- {Remove: Focus item Z — 0 activity}

*Focus Personal:*
- {same structure}

*Values reassessment (only if strong signal):*
- {if applicable}

*Working Style (only if strong signal):*
- {if applicable}

**To resolve:** Read recommendations → manually edit `_system/SOUL.md` если aligned → mark resolved with `Resolution-action: fix-process` + payload summarizing edits. `Resolution-action: dismiss` if no change warranted.

**Uncertainty:** {any recommendation feeling uncertain}
```

---

## Step 7 — Write log_lint.md Entry

Append ONE entry к `_system/state/log_lint.md` (aggregate across all scans + migration):

```markdown
## {ISO UTC timestamp} | lint | by: ztn:lint | batch: —

### Scans Executed
- Scan A (consistency): {N items processed, K auto-fixes, M CLARIFICATIONS}
- Scan B (threads): {...}
- Scan C (people): {...}
- Scan D (notes): {...}
- Scan E (focus): {...}

### Auto-Fixes
- Silent tier: {N} applied — {breakdown by operation}
- Noted tier: {N} applied — {breakdown}
- Reviewed tier: {N} applied (cross-linked to CLARIFICATIONS by fix-id) — {breakdown}

#### fix-{run-id}-{seq} | tier:{t} | target:{path}
- **Operation:** {op}
- **Before:** `{1-line state}` (or «see git diff» for multi-line)
- **After:** `{1-line state}`
- **Reasoning:** {LLM 1-2 sentences}
- **Reversible:** yes
- **Rollback hint:** `git diff HEAD~1 {path}` or manual revert

{... per-fix entries ...}

### Suggestions → CLARIFICATIONS
- {total items} raised under `## lint {YYYY-MM-DD}` header:
  - Surfaced: {N} ({breakdown by reason code})
  - Reviewed (apply + validate): {N} ({breakdown})

### Hidden (verbose audit)
- {N} items hidden (LLM verdict = skip / 2+ counter-evidence). Listed below для audit — NOT surfaced к CLARIFICATIONS.
  - {reason-code}: {subject} — {one-line LLM reasoning}

### Migration (one-time, completed {YYYY-MM-DD}) — present ONLY in first run that performed migration
- Resolved Archive: {N} items migrated, {K} low-confidence flagged
- Profiles normalized: {M} files updated, {P} flagged for manual Контекст
- Unified format achieved: ✓

### Lint Context Store
- Daily: {created {dates} | skipped (exists)}
- Monthly: {created {YYYY-MM}.md | skipped (month not turned)}
- Retention purge: {N daily files deleted}

### Errors / Warnings
- {malformed files encountered с workarounds; empty list if clean run}
```

---

## Step 8 — Release Lock

Delete `_sources/.lint.lock`. Guaranteed finally path.

---

## Step 9 — Report

Write to stdout:

```
## ZTN Lint Report — {YYYY-MM-DD}

### Scans Run
- A (consistency): {counts}
- B (threads): {counts}
- C (people): {counts}
- D (notes): {counts}
- E (focus): {counts}

### Auto-Fixes Applied: {total}
- Silent: {N} — {operations summary}
- Noted: {N} — {operations summary}
- Reviewed: {N} — {operations summary, cross-linked to CLARIFICATIONS}

### CLARIFICATIONS Raised: {total}
- Surfaced: {N} — {reason codes + subjects summary}
- Reviewed (apply + validate): {N} — {reason codes + subjects summary}

### Migration (first run only)
- Resolved Archive: {N migrated} ({K low-confidence})
- Profiles: {M normalized} ({P flagged context-missing})

### State Changes
- Files modified: {N}
- Files created: {N} (profiles + daily + monthly)
- Files deleted: {N} (dedup secondaries + daily retention purge)

### Lint Context Store
- Daily: {created {dates}}
- Monthly: {created {YYYY-MM}.md | skipped}

### Completion Gate
- [x] All scans executed
- [x] Lock released
- [x] log_lint.md entry written
- [x] Lint Context Store updated
- [x] No writes to forbidden territories (HARD RULES invariant)
- [x] Unified format achieved (migration done OR already-migrated)
- [x] **Bare-name three-surface consistency** — for each resolved bare-name, grep frontmatter/tags/body wikilinks → 0 residual bare references
- [x] **Dedup backlink invariant** — for each deleted secondary, grep `[[{deleted-id}]]` in non-audit files → 0 results
- [x] **Suppression via Resolved Items** — no surfaced CLARIFICATION raised для subject matching resolved suppression entry within active window
- [x] **Migration flag frontmatter integrity** — `log_lint.md` frontmatter `migration_completed` map present + parseable if any migration ran

### Next Actions for Owner
Run `/ztn:resolve-clarifications` to review the queue interactively. {N} items accumulated:
- {reason-code-1}: {N items}
- {reason-code-2}: {N items}

The skill clusters items by theme, reminds context + verbatim quotes inline, and applies confirmed resolutions in-place.
```

---

## CLARIFICATIONS Reason Codes

**Structural:**
- `link-broken-2plus-candidates` — broken wikilink с 2+ possible targets
- `link-broken-unresolvable` — broken wikilink с 0 candidates
- `frontmatter-unfixable-schema` — schema mismatch not auto-fixable
- `orphan-file` — file без any inbound references

**Thread lifecycle:**
- `thread-stale-warn` — past warn threshold, no activity (reviewed — no apply, CLARIFICATION)
- `thread-stale-escalate` — past escalate threshold, explicit decision required
- `thread-hub-linkage-backfill-surfaced` — thread без hub, semantic-only match
- `orphan-clarification-escalate` — Open Item unresolved > 3 weeks
- `applied-pending` — structured resolved item с `Applied: no` older than 2 weeks

**People lifecycle:**
- `tier-promote-auto-profile` — crossed Tier 1, profile auto-generated (reviewed)
- `tier-demote-candidate` — below threshold + no profile + no activity (surfaced only)
- `orphan-bare-name-surfaced` — bare name unresolved, multiple profile candidates (surfaced)
- `orphan-bare-name-resolved` — unambiguous bare name auto-substituted (reviewed — apply + validate batch via git diff + log_lint.md grep)
- `mention-count-drift-surfaced` — recount conflicts, source of truth unclear

**Note lifecycle:**
- `dedup-reviewed` — merge applied, validate unique content extraction
- `dedup-surfaced` — similarity detected, tier too low to auto-merge
- `evidence-trail-backfill-surfaced` — legacy note, semantic reconstruction uncertain
- `orphan-note` — not linked, archive candidate

**Focus:**
- `soul-focus-drift` — Focus misaligned vs recent activity (daily scan)
- `soul-update-advice` — monthly structured SOUL review
- `content-pipeline-reminder` — weekly reminder to run `/ztn:check-content`

**Profile normalization:**
- `profile-context-missing` — existing profile без `## Контекст`, semantic content needed
- `profile-non-canonical-sections` — profile has extra sections beyond canonical template (surfaced — policy decision pending between strict / allowed extensions / whitelist)

**Migration (first run only):**
- `migration-item-needs-review` — legacy Resolved Archive item migrated with low LLM confidence

**Anomalies (malformed handling):**
- `lint-malformed-frontmatter` / `hub-dangling-reference` / `person-unknown-in-frontmatter` / `log-malformed-entry` / `lint-context-daily-unreadable` / `lint-scan-exceeded-soft-timeout-surfaced`

Parsable fields stable per Q0. Forward-compat: new codes append-only.

---

## Example Usage

```
/ztn:lint                        # full nightly run
/ztn:lint --dry-run              # hybrid preview (diffs for auto-fixes, prose for CLARIFICATIONS)
/ztn:lint --dry-run --verbose    # full diff including Lint Context Store generation
/ztn:lint --scope fast           # skip expensive scans (dedup + Evidence Trail backfill)
/ztn:lint --verbose              # reasoning traces в stdout
/ztn:lint --force                # bypass «ran recently» warning
/ztn:lint --weekly               # force weekly triggers (content pipeline reminder) even mid-week
```

---

## Invariants

Check during adversarial audit:

1. **HARD RULES (never auto-apply):** thread closure, PEOPLE.md Tier column, SOUL.md, record/note body вне dedup-merge, PEOPLE.md Mentions non-drift, TASKS.md/CALENDAR.md/BATCH_LOG.md/batches/ writes
2. **Confidence tier routing:** silent requires strong+high, noted requires strong+confident (or strong+high with concern), without rule-floor max tier `surfaced`
3. **CLARIFICATIONS:** all items MUST have `**Context:**` field; parsable fields stable (canonical Resolution-action vocabulary); Resolved items structured format с `Applied` field
4. **Idempotency:** second run on unchanged state → Migration absent (already done), only new daily summary diff если new UTC day, else zero state changes
5. **Best-effort:** single malformed file never aborts run; missing Lint Context Store first run handled gracefully
6. **Dedup safety:** no unique content lost (LLM confirmation required); frontmatter lists union (no deletion); Evidence Trail entry prepended; post-merge backlink redirect invariant
7. **Rollback via git:** every lint run produces diff-able changes; fix-id → git diff hunk
8. **Lint Context Store:** daily для every past day (quiet с template); monthly sealed first run new UTC month; retention purge > 30 days only; monthly never deleted
9. **Parsable Resolved:** ALL resolved items structured format; no legacy `## Resolved Archive` table
10. **Empty-run safe:** always ≥ 1 daily summary + 1 log_lint.md entry; zero auto-fixes + zero CLARIFICATIONS = valid healthy run
11. **Cross-skill exclusion symmetric:** process/maintain/lint — любой other lock exists → abort
12. **Log file ownership:** log_lint.md written ONLY by /ztn:lint; others read-only
13. **Profile template unified:** all profiles match canonical schema; `## Мои наблюдения` structurally required, never auto-generated content
14. **CLARIFICATIONS single format:** `## Open Items` + `## Resolved Items` only
15. **SOUL advice cadence:** only immediately previous month raised; deep backfill skips; SOUL never auto-edited
16. **Suppression via Resolved Items:** no surfaced CLARIFICATION raised для subject matching resolved suppression entry within active window
17. **Bare-name three-surface consistency:** per resolved bare-name, grep frontmatter/tags/wikilinks → 0 residual bare references
18. **Dedup backlink integrity:** post-merge grep `[[{deleted-id}]]` in non-audit files → 0 results

---

## Contract dependencies

Lint consumes artifacts produced by other skills:
- `_system/docs/batch-format.md` — batch output contract
- `/ztn:process` inline Mentions increment in PEOPLE.md
- `/ztn:maintain` threads + hub linkage
- Log files с frontmatter migration-flag structure

Forward-compatible: Resolved structured format + canonical `Resolution-action` vocabulary + confidence tier enum — all append-only evolution. New reason codes append-only. Downstream `/ztn:resolve-clarifications` consumer reads structured Resolved Items directly.
