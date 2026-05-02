# Zettelkasten System Configuration

> **Documentation convention (binding):** любые изменения в этом файле + SKILL.md
> файлы + `_system/docs/batch-format.md` + связанные system specs подчиняются правилам
> [CONVENTIONS.md](../_system/docs/CONVENTIONS.md). Файлы описывают IS — current
> behavior, timeless spec. Никаких version/phase/release-notes narratives — они
> живут в git log.

---

## Overview

Это персональная система управления знаниями. Claude Code автоматически обрабатывает source-файлы из `_sources/inbox/` (whitelist живёт в `_system/registries/SOURCES.md` — voice-recorder transcripts, hand-written notes, Claude session recaps, и любые источники, которые owner добавил через `/ztn:source-add`), создавая структурированные Zettelkasten-заметки с богатыми метаданными для автоматизаций. После обработки исходные файлы перемещаются в `_sources/processed/`. Reference-материал (AI-generated profiles, policies, identity drafts) живёт в подкаталогах, помеченных колонкой `Skip Subdirs` в SOURCES.md — пайплайном не обрабатывается; читается отдельным контрактом `/ztn:bootstrap`.

### Будущие автоматизации (контекст)
- Психолог / эдвайзер по жизни
- Рабочий эксперт / коуч / твин / помощник
- Таск-менеджер + календарь
- Агент для публичных профессиональных постов

### Document Ownership

This file is the **runtime configuration** loaded by `/ztn:process` at Step 1.
It defines note formats, routing rules, entity types, naming conventions.

For philosophy and architecture: see `5_meta/CONCEPT.md`.
For processing principles: see `5_meta/PROCESSING_PRINCIPLES.md`.
For pipeline algorithm: see SKILL.md (`/ztn:process`).
For batch output format: see `_system/docs/batch-format.md` (markdown
report + JSON manifest emission per `emit_batch_manifest.py`).

---

## CLARIFICATIONS Safety Valve (HARD RULE)

**При `confidence < threshold` скилл НЕ принимает решение молча — пишет вопрос в
`_system/state/CLARIFICATIONS.md` и продолжает работу с conservative default.**

Применяется ко ВСЕМ скиллам системы:

| Скилл | Типичный trigger для CLARIFICATIONS |
|---|---|
| `/ztn:bootstrap` | Неоднозначный tier человека, неясный thread closure, двусмысленный current focus, person identity collision |
| `/ztn:process` | Роль упомянутого неясна, splitting решение неоднозначно, cross-domain mapping сомнителен |
| `/ztn:maintain` | Thread вероятно закрылся, но confidence < 90% |
| `/ztn:lint` | Вероятный дубль с similarity < 95%, Evidence Trail backfill — какая трактовка |

Цель: система автономна + аудитируема. Owner раз в неделю отвечает на вопросы,
скиллы применяют ответы при следующем прогоне. Никаких молчаливых compromise.

---

## Data & Processing Rules

Canonical rules, разделяемые между скиллами. Single source of truth.

### Mention counting (применяется в `/ztn:process`, `/ztn:maintain`, `/ztn:bootstrap`)

- **1 mention = 1 file**, где person появляется в `people:` frontmatter array OR является subject of record/note
- Не per-utterance, не per-topic. Длинная встреча с 6 упоминаниями человека = +1 mention, не +6
- Monotonic — counts только растут при `/ztn:process`. Decrements только при удалении нот (редкий случай, делается manually или `/ztn:lint` при dedup)
- `last_mention` date = latest `created` date across files referencing person

### People inclusion in `people:` frontmatter (применяется в `/ztn:process`)

- **Inclusion-biased**: если person resolved и упомянут в content (не noise) — добавлять в `people:` array
- Не применять эвристику "central to note" — это subjective и source of gaps
- **Bare first name** (без фамилии, не резолвится в full ID) → **append в `_system/state/people-candidates.jsonl`** (buffer) через `python3 _system/scripts/append_person_candidate.py`. **НЕ добавлять** в `people:`, **НЕ** raise CLARIFICATION per mention. `/ztn:lint` Scan C.5 еженедельно агрегирует buffer и promotes только recurring/information-rich candidates в CLARIFICATIONS. Rationale: снижает friction для one-off mentions (redesigned 2026-04-24).
- **Escape hatch** — raise CLARIFICATION immediately только при одном из явных сигналов: (a) external/client meeting, (b) full surname присутствует elsewhere в transcript но не сматчился из-за STT artifact, (c) user tag `@resolve-now`, (d) role+context полностью specified в mention. Подробности — `/ztn:process` Step 3.8.

### OPEN_THREADS grain (применяется в `/ztn:bootstrap`, `/ztn:maintain`)

- **Strategic grain only**: один thread = umbrella topic покрывающий несколько related TASKS.md Waiting items
- НЕ делать 1:1 mapping с TASKS.md Waiting — это operational layer
- Каждый thread должен иметь поле `## Related Tasks` со ссылками на TASKS.md tasks (для auto-closure tracking)
- Auto-closure: если все related tasks done/stale → thread → Resolved

### Thread ↔ Hub linkage (применяется в `/ztn:maintain` + `/ztn:lint`)

- При создании/обновлении thread: искать hub по теме (match по people + keyword signals). Если найден — thread field `hub: [[hub-id]]`
- При apparence thread — добавить bullet в hub's `## Открытые вопросы`
- При closure thread — убрать из hub's Open Questions, добавить resolution в hub's `## Ключевые выводы`
- `/ztn:lint` nightly verifies consistency: для каждого thread с `hub:` проверить существование hub и отсутствие drift между thread state и hub content

### Tier assignment (применяется в `/ztn:bootstrap`, `/ztn:maintain`, `/ztn:lint`)

