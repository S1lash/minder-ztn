# ZTN Engine Doctrine

> **What this is.** The compact, load-bearing operating philosophy of
> the ZTN engine. Every skill (`/ztn:bootstrap`, `/ztn:process`,
> `/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`, `/ztn:agent-lens-add`,
> `/ztn:capture-candidate`, `/ztn:check-decision`,
> `/ztn:regen-constitution`, `/ztn:check-content`, `/ztn:source-add`)
> reads this file as
> part of Step 1 / Load Context. It is symlinked
> into `~/.claude/rules/ztn-engine-doctrine.md` by `install.sh` so it
> auto-loads in every Claude Code session opened in this repo.
>
> **What this is NOT.** Not the full spec. Pointers below lead to the
> authoritative long-form sources. This file is what every skill
> internalises in 90 seconds before doing anything else.
>
> **Authority order** (top wins on conflict):
>
> 1. `_system/docs/SYSTEM_CONFIG.md` — system contract (the rules the
>    engine MUST hold)
> 2. `_system/docs/CONVENTIONS.md` — documentation conventions (binding
>    on every edit to engine docs and SKILLs)
> 3. **This file (`ENGINE_DOCTRINE.md`)** — operating philosophy +
>    cross-skill principles
> 4. Skill `SKILL.md` — pipeline-specific spec
> 5. `_system/SOUL.md` — owner identity calibration (Values zone
>    auto-rendered from constitution; Working Style hand-edited)
> 6. `0_constitution/` — owner principles (axioms / principles /
>    rules); `constitution-core.md` view auto-loaded as harness rule
>
> The engine doctrine is below the system contract and conventions
> (which are mechanical) but above all skill-level specs (which are
> mechanical applications of the doctrine).

---

## 1. Why ZTN exists — the frame

ZTN is a personal **second consciousness**, not an archive, not a
TODO-list, not a CRM, not a chatbot. The system *thinks alongside its
owner*: holds context across months, surfaces connections between
domains, traces how thinking evolves.

The system optimises for **one user with many contexts** — work,
career, personal, therapy, business ideas, relationships. The
disproportionate value lives at domain boundaries, where a therapy
insight illuminates a work-delegation pattern, or an architecture
decision seeds a product idea. Every skill operates with that in
mind.

### Three levels of value

| Level | Question | Layer that serves it |
|---|---|---|
| 1. Search | «What did we discuss with X in March?» | Records (`_records/`) |
| 2. Context | «What architectural decisions did we make on API v2?» | Knowledge notes (PARA) |
| 3. Synthesis | «How did my understanding of delegation change over six months?» | Hubs (`5_meta/mocs/`) |

Records, knowledge, hubs — three layers, each with a distinct shape.
Skipping a layer breaks the whole.

### The work / personal axis — first-class

Every ZTN owner lives in **at least two contexts simultaneously**: a
work / professional context (job, clients, team, domain expertise) and
a personal context (relationships, health, life decisions, side
projects, therapy, reflections). The system treats this split as a
**universal axis**, not an opinionated assumption.

Where the axis lives mechanically:

