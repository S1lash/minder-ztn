# Folder Registry

**Last Updated:** 2026-04-20

Структура папок системы и правила маршрутизации.

---

## Sources (input)

```
_sources/                             # ВСЕ сырые данные (внутри zettelkasten)
├── inbox/                            # Новые, необработанные файлы
│   └── {source-id}/                  # Whitelist active sources — _system/registries/SOURCES.md.
│                                     # Layout (flat-md | dir-per-item | dir-with-summary)
│                                     # и Skip Subdirs объявлены на row of source.
│                                     # Добавить новый source: /ztn:source-add.
└── processed/                        # Обработанные (зеркальная иерархия)
    └── {source-id}/{id}/...          # Mirrors inbox layout. Reference-подкаталоги
                                      # (Skip Subdirs) переезжают сюда после
                                      # консумации /ztn:bootstrap (например crafted/describe-me/).
```

---

## Zettelkasten Structure (output)

```
zettelkasten/
├── _sources/                     # Сырые данные (см. выше)
│
├── _records/                     # Слой 1: Records (операционная память)
│   ├── meetings/                 # Логи рабочих встреч (kind: meeting)
│   │   └── YYYYMMDD-meeting-{person}-{topic}.md
│   └── observations/             # Соло Plaud-транскрипты: reflection/idea/therapy (kind: observation)
│       └── YYYYMMDD-observation-{topic}.md
│
├── _system/                      # Системные файлы (Phase 4.75 layout, не для заметок)
│   ├── SOUL.md                   # identity + focus + working style
│   ├── TASKS.md                  # автогенерируемый список задач
│   ├── CALENDAR.md               # автогенерируемый календарь
│   ├── POSTS.md                  # реестр опубликованных постов
│   ├── docs/                     # платформенные документы (binding)
│   │   ├── SYSTEM_CONFIG.md      # runtime config
│   │   ├── ARCHITECTURE.md       # системный дизайн
│   │   ├── CONVENTIONS.md        # documentation style rules (binding)
│   │   ├── batch-format.md       # контракт batch формата
│   │   ├── constitution-capture.md  # global hook (symlinked from ~/.claude/rules/)
│   │   └── harness-setup.md      # per-machine install guide
│   ├── views/                    # авто-генерируемые представления (read-only)
│   │   ├── CONSTITUTION_INDEX.md    # registry активных principles
│   │   ├── constitution-core.md  # harness view (symlinked from ~/.claude/rules/)
│   │   ├── HUB_INDEX.md          # индекс всех hub-заметок
│   │   ├── CURRENT_CONTEXT.md    # live state snapshot
│   │   └── CONTENT_OVERVIEW.md   # автогенерируемый обзор контент-кандидатов
│   ├── state/                    # pipeline state (write-heavy)
│   │   ├── BATCH_LOG.md          # index batch-операций
│   │   ├── PROCESSED.md          # source → note маппинг
│   │   ├── CLARIFICATIONS.md     # human-in-the-loop вопросы от скиллов
│   │   ├── OPEN_THREADS.md       # незакрытые стратегические нити
│   │   ├── principle-candidates.jsonl  # append-only candidate buffer
│   │   ├── log_process.md        # хронологический лог /ztn:process
│   │   ├── log_maintenance.md    # append-only лог /ztn:maintain + /ztn:bootstrap
│   │   ├── log_lint.md           # append-only лог /ztn:lint runs
│   │   ├── log_agent_lens.md     # append-only лог /ztn:agent-lens runs
│   │   ├── agent-lens-runs.jsonl # машинный индекс agent-lens runs (one JSON per line)
│   │   ├── agent-lens-rejected/  # raw Stage 2 outputs (validator rejected)
│   │   ├── batches/              # полные batch-отчёты
│   │   └── lint-context/         # Lint Context Store: daily/ (30d rolling) + monthly/ (forever)
│   ├── agent-lens/               # agent-lens outputs (private, owner-only review)
│   │   └── {lens-id}/{date}.md   # one snapshot per run per lens
│   ├── scripts/                  # Python pipeline (см. scripts/README.md)
│   └── registries/               # реестры сущностей (schema-only после 4.75)
│       ├── TAGS.md               # реестр тегов
│       ├── SOURCES.md            # реестр источников
│       ├── AGENT_LENSES.md       # agent-lens registry + concept + lifecycle
│       ├── lenses/               # per-lens definitions
│       │   ├── _frame.md         # two-stage frame + validator rules
│       │   └── {lens-id}/        # one folder per lens
│       │       └── prompt.md     # required; companion *.md files allowed
│       └── FOLDERS.md            # этот файл
│
├── 0_constitution/               # Behavioural principles (Phase 4.5)
│   ├── CONSTITUTION.md           # root doc
│   ├── axiom/                    # Tier-1 axioms
│   ├── principle/                # Tier-2 principles
│   └── rule/                     # Tier-3 rules
│
├── 1_projects/                   # Активные проекты с дедлайнами
│   ├── PROJECTS.md               # реестр проектов (co-located since 4.75)
│   ├── career-promotion/
│   └── psp-router/
│
├── 2_areas/                      # Области ответственности
│   ├── work/
│   │   ├── company/              # Компания, оргструктура
│   │   ├── meetings/             # Встречи, совещания
│   │   ├── planning/             # Планирование, стратегия
│   │   ├── reflection/           # Рабочая рефлексия
│   │   ├── technical/            # Технические обсуждения
│   │   └── team/                 # Команда, люди, процессы
│   ├── career/                   # Карьерное развитие
│   └── personal/
│       ├── reflection/           # Рефлексия, мысли
│       ├── health/               # Здоровье
│       └── relationships/        # Отношения
│
├── 3_resources/                  # Ресурсы, справочники
│   ├── tech/
│   │   ├── ai-agents/            # AI, LLM, агенты
│   │   ├── architecture/         # Архитектура систем
│   │   ├── fintech/              # Финтех, PSP
│   │   └── payments/             # Платежные системы
│   ├── ideas/
│   │   ├── business/             # Бизнес-идеи
│   │   └── products/             # Продуктовые идеи
│   └── people/                   # Профили людей
│       └── PEOPLE.md             # реестр людей (co-located with profiles since 4.75)
│
├── 4_archive/                    # Архив завершённого
│
├── 5_meta/                       # Мета-система
│   ├── templates/                # Шаблоны заметок
│   ├── workflows/                # Воркфлоу
│   └── mocs/                     # Maps of Content
│
├── 5_skills/                     # Skills
│
└── 6_posts/                      # Опубликованный контент
```