- **Tier 1** — profile существует в `3_resources/people/{id}.md` OR mentions ≥ 8
- **Tier 2** — mentions 3-7 (no profile)
- **Tier 3** — mentions 1-2 (no profile)
- **stale** — 0 mentions, no profile (candidate для archival, но не автоматически)
- `/ztn:process` при добавлении нового человека: если creates profile → Tier 1, else Tier 3. Не пересчитывает existing entries
- `/ztn:maintain` при incremental update: **предлагает** promote Tier (3→2, 2→1) через CLARIFICATION `tier-promote-suggested`. **Никогда не применяет автоматически** — apply через `/ztn:resolve-clarifications` (owner confirms, skill diffs PEOPLE.md tier column). Никогда не demote (это `/ztn:lint` territory)
- Profile creation: для new person — inline в `/ztn:process` при достаточном контексте. Для existing person crossing Tier 1 threshold без profile — `/ztn:lint` generates profile skeleton при reviewed tier

### Profile template (canonical — applied by `/ztn:process`, `/ztn:lint`)

Все profiles (existing + auto-generated) match canonical template:

```yaml
---
id: {person-id}
name: "{Name cyrillic}"
role: {role}
org: {org}
tags:
  - person/{id}
  - org/{org}
  - role/{role}
---

# {Name cyrillic}

**Role:** {role summary one line}

## Контекст

{Narrative — role, relationship, recent notable context}

## Мои наблюдения

{Private — owner's subjective opinions. Structurally required section. NEVER auto-generated content. Auto-generation emits placeholder `_(заполняется вручную)_`}

## Упоминания

- [[note-id]] — {brief hint, date}
```

Order mandatory: frontmatter → `# Name` → `**Role:**` → `## Контекст` → `## Мои наблюдения` → `## Упоминания`.

### Log file ownership

- `log_lint.md` — written ONLY by `/ztn:lint`
- `log_maintenance.md` — written ONLY by `/ztn:maintain` + `/ztn:bootstrap`
- `log_process.md` — written ONLY by `/ztn:process`
- `log_agent_lens.md` — written ONLY by `/ztn:agent-lens`
- `agent-lens-runs.jsonl` — written ONLY by `/ztn:agent-lens` (append-only machine index)
- Cross-reads OK (activity detection, context sourcing)

### Skill Write Territory (HARD RULES)

Pipeline skills have non-overlapping write territories. Territory violation is
a schema violation — audits check this via git diff scope.

| Operation | Authorised skill | Rationale |
|---|---|---|
| Create new records / notes / tasks / events | `/ztn:process` only | Extraction from sources is the process domain |
| Increment PEOPLE.md `Mentions` column | `/ztn:process` only | Per-file counting happens inline at batch write |
| Modify body of existing records/notes | `/ztn:process` (initial) + `/ztn:lint` (dedup merge only) | No other skill touches content |
| Append `threads:` back-ref to record/note frontmatter | `/ztn:maintain` only | Structural metadata — body never touched |
| Tier change in PEOPLE.md (promote or demote) | **via `/ztn:resolve-clarifications` only** | Never auto-applied — surfaces CLARIFICATION |
| Thread closure (Active → Resolved in OPEN_THREADS.md) | **via `/ztn:resolve-clarifications` only** | Never auto-applied regardless of signal strength |
| SOUL.md edits (Identity / Focus / Working Style — outside auto-zone) | **manual only** | Identity file; auto-zone is a separate write-lane |
| SOUL.md auto-zone (Values between markers) | `render_soul_values.py` only | Deterministic render from `0_constitution/` |
| Write `_system/state/batches/{id}.md` + `BATCH_LOG.md` row | `/ztn:process` only | One run = one batch; maintain reads, doesn't write |
| Hub linkage back-write (`hub:` field on thread, bullet in hub Open Questions) | `/ztn:maintain` only | Both sides updated atomically; lint verifies |
| Regenerate views (CONSTITUTION_INDEX, constitution-core, HUB_INDEX, CURRENT_CONTEXT) | Scripts via `regen_all.py` / relevant skill | Views are derived — source is `0_constitution/` / knowledge notes |

**Supporting invariants:**
1. `/ztn:maintain` NEVER creates content — only structural metadata (back-refs).
2. `/ztn:lint` NEVER applies closure or tier changes — only surfaces CLARIFICATIONS.
3. Hub `topic_relevance ≥ 1` required for hub ↔ thread linkage — pure people-overlap never links (prevents hub bloat).
4. Dedup (similarity ≥ 95%) is the ONLY body-edit `/ztn:lint` performs — it merges, never deletes unilaterally.
5. CLARIFICATIONS are the universal human-in-the-loop gate — any ambiguity at skill confidence below threshold writes a question, not a decision.

### CLARIFICATIONS format

All CLARIFICATION items MUST include:
- `**Context:**` field (2-4 sentence paragraph) — self-contained для LLM review session (owner не читает CLARIFICATIONS глазами напрямую, обсуждает с LLM)
- `**Quote:**` field — verbatim fragment when source = транскрипт
- Parsable fields: `Type`, `Subject`, `Source`, `Suggested action`, `Confidence tier`

Resolved items use structured format with `**Applied:** no|yes` field + `**Context:**` + `**Rationale:**` + canonical `Resolution-action` vocabulary. Single format — `## Open Items` + `## Resolved Items` sections only.

Owner-facing review path: `/ztn:resolve-clarifications` — interactive walker that clusters items by theme, reminds context inline, pre-forms hypotheses against constitution, applies confirmed resolutions, and archives closed items.

**Canonical `Resolution-action` vocabulary** (append-only evolution — stable contract for `/ztn:resolve-clarifications` and any future automated consumer):