| Layer | How the axis is encoded | Notes |
|---|---|---|
| Records | NOT encoded at folder level. `_records/meetings/` and `_records/observations/` is a **shape axis** (multi-speaker vs solo Plaud / journal), not a scope axis. A solo work-reflection is still an `observation`; a personal book-club meeting is still a `meeting`. | Don't conflate shape and scope. |
| Knowledge notes | `domains:` frontmatter array. `work` is one valid value; personal-side values are richer (`identity`, `relationships`, `health`, `learning`, etc) — «personal» itself is too vague to tag. | Cross-domain notes carry both: `domains: [work, learning]`. |
| Hubs | `domains:` frontmatter array (same vocabulary as knowledge notes). | Cross-domain hubs are some of the highest-value (e.g. delegation patterns spanning therapy + work). |
| Tasks (`TASKS.md`) | Dedicated `## Personal` section + the rest defaulting to work. | Already in template. |
| Goals + Focus (`SOUL.md`) | Explicit `### Work` and `### Personal` subsections under both. | Already in template. |
| Projects (`PROJECTS.md`) | `Scope` column with values `work` / `personal` / `side` / `mixed`. | Scope is owner-tagged; bootstrap seeds with hint, owner edits. |
| People (`PEOPLE.md`) | `Org` column. Empty Org → personal-context relation; non-empty → work-context. | De-facto convention; surfaced in onboarding. |
| Constitution principles | `domain` field on each principle. Same vocabulary as knowledge notes. | A principle can be `domain: work` (applies in professional context) or `domain: identity` (applies everywhere); axiom-level principles typically span both. |
| Capture origin | `--origin work` flag on `/ztn:capture-candidate`. Default `personal`. Bootstrap adds `bootstrap-raw-scan` / `bootstrap-profile`. | F.5 non-personal-origin guard requires manual review for any non-personal origin (per §3.6). |

**Why the axis matters for skill calibration:**

1. **Texture preservation differs.** Personal observations (therapy,
   reflections) carry emotional and narrative texture that is signal,
   not noise. Work-meeting transcripts compress aggressively to
   facts + decisions. Principle 8 (Texture & Narrative) is calibrated
   per scope.
2. **People resolution differs.** Work people resolve via Org +
   role + first name; personal people often have only first name +
   relationship type — bootstrap and `/ztn:process` apply different
   confidence thresholds.
3. **Constitution scope differs.** Work-origin principle candidates
   never auto-merge (per F.5). Personal-origin ones can, post-
   threshold.
4. **Cross-domain insights are the highest-value class.** A therapy
   insight applied to work delegation; a work architecture decision
   seeding a side-project idea. Skills that detect cross-domain
   permeability (Principle 4) actively look for the work ↔ personal
   crossings.

The axis is **owner-defined**, not engine-imposed. Friends with
unusual splits (multiple work contexts, no work context, blended
freelance) tag accordingly — the system doesn't assume a 9-to-5
structure.

### Constitution — the fourth layer

Above the three knowledge layers sits the **constitution**
(`0_constitution/` — axioms / principles / rules). It is the
rules-of-engagement layer: how skills should reason and act on the
owner's behalf. Quality-first, narrowly curated; never accumulates on
autopilot. Knowledge is capture-first; constitution is curation-first.
Both are sacred for different reasons.

> Long form: `5_meta/CONCEPT.md`, `0_constitution/CONSTITUTION.md`.

---

## 2. The 8 processing principles (load-bearing)

These govern every transcript-processing decision. Inclusion-biased.
Skills calibrate their judgement against this list.

1. **Capture First, Filter Never** — every deliberate utterance lands
   in a record. False positives are cheap (a minute on next sweep);
   false negatives are forever. «Too small to record» is forbidden.
2. **Importance Gradient — Weight, Don't Discard** — importance shapes
   FORMAT (record line vs knowledge note vs hub), never filtering.
3. **Connection Awareness** — for every fact, actively probe causal /
   evolutionary / structural links to the loaded context. Wikilinks +
   hub updates are the artefacts.
4. **Cross-Domain Permeability** — the highest-value insights live at
   domain boundaries. Threshold ≈ 30 % confidence: if it *might* be
   relevant in another domain, link it.
5. **Evolution Tracking — Accumulate, Don't Deduplicate** — knowledge
   accumulates. January's decision and March's revised decision both
   stay. Hubs trace the evolution; nothing rewrites history.
6. **Action vs Knowledge — Capture Both** — dual-nature items become
   BOTH a `[ ]` task AND a knowledge insight. Never one or the other.
7. **People — Capture Every Deliberate Mention** — participants AND
   discussed-about. Three levels (participant / discussed / new
   context). Drives PEOPLE.md tier and profile growth.
