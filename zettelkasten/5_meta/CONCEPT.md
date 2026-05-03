# ZTN — Концепция системы управления знаниями

**Статус:** Архитектурный документ (source of truth)

---

## Оглавление

1. [Философия](#философия)
2. [Три слоя системы](#три-слоя-системы)
3. [Четвёртый слой — Конституция](#четвёртый-слой--конституция)
4. [Концепты и приватность — поперечные оси](#концепты-и-приватность--поперечные-оси)
5. [Архитектура](#архитектура)
6. [8 принципов обработки](#8-принципов-обработки)
7. [Обработка транскриптов](#обработка-транскриптов)
8. [Hub-заметки (Maps of Content)](#hub-заметки-maps-of-content)
9. [Примеры обработки](#примеры-обработки)
10. [Query → Compound паттерн](#query--compound-паттерн)
11. [Lint и Sweep операции](#lint-и-sweep-операции)
12. [Генерализация](#генерализация)
13. [Журнал решений](#журнал-решений)
14. [Интеллектуальное наследие](#интеллектуальное-наследие)
15. [Scaling и будущее](#scaling-и-будущее)

---

## Философия

ZTN — это персональное «второе сознание». Не архив, не TODO-лист, не CRM.
Система, которая *думает вместе с тобой*: запоминает контекст, видит связи между доменами,
отслеживает эволюцию мышления.

Ключевой принцип: **лучше захватить лишнее, чем потерять факт**.
Пропущенный инсайт — это навсегда потерянная связь. Лишняя заметка — минута при следующем sweep.

Система оптимизирована для одного пользователя с множеством контекстов:
работа (тимлид/PM), карьера, личное развитие, терапия, бизнес-идеи, отношения.
Ценность рождается на стыке этих контекстов — когда инсайт из терапии
освещает рабочий паттерн делегирования, или рабочее решение вдохновляет продуктовую идею.

### Три уровня ценности

```
Уровень 1: Поиск    "Что мы обсуждали с Иваном в марте?"
Уровень 2: Контекст  "Какие архитектурные решения приняли по API v2?"
Уровень 3: Синтез    "Как менялось моё понимание делегирования за полгода?"
```

Records обслуживают уровень 1. Knowledge — уровень 2. Hubs — уровень 3.

---

## Три слоя системы

```
┌─────────────────────────────────────────────────────────────────┐
│                        ZTN v4 Architecture                      │
│                                                                 │
│  ┌──────────────────┐                                           │
│  │   RAW SOURCES    │  plaud, dji, superwhisper, apple, claude  │
│  │   (transcripts)  │  sessions, crafted documents              │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    PROCESSING (LLM)                        │ │
│  │  Pre-scan → Load → Gate → Classify → Atomize → Audit      │ │
│  └────────┬───────────────┬──────────────────┬────────────────┘ │
│           │               │                  │                  │
│           ▼               ▼                  ▼                  │
│  ┌────────────┐  ┌───────────────┐  ┌───────────────┐          │
│  │  RECORDS   │  │  KNOWLEDGE    │  │  HUBS         │          │
│  │ _records/  │  │  PARA (1-4)   │  │  5_meta/mocs/ │          │
│  │            │  │               │  │               │          │
│  │ Оперативные│  │ Атомарные     │  │ Синтез и      │          │
│  │ логи       │  │ инсайты       │  │ эволюция      │          │
│  │ встреч     │  │               │  │ мышления      │          │
│  └────────────┘  └───────────────┘  └───────────────┘          │
│                                                                 │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  _system/  docs/, views/, state/, scripts/, registries/       ││
│  │            SOUL, TASKS, CALENDAR, POSTS at root               ││
│  └────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Слой 1: Records — операционная память

**Путь:** `_records/{meetings,observations}/`

Records — это *поисковые логи* transcript-grounded событий: рабочих встреч и
соло Plaud-записей. Не знания, не инсайты. Их цель — быстро ответить:
«Что обсуждали на встрече с X?» / «Что я надиктовал в машине 22 апреля?»

**Два kind'а:**
- `kind: meeting` (`_records/meetings/`) — multi-speaker рабочие встречи
- `kind: observation` (`_records/observations/`) — соло Plaud: рефлексии, идеи, терапия

**Общие характеристики:**
- Лёгкий формат: summary, ключевые пункты
- 1:1 с источником — один транскрипт = один record
- Не содержат рефлексии или аналитики (они в knowledge notes с `extracted_from:`)
- Ссылаются на исходный транскрипт через `source:` в frontmatter
- **Контракт wikilink:** knowledge notes всегда якорятся на record-id, никогда на путь транскрипта

**Различия:**
- Meeting — содержит `## Решения` + `## Action Items` + `## Упоминания людей`
- Observation — solo speaker (`speaker:` field), нет решений/задач (живут в knowledge), есть опц. `## Контекст / настроение`

**Аналогия:** Literature notes у Лумана. Сырой материал с минимальной структуризацией.

**Когда НЕ создаётся record:**
- Если транскрипт пустой / служебный (формальная встреча без значимых пунктов)
- Не: «соло-записи в knowledge напрямую» — каждый транскрипт получает observation record как якорь.

### Слой 2: Knowledge — кристаллизованное знание

**Путь:** PARA-структура (`1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`)

Knowledge notes — это *атомарные инсайты*: одна мысль, одно решение, одна идея.
Они concept-oriented, а не source-oriented.

**Характеристики:**
- Атомарные: одна заметка = один инсайт/решение/идея
- Имеют собственную ценность без контекста источника
- Связаны между собой через `[[wikilinks]]`
- Богатый frontmatter для автоматизаций
- Могут быть извлечены из records, или созданы напрямую из личных транскриптов

**Примеры knowledge notes:**
- `20260115-decision-api-platform-payload-design.md` — архитектурное решение
- `20260213-insight-delegation-as-trust.md` — инсайт из терапии
- `20260301-idea-agentic-commerce-platform.md` — продуктовая идея

**Аналогия:** Permanent notes у Лумана. Evergreen notes у Matuschak.

### Слой 3: Hubs — синтез и эволюция

**Путь:** `5_meta/mocs/`

Hubs — это *живые документы*, которые агрегируют, синтезируют и отслеживают эволюцию
мышления по теме. Комбинация Map of Content (структура) и Evergreen doc (текущее понимание).

**Характеристики:**
- Создаются автоматически, когда 3+ knowledge notes затрагивают тему
  (records не считаются — они операционные логи, не кристаллизованное знание)
- Перезаписываются при каждом обновлении (секция «Текущее понимание»)
- Содержат хронологическую карту всех связанных заметок
- Отслеживают, как менялось мышление (changelog)

**Примеры хабов:**
- `hub-api-platform.md` — всё про API v2 платформы
- `hub-career-promotion.md` — путь к повышению
- `hub-delegation-pattern.md` — паттерн делегирования (cross-domain!)

**Аналогия:** MOC у Nick Milo, но с эволюционной семантикой.

### Как слои взаимодействуют

```
Транскрипт рабочей встречи:
  ├── Record (всегда, если встреча значимая)
  ├── Knowledge note (если есть архитектурное решение, инсайт)
  └── Hub update (если тема уже существует)

Транскрипт личного размышления:
  ├── Knowledge note(s) (1-N, по числу атомарных мыслей)
  └── Hub update/creation (если тема рекуррентная)

Транскрипт терапии:
  ├── Knowledge notes (по числу тем, 2-5 обычно)
  ├── Cross-domain extraction (инсайт → рабочий контекст)
  └── Hub updates (может затронуть и личные, и рабочие хабы)
```

---

## Четвёртый слой — Конституция

Поверх Records/Knowledge/Hubs лежит **Constitution Layer** (`0_constitution/`):
курируемый набор аксиом, принципов и правил — rules of engagement, по которым
Claude Code и производные агенты принимают решения от имени пользователя.
Это не архив фактов и не синтез; это явный, типизированный слой
**идентичности**, который агент читает вместо того, чтобы выводить из
разрозненных records.

### Зачем отдельный слой

Records и Knowledge отвечают на «что я думал», Hubs — на «как менялось
моё понимание». Ни один из них не говорит агенту «принимай вот эти
решения так, а не иначе». Без конституции агент вынужден выводить
поведение из rough average текста, что порождает дрейф (в какой-то
момент пишет не-owner). Конституция закрывает эту дыру — описывает
identity точечно, с приоритетами и tie-break'ами.

### Три типа принципов

```
[axiom]       — фундаментальная истина про себя     priority_tier: 1
    │
    │ derived_from (опционально)
    ▼
[principle]   — поведенческий паттерн               priority_tier: 1-3
    │          binding: hard | soft
    │
    │ derived_from (опционально)
    ▼
[rule]        — жёсткое 1/0 ограничение             priority_tier: 1
```

Target: ~5-8 `core: true` аксиом — несводимое ядро, из которого
остальное выводимо. Всё остальное — 25-35 active principles +
несколько rules. Компрессия обязательна, раздувание ядра = потеря
«цинической сути».

### Философия «quality-first» vs ZTN capture-first

| Слой | Philosophy | Почему |
|---|---|---|
| **ZTN memory** (records, knowledge, hubs) | capture-first | Знание, не записанное = потерянное. Шум отфильтруем позже |
| **Constitution** | quality-first | Шум в rules of engagement = агент ведёт себя не как owner. Лучше миссануть, чем испортить ядро |

Это различие проявляется в infrastructure: capture в ZTN широкий, в
constitution — 4 узких trigger + 5 anti-trigger.

### Как конституция подключается к существующим пайплайнам

```
0_constitution/  ─── source of truth
       │
       │ regen (детерминистичный Python)
       ▼
       ├── _system/views/CONSTITUTION_INDEX.md     (registry для человека)
       ├── _system/views/constitution-core.md      (~/.claude/rules симлинк — harness)
       └── _system/SOUL.md Values zone       (между markers)
                 │
                 │ SOUL загружается во ВСЕ три пайплайна
                 ▼
       /ztn:process /maintain /lint  ─── видят Values как часть system-prompt

       /check-decision — читает полное дерево по запросу (Opus reasoning)
       /ztn:capture-candidate — фоновый capture наблюдений в buffer
```

Правило единое: **любой пайплайн, читающий derived view, первым шагом
зовёт `/ztn:regen-constitution`** (Architecture C). Это убирает
«иногда auto, иногда руками» — один триггер, одно место.

### Ключевые решения

1. **Source of truth в ZTN, не в model.** Constitution — markdown-файлы,
   не промпты. Переезд на новую модель ничего не ломает.
2. **Scripts без LLM.** Фильтрация, рендер, архивирование, compaction —
   Python + PyYAML. Детерминизм важнее «умного». LLM зарезервирован для
   reasoning (`/check-decision`, F.5 merge judgment).
3. **Human-in-the-loop на landing.** Агенты append'ят Evidence Trail и
   bump'ят `last_applied` (L1). Новые принципы / tier change / `core`
   flag — только owner (L3/L4).
4. **Никогда silent delete.** Кандидаты архивируются weekly с
   verify-before-clear. Отказ → файл остаётся в git history.
5. **Scope как data marker.** Поле `scope: shared|personal|sensitive`
   хранится сразу на каждом принципе — когда ship'ится sharing
   (wife / friends / MCP), фильтр ставится в один коммит, а не в
   ретроспективную миграцию.

### Где искать подробности

- **Protocol doc:** `0_constitution/CONSTITUTION.md` — полная схема
  frontmatter, enum списки, резолюция конфликтов, writeability matrix,
  design rationale.
- **Скрипты:** `_system/scripts/README.md`.
- **Skills:** `~/.claude/skills/ztn-{regen-constitution,check-decision,capture-candidate}/`.

---

## Концепты и приватность — поперечные оси

Поверх трёх слоёв (Records / Knowledge / Hubs) и четвёртого слоя
(Constitution) существуют **поперечные axes**, прорезающие все
сущности: концептный слой и privacy trio. Они не формируют отдельный
слой хранения, но определяют семантический контекст и видимость
каждой entity.

### Концептный слой — `concepts:` frontmatter

«Концепт» = thing-in-the-world, который база отслеживает: тема, tool,
класс решения, организация, навык, событие, идея, ценность, и т.д.
Open-vocabulary; новые концепты возникают естественно по мере роста
базы. **Не путать с tags** (closed registry of `category/value`
labels) и не с **domains** (tiny closed set: `work`, `identity`,
`learning`, etc).

| Field | Где | Назначение |
|---|---|---|
| `concepts:` | frontmatter records / knowledge notes / project profiles | Каноничные snake_case ASCII имена концептов, которых entity касается |
| `concept_hints[]` | per-record / per-note манифест | Зеркало `concepts:` в JSON manifest для downstream consumer |
| `member_concepts[]` | per-hub манифест | Объединение `concepts:` всех member knowledge notes; manifest-only, не во frontmatter хаба |
| `applies_in_concepts[]` | constitution principle манифест | Концепты, в которых принцип применим |
| `concepts.upserts[]` | top-level манифест | Дедуплицированный реестр концептов batch'a с `name` / `type` / `subtype` / `related_concepts` / `previous_slugs` |

**Format**: snake_case `[a-z0-9_]`, ASCII, English-only, length ≤ 64,
no forbidden type prefix. Spec: `_system/registries/CONCEPT_NAMING.md`.

**Type enum** (lowercase, в манифесте только): `theme`, `tool`,
`decision`, `idea`, `event`, `organization`, `skill`, `location`,
`emotion`, `goal`, `value`, `preference`, `constraint`, `algorithm`,
`fact`, `other`. `person` и `project` зарезервированы спецой, но ZTN
их в `concepts.upserts[]` не эмитит — они first-class через
`tier1_objects.{people,projects}`.

**Translation contract**: non-English source terms ОБЯЗАТЕЛЬНО
переводятся семантически в `/ztn:process` Q15 ДО эмиссии. Никогда
не транслитерируются (раскалывает identity графа). Untranslatable
terms — silent drop (теряем mention, но сохраняем граф stable).

### Privacy trio — три ортогональных слота

| Field | Тип | Default | Question |
|---|---|---|---|
| `origin` | enum `personal\|work\|external` | `personal` | Where was this captured? (provenance) |
| `audience_tags` | `text[]` | `[]` | Who is allowed to see it? |
| `is_sensitive` | bool | `false` | Does sharing require extra friction? |

**На каждой entity**: records, knowledge notes, hubs, person profiles,
project profiles, tasks, events, ideas, principles, Tier 2 typed
objects.

**Audience whitelist**: canonical 5 (`family`, `friends`, `work`,
`professional-network`, `world`) + tenant Extensions table в
`_system/registries/AUDIENCES.md`. Empty `[]` = owner-only (safest
state — fail-closed).

**Hub auto-derivation**: `_common.py::recompute_hub_trio()` fills
missing trio fields from members (dominant origin / audience
intersection / sensitivity contagion); НИКОГДА не overwrites
owner-set values. Owner может вручную поставить `audience_tags:
[work]` на hub — engine preserve через все будущие touches.

### Autonomous resolution — layer-specific исключение из §3.1

Концептный и аудиенс-слой **полностью автономны**: engine resolves
все format issues деноминистически через `_common.py` нормализаторы;
никогда не raises CLARIFICATION для owner action. Это **исключение
из ENGINE_DOCTRINE §3.1** ("Surface, don't decide silently"),
обоснованное:

- High-volume layer (десятки концептов в одном транскрипте)
- Per-decision low-stakes (wrong concept name теряет одну mention,
  не data integrity)
- Fully-specified algorithm (нормализация — pure function, нет
  judgment)

Surfacing per-decision drowned бы owner queue без actual decision'ов,
которые owner мог бы принять. Все остальные layers (threading,
dedup, principle promotion, people identity, и т.д.) сохраняют
surface-don't-decide правило.

### Где искать подробности

- **Concept format spec:** `_system/registries/CONCEPT_NAMING.md`.
- **Audience whitelist + extensions:** `_system/registries/AUDIENCES.md`.
- **Manifest contract:** `_system/docs/batch-format.md` + downstream
  schema в `minder-project/strategy/ARCHITECTURE.md` §4.5.
- **Helpers:** `_system/scripts/_common.py` (normalize_concept_name,
  normalize_audience_tag, recompute_hub_trio).
- **Producer-side:** `/ztn:process` Step 3.4 Q15/Q16 + Step 4.7.
- **Post-write defence-in-depth:** `/ztn:lint` Scan A.7 +
  `lint_concept_audit.py`.
- **Manifest emitter:** `emit_batch_manifest.py`.

---

## Архитектура

### Структура файловой системы

```
zettelkasten/
├── _sources/                          # Сырые данные
│   ├── inbox/                         # Новые, необработанные файлы
│   └── processed/                     # Обработанные файлы
├── _records/                          # Слой 1: Records
│   ├── meetings/                      # Логи рабочих встреч (kind: meeting)
│   │   └── YYYYMMDD-meeting-{person}-{topic}.md
│   └── observations/                  # Соло Plaud-транскрипты (kind: observation)
│       └── YYYYMMDD-observation-{topic}.md
│
├── 1_projects/                        # Активные проекты
├── 2_areas/                           # Области ответственности
│   ├── work/
│   │   ├── company/
│   │   ├── meetings/                  # [DEPRECATED в v4, миграция в _records/]
│   │   ├── planning/
│   │   ├── reflection/
│   │   ├── technical/
│   │   └── team/
│   ├── career/
│   └── personal/
│       ├── reflection/
│       ├── health/
│       └── relationships/
├── 3_resources/                       # Ресурсы
│   ├── tech/
│   ├── ideas/
│   │   ├── business/
│   │   └── products/
│   └── people/                        # Профили людей
├── 4_archive/                         # Архив
├── 5_meta/                            # Мета-система
│   ├── CONCEPT.md                     # ЭТОТ ФАЙЛ
│   ├── templates/
│   ├── workflows/
│   └── mocs/                          # Слой 3: Hubs
│       └── hub-{topic}.md
├── 5_skills/                          # Claude Code skills
├── 6_posts/                           # Опубликованный контент
│
└── _system/                           # Системные файлы (Phase 4.75 layout)
    ├── SOUL.md                        # Identity + Focus + Working Style
    ├── TASKS.md                       # Все открытые задачи
    ├── CALENDAR.md                    # Все события
    ├── POSTS.md                       # Реестр опубликованных постов + content strategy
    ├── docs/                          # Платформенные документы (binding)
    │   ├── SYSTEM_CONFIG.md           # Runtime config (форматы, routing, типы)
    │   ├── ARCHITECTURE.md            # Системный дизайн
    │   ├── CONVENTIONS.md             # Documentation style rules (binding)
    │   ├── batch-format.md            # Контракт batch формата
    │   ├── constitution-capture.md    # Global hook (symlinked from ~/.claude/rules/)
    │   └── harness-setup.md           # Per-machine install guide
    ├── views/                         # Авто-генерируемые представления (read-only)
    │   ├── CONSTITUTION_INDEX.md      # Registry активных principles
    │   ├── constitution-core.md       # Harness view (symlinked from ~/.claude/rules/)
    │   ├── HUB_INDEX.md               # Индекс хабов
    │   ├── INDEX.md                   # Surface catalog (knowledge + archive + constitution + hubs, faceted)
    │   ├── CURRENT_CONTEXT.md         # Live state snapshot
    │   └── CONTENT_OVERVIEW.md        # Автогенерируемый обзор контент-кандидатов
    ├── state/                         # Pipeline state (write-heavy)
    │   ├── BATCH_LOG.md               # Index batch-операций
    │   ├── PROCESSED.md               # Source → Note маппинг
    │   ├── CLARIFICATIONS.md          # Уточнения и решения
    │   ├── OPEN_THREADS.md            # Незакрытые стратегические нити
    │   ├── principle-candidates.jsonl # Append-only candidate buffer
    │   ├── log_process.md             # Хронологический лог /ztn:process
    │   ├── log_maintenance.md         # Append-only лог /ztn:maintain + /ztn:bootstrap
    │   ├── log_lint.md                # Append-only лог /ztn:lint runs
    │   ├── batches/                   # Полные batch-отчёты
    │   └── lint-context/              # Lint Context Store
    ├── scripts/                       # Python pipeline
    └── registries/                    # Реестры сущностей (schema-only после 4.75)
        ├── TAGS.md                    # Реестр тегов
        ├── SOURCES.md                 # Реестр источников
        └── FOLDERS.md                 # Структура папок

Примечание (Phase 4.75): `PEOPLE.md` co-located с профилями —
`3_resources/people/PEOPLE.md`. `PROJECTS.md` co-located с проектами —
`1_projects/PROJECTS.md`.
```

### Миграция 2_areas/work/meetings/ → _records/meetings/

В v3 рабочие встречи хранились в `2_areas/work/meetings/` как полноценные knowledge notes.
Проблема: шум рабочих встреч (статусы, мелкие задачи) засорял knowledge graph.

**В v4:**
- Новые рабочие встречи → `_records/meetings/` (лёгкий формат)
- Из рабочих встреч *извлекаются* knowledge notes, если есть значимый инсайт/решение
- Старые заметки в `2_areas/work/meetings/` остаются (обратная совместимость)
- Постепенная миграция при sweep-операциях

**Примечание:** Авторитетная спецификация форматов — в `_system/docs/SYSTEM_CONFIG.md`.
Ниже приведены примеры для иллюстрации.

### Frontmatter: Record

```yaml
---
id: 20260330-meeting-ivan-api-platform-status
title: "Встреча с Иваном: статус API v2 платформы"
created: 2026-03-30
source: _sources/processed/plaud/2026-03-30T18:45:23Z/transcript_with_summary.md

layer: record
people:
  - ivan-petrov
  - anna-smirnova
projects:
  - acme-payments
concepts:                  # canonical concept names per CONCEPT_NAMING.md
  - api_v2_design
  - service_architecture
origin: work               # privacy trio per ENGINE_DOCTRINE §3.8
audience_tags: []          # default `[]` = owner-only; widen explicitly
is_sensitive: false
tags:
  - record/meeting
  - project/acme-payments
  - person/ivan-petrov
---
```

Record-формат минимален: нет `types`, `domains`, `contains`, `status`, `priority`.
Только кто, когда, о чём, откуда. **Concepts** — открытый словарь
семантических якорей в snake_case ASCII (см. слой ниже).
**Privacy trio** (`origin` / `audience_tags` / `is_sensitive`) на
каждой entity; defaults conservative-safe.

### Frontmatter: Knowledge Note

```yaml
---
id: 20260330-decision-api-platform-payload-design
title: "Решение: структура request payload в API v2"
created: 2026-03-30
modified: 2026-03-30
source: _sources/processed/plaud/2026-03-30T18:45:23Z/transcript_with_summary.md
extracted_from: 20260330-meeting-ivan-api-platform-status

layer: knowledge
types:
  - decision
  - technical
domains:
  - work
projects:
  - acme-payments
people:
  - ivan-petrov
concepts:                  # canonical concept names per CONCEPT_NAMING.md
  - api_v2_design
  - request_payload_design

contains:
  tasks: 0
  meetings: 0
  ideas: 0
  reflections: 0

status: reference
priority: normal

# Privacy trio per ENGINE_DOCTRINE §3.8 — defaults conservative-safe
origin: work
audience_tags: []
is_sensitive: false

tags:
  - type/decision
  - type/technical
  - domain/work
  - project/acme-payments
  - person/ivan-petrov
  - topic/api
  - topic/architecture
---
```

Поле `extracted_from` указывает на record, из которого был извлечён инсайт.
Для knowledge notes, созданных напрямую из личных транскриптов, это поле отсутствует.

### Frontmatter: Hub

```yaml
---
id: hub-api-platform
title: "Hub: API v2 платформы"
created: 2026-01-15
modified: 2026-03-30

layer: hub
domains:
  - work
projects:
  - acme-payments
people:
  - ivan-petrov
  - anna-smirnova

# Privacy trio — auto-derived from members via
# `_common.py::recompute_hub_trio()`. Hub frontmatter does NOT carry
# `concepts:` — `member_concepts[]` is manifest-only, derived at
# emission time from member knowledge notes.
origin: work
audience_tags: []
is_sensitive: false

tags:
  - hub
  - project/acme-payments
  - topic/api
  - topic/p2p
---
```

### log_process.md — хронологический лог операций

Каждый запуск `/ztn:process` создаёт запись в `_system/state/log_process.md`
(параллельные лог-файлы: `log_maintenance.md` для `/ztn:maintain` +
`/ztn:bootstrap`, `log_lint.md` для `/ztn:lint`):

```markdown
## 2026-03-30 — Processing Run

**Source files:** 3
**Records created:** 2
**Knowledge notes created:** 1
**Knowledge notes extracted:** 1
**Hubs updated:** 1 (hub-api-platform)
**Hubs created:** 0
**People updated:** 2 (ivan-petrov, anna-smirnova)

### Details
- plaud/.../2026-03-30T18:45:23Z → record: 20260330-meeting-ivan-api-platform-status
  + extracted: 20260330-decision-api-platform-payload-design
  + hub update: hub-api-platform
- plaud/.../2026-03-30T14:22:11Z → record: 20260330-meeting-olga-qa-status
- superwhisper/.../2026-03-30_evening-reflection → knowledge: 20260330-reflection-energy-management
```

LOG.md — append-only. Не переписывается, не очищается. Новые записи добавляются в начало.

---

## 8 принципов обработки

Принципы управляют всеми решениями при обработке транскриптов.
Полная спецификация: **`5_meta/PROCESSING_PRINCIPLES.md`** (source of truth).

**Краткий перечень:**
1. Capture First, Filter Never — всё с намерением фиксируется
2. Importance Gradient — вес определяется форматом, не фильтрацией
3. Connection Awareness — каузальные, эволюционные, структурные связи
4. Cross-Domain Permeability — порог ~30% для кросс-доменных связей
5. Evolution Tracking — накопление, не дедупликация
6. Action vs Knowledge — dual-nature items фиксируются дважды
7. People — низкий порог фиксации преднамеренных упоминаний
8. Preserve Texture and Narrative — эмоции, цитаты, нарратив

**Enhanced Decision Tracking (ADR-013):** Решения фиксируются с alternatives considered,
who decided, scope (final/tentative), supersedes. Implicit consensus detection включён.
Подробности: `5_meta/PROCESSING_PRINCIPLES.md`.

---

## Обработка транскриптов

> **Примечание:** Нумерация шагов ниже — концептуальная (для объяснения архитектуры).
> Точная нумерация executable pipeline: SKILL.md (`/ztn:process`), Steps 0-6.

### Процесс детерминирован. Суждения — нет.

Шаги обработки выполняются в фиксированном порядке (pipeline).
Но *все решения внутри шагов* — классификация, разбиение, определение связей,
обнаружение хабов — принимаются LLM, а не детерминированными правилами.

**Почему:** Правила хрупки. «Если > 2 тем → разбить» не работает, потому что темы
могут быть переплетены. «Если упоминается проект → тег project/X» не работает,
потому что упоминание может быть контекстом, а не принадлежностью.
Opus-level LLM справляется с этими нюансами лучше, чем любая система правил.

**Качество обеспечивается** adversarial source audit (шаг 9) — независимой
перечиткой исходного транскрипта после создания заметок, которая выявляет
пропущенные факты (MISSED), искажения (DISTORTED) и галлюцинации (HALLUCINATED).

### Маппинг 1:N

Один транскрипт может произвести:
- 0-1 record (для рабочих встреч)
- 0-N knowledge notes (по числу атомарных инсайтов)
- 0-N hub updates (по числу затронутых тем)
- 0-N hub creations (когда тема накопила 3+ упоминаний)

### Pipeline обработки (v4.4)

Источники обрабатываются **последовательно**, один за другим (ADR-012).
Никакой batch-группировки по темам — каждый транскрипт проходит полный pipeline,
а контекст (созданные заметки, обновлённые хабы) передаётся следующему.

```
                    ┌─────────────────────┐
                    │  0. PRE-SCAN        │
                    │  People Resolution  │
                    │  Map (three-tier)   │
                    │  ADR-011            │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  1. LOAD CONTEXT    │
                    │  registries, hubs,  │
                    │  related notes,     │
                    │  existing ZTN       │
                    │  knowledge (ADR-017)│
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  2. READ SOURCE     │
                    │  transcript +       │
                    │  summary (if any)   │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  3. LLM NOISE GATE  │
                    │  Is this processable│
                    │  content? (ADR-016) │
                    │  Skip: silence,     │
                    │  ambient, no signal │
                    └─────────┬───────────┘
                              │ (pass)
                    ┌─────────▼───────────┐
                    │  4. CLASSIFY        │
                    │  work meeting?      │
                    │  personal? mixed?   │
                    └─────────┬───────────┘
                              │
                 ┌────────────┼────────────┐
                 │            │            │
      ┌──────────▼─┐  ┌──────▼────┐  ┌────▼──────────┐
      │ Work mtg   │  │ Personal  │  │ Mixed         │
      │ → Record   │  │ → Knowl.  │  │ → Record +    │
      │ + extract? │  │ notes     │  │   Knowledge   │
      └──────┬─────┘  └─────┬─────┘  └──────┬────────┘
             │              │               │
             └──────────────┼───────────────┘
                            │
                  ┌─────────▼──────────┐
                  │  5. ATOMIZE        │
                  │  Split into        │
                  │  atomic notes      │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │  6. CROSS-DOMAIN   │
                  │  Scan for links    │
                  │  to other domains  │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │  7. HUB DETECTION  │
                  │  3+ mentions →     │
                  │  create hub.       │
                  │  Existing hub →    │
                  │  update.           │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │  8. WRITE          │
                  │  Records, notes,   │
                  │  hubs, profiles,   │
                  │  registries, LOG   │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │  9. ADVERSARIAL    │
                  │  SOURCE AUDIT      │
                  │  Independent       │
                  │  re-read (ADR-010) │
                  └─────────┬──────────┘
                            │
                  ┌─────────▼──────────┐
                  │ 10. VERIFY         │
                  │  Integrity check   │
                  └────────────────────┘
```

**Sequential processing с context handoff:** Когда обрабатывается batch из N
транскриптов, каждый проходит полный pipeline. Результаты предыдущего (созданные
записи, обновлённые хабы, новые люди) доступны следующему. Это обеспечивает
корректную дедупликацию и эволюцию знания внутри одного сеанса обработки.

### Шаг 0: Pre-Scan — People Resolution Map (ADR-011)

Перед основным pipeline выполняется предварительное сканирование ВСЕХ новых
транскриптов для резолвинга людей. Трёхуровневый подход:

| Tier | Условие | Действие |
|------|---------|----------|
| RESOLVED | Однозначное совпадение с PEOPLE.md (имя, алиас) | Использовать существующий ID. Обязательно для всех файлов |
| NEW | Нет совпадения, достаточно контекста для профиля | Назначить canonical ID. Обязательно для всех файлов |
| AMBIGUOUS | Может совпадать с несколькими людьми | Отложить до Step 3.3 (полный контекст транскрипта) |

People Resolution Map — живой и мутабельный: новые люди, обнаруженные при
обработке, добавляются немедленно для консистентности последующих файлов.
Передаётся во все последующие шаги.

### Шаг 1: Load Context

Перед обработкой транскрипта система загружает:

1. **Registries:** PEOPLE, PROJECTS, TAGS, HUBS — для entity matching
2. **Hub index** (`_system/views/HUB_INDEX.md`) — для hub detection
3. **Related notes:** если транскрипт упоминает проект/человека — загружаем
   последние 2-3 заметки по этой теме для контекста эволюции
4. **PROCESSED.md** — чтобы не обработать дважды
5. **Existing ZTN knowledge** (ADR-017) — релевантные knowledge notes и hubs,
   чтобы LLM мог отличить *новый* инсайт от *повторения* уже известного

**Зачем:** Контекст позволяет LLM определить: это *новый* инсайт или *развитие*
существующего? Нужен новый hub или достаточно обновить существующий?
Загрузка существующих знаний предотвращает создание дубликатов и позволяет
точнее определять эволюцию мышления.

### Шаг 2: Read Source

Два формата:
- `transcript_with_summary.md`: разделён `<transcript_to_summary_delimiter>`.
  Часть до — raw transcript (остаётся в `_sources/`). Часть после — LLM-summary
  (используется как подсказка для классификации, не как source of truth).
- `transcript.md`: только raw transcript.

### Шаг 3: LLM Noise Gate (ADR-016)

LLM оценивает, содержит ли транскрипт обрабатываемый сигнал.
Не line-count эвристика — семантическая оценка.

**Skip (не обрабатывать):**
- Тишина, фоновый шум, случайная активация записи
- Бессодержательный smalltalk без единого факта, решения или мысли
- Дубликат уже обработанного источника

**Pass (обрабатывать):**
- Любой транскрипт с хотя бы одним значимым фактом, решением или мыслью
- Inclusion bias: при сомнении — pass. Лучше шумная заметка, чем потерянный факт

Noise-gated файлы НЕ записываются в PROCESSED.md (ADR-022): они остаются «новыми»
и переоцениваются при каждом запуске. Это позволяет подхватить файл, если контент
был добавлен позже.

### Шаг 4: Classify

LLM определяет тип источника:
- **Work meeting** → record + optional knowledge extraction
- **Personal** (рефлексия, терапия, идея, размышление) → knowledge notes directly
- **Mixed** (рабочая встреча с личным/карьерным контекстом) → record + knowledge notes

### Шаг 5: Atomize

Ключевой шаг. LLM разбивает содержимое на атомарные единицы:

**Для record:** не разбивает. Record — цельный документ.

**Для knowledge:** каждая *самодостаточная* мысль становится отдельной заметкой.
- Одна терапевтическая сессия (1 час, 4 темы) → 4 knowledge notes
- Одна рабочая встреча с архитектурным решением → 1 record + 1 knowledge note
- Одно размышление на прогулке → 1-2 knowledge notes

**Primary note:** когда из одного транскрипта создаётся N knowledge notes,
все они ссылаются на исходный транскрипт через `source:` в frontmatter.
Первая (наиболее близкая к основной теме транскрипта) считается primary.
Остальные ссылаются на неё через `related_to:` в frontmatter (аналогично `extracted_from` и `supersedes`).

### Шаг 6: Cross-Domain Scan

Для каждой knowledge note LLM проверяет: есть ли здесь что-то,
что меняет понимание в другом домене?

Порог ~30%: если *может* быть релевантно — фиксируем связь.

Результат: дополнительные `[[wikilinks]]` и hub updates в неочевидных местах.

### Шаг 7: Hub Detection

Два сценария:

**Обновление существующего хаба:**
- Загружаем текущее состояние хаба
- Добавляем новые записи в хронологическую карту
- *Перезаписываем* «Текущее понимание» с учётом новой информации
- Добавляем запись в Changelog

**Создание нового хаба:**
- Проверяем hub index: тема встречается 3+ раз в knowledge notes
- Если порог достигнут — создаём хаб, заполняем все 4 секции
- Добавляем в `_system/views/HUB_INDEX.md`

### Шаг 8: Write

Всё записывается атомарно: records, knowledge notes, hub updates, profile updates,
registry updates, LOG.md entry, PROCESSED.md entry.

### Шаг 9: Adversarial Source Audit (ADR-010)

Независимая перечитка исходного транскрипта после создания всех артефактов.
LLM получает *только* исходник и список созданных заметок, и проверяет три категории:

- **MISSED** — факт/решение/задача/упоминание человека есть в источнике, но отсутствует в заметках
- **DISTORTED** — факт присутствует, но искажён (перепутаны участники, неточная формулировка)
- **HALLUCINATED** — в заметках есть информация, которой нет в источнике

Найденные проблемы исправляются *в этом же проходе*. Это quality gate,
не optional step. Принцип inclusion bias: лучше шумный факт, чем пропущенный.

### Шаг 10: Verify

Integrity check:
- Все entity references резолвятся
- Frontmatter валиден
- Файлы на месте
- PROCESSED.md обновлён

### Автоматический режим с non-blocking human-in-the-loop

Обработка автоматическая — не блокируется на неясностях. Вместо остановки pipeline
используется **CLARIFICATIONS.md** (ADR-014): если LLM не может уверенно
идентифицировать человека, определить контекст решения, или разрешить неоднозначность —
он записывает вопрос в `_system/state/CLARIFICATIONS.md` и продолжает с лучшей гипотезой.

**Почему:** Friction kills adoption. Если каждый транскрипт требует ручной проверки,
система умирает на второй неделе. Автоматический режим принимает *noise* как цену
за *completeness*. Noise устраняется периодическими sweep-операциями и post-processing
коррекциями (см. ниже).

**Post-processing corrections:** Пользователь периодически просматривает
CLARIFICATIONS.md и отвечает на вопросы. LLM применяет ответы — обновляет заметки,
профили, хабы. Это non-blocking: система работает и без ответов, но становится
точнее с каждым ответом.

---

## Hub-заметки (Maps of Content)

### Шаблон хаба

```markdown
---
id: hub-{topic}
title: "Hub: {Тема}"
created: YYYY-MM-DD
modified: YYYY-MM-DD

layer: hub
domains:
  - {domain1}
  - {domain2}
projects:
  - {project-id}
people:
  - {person-id}

tags:
  - hub
  - topic/{topic}
  - domain/{domain}
---

> **Примечание:** Упрощённый пример. Полная спецификация hub frontmatter (с `aliases`, `hub_created`,
> `related_notes`, `first_mention`, `last_mention`, `cadence`, `status`, `priority`)
> — в `_system/docs/SYSTEM_CONFIG.md`.

# Hub: {Тема}

## Текущее понимание

[Перезаписывается при каждом обновлении.
Отражает *текущее* состояние знания по теме.
Написано от первого лица, как summary для будущего себя.
1-3 абзаца.]

### Ключевые выводы
- {вывод}

### Открытые вопросы
- {нерешённый вопрос}

### Активные риски
- {риск или блокер}

---

## Хронологическая карта

| Дата | Заметка | Тип | Что произошло |
|------|---------|-----|---------------|
| 2026-01-15 | [[record-id\|Title]] | record | Первое обсуждение |
| 2026-02-03 | [[note-id\|Title]] | decision | Выбрали подход X |
| 2026-03-10 | [[note-id\|Title]] | insight | Поняли, что X не работает |
| 2026-03-30 | [[record-id\|Title]] | record | Обсудили альтернативу Y |

---

## Связанные знания

### Решения
- [[note-id|Решение 1]] — почему выбрали X
- [[note-id|Решение 2]] — пересмотр в пользу Y

### Инсайты
- [[note-id|Инсайт 1]] — cross-domain связь с {другая тема}

### Cross-Domain связи
- [[note-id|Title]] — {связь с другим доменом}

---

## Changelog

| Дата | Что изменилось |
|------|---------------|
| 2026-03-30 | Добавлена альтернатива Y, текущее понимание обновлено |
| 2026-02-03 | Первоначальный выбор подхода X |
| 2026-01-15 | Hub создан, начальное понимание |
```

### Четыре секции хаба

1. **Текущее понимание** — *перезаписывается* при каждом обновлении. Это «что я знаю сейчас»,
   не «что я знал на момент создания». Написано от первого лица. Может содержать
   неуверенность и открытые вопросы.

2. **Хронологическая карта** — *append-only* таймлайн. Каждая связанная заметка (и record,
   и knowledge note) добавляется с датой и кратким «что произошло». Позволяет
   восстановить полную историю темы.

3. **Связанные знания** — организованные по типу (решения, инсайты, вопросы).
   Cross-domain связи здесь особенно ценны.

4. **Changelog** — как менялось «Текущее понимание». Самые последние записи вверху.
   Позволяет ответить на вопрос: «Как эволюционировало моё мышление по этой теме?»

### Почему один файл, а не два (evolving + structure)

Рассматривалась альтернатива: отдельный файл для «Текущего понимания» и отдельный
для хронологической карты. Отвергнута: один файл читается целиком, контекст не теряется.
Два файла требуют постоянного переключения.

---

## Примеры обработки

### Пример A: Тактическая рабочая встреча

**Источник:** Встреча с Иваном про API v2 платформы (30 минут, технический статус)

**Что создаётся:**

```
1. Record: _records/meetings/20260330-meeting-ivan-api-platform-status.md
   - Summary: Статус API v2, типизация связок, новые payment methods
   - Action items: 4 задачи
   - Упоминания: ivan-petrov, anna-smirnova

2. Hub update: 5_meta/mocs/hub-api-platform.md
   - Хронологическая карта: +1 запись (30.03 — статус тестирования)
   - Текущее понимание: обновлено (тесты покрыты, мелкие проблемы на стенде)

3. Knowledge extraction: 0-1
   - Если решение по структуре request payload значимое → 1 knowledge note
   - Если просто статус-апдейт → 0 knowledge notes
```

**Что НЕ создаётся:**
- Нет personal reflection
- Нет cross-domain links (чисто технический контекст)
- Нет нового хаба (hub-api-platform уже существует)

### Пример B: Сессия терапии (1 час, 4 темы)

**Источник:** Сессия с Татьяной — делегирование, отношения, energy management, выгорание

**Что создаётся:**

```
1. Knowledge notes: 4 штуки

   a) 20260330-reflection-delegation-trust.md (PRIMARY)
      → 2_areas/personal/reflection/
      Инсайт: делегирование как акт доверия, не слабости

   b) 20260330-reflection-relationship-boundaries.md
      → 2_areas/personal/relationships/
      related_to: 20260330-reflection-delegation-trust
      Инсайт: границы в отношениях как форма заботы

   c) 20260330-reflection-energy-management.md
      → 2_areas/personal/health/
      related_to: 20260330-reflection-delegation-trust
      Инсайт: физическая нагрузка как регулятор когнитивной энергии

   d) 20260330-insight-burnout-prevention-routine.md
      → 2_areas/personal/reflection/
      related_to: 20260330-reflection-delegation-trust
      Инсайт: предотвращение выгорания через рутину, не через отдых

2. Cross-domain: delegation insight → обновляет hub-api-platform
   «Я понял, что не делегирую техническое лидерство по P2P Матвею —
   это не вопрос его готовности, а моего доверия»
   + Связь: [[20260330-reflection-delegation-trust|Делегирование как доверие]]

3. Hub updates:
   - hub-career-promotion (если существует) — delegation → leadership growth
   - hub-delegation-pattern (если 3+ заметок — создаётся новый hub)

4. Record: НЕ создаётся (это не рабочая встреча)
```

### Пример C: Стратегическая встреча (работа + карьера)

**Источник:** Встреча с Василием — бюджет, SVIP, карьерный рост, PM-переход

**Что создаётся:**

```
1. Record: _records/meetings/20260330-meeting-vasily-budget-swip.md
   - Рабочая часть: бюджет, SVIP items, грузинские клиенты
   - Мимолётное упоминание грузинских клиентов → одна строка в record
     (не knowledge note, но поисково)

2. Knowledge note: 20260330-career-pm-transition-conversation.md
   → 2_areas/career/
   Карьерная часть: Иван подтвердил PM-трек, timeline обсуждён
   extracted_from: 20260330-meeting-ivan-budget-planning

3. Hub updates:
   - hub-restructuring (рабочая реструктуризация)
   - hub-career-promotion (PM transition update)

4. People:
   - vasily: +1 упоминание
```

**Ключевое:** «грузинские клиенты» — пример Принципа 1 (Capture First).
Мимолётное упоминание, но зафиксировано в record. Через полгода это может
стать связью с проектом локализации.

---

## Query → Compound паттерн

Когда пользователь задаёт вопрос по ZTN, и ответ требует синтеза из нескольких заметок,
результат может быть *сохранён обратно* в систему как новая knowledge note или hub.

```
Вопрос: "Как менялось моё понимание делегирования?"
    │
    ▼
Поиск: grep по тегам, людям, содержимому
    │
    ▼
Синтез: LLM агрегирует 7 заметок в связный ответ
    │
    ▼
Опционально: сохраняем как hub-delegation-evolution.md
```

**Когда сохранять:**
- Ответ синтезирует 3+ заметки
- Синтез содержит новый инсайт (не просто перечисление)
- Тема вероятно будет развиваться

**Когда НЕ сохранять:**
- Простой lookup: «Когда следующая встреча с Василием?»
- Перечисление без синтеза: «Все заметки про API v2»

---

## Lint и Sweep операции

Автоматическая обработка acceptance noise. Периодические sweep-операции
очищают систему, находят проблемы, улучшают связность.

### Виды sweep

| Операция | Частота | Что делает |
|----------|---------|-----------|
| **Contradiction scan** | Ежемесячно | Ищет заметки, которые противоречат друг другу. Не удаляет — помечает и предлагает reconciliation |
| **Orphan detection** | Ежемесячно | Заметки без входящих ссылок (кроме records). Предлагает связи или архивацию |
| **Stale claims** | Ежеквартально | Заметки с `status: actionable` старше 30 дней без обновлений. Предлагает переход в `waiting`/`archived` |
| **Missing cross-refs** | Ежемесячно | Заметки, которые упоминают тему хаба, но не связаны с ним |
| **Hub health** | Ежемесячно | Хабы без обновлений > 60 дней. «Текущее понимание» устарело? |
| **People completeness** | Ежеквартально | Профили людей без контекста (только упоминания). Предлагает дополнить |
| **Task hygiene** | Еженедельно | Задачи без дедлайна, дубликаты, завершённые но не отмеченные |

### Принципы sweep

- Sweep *предлагает*, не *выполняет*. Человек подтверждает.
- Sweep НЕ удаляет заметки. Только архивирует (`4_archive/`), помечает, или предлагает merge.
- Результаты sweep записываются в LOG.md.

### Correction mechanisms

**CLARIFICATIONS.md (ADR-014):** Non-blocking human-in-the-loop. Вопросы,
которые LLM не смог разрешить при обработке, записываются в `_system/state/CLARIFICATIONS.md`.
Пользователь отвечает в удобное время, LLM применяет ответы к существующим заметкам.

**Post-processing corrections:** После обработки пользователь может:
- Исправить ошибки идентификации людей
- Уточнить контекст решений
- Добавить пропущенные связи
LLM применяет коррекции, обновляя заметки, профили и хабы.

**Decision freshness check:** При sweep проверяется:
- Решения с `scope: tentative` старше 30 дней — предложить пересмотр или перевод в `final`
- Решения, которые были `superseded` — проверить, что новое решение действительно актуально
- Цепочки `supersedes` — не осталось ли «висящих» решений

**Расширенные sweep-операции (v4.2):**

| Операция | Частота | Что делает |
|----------|---------|-----------|
| **Decision freshness** | Ежемесячно | Tentative решения старше 30 дней, висящие supersedes-цепочки |
| **People completeness** | Ежеквартально | Профили без контекста, неразрешённые алиасы в PEOPLE.md |
| **Contradiction scan** | Ежемесячно | Заметки, противоречащие друг другу — reconciliation |
| **Orphan detection** | Ежемесячно | Knowledge notes без входящих ссылок — предложить связи |

---

## Генерализация

ZTN v4 спроектирован для одного пользователя, но архитектура допускает *калибровку*.

### Три уровня adoption

```
┌─────────────────────────────────────────────────────────────┐
│ Level 3: Full ZTN                                           │
│ Records + Knowledge + Hubs                                  │
│ Для: knowledge worker, лидер с множеством контекстов        │
│ "Второе сознание": синтез, эволюция, cross-domain           │
├─────────────────────────────────────────────────────────────┤
│ Level 2: Records + Knowledge extraction                     │
│ Для: IC, инженер, аналитик                                  │
│ "Что я решил и почему" — без хабов и cross-domain           │
├─────────────────────────────────────────────────────────────┤
│ Level 1: Records only                                       │
│ Для: менеджер, PM                                           │
│ "Что обсуждали на встрече с Петей?" — поисковый лог         │
└─────────────────────────────────────────────────────────────┘
```

### Values Profile

8 принципов обработки универсальны, но их *калибровка* — персональна.

**Текущий профиль и параметры калибровки:** `5_meta/PROCESSING_PRINCIPLES.md` (source of truth).

Архитектура допускает альтернативные профили. Пример — менеджер уровня 1:
```yaml
capture_threshold: high
atomization_depth: coarse
cross_domain_sensitivity: low
texture_preservation: minimal
hub_creation_threshold: high
action_bias: action-first
```

---

## Журнал решений

### ADR-001: Records отделены от Knowledge

**Контекст:** В v3 рабочие встречи хранились как полноценные knowledge notes
в `2_areas/work/meetings/`. С ростом базы (370+ заметок) шум рабочих встреч
(статус-апдейты, мелкие задачи, логистика) начал засорять knowledge graph.

**Решение:** Выделить Records в отдельный слой `_records/meetings/` с лёгким форматом.
Knowledge notes извлекаются из records только когда есть значимый инсайт.

**Альтернативы:**
- Оставить всё в PARA → noise в knowledge graph растёт линейно
- Автоматическая чистка → теряется context для поиска

**Следствие:** Два формата frontmatter. Record проще, knowledge — богаче.

### ADR-002: Hubs объединяют evolving + structure

**Контекст:** Рассматривались два варианта: (a) один файл с обеими секциями,
(b) два файла — evolving doc + chronological map.

**Решение:** Один файл. Контекст не теряется при чтении. Хронологическая карта
объясняет *почему* текущее понимание такое. Changelog показывает *эволюцию*.

**Альтернативы:**
- Два файла → переключение контекста, сложнее поддерживать
- Только evolving → теряется история

### ADR-003: Полная автоматизация (no human-in-the-loop)

**Контекст:** Friction kills adoption. Если каждый из ~5 транскриптов в день
требует ручной проверки, система умирает.

**Решение:** Полная автоматизация. Принимаем noise как цену за completeness.
Noise устраняется периодическими sweep-операциями.

**Альтернативы:**
- Manual review → friction → abandonment
- Semi-auto (review only edge cases) → edge case detection is itself unreliable

**Следствие:** Inclusion bias во всех 8 принципах. Better to over-capture.

### ADR-004: Все решения принимает LLM

**Контекст:** В v1-v2 были детерминированные правила (if > 2 topics → split;
if mentions project → tag). Правила хрупки и не обрабатывают нюансы.

**Решение:** Процесс (pipeline) детерминирован. Суждения (split/classify/link) — LLM.
Opus-level модели справляются с контекстно-зависимыми решениями лучше правил.

**Альтернативы:**
- Rules-based → brittle, can't handle nuance
- Hybrid (rules + LLM fallback) → complexity without benefit
- Human judgment → see ADR-003

### ADR-005: Inclusion-biased принципы

**Контекст:** Ложноотрицательные (пропущенный факт) хуже ложноположительных
(лишняя заметка). Пропущенный факт — навсегда потерянная связь.
Лишняя заметка — минута при sweep.

**Решение:** Все 8 принципов сдвинуты в сторону inclusion. Capture First (принцип 1),
30% cross-domain threshold (принцип 4), low people threshold (принцип 7).

**Альтернативы:**
- Precision-biased → misses cross-domain insights
- Balanced → in practice drifts toward precision (easier to not capture)

### ADR-006: Единая система (не две)

**Контекст:** Рассматривалась альтернатива: отдельная система для работы
и отдельная для личного. Проще, чище boundaries.

**Решение:** Одна система. Cross-domain insights (терапия → делегирование → работа)
ломаются на границе систем. Ценность ZTN — именно в кросс-доменных связях.

**Альтернативы:**
- Две системы → no cross-domain insights
- Shared search, separate storage → complexity without full benefit

### ADR-007: PARA + Records + Hubs

**Контекст:** Каждый слой обслуживает свой паттерн retrieval:
- Records: «Что обсуждали?» (operational lookup)
- Knowledge: «Что решили / поняли?» (conceptual retrieval)
- Hubs: «Как менялось понимание?» (synthesis & evolution)

**Решение:** Три слоя. PARA для knowledge, Records для operational logs, Hubs для synthesis.

**Альтернативы:**
- Only PARA → no clean separation of noise from signal
- Only flat notes → no synthesis layer
- Tags instead of layers → tagging doesn't change retrieval UX

### ADR-008: Karpathy LLM Wiki validates, мы расширяем

**Контекст:** Андрей Карпати описал трёхслойную LLM Wiki: raw feed → wiki articles →
topic pages. Концептуально совпадает с Records → Knowledge → Hubs.

**Решение:** Валидация архитектуры. ZTN расширяет модель Карпати:
- PARA structure (не flat wiki)
- 8 processing principles (explicit inclusion bias)
- People tracking с профилями
- Cross-domain detection с порогом 30%
- Values Profile для per-user calibration
- Hubs с evolution tracking (changelog)

Карпати описал *что*. ZTN описывает *как* и *с какими принципами*.

### ADR-009: Source link instead of `<details>`

**Контекст:** В ранних версиях полный транскрипт встраивался в заметку
через `<details>` (collapsible). Это раздувало файлы и дублировало источники.

**Решение:** Records и knowledge notes содержат секцию `## Source` со ссылкой
на файл в `_sources/processed/`. Полнотекстовый поиск — grep по `_sources/`.

**Следствие:** Заметки стали компактнее. Single source of truth для транскрипта.

### ADR-010: Adversarial Source Audit

**Контекст:** При автоматической обработке LLM может пропустить факты,
исказить формулировки или добавить информацию, которой нет в источнике.
Без проверки эти ошибки накапливаются.

**Решение:** После создания всех артефактов выполняется независимая перечитка
источника. LLM получает *только* исходник и список заметок, проверяет три категории:
MISSED, DISTORTED, HALLUCINATED. Найденные проблемы исправляются в этом же проходе.

**Альтернативы:**
- Не проверять → ошибки накапливаются, подрывают доверие к системе
- Проверять отдельным проходом позже → context lost, дороже

### ADR-011: Three-tier People Resolution Map

**Контекст:** Люди в транскриптах упоминаются по-разному: имя, фамилия, прозвище,
должность, отношение. Простой string matching по PEOPLE.md пропускает большинство.

**Решение:** Трёхуровневый резолвинг:
- **RESOLVED** — однозначное совпадение с PEOPLE.md (имя, alias). Binding: все файлы используют этот ID.
- **NEW** — нет совпадения, но контекста достаточно для создания профиля. Назначается canonical ID.
- **AMBIGUOUS** — может совпадать с несколькими людьми или неясная личность. Откладывается до Step 3.3 (полный контекст транскрипта).

People Resolution Map — живой и мутабельный: новые люди, обнаруженные при обработке,
добавляются немедленно для консистентности последующих файлов.

**Следствие:** PEOPLE.md расширен полем `aliases` для каждого человека.

### ADR-012: No batch strategy — always sequential

**Контекст:** Рассматривалась batch-обработка: группировка транскриптов по теме
перед обработкой (все встречи про API v2 обрабатываются вместе).

**Решение:** Всегда sequential. Каждый транскрипт проходит полный pipeline
отдельно. Результаты предыдущего (созданные записи, обновлённые хабы) доступны
следующему через context handoff.

**Альтернативы:**
- Topic grouping → требует pre-classification, ошибки в группировке каскадируются
- Parallel → потеря контекста между связанными транскриптами

**Следствие:** Pipeline проще, предсказуемее, debuggable.

### ADR-013: Enhanced Decision tracking

**Контекст:** Решения — один из самых ценных типов заметок, но в v4.0 они
фиксировались без контекста: что рассматривалось, кто решил, финальное ли решение.

**Решение:** Расширенная фиксация: alternatives considered, who decided,
scope (final/tentative), `supersedes:` для пересмотренных решений.
Implicit consensus detection для неявных решений.

**Следствие:** Decision freshness check в sweep-операциях.

### ADR-014: CLARIFICATIONS.md — non-blocking human-in-the-loop

**Контекст:** Полная автоматизация (ADR-003) означает, что LLM иногда
принимает решения с низкой уверенностью. Остановка pipeline — не вариант (friction).

**Решение:** LLM записывает неуверенные места в `_system/state/CLARIFICATIONS.md`,
продолжает с лучшей гипотезой. Пользователь отвечает асинхронно,
LLM применяет коррекции к существующим заметкам.

**Альтернативы:**
- Blocking HitL → friction → abandonment (ADR-003)
- Ignore uncertainty → silent errors accumulate
- Mark in notes → scattered, hard to review

### ADR-015: disable-model-invocation: false

**Контекст:** В v4.0 SKILL.md frontmatter содержал `disable-model-invocation: true`,
что блокировало вызов skill через `/ztn:process`.

**Решение:** Установить `disable-model-invocation: false` для нормального вызова.

### ADR-016: LLM noise gate

**Контекст:** Не все транскрипты содержат обрабатываемый сигнал.
Случайные активации записи, тишина, бессодержательный smalltalk.
Ранее фильтрация была по количеству строк — хрупкая эвристика.

**Решение:** LLM оценивает семантическое содержание транскрипта.
Inclusion-biased: при сомнении — обрабатывать. Noise-gated файлы
НЕ записываются в PROCESSED.md (ADR-022) — остаются «новыми» для переоценки.

**Альтернативы:**
- Line-count threshold → пропускает короткие но ценные записи
- Keyword matching → brittle, language-dependent

### ADR-017: Leverage existing ZTN knowledge

**Контекст:** При обработке нового транскрипта LLM не видел, что уже есть
в системе по этой теме. Результат: дубликаты, противоречия, пропущенная эволюция.

**Решение:** На шаге Load Context загружаются релевантные существующие
knowledge notes и hubs. LLM использует их для:
- Определения: новый инсайт или повторение
- Точного отслеживания эволюции мышления
- Избежания дублирования
- Обогащения связей

**Альтернативы:**
- Не загружать → дубликаты, нет awareness of evolution
- Загружать всё → context window overflow при 500+ notes

### ADR-018: Document Architecture Cleanup — Ownership Matrix

**Контекст:** Пять документов содержали пересекающийся контент без чёткого владения.
Принципы — в CONCEPT.md и PROCESSING_PRINCIPLES.md. Форматы — в CONCEPT.md и SYSTEM_CONFIG.md.
Pipeline — описан по-разному в трёх файлах.

**Решение:** Матрица ответственности:
- CONCEPT.md = человеческая документация (философия, архитектура, ADR). НЕ загружается SKILL.md.
- SYSTEM_CONFIG.md = runtime config (форматы, routing, типы). Загружается SKILL.md.
- PROCESSING_PRINCIPLES.md = guide для LLM-суждений. Загружается SKILL.md.
- SKILL.md = executable pipeline. Ссылается на файлы по путям, не инлайнит.

**Правило:** Один source of truth на концепт. Дубликаты заменяются указателями.

### ADR-019: `contains:` block made optional

**Контекст:** Блок `contains:` в frontmatter knowledge note (tasks: N, meetings: N, ideas: N,
reflections: N) — boilerplate в 80%+ случаев. Reflection note с reflections:1, остальное:0
не добавляет информации.

**Решение:** `contains:` опционален. Включать только когда заметка содержит tasks/ideas/meetings.

### ADR-020: POSTS.md as post-pipeline enrichment

**Контекст:** POSTS.md сканирование существовало в SKILL.md, но отсутствовало в pipeline
CONCEPT.md. Undocumented step.

**Решение:** POSTS.md — post-pipeline enrichment в post-processing, не core pipeline step.
Не влияет на создание заметок — это вторичное сканирование на идеи для контента.

### ADR-021: Hub threshold — 3+ knowledge notes

**Контекст:** Порог создания хабов «3+ упоминаний» был размытым. 3+ чего?

**Решение:** 3+ knowledge notes, затрагивающих тему. Records не считаются — они
операционные логи, не кристаллизованное знание. Тема, обсуждавшаяся на 10 стендапах
(10 records), но не породившая ни одного knowledge note, не создаёт hub.

### ADR-022: Noise gate does NOT write to PROCESSED.md

**Контекст:** SDD-v4.2 предполагал запись skipped файлов в PROCESSED.md с пометкой
`skipped: noise`. Это означает, что ошибочно пропущенный файл исключён навсегда.

**Решение:** Noise-gated файлы НЕ записываются в PROCESSED.md. Они остаются «новыми»
и переоцениваются при каждом запуске. Noise gate достаточно детерминирован для
действительно шумных файлов (low cost). Если пользователь добавит контент в ранее
пустую папку, он будет подхвачен.

### ADR-023: SDD-файлы удаляются после имплементации

**Контекст:** SDD-файлы (v4.0, v4.2, v4.3) — implementation guides, не operational документы.
После имплементации они не несут runtime-ценности.

**Решение:** SDD-файлы удаляются после успешной имплементации. Решения (ADR) живут
в CONCEPT.md, pipeline — в SKILL.md, конфигурация — в SYSTEM_CONFIG.md. SDD — временный
артефакт планирования.

### ADR-024: Content Potential field (updated ADR-027)

**Контекст:** Система хорошо создаёт заметки, но не помогает пользователю публиковать контент.
Из 319 заметок многие содержат потенциально публичные инсайты, но нет механизма их выявления.

**Решение:** Три optional поля в frontmatter knowledge notes:
- `content_potential: high|medium` — уровень потенциала для публикации
- `content_type: expert|reflection|story|insight|observation` — доминирующий тип заметки (single)
- `content_angle: string | [array]` — один или несколько углов/зацепок для потенциальных постов

Pipeline оценивает каждый knowledge stream на 14-м вопросе классификации (Q14).
Оценка inclusion-biased: при сомнении ставится `medium`. Фильтрация — задача `/ztn:check-content`.

**Альтернативы:**
- Отдельный тег `content/candidate` → менее выразительно (нет градации high/medium)
- Отдельный файл-тип для контент-кандидатов → оверинжиниринг, создаёт дублирование

### ADR-025: POSTS.md — published-only archive (updated ADR-027)

~~**Старое решение:** Разделить на POSTS.md + CONTENT_PIPELINE.md.~~

**Контекст:** CONTENT_PIPELINE.md дублировал информацию из frontmatter заметок.
Два файла (POSTS.md + CONTENT_PIPELINE.md) рассинхронизировались.

**Решение (ADR-027):** Убрать CONTENT_PIPELINE.md. Кандидаты живут в frontmatter заметок.
`/ztn:check-content` обнаруживает их динамически через grep.
POSTS.md — только опубликованные посты + content strategy.

### ADR-027: Content pipeline simplification

**Контекст:** Три артефакта (CONTENT_PIPELINE.md, POSTS.md с кандидатами, frontmatter)
хранили одни и те же данные, рассинхронизировались, создавали путаницу.

**Решение:**
1. Frontmatter = единственный source of truth для кандидатов (3 поля: potential, type, angle)
2. `content_type` — single value (доминирующий тип заметки), `content_angle` — string или array
   (одна заметка может порождать посты с разным фреймингом)
3. CONTENT_PIPELINE.md — удалён
4. CONTENT_OVERVIEW.md — автогенерируемый read-only обзор (кэш, не source of truth).
   Регенерируется при каждом `/ztn:check-content`. Даёт bird's-eye view тем и кластеров
5. POSTS.md — только published archive + content strategy
6. `/ztn:process` не обновляет внешние реестры — только ставит поля на заметках
7. `/ztn:check-content` при кластеризации индексирует multi-angle заметки в несколько тем

**Альтернативы content_angle:**
- Оба поля (type + angle) как массивы → проблема спаривания type↔angle
- Paired objects `{type, angle}` → тяжёлый YAML, усложняет pipeline
- ✅ Выбрано: type single + angle array — тип описывает заметку, углы описывают подачу

**Альтернативы обзору:**
- Без обзора → теряется bird's-eye view, пользователь не видит ландшафт
- Ручной registry → рассинхронизация (старая проблема)
- ✅ Выбрано: auto-generated read-only view — лучшее из обоих миров

### ADR-026: Ideas as living documents

**Контекст:** ~100 idea-файлов, многие дублируются по теме. Каждое упоминание идеи
создавало новый файл вместо обогащения существующего.

**Решение:** Idea notes — living documents. При обнаружении идеи в транскрипте:
1. Поиск существующей идеи (три сигнала: теги 40%, ключевые слова 35%, подпапка 25%)
2. При совпадении ≥80% — append `## Update YYYY-MM-DD` к существующей заметке
3. При 50-79% — создать новую + лог в CLARIFICATIONS.md
4. При <50% — создать новую как раньше

Поле `mentions: N` отслеживает количество упоминаний идеи.

**Отличие от Hub:** Hub = синтез по кросс-доменной ТЕМЕ. Idea = конкретный КОНЦЕПТ с эволюцией.

### ADR-027: Skill namespace `ztn:*`

**Контекст:** Скиллы ZTN назывались непоследовательно: `/process-notes`, `/ztn-recap`, `/ztn-search`.
Нет единого namespace для autocomplete и группировки.

**Решение:** Все ZTN-скиллы переименованы в `ztn:*` namespace:
- `/ztn:process` — обработка транскриптов (бывший `/process-notes`)
- `/ztn:recap` — session recap
- `/ztn:search` — поиск по базе
- `/ztn:check-content` — review контент-пайплайна (новый)

Все команды и скиллы (`ztn:recap`, `ztn:search`, `ztn:process`, `ztn:check-content`, `ztn:lint`, `ztn:maintain`, `ztn:bootstrap`, `ztn:capture-candidate`, `ztn:check-decision`, `ztn:regen-constitution`) глобально доступны из любой CWD — `integrations/claude-code/install.sh` симлинкает их в `~/.claude/{commands,skills}/`.

---

## Интеллектуальное наследие

ZTN v4 стоит на плечах нескольких систем и мыслителей:

### Niklas Luhmann — Zettelkasten (1951-1997)

**Что взято:**
- Разделение на literature notes (наши records) и permanent notes (наши knowledge notes)
- Атомарность: одна карточка = одна мысль
- Связи между карточками важнее иерархии

**Чем отличаемся:**
- Автоматическая экстракция permanent notes из literature notes (Луман делал вручную)
- Третий слой (hubs) для синтеза — у Лумана его не было явно
- Digital-native: wikilinks, frontmatter, full-text search

### Tiago Forte — PARA Method (2017)

**Что взято:**
- Четырёхчастная иерархия: Projects, Areas, Resources, Archive
- Actionability как принцип организации
- «Перемещение вниз» по мере снижения актуальности

**Чем отличаемся:**
- Records layer вне PARA (operational logs не вписываются)
- Hubs layer над PARA (synthesis notes)
- Processing principles (PARA не определяет, *как* создавать заметки)

### Nick Milo — Maps of Content (2020)

**Что взято:**
- MOC как hub, агрегирующий заметки по теме
- MOC создаётся, когда тема «набирает массу»

**Чем отличаемся:**
- Хабы содержат evolving «Текущее понимание» (не только ссылки)
- Changelog как явная секция (эволюция мышления)
- Автоматическое создание при пороге 3+ упоминаний

### Andy Matuschak — Evergreen Notes (2019)

**Что взято:**
- Concept-oriented, не source-oriented
- Заметки должны быть самодостаточны
- Titled as atomic claims

**Чем отличаемся:**
- Автоматическая экстракция (Matuschak ратует за ручное осмысление)
- Мы принимаем «автоматическое осмысление» как trade-off за adoption

### Andrej Karpathy — LLM Wiki concept (2025)

**Что взято:**
- Трёхслойная архитектура: raw feed → wiki articles → topic pages
- LLM как движок обработки, не человек
- Continuous processing (не batch)

**Чем расширяем:**
- PARA-структура вместо flat wiki
- 8 processing principles с inclusion bias
- People tracking с профилями и cross-references
- Cross-domain detection (30% threshold)
- Values Profile для per-user calibration
- Hubs с evolution tracking
- Sweep/lint операции для quality maintenance

---

## Scaling и будущее

### Пороги масштабирования

По мере роста базы некоторые механизмы потребуют адаптации:

| Порог | Механизм | Адаптация |
|-------|---------|-----------|
| **200+ people aliases** | People Resolution Map | Tier 1 поиск по PEOPLE.md станет медленным. Перейти на pre-built lookup dict или индекс |
| **50+ hubs** | Hub loading при обработке | Загружать только секцию «Текущее понимание», не весь hub. Остальное — по запросу |
| **500+ notes** | TASKS.md / CALENDAR.md | Инкрементальное обновление (append), не full rewrite. Архивация закрытых задач |
| **1000+ notes** | Curated links | Embedding layer становится критичным (см. ниже) |

### FTS + Embeddings

Текущая система полагается на *курируемые связи* (wikilinks, hubs, tags).
Это мощно для known-known retrieval: «Что я знаю про API v2?».
Но слабо для known-unknown: «Что ещё связано с делегированием, о чём я не думал?»

### Discovery layer (планируемая)

```
┌──────────────────────────────────────────────────────────────┐
│                     DISCOVERY LAYER                           │
│                                                               │
│  Curated links (current)     Embeddings (future)              │
│  [[wikilinks]]               Semantic similarity              │
│  hub references              "Notes like this one"            │
│  tag-based search            Fuzzy cross-domain discovery     │
│                                                               │
│  Known-known retrieval       Known-unknown retrieval          │
│  "Find my note about X"     "What else relates to X?"        │
└──────────────────────────────────────────────────────────────┘
```

**Embeddings complement, not replace, curated links.**
Wikilinks = explicit, deliberate connections. Embeddings = latent, discovered connections.

### Конкретный план

1. **Surface catalog (INDEX.md)** — `_system/views/INDEX.md`, авто-
   генерируется `_system/scripts/render_index.py` (запускается
   `/ztn:maintain` Step 7.6 + доступен напрямую). Покрывает knowledge
   (`1_projects` / `2_areas` / `3_resources`) + archive (`4_archive/`,
   маркер `[archived]`) + constitution (`0_constitution/{axiom,principle,
   rule}/`, маркер `tier N`) + hubs (`5_meta/mocs/`). Faceted by PARA
   (структурно), `domains:` (семантически), cross-domain (≥2 доменов).
   Surface-line discipline: одна строка на запись (`[[id]] — summary ·
   [domains] · date`). Detail живёт в специализированных индексах —
   `HUB_INDEX.md` (хабы) и `CONSTITUTION_INDEX.md` (axioms / principles /
   rules). Records и posts вне INDEX — у них свои pipeline. Это первая
   точка входа: читаешь INDEX → drill в нужную ноту или индекс. Karpathy-
   style navigation surface.
2. **FTS (Full-Text Search)** — grep + локальный поисковый MCP (qmd
   опционально). На текущем масштабе INDEX + grep достаточно.
3. **Embedding index** — каждая knowledge note + hub → embedding vector.
   При создании новой заметки: найти top-5 семантически близких.
   Предложить как связи при следующем sweep.
4. **Semantic query** — «Расскажи всё, что я знаю про leadership»
   использует и теги, и embeddings, и hub содержимое.

**Сейчас реализовано:** INDEX.md (1) + grep (2). Текущие 400+ заметок
управляемы через курируемые связи + INDEX. Embedding layer (3-4)
станет критичным при 1000+ заметок.

---

## Приложение: Record-формат (полный пример)

```markdown
---
id: 20260330-meeting-ivan-api-platform-status
title: "Встреча с Иваном: статус API v2 платформы"
created: 2026-03-30
source: _sources/processed/plaud/2026-03-30T18:45:23Z/transcript_with_summary.md

layer: record
people:
  - ivan-petrov
  - anna-smirnova
projects:
  - acme-payments
tags:
  - record/meeting
  - project/acme-payments
  - person/ivan-petrov
  - person/anna-smirnova
---

# Встреча с Иваном: статус API v2 платформы

## Summary

Обсудили статус тестирования API v2 платформы. Тесты покрыты в шлюзе и проксе,
идёт тестирование на стенде. Много мелких проблем — P2P достался в сложном состоянии.

## Ключевые пункты

- Иван начинает ходить на архитектуру — вторник 16:00 МСК
- На верхнем уровне API: P2P-атрибуты (тип трансфера, данные пейера, получателя)
- Внутри payment_details: способ оплаты (Card, Apple Pay, Samsung, Google, Network Token)
- Добавлена оплата по Token ID — и в P2P, и в e-com, и в API v1

## Решения

- Структура вложенности payment_details утверждена: P2P-атрибуты наверху, способы оплаты внутри

## Action Items

- [ ] Тестирование P2P на стенде → [[ivan-petrov]] ^task-p2p-testing
- [ ] Подготовить список типизированных связок ^task-typed-bindings
- [ ] Согласовать время архитектурных встреч (конфликт 15:00/16:00) ^task-arch-schedule
- [ ] Привлечь [[anna-smirnova]] к ревью спецификации ^task-anna-smirnova-review

## Упоминания людей

- [[ivan-petrov]] — основной исполнитель API v2 P2P
- [[anna-smirnova]] — ревью спецификации

---

## Evidence Trail

- 2026-03-30: original insight captured — source: `transcript_with_summary.md` (backfilled retroactively by /ztn:lint 2026-04-20; trail started post-v4.5)

## Source

Полный транскрипт: `_sources/processed/plaud/2026-03-30T18:45:23Z/transcript_with_summary.md`
```

## Приложение: Knowledge Note (полный пример)

```markdown
---
id: 20260330-reflection-delegation-trust
title: "Инсайт: делегирование как акт доверия, а не слабости"
created: 2026-03-30
modified: 2026-03-30
source: _sources/processed/superwhisper/2026-03-30_therapy-session/transcript.md

layer: knowledge
types:
  - reflection
  - insight
domains:
  - personal
  - work
projects: []
people:
  - tatyana
  - ivan-petrov

contains:
  tasks: 0
  meetings: 0
  ideas: 0
  reflections: 1

status: reference
priority: normal

tags:
  - type/reflection
  - type/insight
  - domain/personal
  - domain/work
  - person/tatyana
  - topic/delegation
  - topic/leadership
  - topic/trust
---

# Инсайт: делегирование как акт доверия, а не слабости

## Контекст

Сессия с Татьяной. Обсуждали, почему я не отпускаю техническое лидерство по P2P,
хотя Иван готов и способен.

## Ключевая мысль
^insight-delegation-trust

Делегирование — это не «я не справляюсь, поэтому отдаю», а «я доверяю тебе
это сделать». Разница в фрейминге: в первом случае я теряю контроль, во втором —
*выбираю* дать контроль.

> "Если ты не доверяешь человеку достаточно, чтобы отдать ему задачу целиком —
> вопрос не в задаче, а в доверии."

## Применение к работе

Конкретно с Иваном и API v2 платформы: я продолжаю микроменеджить архитектурные
решения, хотя он уже самостоятельно приходит к тем же выводам. Мой контроль —
не добавляет качества, а тормозит его рост.

## Связи

- [[hub-api-platform|API v2 P2P]] — контекст делегирования
- [[hub-career-promotion|Карьерный рост]] — delegation как leadership skill
- [[tatyana]] — терапевтический контекст

---

## Source

Полный транскрипт: `_sources/processed/superwhisper/2026-03-30_therapy-session/transcript.md`
```

## Приложение: Hub (полный пример)

```markdown
---
id: hub-api-platform
title: "Hub: API v2 платформы"
created: 2026-01-15
modified: 2026-03-30

layer: hub
domains:
  - work
projects:
  - acme-payments
people:
  - ivan-petrov
  - anna-smirnova

tags:
  - hub
  - project/acme-payments
  - topic/api
  - topic/p2p
---

# Hub: API v2 платформы

## Текущее понимание

API v2 платформы прошёл основную разработку и находится в фазе тестирования на стенде.
Архитектурно: P2P-атрибуты (тип трансфера, данные участников) живут на верхнем уровне,
способы оплаты (Card, Apple Pay, Token ID и т.д.) — внутри payment_details.

Иван ведёт это автономно, подключается к архитектурным встречам. Я осознал
(через терапию с Татьяной), что мой контроль здесь — не про качество, а про доверие.
Нужно отпустить.

### Ключевые выводы
- P2P-атрибуты наверху, payment methods внутри payment_details
- Иван ведёт автономно, тестирование на стенде

### Открытые вопросы
- Сколько ещё мелких проблем всплывёт на стенде?
- Готов ли Иван к полной автономии по этому направлению?

### Активные риски
- Масштабируемость при добавлении новых payment methods

---

## Хронологическая карта

| Дата | Заметка | Тип | Что произошло |
|------|---------|-----|---------------|
| 2026-01-15 | [[20260115-meeting-matvey-api2-kickoff\|Kickoff]] | record | Начало работы над API v2 P2P |
| 2026-02-03 | [[20260203-decision-payment-details-structure\|Структура]] | decision | Решили: P2P наверху, payment methods внутри |
| 2026-03-10 | [[20260310-meeting-matvey-api2-testing\|Тестирование]] | record | Тесты покрыты, переход к стенду |
| 2026-03-30 | [[20260330-meeting-ivan-api-platform-status\|Статус]] | record | Мелкие проблемы на стенде, Token ID добавлен |
| 2026-03-30 | [[20260330-reflection-delegation-trust\|Делегирование]] | insight | Cross-domain: доверие к Матвею |

## Связанные знания

### Решения
- [[20260203-decision-payment-details-structure|Вложенность payment_details]] — P2P наверху, способы оплаты внутри

### Инсайты
- [[20260330-reflection-delegation-trust|Делегирование как доверие]] — cross-domain из терапии

### Cross-Domain связи
- [[20260330-reflection-delegation-trust|Делегирование]] — терапия → рабочий контекст P2P

---

## Changelog

| Дата | Что изменилось |
|------|---------------|
| 2026-03-30 | Cross-domain инсайт: делегирование = доверие. Обновлено текущее понимание |
| 2026-03-30 | Статус тестирования, Token ID. Мелкие проблемы на стенде |
| 2026-03-10 | Тесты покрыты, переход к стендовому тестированию |
| 2026-02-03 | Архитектурное решение по структуре payment_details |
| 2026-01-15 | Hub создан. Начало работы над API v2 P2P |
```