| Action | Target | Payload example |
|---|---|---|
| `close-thread` | thread-id | `resolution_text: "Решение принято, выкатили X"` |
| `keep-thread-open` | thread-id | `(none)` |
| `close-partial` | thread-id | `remaining_tasks: [ids], new_status: "needs-decision"` |
| `promote-tier` | person-id | `from: 2, to: 1` |
| `demote-tier` | person-id | `from: 1, to: 2, reason: "inactive"` |
| `merge-notes` | kept-note-id | `deleted: [ids], merge_strategy: "A superset of B"` |
| `dismiss-duplicate` | note-id | `(none)` |
| `backfill-evidence-trail` | note-id | `entries: [{date, source, action}]` |
| `resolve-bare-name` | subject-string | `person: person-id` OR `ignore: true` |
| `create-profile` | person-id | `from_tier: N, context_sources: [record-ids]` |
| `fix-process` | (free-form) | `suggestion: "process Step X.Y ..."` |
| `dismiss` | subject | `reason: noise | not-actionable | wontfix | stt-artifact` |
| `defer` | subject | `until: YYYY-MM-DD` |
| `validate-applied-fixes` | fix-id-range | `fix_ids: [ids], all_correct: bool, reverts: [ids]` |
| `pursue-or-close` | thread-id | `choice: pursue | close | keep-watching, note: "why"` |
| `review-soul` | soul-section | `edits_applied: bool, rationale: "..."` |
| `run-check-content` | (none) | `content_overview_generated: true, notes_reviewed: N` |
| `decide-policy` | subject | `policy_chosen: "a|b|c|d", sdd_updated: bool` |
| `suppress-until` | subject | `date: YYYY-MM-DD, reason: "..."` — suppression cache entry |
| `update-hub-synthesis` | hub-id | `sections_updated: ["Текущее понимание", "Changelog"], notes_integrated: [ids]` — owner refreshed hub against fresh underlying material (D.4) |
| `split-hub` | hub-id | `new_hub_ids: [ids], theme_separation: "..."` — owner split a hub into ≥ 2 narrower hubs (D.4 split-mismatch resolution) |
| `archive-hub` | hub-id | `target_path: "4_archive/...", reason: "..."` — owner archived a hub whose theme is no longer active |

**Vocabulary governance:**
- Reason codes ending `-suggested` / `-resolved` / `-drift-warn` / `-promote-*` MUST use canonical vocabulary — feed `/ztn:resolve-clarifications` execution
- Reason codes ending `-reminder` / `-surfaced (policy-decision)` / `-advice` MAY use free-form Suggested action — conversational triggers, not executable operations
- New canonical verbs: append-only addition к this table. Removed / renamed verbs = breaking change requires migration of existing Resolved Items

### Cross-skill exclusion

All four pipeline skills (`/ztn:process`, `/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`) mutually exclusive. Each reads all four `.{skill}.lock` files в `_sources/` on start. Any other skill's lock exists → abort.

`/ztn:agent-lens-add` (lens creation wizard) is owner-driven, not in the lock matrix. It respects `/ztn:agent-lens`'s lock at pre-flight (would race on registry writes) but does not acquire its own — uses concurrent-edit detection (snapshot at Step 0, re-validate at write) to defend against rare parallel owner invocations.