8. **Preserve Texture and Narrative** — quotes, emotion, metaphor,
   narrative arcs are *signal*. Knowledge notes preserve them; records
   keep them only when load-bearing. Filler and stutter are removed.

> Long form (with antipatterns and examples):
> `5_meta/PROCESSING_PRINCIPLES.md`. The values-profile calibration
> (capture_threshold, atomization_depth, etc.) lives in the same file
> §«Values Profile» — overrides are read from `SOUL.md`.

---

## 3. Cross-skill philosophy

These are the rules every skill enforces, regardless of pipeline.

### 3.1 Surface, don't decide silently

Whenever judgement is uncertain, write a CLARIFICATION to
`_system/state/CLARIFICATIONS.md` with a conservative default and
continue. Never block; never silently choose. The owner reviews and
resolves. CLARIFICATION types are canonicalised in
`SYSTEM_CONFIG.md` and per-skill SKILL.md.

**Layer-specific exception: the concept and audience surfaces.**
Concept-name format normalisation, audience-tag whitelist checks,
and privacy-trio backfill are **deterministic mechanical work, not
judgment**. The shared helpers in `_system/scripts/_common.py`
(`normalize_concept_name`, `normalize_concept_list`,
`normalize_audience_tag`, `recompute_hub_trio`) resolve every case
with a fixed algorithm, autofix or silent-drop on impossibility, and
NEVER raise a CLARIFICATION. The cost-benefit favours autonomous
resolution: per-decision low risk, high volume, and the algorithm is
fully specified — surfacing would drown the owner queue without
adding value the algorithm can't already provide. Every other layer
(threading, dedup, drift detection, principle promotion, people
identity, etc.) retains the surface-don't-decide rule unchanged.
The exception is scoped — see `_system/registries/CONCEPT_NAMING.md`,
`_system/registries/AUDIENCES.md`, `_system/docs/batch-format.md`
"Autonomous resolution" clause for the full rule set.

### 3.2 Inclusion bias on capture, curation on promotion

Capture (records, raw scan, candidates buffer) is high-recall: better
to include and dismiss later than miss. Promotion (knowledge → hub,
candidate → constitution principle, tier shifts) is high-precision:
gated by thresholds, owner review, weekly lint.

### 3.3 Idempotency

Every skill is re-runnable. Re-runs match by id (thread-id, person-id,
candidate triple, batch_id) and never overwrite owner edits. Updates
take the «add new entry» path, not the «rewrite existing» path.
Resolved threads, archived principles, and historical entries never
re-open or re-mutate.

### 3.4 Locks and exclusivity

`/ztn:process`, `/ztn:maintain`, `/ztn:lint`, and `/ztn:agent-lens` are
mutually exclusive (cross-skill lock matrix in their SKILL.md).
`/ztn:bootstrap` is not in the matrix — owner ensures system idle before
invoking it. `/ztn:capture-candidate` is fire-and-forget, no lock.
`/ztn:agent-lens-add` does not acquire its own lock but respects
`/ztn:agent-lens`'s lock at pre-flight (registry would race) and uses
concurrent-edit detection (snapshot + re-validate) to defend against
parallel owner-driven invocations of itself. Stale locks > 2 h are
surfaced as warnings, never silently deleted.

### 3.5 Logs and audit trail

| Log | Skill | Append-only |
|---|---|---|
| `_system/state/log_process.md` | `/ztn:process` | yes |
| `_system/state/log_maintenance.md` | `/ztn:maintain`, `/ztn:bootstrap` | yes |
| `_system/state/log_lint.md` | `/ztn:lint` | yes |
| `_system/state/log_agent_lens.md` | `/ztn:agent-lens` | yes |
| `_system/state/BATCH_LOG.md` | `/ztn:process` | yes |
| `_system/state/PROCESSED.md` | `/ztn:process` | yes |
| `_system/state/agent-lens-runs.jsonl` | `/ztn:agent-lens` | yes |
| Knowledge note `## Evidence Trail` | every skill that touches the note | yes |