---

## Routing Rules

### По типу (приоритет)

| Type | Folder |
|------|--------|
| project | 1_projects/{project-id}/ |
| meeting | 2_areas/work/meetings/ **[DEPRECATED — v3 only. New meetings → record type]** |
| planning | 2_areas/work/planning/ |
| technical + work | 2_areas/work/technical/ |
| technical + ideas | 3_resources/tech/ |
| idea + business | 3_resources/ideas/business/ |
| idea + product | 3_resources/ideas/products/ |
| idea (general) | 3_resources/ideas/ |
| reflection | 2_areas/personal/reflection/ |
| person | 3_resources/people/ |
| log | 2_areas/personal/ |
| record (kind: meeting) | _records/meetings/ |
| record (kind: observation) | _records/observations/ |
| hub | 5_meta/mocs/ |

### По домену (если тип неясен)

| Domain | Folder |
|--------|--------|
| work | 2_areas/work/ |
| career | 2_areas/career/ |
| personal | 2_areas/personal/ |

### По контенту (keywords)

| Keywords | Folder |
|----------|--------|
| RBS, PSP, команда, проект, релиз | 2_areas/work/ |
| повышение, зарплата, должность | 2_areas/career/ |
| AI, LLM, агенты, модели | 3_resources/tech/ai-agents/ |
| архитектура, система, дизайн | 3_resources/tech/architecture/ |
| платежи, эквайринг, карты | 3_resources/tech/payments/ |
| стартап, бизнес, монетизация | 3_resources/ideas/business/ |
| продукт, MVP, фича | 3_resources/ideas/products/ |

---

## Creating New Folders

1. Только если есть 3+ заметок для категории
2. Добавить в эту структуру
3. Использовать lowercase-with-dashes
4. Обновить routing rules