**`/ztn:bootstrap` не входит в lock matrix** — disposable one-shot skill (запускается при системной инициализации, disaster recovery, onboarding'е друга). User ensures system idle before running bootstrap (runs <1 раз в год после initial setup).

---

## Architecture — Three Layers

ZTN v4 использует три слоя обработки знаний:

| Слой | Путь | Назначение | Формат |
|------|------|-----------|--------|
| Records | `_records/{meetings,observations}/` | Операционные логи transcript-grounded событий: рабочих встреч (`kind: meeting`) и соло Plaud-записей (`kind: observation`) | Лёгкий: summary + key points (+ action items для meetings) |
| Knowledge | PARA (`1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`) | Атомарные инсайты, решения, идеи | Полный frontmatter + structured content |
| Hubs | `5_meta/mocs/` | Синтез и эволюция мышления по теме | Living document с chronological map |

**Принципы обработки:** `5_meta/PROCESSING_PRINCIPLES.md` (source of truth для LLM-суждений)
**Архитектура:** `5_meta/CONCEPT.md` (философия, ADR, примеры)
**Pipeline:** SKILL.md (`/ztn:process`) — полный алгоритм обработки

---

## Repository Structure

```
zettelkasten/
├── _sources/                         # ВСЕ сырые данные (input + processed)
│   ├── inbox/                        # Новые, необработанные файлы
│   │   └── {source-id}/              # Whitelist живёт в _system/registries/SOURCES.md.
│   │                                 # Layout каждой папки определяется колонкой Layout
│   │                                 # на её row: flat-md (*.md в корне) | dir-per-item
│   │                                 # ({folder}/transcript.md) | dir-with-summary
│   │                                 # ({folder}/transcript_with_summary.md preferred).
│   │                                 # Подкаталоги, объявленные в Skip Subdirs, исключены.
│   └── processed/                    # Обработанные файлы (зеркальная иерархия)
│       └── {source-id}/{id}/...
├── _records/                         # Слой 1: Records (операционная память)
│   ├── meetings/                     # Логи многосторонних встреч (kind: meeting)
│   └── observations/                 # Соло-записи: рефлексии, идеи, терапия (kind: observation)
├── _system/                          # Системные файлы (Phase 4.75 layout)
│   ├── SOUL.md                       # Identity + Focus + Working Style
│   ├── TASKS.md                      # Автогенерируемый список задач
│   ├── CALENDAR.md                   # Автогенерируемый календарь
│   ├── POSTS.md                      # Реестр опубликованных постов
│   ├── docs/                         # Платформенные документы (binding)
│   │   ├── SYSTEM_CONFIG.md          # Этот файл — runtime config
│   │   ├── ARCHITECTURE.md           # Системный дизайн
│   │   ├── CONVENTIONS.md            # Documentation style rules (binding)
│   │   ├── batch-format.md           # Контракт batch формата
│   │   ├── constitution-capture.md   # Global hook (symlinked from ~/.claude/rules/)
│   │   └── harness-setup.md          # Per-machine install guide
│   ├── views/                        # Авто-генерируемые представления (read-only)
│   │   ├── CONSTITUTION_INDEX.md     # Registry активных principles
│   │   ├── constitution-core.md      # Harness view (symlinked from ~/.claude/rules/)
│   │   ├── HUB_INDEX.md              # Индекс всех hub-заметок
│   │   ├── INDEX.md                  # Content catalog (knowledge + hubs, faceted)
│   │   ├── CURRENT_CONTEXT.md        # Live state snapshot
│   │   └── CONTENT_OVERVIEW.md       # Автогенерируемый обзор контент-кандидатов
│   ├── state/                        # Pipeline state (write-heavy)
│   │   ├── BATCH_LOG.md              # Index всех batch-операций
│   │   ├── PROCESSED.md              # Source → Note маппинг
│   │   ├── CLARIFICATIONS.md         # Human-in-the-loop вопросы от скиллов
│   │   ├── OPEN_THREADS.md           # Незакрытые темы и ожидания
│   │   ├── principle-candidates.jsonl  # Append-only candidate buffer
│   │   ├── log_process.md            # Хронологический лог /ztn:process
│   │   ├── log_maintenance.md        # Append-only лог /ztn:maintain + /ztn:bootstrap
│   │   ├── log_lint.md               # Append-only лог /ztn:lint runs
│   │   ├── batches/                  # Полные batch-отчёты
│   │   └── lint-context/             # Lint Context Store: daily/ (30d rolling) + monthly/ (forever)
│   ├── scripts/                      # Python pipeline (см. scripts/README.md)
│   └── registries/                   # Реестры сущностей и форматные спеки
│       ├── TAGS.md                   # Реестр `tags:` namespace labels
│       ├── SOURCES.md                # Реестр источников
│       ├── FOLDERS.md                # Структура папок (этот layout)
│       ├── CONCEPT_NAMING.md         # Канонический формат concept-имён (snake_case)
│       ├── AUDIENCES.md              # Whitelist `audience_tags` privacy labels
│       ├── AGENT_LENSES.md           # Agent-lens registry
│       └── lenses/                   # Per-lens prompts + frame contract
├── 0_constitution/                   # Behavioural principles layer (Phase 4.5)
│   ├── CONSTITUTION.md               # Root doc — scope, invariants, tree
│   ├── axiom/                        # Tier-1 axioms
│   ├── principle/                    # Tier-2 principles
│   └── rule/                         # Tier-3 rules
├── 1_projects/                       # Активные проекты
│   └── PROJECTS.md                   # Реестр проектов (co-located here since 4.75)
├── 2_areas/                          # Области ответственности
│   ├── work/
│   │   ├── company/
│   │   ├── meetings/
│   │   ├── planning/
│   │   ├── reflection/
│   │   ├── technical/
│   │   └── team/
│   ├── career/
│   └── personal/
│       ├── reflection/
│       ├── health/
│       └── relationships/
├── 3_resources/                      # Ресурсы
│   ├── tech/
│   │   ├── ai-agents/
│   │   ├── architecture/
│   │   ├── fintech/
│   │   └── payments/
│   ├── ideas/
│   │   ├── business/
│   │   └── products/
│   └── people/                       # Профили людей
│       └── PEOPLE.md                 # Реестр людей (co-located with profiles since 4.75)
├── 4_archive/                        # Архив
├── 5_meta/                           # Мета-система
│   ├── CONCEPT.md                    # Архитектурный документ (source of truth)
│   ├── PROCESSING_PRINCIPLES.md      # 8 принципов обработки + values profile
│   ├── templates/
│   ├── workflows/
│   └── mocs/                         # Слой 3: Hubs (синтез и эволюция)
├── 5_skills/                         # Skills
└── 6_posts/                          # Опубликованный контент
```

---

## Naming Conventions

### Files
```
YYYYMMDD-short-semantic-name.md
```
- Дата в начале для сортировки
- Короткое смысловое имя на английском
- Lowercase, дефисы

**Примеры:**
- `20260125-meeting-ivan-petrov-restructuring.md`
- `20260113-idea-game-payment-gateway.md`
- `20260120-reflection-work-life-balance.md`

### Tags
```
category/specific-tag
```
- Lowercase
- Дефисы внутри слов
- Иерархия через `/`

**Примеры:**
- `type/meeting`
- `project/career-promotion`
- `person/ivan-petrov`

### Folders
- Lowercase
- Дефисы
- Без пробелов

### Entity IDs (people, projects)
- Lowercase
- Короткое имя
- `ivan-petrov`, `john-doe`, `acme-payments`, `agentic-commerce`

---

## Note Formats (v4)

ZTN v4 использует два формата: Record (лёгкий) и Knowledge Note (полный).
Шаблоны: `5_meta/templates/record-template.md`, `5_meta/templates/note-template.md`

### Record Frontmatter (layer: record)

Records have two kinds. `kind: meeting` для multi-speaker встреч; `kind: observation` для solo Plaud-записей. Поле `kind:` обязательно для observation; для meeting опционально (отсутствие = meeting для backward compat).

**Meeting record:**

```yaml
---
id: YYYYMMDD-meeting-{person}-{topic}
title: "Встреча: {тема}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md

layer: record
kind: meeting              # optional — absence implies meeting (backward compat)
people:
  - person-id
projects:
  - project-id
concepts:                  # canonical concept names per CONCEPT_NAMING.md (snake_case ASCII)
  - concept_name_1
origin: work               # privacy trio per ENGINE_DOCTRINE §3.8 — defaults: work / [] / false on meeting
audience_tags: []
is_sensitive: false
tags:
  - record/meeting
  - person/{id}
  - project/{id}
---
```

Body: `## Summary`, `## Ключевые пункты`, `## Решения`, `## Action Items`, `## Упоминания людей`, `## Source`.

**Observation record:**

```yaml
---
id: YYYYMMDD-observation-{topic-slug}
title: "Наблюдение: {тема}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript_with_summary.md
recorded_at: {ISO timestamp}

layer: record
kind: observation          # mandatory
speaker: {person-id of the owner from SOUL.md Identity; "unknown" если ambiguous}
people:
  - {упомянутые по имени}
projects:
  - {если затронуты}
concepts:                  # canonical concept names per CONCEPT_NAMING.md
  - concept_name_1
origin: personal           # privacy trio — defaults: personal / [] / false on solo Plaud capture
audience_tags: []
is_sensitive: false        # set true on therapy / health / family / financial content
tags:
  - record/observation
  - person/{speaker}
  - topic/{topic}
---
```

Body: `## Summary`, `## Ключевые пункты`, `## Контекст / настроение` (опц.), `## Упоминания людей` (опц.), `## Source`. NO `## Решения` / `## Action Items` (живут в knowledge notes c `extracted_from:`).

Полный шаблон observation: `5_meta/templates/observation-record-template.md`.

### Knowledge Note Frontmatter (layer: knowledge)

```yaml
---
id: YYYYMMDD-{type}-{topic}
title: "{Title}"
created: YYYY-MM-DD
modified: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md
extracted_from: {record-id}  # если извлечён из record
related_to: {primary-note-id}  # если не primary note из группы (optional)
supersedes: {previous-note-id}  # если пересматривает предыдущее решение (optional)

layer: knowledge
types:
  - decision|insight|reflection|idea|technical
domains:
  - work|career|personal
projects:
  - project-id
people:
  - person-id

# contains: (OPTIONAL — include only when note has tasks/ideas/meetings)
# Omit entirely if all counts are 0 or if the only non-zero count is obvious from type.
#   tasks: N
#   ideas: N

status: actionable|reference|archived
priority: high|normal|low
content_potential: high|medium  # OPTIONAL — set by pipeline when note has public value
content_type: expert|reflection|story|insight|observation  # OPTIONAL — set with content_potential
content_angle: "hook" | ["hook1", "hook2"]  # OPTIONAL — string or array of angle hooks
mentions: N  # OPTIONAL — for idea notes, counts how many times idea surfaced across transcripts

concepts:                                 # canonical concept names per CONCEPT_NAMING.md
  - concept_name_1
  - concept_name_2

# Privacy trio per ENGINE_DOCTRINE §3.8.
# `origin` ∈ {personal, work, external}; `audience_tags[]` from
# canonical 5 + AUDIENCES.md extensions; `is_sensitive` is bool.
# Defaults are conservative-safe (`personal` / `[]` / `false`).
origin: personal
audience_tags: []
is_sensitive: false

tags:
  - type/{type}
  - domain/{domain}
  - person/{id}
  - project/{id}
---
```

Knowledge note content: structured по теме (контекст, ключевая мысль, применение, связи).

### Hub Frontmatter (layer: hub)

```yaml
---
id: hub-{topic-slug}
title: "Hub: {Topic Name}"
aliases: []
created: YYYY-MM-DD
modified: YYYY-MM-DD
hub_created: YYYY-MM-DD

layer: hub
domains:
  - work|personal|career
projects: []
people: []

# Privacy trio — auto-derived by `_common.py::recompute_hub_trio()`
# from member-note trios. `_engine_derived` lists fields the engine
# currently owns and re-derives on every touch. Owner takes over a
# field by removing its name from `_engine_derived`; the value is then
# preserved permanently. Hub frontmatter does NOT carry `concepts:` —
# `member_concepts` is manifest-only, derived at emission time.
origin: personal|work|external
audience_tags: []
is_sensitive: false
_engine_derived:
  - origin
  - audience_tags
  - is_sensitive

related_notes: N
first_mention: YYYY-MM-DD
last_mention: YYYY-MM-DD
cadence: daily|weekly|sporadic

status: active|dormant|resolved
priority: high|normal|low

tags:
  - hub
  - domain/{domain}
  - topic/{topic}
---
```

Hub content structure: `## Текущее понимание` (с подсекциями `### Ключевые выводы`,
`### Открытые вопросы`, `### Активные риски`), `## Хронологическая карта`,
`## Связанные знания` (с подсекциями `### Решения`, `### Инсайты`, `### Cross-Domain связи`),
`## Changelog`.

Шаблон: `5_meta/templates/hub-template.md`

### Source Section (вместо `<details>`)

Оригинальный транскрипт НЕ дублируется в заметках — он живёт в `_sources/processed/`.
Записи и заметки содержат `## Source` секцию со ссылкой:

```markdown
## Source

**Transcript:** `_sources/processed/plaud/{timestamp}/transcript_with_summary.md`
**Recorded:** YYYY-MM-DDTHH:MM:SSZ
```

Full-text search по raw content: `grep -r "keyword" zettelkasten/_sources/`

---

## Types (type:)

| Type | Description | Папка по умолчанию |
|------|-------------|-------------------|
| meeting | Встреча, совещание | **DEPRECATED** — новые встречи → `_records/meetings/` как records. Legacy notes в `2_areas/work/meetings/` сохраняются |
| reflection | Рефлексия, размышления | 2_areas/personal/reflection/ |
| task | Задача (редко отдельно) | по контексту |
| idea | Идея | 3_resources/ideas/ |
| decision | Решение | по контексту |
| log | Дневник, отчёт | 2_areas/personal/ |
| planning | Планирование | 2_areas/work/planning/ |
| technical | Техническое | 2_areas/work/technical/ или 3_resources/tech/ |
| reference | Справка | 3_resources/ |
| person | Профиль человека | 3_resources/people/ |
| project | Описание проекта | 1_projects/ |
| record | Операционный лог transcript-grounded события (kind: meeting или observation) | `_records/meetings/` (встречи) или `_records/observations/` (соло Plaud) |
| hub | Hub — синтез и эволюция по теме | 5_meta/mocs/ |

---

## Domains (domain:)

| Domain | Description |
|--------|-------------|
| work | Работа (RBS, PSP, проекты) |
| career | Карьера (повышение, развитие) |
| personal | Личное (рефлексия, здоровье) |

---

## Statuses (status:)

| Status | Description |
|--------|-------------|
| actionable | Требует действий |
| waiting | Ждёт чего-то |
| someday | Когда-нибудь |
| reference | Просто информация |
| archived | В архиве |

---

## Concepts (concepts:)

Open-vocabulary semantic anchors — every "thing-in-the-world" the
knowledge base tracks. Format and rules: `_system/registries/CONCEPT_NAMING.md`.

- **Field on:** records (meeting + observation), knowledge notes,
  project profiles. NOT on hubs (hubs carry `member_concepts[]` only
  in the manifest, derived from members) and NOT on person profiles
  (people are first-class entities; their identifier is `firstname-lastname`).
- **Format:** snake_case ASCII `[a-z0-9_]`, length 1–64, no forbidden
  type prefix, English-only (translate non-English source terms; never
  transliterate).
- **Type lives in metadata, not in name.** The 18-enum
  (`theme`/`tool`/`decision`/`idea`/`event`/`organization`/`skill`/
  `location`/`emotion`/`goal`/`value`/`preference`/`constraint`/
  `algorithm`/`fact`/`other` — `person` and `project` reserved but
  not emitted by ZTN) lives in manifest `concepts.upserts[].type`.
- **Autonomous resolution.** Engine resolves every format issue via
  `_system/scripts/_common.py::normalize_concept_name()`; never raises
  CLARIFICATIONs (see ENGINE_DOCTRINE §3.1 layer-specific exception).

## Privacy Trio (origin / audience_tags / is_sensitive)

Three orthogonal slots on every entity per ENGINE_DOCTRINE §3.8.
Spec: `_system/registries/AUDIENCES.md` for `audience_tags`.

| Field | Type | Default | Spec |
|---|---|---|---|
| `origin` | enum `personal \| work \| external` | `personal` | Source provenance — does NOT determine sharing scope |
| `audience_tags` | `text[]` | `[]` (owner-only) | Whitelist: canonical 5 (`family`/`friends`/`work`/`professional-network`/`world`) ∪ active extensions in AUDIENCES.md |
| `is_sensitive` | bool | `false` | Friction modifier on share — orthogonal to audience |

- **On records, knowledge notes, hubs, person profiles, project
  profiles, principles, every Tier 1/2 typed object.**
- **Hub auto-derivation:** `recompute_hub_trio()` fills MISSING fields
  from members (dominant origin / audience intersection / sensitivity
  contagion); never overwrites owner-set values.
- **Lint Step 1.D backfill** applies conservative defaults to existing
  entities lacking the trio (one-time migration on first lint run
  after the engine adopts the trio).

## Content Potential Fields

Three optional fields set together when a note has public sharing value.
Omit all three if note is purely operational, private, or context-free.

### content_potential: high|medium

| Value | When to set |
|-------|------------|
| high | Personal experience illustrating professional principle; specific technical insight/decision; industry opinion; career/leadership reflection; original business/product angle; useful workflow/process; personal reflection with universal resonance |
| medium | Interesting kernel not fully developed; public topic but private context needs rework; fragment that could combine with other notes into a post |
| (omit) | Purely operational, private, or context-free content |

### content_type: expert|reflection|story|insight|observation

| Type | What it is |
|------|-----------|
| expert | Professional/technical knowledge, architectural decisions, domain expertise |
| reflection | Personal introspection, psychology, self-analysis, therapy insights |
| story | Narrative arc — career journey, personal experience, life event |
| insight | Non-obvious connection, counter-intuitive observation, pattern recognition |
| observation | Lightweight seed thought, casual noticing, not yet developed |

### content_angle: string OR array of strings

Each angle is one sentence — the "why would someone read this?" framing.
Written in the language of the target audience.

- **String** (default): single angle for most notes
- **Array**: multiple distinct framings when a note sits at the intersection of domains

```yaml
# Single angle (most notes)
content_angle: "Why delegation is hard for tech leads"

# Multiple angles (note can produce different posts)
content_angle:
  - "Childhood perfectionism → adult control patterns"
  - "Why delegation is hard for tech leads — it's not about trust"
```

---

## Folder Routing Logic

При определении папки для заметки:

1. **По layer (приоритет v4):**
   - record + `kind: meeting` (или kind отсутствует) → `_records/meetings/`
   - record + `kind: observation` (solo Plaud: reflection / idea / therapy) → `_records/observations/`
   - hub → `5_meta/mocs/`

2. **Несколько types** → выбираем по приоритету:
   - project → 1_projects/
   - meeting → 2_areas/work/meetings/ [DEPRECATED в v4 для новых заметок, используй _records/meetings/]
   - planning → 2_areas/work/planning/
   - technical + domain/work → 2_areas/work/technical/
   - technical + ideas → 3_resources/tech/
   - idea → 3_resources/ideas/
   - reflection → 2_areas/personal/reflection/
   - person → 3_resources/people/

3. **По domain если неясно:**
   - work → 2_areas/work/
   - career → 2_areas/career/
   - personal → 2_areas/personal/

4. **По контенту:**
   - RBS, PSP, команда → 2_areas/work/
   - AI, LLM, архитектура → 3_resources/tech/
   - Бизнес-идеи → 3_resources/ideas/business/
   - Продуктовые идеи → 3_resources/ideas/products/

---

## Processing Workflow (/ztn:process)

Pipeline обработки определён в SKILL.md (`/ztn:process`).

Краткая последовательность:
0. Pre-Scan — People Resolution Map (three-tier: RESOLVED / NEW / AMBIGUOUS), hub signal matching
1. Load Context — SYSTEM_CONFIG, PROCESSING_PRINCIPLES, registries, hubs, CLARIFICATIONS
2. Find New Files — scan `_sources/inbox/`, sort chronologically, move to `_sources/processed/`
3. **Process Files (per-batch full-pipeline subagents)** —
   Orchestrator partitions chronologically-sorted file list into batches
   (T = 250k input tokens, N = 6 transcripts max per batch, max 3 parallel
   subagents). Each subagent runs 3.1–3.7 for every transcript in its
   batch in shared context, returns manifest with notes + coverage data.
   - 3.1 Read transcript (two formats: with/without summary) — *in subagent*
   - 3.2 LLM Noise Gate (genuine vs noise, inclusion-biased) — *in subagent*
   - 3.3 Semantic Context Loading (resolve people, load hubs from briefing) — *in subagent*
   - 3.4 LLM Classification (14 questions) — *in subagent*
   - 3.5 Create Outputs (records, knowledge notes, hub updates/creates, cross-domain) — *in subagent*
   - 3.6 Structural Verification — *in subagent*
   - 3.7 **Self-Review** — producer-side coverage manifest (PEOPLE / TOPICS / DECISIONS / ACTIONS) reconciled against produced notes, fixes applied in place — *in subagent*
   - 3.7.5 Constitution Alignment Check — *in orchestrator, post-aggregate*
   - 3.8 People Profiles (create/update, CLARIFICATIONS for uncertain) — *in orchestrator, post-aggregate*
   - 3.9 System updates (PROCESSED, LOG) — *in orchestrator*
   - 3.10 Verify source integrity (file completeness invariant: union of subagent-processed paths = enumerated source set) — *in orchestrator*
4. Post-Processing — TASKS, CALENDAR, HUB_INDEX, content potential verification, batch verification
5. Completion Gate — mandatory checklist, halt-on-error, no deferring
6. Report — summary with coverage fix rate and clarifications

Принципы обработки: `5_meta/PROCESSING_PRINCIPLES.md`
Архитектура: `5_meta/CONCEPT.md`

---

## Entity Matching

### Before creating any new entity:

```
1. Normalize name (lowercase, dashes, transliterate if needed)
2. Search in registry:
   - Exact match
   - Fuzzy match (similar names)
3. If found → use existing
4. If not found → create new → add to registry
```

### Name normalization:
- "Иван Петров" → "ivan-petrov"
- "Acme Payments" → "acme-payments"
- "Career Promotion" → "career-promotion"
- "AI Agents" → "ai-agents"

---

## People Profiles

When a person is mentioned:

1. Check PEOPLE.md registry
2. If exists → add mention link to their profile
3. If not exists:
   - Create profile in 3_resources/people/{id}.md
   - Add to PEOPLE.md registry

### Profile format:
```markdown
---
id: ivan-petrov
name: "Иван Петров"
role: CEO
org: acme
tags:
  - person/ivan-petrov
  - org/acme
  - role/ceo
---

# Иван Петров

**Role:** CEO @ Acme

## Контекст
[Описание роли и отношений]

## Упоминания
- [[20260125-meeting-ivan-petrov|Встреча 25 января]] — example link
```

---

## Task Format

### Inline в заметках (source)

```markdown
- [ ] Описание задачи → [[связь]] ^task-unique-id
- [x] Завершённая задача ✅ YYYY-MM-DD ^task-id
```

Task IDs: уникальные в рамках файла, формат `^task-short-description`.
Примеры: `^task-write-letter-ivan-petrov`, `^task-prepare-presentation`.

### Aggregate в TASKS.md (regenerated by /ztn:process)

**Структура (6 секций):**

1. **Action — я делаю** — owner is the executor
2. **Waiting — жду от других** — другой человек должен прислать/дать результат owner'у
3. **Delegate — контролирую выполнение** — owner назначил/эскалировал, отслеживает
4. **Someday** — низкий приоритет / идеи на будущее
5. **Personal** — не связано с работой
6. **Stale** — кандидаты на удаление (устарели, поглощены, потерян контекст)

Внутри каждой секции — группировка по **потоку** (`### Stream Name`).
Потоки органические: создавай по мере появления кластеров задач —
кластеризация по теме / проекту / области ответственности; имена потоков
определяются органически из контента, а не предзаданы.

**Форматы по типу:**
```markdown
# Action:
- [ ] Description — [[note-link]] ^task-id

# Waiting:
- [ ] **@person-id** What I'm waiting for — deadline — [[note-link]] ^task-id

# Delegate:
- [ ] **@person-id** What they're doing — deadline — [[note-link]] ^task-id
```

**Правила классификации (Action / Waiting / Delegate):**

Owner-first-name = first name from SOUL.md `## Identity` `Name:` line. Skill resolves it at runtime.

| Признак | Тип |
|---------|-----|
| Источник: «{owner-first-name}: ...» / first-person speech (`I:` / `я:`) / задача явно для исполнения owner'ом | Action |
| Источник: «@person: ...» и owner — получатель результата (ответ, документ, данные) | Waiting |
| Owner поставил задачу / эскалировал / ведёт как owner-of-tracking, output нужен команде/процессу, не лично owner'у | Delegate |
| Не ясно кто исполнитель | Action (безопасный дефолт) |

**Практический маркер Waiting vs Delegate:**
- Waiting = «owner не может двигаться, пока X не ответит» (блокер для owner'а)
- Delegate = «X работает над задачей, owner следит за прогрессом» (owner как менеджер)

**Stale preservation (важно):**
При регенерации TASKS.md **секция Stale сохраняется** — прочитай текущий файл,
извлеки task-id из секции Stale, при записи новой версии положи их обратно в Stale
(не возвращай в активные секции, даже если в source note всё ещё `- [ ]`).
Stale — это результат ручного ревью пользователя, машина его не переопределяет.

**Шапка TASKS.md (обновляется каждую регенерацию):**
```markdown
**Last Updated:** YYYY-MM-DD
**Open:** N action / N waiting / N delegated / N someday / N personal
**Stale candidates:** N
**Total unique:** N
```

---

## Event/Meeting Format

### Inline в заметках (source)

```markdown
- 📅 **YYYY-MM-DD HH:MM** — Описание события ^meeting-id
```

### Aggregate в CALENDAR.md (regenerated by /ztn:process)

**Структура (4 секции):**

1. **Recurring** — регулярные встречи (маркер 🔄)
2. **Upcoming** — будущие одноразовые события owner'а (маркер 📅)
3. **Deadlines** — чужие дедлайны которые owner отслеживает (маркер ⏰, префикс `**@person**`)
4. **Past** — **только последние 2 недели**; более старые удаляются при регенерации

**Форматы:**
```markdown
# Recurring:
- 🔄 **День недели ЧЧ:ММ МСК** — Описание — [[note-link]]

# Upcoming:
- 📅 **YYYY-MM-DD** — Описание события — [[note-link]]

# Deadlines:
- ⏰ **YYYY-MM-DD** — **@person-id**: что они должны сделать — [[note-link]]

# Past:
- 📅 **YYYY-MM-DD** — Описание — [[note-link]]
```

---

## Language Rules

1. **Tags, types, IDs** → English
2. **Note content (title, text)** → Same language as source
3. **Folder names** → English
4. **Frontmatter keys** → English

---

## Quality Checklist

Before saving each note:
- [ ] ID matches filename
- [ ] All mentioned people exist in registry
- [ ] All mentioned projects exist in registry
- [ ] Tags follow naming convention
- [ ] Source section links to raw transcript in `_sources/processed/`
- [ ] Links use [[wikilink]] format
- [ ] Tasks have unique ^task-id
- [ ] Contains section exists if note has tasks/ideas/meetings (optional otherwise)

---

## Files Reference

| File | Purpose | Updated |
|------|---------|---------|
| _system/docs/SYSTEM_CONFIG.md | This file — runtime config (formats, routing, types) | Manual |
| _system/SOUL.md | Identity + Focus + Working Style | Manual + /ztn:bootstrap (once) |
| _system/state/OPEN_THREADS.md | Active open threads + resolved history | /ztn:bootstrap, /ztn:maintain |
| _system/views/CURRENT_CONTEXT.md | Live state snapshot for thin orientation | /ztn:maintain, /ztn:lint |
| _system/views/INDEX.md | Content catalog of knowledge notes + hubs (PARA / domains / cross-domain / hubs facets) | /ztn:maintain Step 7.6 |
| _system/state/log_lint.md | Append-only log of /ztn:lint runs | Each /ztn:lint |
| _system/state/log_maintenance.md | Append-only log of /ztn:maintain + /ztn:bootstrap runs | Each /ztn:maintain / /ztn:bootstrap |
| _system/state/log_process.md | Chronological log of /ztn:process operations | Each /ztn:process |
| _system/state/log_agent_lens.md | Append-only log of /ztn:agent-lens runs | Each /ztn:agent-lens |
| _system/state/agent-lens-runs.jsonl | Machine index of every agent-lens run (one JSON line per run) | Each /ztn:agent-lens |
| _system/state/agent-lens-rejected/{lens}/{ts}.md | Raw Stage 2 outputs that failed structural validator | On validator rejection |
| _system/agent-lens/{lens}/{date}.md | Structured agent-lens observation outputs | Each successful /ztn:agent-lens lens run |
| _system/registries/AGENT_LENSES.md | Agent-lens registry (active/draft/paused, cadence, schema) | /ztn:agent-lens-add (table row append on creation) + Manual (owner edits) + /ztn:agent-lens (status updates only on auto-pause) |
| _system/registries/lenses/{id}/prompt.md | Per-lens prompt + frontmatter | /ztn:agent-lens-add (creates new lens) + Manual (owner edits) |
| _system/registries/lenses/_frame.md | Two-stage frame (thinker + structurer) + validator rules | Manual (engine-shipped) |
| _system/state/lint-context/daily/*.md | 30-day rolling daily summaries | Each /ztn:lint |
| _system/state/lint-context/monthly/*.md | Append-forever monthly summaries | First /ztn:lint of new UTC month |
| _system/state/BATCH_LOG.md | Append-only index of batch operations | Each /ztn:process |
| _system/state/batches/{id}.md | Full batch reports (one per /ztn:process run) | Each /ztn:process |
| _system/docs/batch-format.md | Batch format contract — markdown report + JSON manifest; per-entity privacy trio + concept fields; sections `## Concepts Upserted` + `## Sensitive Entities` | Manual (bump version on change) |
| _system/state/PROCESSED.md | Source → Note mapping | Each /ztn:process |
| _system/TASKS.md | All open tasks | Regenerated |
| _system/CALENDAR.md | All events | Regenerated |
| _system/POSTS.md | Published posts archive + content strategy | Manual or /ztn:check-content |
| _system/CONTENT_OVERVIEW.md | Auto-generated content candidates overview | Each /ztn:check-content (read-only) |
| _system/state/CLARIFICATIONS.md | Non-blocking human-in-the-loop questions | All skills (safety valve) |
| _system/registries/TAGS.md | Tag registry (`tags:` namespace labels) | When new tags |
| _system/registries/CONCEPT_NAMING.md | Spec — canonical concept-name format (engine-shipped) | Manual (engine maintainer) |
| _system/registries/AUDIENCES.md | Spec + extensions for `audience_tags` privacy labels | /ztn:resolve-clarifications (extension append on owner approval) + Manual (owner edits) |
| 1_projects/PROJECTS.md | Project registry | When new projects |
| 3_resources/people/PEOPLE.md | People registry | When new people |
| _system/registries/FOLDERS.md | Folder structure | Rarely |
| _system/views/HUB_INDEX.md | Index of all hub notes | Each /ztn:process |
| 5_meta/CONCEPT.md | Architecture, philosophy, ADRs (human reference) | Manual |
| 5_meta/PROCESSING_PRINCIPLES.md | 8 principles + values profile (LLM guidance) | Manual |