Logs document WHAT happened and WHY. They are the engine's memory of
its own operation; never edited retroactively.

### 3.6 The owner-LLM contract — what skills NEVER do silently

- Never auto-create a knowledge profile in `3_resources/people/{id}.md`
  without surfacing the threshold-crossing → CLARIFICATION first.
- Never auto-promote a principle candidate from
  `principle-candidates.jsonl` to `0_constitution/`. Promotion is L2
  merge in `/ztn:lint` F.5 — and only `origin: personal` candidates
  qualify (work / external / bootstrap origins always require manual
  review per F.5 non-personal-origin guard).
- Never overwrite owner edits to SOUL.md / PEOPLE.md / PROJECTS.md /
  hub files. Re-runs add or surface, never rewrite.
- Never demote tier silently — tier downgrades go through
  CLARIFICATIONS only.
- Never close an open thread silently — closure requires explicit
  signal in subsequent records or owner action.
- Never delete files from `_sources/`. The only `_sources/` mutation
  any skill performs is move-to-processed (`/ztn:process`) or
  consume-and-move-describe-me (`/ztn:bootstrap`).

### 3.7 Documentation conventions

Engine docs and SKILLs describe **current behaviour**. No version
narratives, no «previously this worked like X», no rename history. The
file IS the contract. When behaviour changes, the file changes; git
log carries the history.

> Binding spec: `_system/docs/CONVENTIONS.md`.

### 3.8 Manifest emission — bridging to downstream consumers

Every ZTN engine skill that produces persistent state changes
emits a structured **batch manifest** in JSON form alongside its
existing markdown summaries:

```
_system/state/batches/{ts}-process.json
_system/state/batches/{ts}-maintain.json
_system/state/batches/{ts}-lint.json
_system/state/batches/{ts}-agent-lens.json
```

The manifest schema is shared across all four skills, distinguished
by top-level `processor` field. It carries:
- Section per artifact kind (`sources`, `records`, `knowledge_notes`,
  `hubs`, `tier1_objects.{tasks,ideas,events,decisions,people,
  projects,content}`, `tier2_objects.{inventory,wardrobe,
  lens-observation,...}`, `concepts`, `constitution.principles`,
  `constitution.constitution_core_view`, `constitution.soul`)
- Privacy trio per entity: `origin`, `audience_tags`, `is_sensitive`
  (defaults `personal / [] / false`)
- Format version (`format_version: "MAJOR.MINOR"`) for evolution
  policy
- `section_extras: jsonb` per section for forward-compat new fields
- Idempotency via `batch_id` (top-level) + checksums per file

**Manifest is the contract** between the ZTN engine and downstream
consumers (currently Minder Java backend). Downstream:
- Reads manifests chronologically
- Idempotent by `batch_id` + checksums
- Routes per `processor` field semantics
- Rejects incompatible major versions with loud alert; accepts
  unknown minor fields via `section_extras`

**Universality matters:** new ZTN skills emitting persistent state
inherit this contract by default. Downstream consumers need no code
change to integrate. The contract is engine-level, not skill-level.

**What is intentionally NOT in manifest:**
- Pre-resolution staging (`people-candidates.jsonl`,
  `principle-candidates.jsonl`)
- Working memory (`OPEN_THREADS.md` — until focus engine arrives)
- HITL queues (`CLARIFICATIONS.md`)
- Audit trails (`log_*.md`)
- Derived/regenerable views (`CURRENT_CONTEXT.md`,
  `lint-context/{daily,monthly}/*`)

> Full manifest schema spec: `strategy/ARCHITECTURE.md` §4.5 in the
> minder-project repo. ZTN skills emit; Minder consumes.

---

## 4. Sacred state

These files are the engine's load-bearing state. Every skill knows
their schema and respects them. They are listed in `SYSTEM_CONFIG.md`
with full schemas; here is the index.

