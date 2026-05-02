---
id: batch-format
layer: system
version: 2.0
modified: 2026-05-02
---

# Batch Format

> Контракт формата batch-отчётов `/ztn:process`. Все skill-потребители
> (`/ztn:maintain`, `/ztn:lint`) и `ztn-bridge` plugin ссылаются сюда.
> Изменение формата = bump `version:` во frontmatter + добавление row в Version History.
>
> **Authority for downstream contract.** Markdown report (`{batch-id}.md`)
> is human-readable narrative; the JSON manifest (`{batch-id}.json`) is the
> machine-parseable contract consumed by Minder backend. The full JSON
> schema lives in `minder-project/strategy/ARCHITECTURE.md` §4.5 — this
> file mirrors the per-entity field set so ZTN-side emitters stay
> consistent with downstream expectations.

---

## Version History

- **v2.0**: added concept emission (`concepts:` frontmatter,
  `concept_hints[]` per-entity, `member_concepts[]` per-hub,
  `concepts.upserts[]` registry-level) and privacy trio (`origin`,
  `audience_tags`, `is_sensitive`) per-entity. Markdown report sections
  unchanged; JSON manifest gains `concepts` top-level section + privacy
  fields on every entity. Format-version flips to `2.0` in frontmatter.
- **v1.0**: initial markdown format.

---

## File Locations

- **Index:** `_system/state/BATCH_LOG.md` — append-only markdown table, one row per batch
- **Reports:** `_system/state/batches/{batch-id}.md` — one file per batch, full structured report

---

## batch-id Format

```
YYYYMMDD-HHmmss
```

- UTC timestamp начала обработки
- Уникален, монотонно возрастает
- Сортируется корректно как строка

**Пример:** `20260416-103000`

---

## BATCH_LOG.md Schema

Одна строка markdown-таблицы на каждый batch. Append-only, не перезаписывается.