| File | Owner / writer | Purpose |
|---|---|---|
| `_system/SOUL.md` | owner (manual) + `/ztn:bootstrap` (draft) + `regen` (Values zone) | Identity, values, focus, working style |
| `_system/TASKS.md`, `CALENDAR.md`, `POSTS.md` | owner | Operational layers |
| `_system/registries/{TAGS,SOURCES}.md` | `/ztn:maintain`, `/ztn:lint` | Tag and source whitelists |
| `_system/state/OPEN_THREADS.md` | `/ztn:bootstrap`, `/ztn:maintain` | Strategic open threads |
| `_system/state/CLARIFICATIONS.md` | every skill | Owner-gated resolution queue |
| `_system/state/principle-candidates.jsonl` | `/ztn:capture-candidate`, `/ztn:bootstrap` | Append-only principle buffer |
| `_system/state/people-candidates.jsonl` | `/ztn:process`, `/ztn:bootstrap` | Append-only people buffer |
| `_system/views/CURRENT_CONTEXT.md` | `/ztn:bootstrap`, `/ztn:maintain` | Auto-generated focus snapshot |
| `_system/views/HUB_INDEX.md` | `/ztn:maintain` | Hub registry (auto-generated) |
| `_system/views/INDEX.md` | `/ztn:maintain` | Content catalog of knowledge + hubs (auto-generated, faceted by PARA / domains / cross-domain) |
| `_system/views/constitution-core.md` | `/ztn:regen-constitution` | Harness-loaded core principles |
| `3_resources/people/PEOPLE.md` | `/ztn:bootstrap`, `/ztn:process`, `/ztn:lint` | People registry with tiers |
| `1_projects/PROJECTS.md` | owner + `/ztn:bootstrap` (candidates) | Project registry |

Skills writing to these files do so per the schema; deviations surface
as `process-compatibility` CLARIFICATIONS rather than silent format
drift.

---

## 5. Bootstrap as doctrine transmission

`/ztn:bootstrap` is the **first contact** between the engine and a
fresh instance. It is responsible for:

1. Loading this doctrine (Step 1) and confirming the LLM session
   operates against it.
2. Surfacing the doctrine briefly to the owner at pre-flight summary
   (Step 0.6) — so the owner sees the frame their system runs by.
3. Seeding system files (SOUL, PEOPLE, PROJECTS, OPEN_THREADS,
   CURRENT_CONTEXT, candidates buffers) such that future
   `/ztn:process` runs inherit the seeded context.
4. Pinning a doctrine reference into `CURRENT_CONTEXT.md` frontmatter
   so any future skill loading CURRENT_CONTEXT alone still has a
   pointer back to this file.

After bootstrap completes, the doctrine flows into every subsequent
skill invocation through:

- the harness symlink (`~/.claude/rules/ztn-engine-doctrine.md`)
- explicit Step 1 loads inside each SKILL.md
- the CURRENT_CONTEXT frontmatter pointer

If those three transmission paths drift, the engine drifts.

---

## 6. Pointers to long-form sources

| Topic | File |
|---|---|
| System concept, three-layer model, full philosophy | `5_meta/CONCEPT.md` |
| 8 processing principles + values-profile calibration | `5_meta/PROCESSING_PRINCIPLES.md` |
| System contract, schemas, hard rules | `_system/docs/SYSTEM_CONFIG.md` |
| Documentation style (binding) | `_system/docs/CONVENTIONS.md` |
| Architecture / multi-user planning | `_system/docs/ARCHITECTURE.md` |
| Constitution protocol (axiom / principle / rule schema, scope, evolution ladder) | `0_constitution/CONSTITUTION.md` |
| Folder routing | `_system/registries/FOLDERS.md` |
| Inbox source whitelist | `_system/registries/SOURCES.md` |
| Constitution capture trigger spec (in-the-moment) | `_system/docs/constitution-capture.md` |

A skill that finds itself making a non-obvious judgement should consult
the relevant long-form file before acting, and surface a CLARIFICATION
if the doctrine is silent on the case.