| Column | Type | Description |
|---|---|---|
| `batch_id` | string | `YYYYMMDD-HHmmss` (UTC) |
| `timestamp` | ISO 8601 | начало обработки (UTC, с суффиксом `Z`) |
| `sources` | int | сколько файлов из inbox обработано в этом batch |
| `records` | int | создано записей в `_records/{meetings,observations}/` (обоих kind'ов суммарно) |
| `notes` | int | создано knowledge notes в PARA (`1_projects/` … `4_archive/`) |
| `tasks` | int | извлечено задач (inline `^task-*` в нотах) |
| `events` | int | извлечено событий (inline 📅) |
| `threads_open` | int | новых open threads за batch |
| `threads_close` | int | переведено в resolved за batch |

---

## batches/{batch-id}.md Schema

### Frontmatter (required)

```yaml
---
batch_id: YYYYMMDD-HHmmss
timestamp: YYYY-MM-DDTHH:MM:SSZ
processor: ztn:process v{version}
batch_format_version: 2.0
sources: N
records: N
notes: N
tasks: N
events: N
threads_opened: N
threads_resolved: N
clarifications_raised: N
people_candidates_appended: N
concepts_upserted: N        # v2.0 — count of distinct concepts in concepts.upserts[]
sensitive_entities: N       # v2.0 — count of entities with is_sensitive=true
---
```

### Sections (in order)

1. `## Sources Processed`
2. `## Records Created`
3. `## Knowledge Notes Created`
4. `## Tasks Extracted`
5. `## Events Extracted`
6. `## People Updates`
7. `## Threads` → `### Opened` + `### Resolved`
8. `## Hubs Updated`
9. `## CLARIFICATIONS Raised`
10. `## People Candidates Appended` (added 2026-04-24) — per entry: `{candidate_id} | {name_as_transcribed} | {note-id} | {role_hint or —}`. Count MUST equal `people_candidates_appended` in frontmatter. Use `(none)` if empty. Rationale: bare-name mentions routed to `_system/state/people-candidates.jsonl` instead of CLARIFICATIONS — see `/ztn:process` Step 3.8 + `/ztn:lint` Scan C.5.
11. `## Concepts Upserted` (added v2.0) — per entry: `{name} | {type} | {subtype or —} | {related_concepts comma-list or —}`. Count MUST equal `concepts_upserted` in frontmatter. Use `(none)` if empty. Mirrors the JSON manifest's `concepts.upserts[]`. Names MUST conform to `_system/registries/CONCEPT_NAMING.md` (snake_case ASCII, English-only, no type prefix in name).
12. `## Sensitive Entities` (added v2.0) — per entry: `{path or id} | {kind: record|note|hub|task|...} | audience_tags: {[...] or "[]"}`. Count MUST equal `sensitive_entities` in frontmatter. Use `(none)` if empty. Lists every entity emitted in this batch with `is_sensitive: true` so downstream sync can apply extra-friction handling without re-scanning frontmatter.

Пустые секции сохраняются с пометкой `(none)` — удобнее для diff и downstream consumer.

---

## Example Batch Report

```markdown
---
batch_id: 20260416-103000
timestamp: 2026-04-16T10:30:00Z
processor: ztn:process
batch_format_version: 2.0
sources: 1
records: 1
notes: 2
tasks: 2
events: 1
threads_opened: 1
threads_resolved: 0
clarifications_raised: 0
people_candidates_appended: 0
concepts_upserted: 2
sensitive_entities: 0
---

## Sources Processed
- _sources/inbox/plaud/2026-04-16T10-15-00/transcript_with_summary.md (plaud)

## Records Created
- [[20260416-meeting-petya-strategy]] | Встреча с Петей: стратегия инвестиций
  - People: petya-ivanov
  - Projects: —

## Knowledge Notes Created
- [[20260416-investment-approach]] | Подход к инвестиционной стратегии
  - Types: insight | Domains: work
  - Evidence Trail: started

## Tasks Extracted
- task-20260416-001 | Позвонить Пете до пятницы | deadline: 2026-04-18 | priority: high
  - From: [[20260416-meeting-petya-strategy]]

## Events Extracted
- 2026-04-18T14:00:00+04:00 | Follow-up с Петей | participants: petya-ivanov
  - From: [[20260416-meeting-petya-strategy]]

## People Updates
- petya-ivanov | new_context | mentions: 4→5 | tier: 2 (no change)

## Threads

### Opened
- thread-20260416-investment-proposal | Ожидаем proposal от Пети | status: waiting-for-response

### Resolved
(none)

## Hubs Updated
- [[hub-investment-strategy]]

## CLARIFICATIONS Raised
(none)

## Concepts Upserted
- investment_approach | theme | — | risk_tolerance, portfolio_strategy
- portfolio_strategy | theme | — | investment_approach

## Sensitive Entities
(none)
```

---

---

## v2.0 Per-Entity Fields — Concepts and Privacy Trio

Every entity emitted by `/ztn:process` (record, knowledge note, hub,
task, event, idea, person profile, project profile, principle, content
candidate) carries the **privacy trio**:

| Field | Type | Default | Source of values |
|---|---|---|---|
| `origin` | enum | `personal` | `personal` / `work` / `external`. Inferred per `/ztn:process` Step 3.4 Q16 from SOURCE TYPE + content signals. |
| `audience_tags` | `text[]` | `[]` | Whitelist in `_system/registries/AUDIENCES.md` (canonical 5 + Extensions). Empty = owner-only. |
| `is_sensitive` | bool | `false` | Set `true` on NDA, salary, health, financial detail, intimate disclosure. Friction-modifier, NOT audience narrower. |

The trio is **slot-only** at this layer: ZTN emits values, downstream
consumers (Minder backend, sync targets) apply policy. Defaults are
chosen so that absence of inference fails closed (private, not leaked).

Concept fields per entity:

| Field | Where | Purpose |
|---|---|---|
| `concepts:` | frontmatter on records and knowledge notes | Canonical concept-name list ("what things does this entity touch"); list of strings per CONCEPT_NAMING. |
| `concept_hints[]` | per-record / per-note section in JSON manifest | Mirror of frontmatter `concepts:` for downstream consumption. Same values; "hint" name preserves the upstream-tentative semantics. |
| `member_concepts[]` | per-hub section in JSON manifest | Union of concepts from hub's member knowledge notes. Aggregated at manifest emission time; not stored in hub frontmatter. |
| `applies_in_concepts[]` | per-principle section in JSON manifest | Concepts a principle applies to. Sourced from constitution principle frontmatter (`/ztn:regen-constitution` reads). |
| `concepts.upserts[]` | top-level JSON manifest section | Registry-level deduplicated concept emission for the batch. Each entry: `{name, type, subtype?, related_concepts[]?, previous_slugs[]?}`. Where the same concept appeared in N entities, ONE upsert entry is emitted with consolidated metadata. |

**Concept scope.** `/ztn:process` emits non-person, non-project concepts.
People are tracked via `tier1_objects.people` and `people:` frontmatter;
projects via `tier1_objects.projects` and `projects:` frontmatter. The
`type` enum in `CONCEPT_NAMING.md` includes `person` and `project` for
downstream graph completeness, but ZTN-side emission deliberately
excludes them to avoid dual-emit ambiguity. Downstream consumers infer
person↔concept and project↔concept edges from co-occurrence in the
manifest.

**Concept-name format.** All concept-name strings (frontmatter values,
`concept_hints[]`, `member_concepts[]`, `applies_in_concepts[]`,
`concepts.upserts[].name`, `subtype`, every entry in `related_concepts`,
every entry in `previous_slugs`) MUST conform to
`_system/registries/CONCEPT_NAMING.md` — snake_case `[a-z0-9_]`, ≤64
chars, no forbidden type prefix, English-only. Non-English source terms
MUST be translated upstream (in `/ztn:process` Step 3.4 Q15) BEFORE
emission, never transliterated. Any non-conformant value lands in the
batch and is caught by `/ztn:lint` Scan A.7 with the appropriate
CLARIFICATION code (`concept-format-mismatch`,
`concept-type-prefix-in-name`, `concept-name-too-long`).

**Audience-tag format.** All `audience_tags[]` values MUST be either one
of the canonical five (`family`, `friends`, `work`,
`professional-network`, `world`) or appear in the Extensions table of
`_system/registries/AUDIENCES.md`. Unknown values trigger
`audience-tag-unknown` CLARIFICATION at lint time;
reserved-keyword conflicts trigger `audience-tag-reserved-conflict`;
format violations trigger `audience-tag-format-mismatch`.

### v2.0 Manifest Section Sketch (JSON, illustrative)

The JSON manifest schema is authoritative in
`minder-project/strategy/ARCHITECTURE.md` §4.5. ZTN emits to that schema.
Privacy + concept fields on every per-entity entry:

```json
{
  "format_version": "2.0",
  "records": {
    "created": [
      {
        "path": "_records/meetings/...",
        "concept_hints": ["org_structure", "delivery_lead_role"],
        "origin": "work",
        "audience_tags": ["work"],
        "is_sensitive": false
      }
    ]
  },
  "knowledge_notes": {
    "created": [
      {
        "path": "1_projects/.../...md",
        "concept_hints": ["org_structure", "intl_restructuring"],
        "origin": "work",
        "audience_tags": [],
        "is_sensitive": false
      }
    ]
  },
  "hubs": {
    "updated": [
      {
        "path": "5_meta/mocs/hub-team-restructuring.md",
        "member_concepts": ["org_structure", "delivery_lead_role"],
        "origin": "work",
        "audience_tags": [],
        "is_sensitive": false
      }
    ]
  },
  "concepts": {
    "upserts": [
      {
        "name": "org_structure",
        "type": "theme",
        "subtype": null,
        "related_concepts": ["intl_restructuring", "delivery_lead_role"],
        "previous_slugs": []
      }
    ]
  }
}
```

`type` enum (lowercase): `theme`, `tool`, `decision`, `idea`, `event`,
`organization`, `skill`, `location`, `emotion`, `goal`, `value`,
`preference`, `constraint`, `algorithm`, `fact`, `other`. (`person` and
`project` are reserved in CONCEPT_NAMING but not emitted by ZTN — see
"Concept scope" above.)

---

## Consumers

Формат потребляют:

- **`/ztn:process`** (writer) — генерирует `batches/{id}.md` + добавляет строку в `BATCH_LOG.md`
- **`/ztn:maintain`** (reader) — читает последний batch для incremental обновлений (mention counts, thread detection, CURRENT_CONTEXT regen)
- **`/ztn:lint`** (reader) — сканирует `BATCH_LOG.md` для detect stale threads, Evidence Trail gaps, content pipeline candidates
- **`ztn-bridge` plugin** (reader) — читает последний batch для session_end обогащения

При bump версии (v2.0+) — migration path документируется здесь же.
