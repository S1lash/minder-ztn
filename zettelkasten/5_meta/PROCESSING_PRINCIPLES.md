# ZTN v4 — 8 Принципов Обработки

**Версия:** 1.1
**Дата:** 2026-04-09

Эти принципы управляют ВСЕМИ решениями при обработке транскриптов.
Они — inclusion-biased: лучше захватить лишнее, чем потерять факт.

Принципы загружаются на шаге 1.2 pipeline и действуют на всех последующих шагах.
Они НЕ являются правилами маршрутизации — это ценностные ориентиры для LLM-суждений.

---

## 1. Capture First, Filter Never

Всё, что сказано с намерением (не оговорка, не повтор), фиксируется.
Не существует «слишком мелкого» факта — мелкие факты образуют кросс-доменные связи.

**Практика:**
- Мимолётное упоминание → строка в record (не отбрасывается)
- «Кстати, у грузинских клиентов тоже проблемы с этим API» — одна строка в Key Points,
  но именно она может создать связь с проектом локализации через полгода
- Сомневаешься, включать ли? Включай. Ложноположительные дёшевы (минута при sweep),
  ложноотрицательные — дороги (потерянная связь навсегда)

**Антипаттерн:** «Это мелочь, не буду записывать» — ЗАПРЕЩЕНО.

---

## 2. Importance Gradient — Weight, Don't Discard

Не всё захваченное одинаково важно. Вес определяется СТРУКТУРОЙ, а не фильтрацией:

| Уровень важности | Формат |
|-----------------|--------|
| Решение (выбор из альтернатив) | Отдельный Knowledge Note |
| Ключевая мысль / инсайт | Секция «Ключевые мысли» + возможно Knowledge Note |
| Факт / контекст | Строка в record Key Points |
| Мимолётное упоминание | Строка в record Key Points (не в knowledge) |

Градиент определяет ФОРМАТ, но НЕ фильтрацию. Мимолётное упоминание всё равно
попадает в record — просто не становится отдельной knowledge note.

**Антипаттерн:** Решить, что что-то «не достаточно важно» и пропустить совсем.

---

## 3. Connection Awareness

При обработке каждого транскрипта активно ищи связи трёх типов:

- **Каузальные:** это решение было принято ПОТОМУ ЧТО произошло то
- **Эволюционные:** эта мысль РАЗВИВАЕТ / ПРОТИВОРЕЧИТ предыдущей мысли
- **Структурные:** это принадлежит к ТОМУ ЖЕ домену / проекту / теме

Связи оформляются через:
- `[[wikilinks]]` в секции «Связи» knowledge notes
- Hub updates (хронологическая карта + текущее понимание)
- `extracted_from` в frontmatter (record → knowledge note)

**Практика:** При чтении транскрипта, держи в голове загруженный контекст (Step 3.3).
Каждый новый факт — проверяй: «Это подтверждает, развивает, или противоречит
чему-то, что я уже знаю?»

---

## 4. Cross-Domain Permeability

Самые ценные инсайты живут НА СТЫКЕ доменов. При обработке КАЖДОГО транскрипта
проверяй: есть ли здесь что-то, что меняет понимание В ДРУГОМ домене?

**Порог: ~30% уверенности.** Если мысль МОЖЕТ быть релевантна другому домену —
фиксируй связь. Ложноположительные дёшевы, ложноотрицательные — нет.

**Примеры cross-domain связей:**
- Терапевтический инсайт про делегирование → рабочий контекст (P2P, управление командой)
- Рабочее архитектурное решение → идея для личного проекта
- Карьерное размышление → влияние на подход к командным процессам

**Результат:** Дополнительные `[[wikilinks]]` и hub updates в неочевидных местах.

---

## 5. Evolution Tracking — Accumulate, Don't Deduplicate

Знание НАКАПЛИВАЕТСЯ, а не ДЕДУПЛИЦИРУЕТСЯ. Если в январе принято решение X,
а в марте то же решение изменено на Y — обе записи сохраняются.

Hub отслеживает эволюцию:
- «Текущее понимание» отражает ПОСЛЕДНЕЕ состояние (перезаписывается)
- «Changelog» показывает КАК мы сюда пришли (append-only)
- «Хронологическая карта» показывает ВСЕ точки на таймлайне (append-only)

**Антипаттерн:** «Это уже есть в заметке от января, не буду дублировать» —
НЕПРАВИЛЬНО. Новое упоминание может содержать новый контекст, эмоцию, или нюанс.
Зафиксируй его, hub-механизм покажет эволюцию.

---

## 6. Action vs Knowledge

Задачи и знания часто живут в одном предложении:
«Нужно переделать API, потому что текущая вложенность не масштабируется.»

**Dual-nature items фиксируются ДВАЖДЫ:**
- Action → `- [ ] Переделать API v2 — вложенность payment_details` (задача в record/note)
- Knowledge → «Текущая вложенность не масштабируется при добавлении новых способов оплаты»
  (инсайт → knowledge note или запись в hub)

Не выбирай одно. Фиксируй оба аспекта.

---

## 7. People — Capture Every Deliberate Mention

Каждое ПРЕДНАМЕРЕННОЕ упоминание человека фиксируется. Не только участники встречи,
но и люди, О КОТОРЫХ говорили.

**Три уровня:**
1. **Участник** → backlink в профиле + запись в record «Упоминания людей»
2. **Обсуждаемый** → backlink в профиле + контекст обсуждения
3. **Новый контекст** (роль, компетенция, отношения) → обновление профиля

**При обнаружении нового человека:**
- Создать профиль в `3_resources/people/{id}.md`
- Добавить в `3_resources/people/PEOPLE.md`
- Добавить тег `person/{id}` в `_system/registries/TAGS.md`

**Антипаттерн:** «Этот человек упомянут мимоходом, не буду добавлять» — ЗАПРЕЩЕНО
(если упоминание преднамеренное, а не оговорка).

---

## 8. Preserve Texture and Narrative

Транскрипты содержат ТЕКСТУРУ: эмоции, точные формулировки, метафоры,
нарративные арки. Это не шум — это контекст, который делает заметки ЖИВЫМИ.

**Что сохраняем в knowledge notes:**
- Прямые цитаты, если формулировка точнее пересказа (в формате `> "цитата"`)
- Эмоциональный контекст («был раздражён», «впервые почувствовал уверенность»)
- Метафоры и аналогии автора
- Нарративную арку (было → произошло → осознал → решил)

**Что НЕ сохраняем:**
- Речевые паразиты, повторы, заикания (артефакты транскрипции)
- Логистику встречи («давай перенесём на 15:00» — если нет контекста)

**В records:** текстура менее важна. Records = факты + решения + задачи.
Но если ключевая формулировка important — цитата допустима.

---

## 9. Project Tagging — Primary-Topic Only

`projects:` frontmatter array carries **one semantic only** — primary topic
of the record/note. The field does NOT carry umbrella context, peripheral
relevance, or graph-style backlinks; those signals already live in
`tags:` (`project/foo`), `concepts:`, `[[wikilinks]]` in body, and hub
`related_notes`.

### Definition of «primary»

A project is `primary` for a record if removing all references to that
project would make the record lose its core meaning. The test:

> «Если убрать упоминания этого проекта из записи — она теряет смысл?»

«Касается», «затрагивает», «упоминает» — НЕ primary. Only «*about*».

### Cardinality

- **Strict default:** exactly 1 element.
- **Boundary exception:** 2 elements ONLY when the record is a genuine
  cross-project decision/meeting (e.g., joint PSP↔Agentic Commerce
  roadmap review). Must be annotated in body with explicit
  «boundary case» language.
- **Never:** 3+ elements. The frontmatter `projects:` array is NEVER
  used as an «umbrella tag cloud».

`/ztn:lint` Scan A.X warns on any `projects.length > 2`, and on
`projects.length == 2` without `boundary` annotation in body.

### What goes elsewhere (not in `projects:`)

| Signal | Goes to |
|---|---|
| «record touches some-project peripherally» | `tags: [project/some-project]` |
| «record discusses an abstract concept relevant to a project» | `concepts: [...]` |
| «specific reference / dependency on another note about a project» | `[[wikilink]]` in body |
| «cross-hub connection between two distinct project topics» | hub frontmatter `related_notes` or hub body «Cross-Domain связи» |

### Hub kinds: project vs trajectory vs domain

Hubs have different semantic types. The `hub_kind:` frontmatter field
distinguishes them:

| `hub_kind:` | What it represents | `projects:` axis member? |
|---|---|---|
| `project` (default) | Concrete project with deliverables (a real shipping product or work stream) | yes — records use `projects: [proj-id]` for primary topic |
| `trajectory` | Personal arc / multi-year theme (career arc, learning trajectory) | NO — records use `tags: [trajectory/{slug}]`; `projects:` reserved for actual projects |
| `domain` | Broad knowledge area (database reliability, leadership patterns) | NO — records use `domains: [...]` and `tags:` |

### Why this matters

- Hub `## Хронологическая карта` is a **derived view**: every record where
  this hub's project is `primary` belongs in the map. With strict
  semantics, hub-completeness becomes an invariant, not a metric.
- Lint scan can detect drift at write-time, not via post-factum audits.
- Cross-project search still works through `tags:` axis (umbrella) without
  polluting primary-classifier semantics.

### Migration & enforcement

- `/ztn:process` projects-extraction prompt enforces primary-only at write.
- `/ztn:lint` Scan A.X catches drift in existing records.
- `/ztn:process --reprocess-corpus` re-derives `projects:` arrays for the
  corpus when the prompt strict-semantic changes (rare).

> **See also:** `_system/docs/ARCHITECTURE.md` §«Hub kinds» and
> `_system/registries/PROJECTS.md` for the project-vs-trajectory list.

---

## Enhanced Decision Tracking (ADR-013)

Решения — один из самых ценных типов knowledge notes. При фиксации решений
записываются дополнительные атрибуты:

- **Alternatives considered** — какие варианты рассматривались и почему отвергнуты
- **Who decided** — кто принял решение (и кто повлиял)
- **Scope** — `final` (окончательное) или `tentative` (предварительное, может измениться)
- **`supersedes:`** — если решение пересматривает предыдущее, ссылка на заменяемую заметку

**Implicit consensus detection:** Не все решения оформляются словами «мы решили».
LLM должен распознавать неявные решения: когда участники обсуждают варианты
и переходят к следующей теме, молчаливо согласившись на один из них. Такие решения
фиксируются с пометкой `decision_style: implicit_consensus`.

**Decision markers to scan for:**
- Explicit: «решили», «договорились», «будем делать», «выбрали», «утвердили», «отложили», «пока так», «по итогу»
- Implicit: repeated agreement, lack of objection, "ну давай так и сделаем", default acceptance

---

## Values Profile (калибровка)

Принципы универсальны, но их ИНТЕНСИВНОСТЬ — персональна. Каждый
инстанс ZTN определяет свой профиль в `_system/SOUL.md` (секция
`## Working Style` / `## Values`). Если профиль не задан — действуют
дефолты ниже.

### Параметры профиля

```yaml
capture_threshold: low | medium | high   # порог захвата сигнала
atomization_depth: fine | coarse         # дробить ли инсайты атомарно
cross_domain_sensitivity: low|med|high   # threshold для cross-domain связей
texture_preservation: rich | minimal     # цитаты/эмоции/нарратив или сухо
hub_creation_threshold: low | high       # сколько notes по теме → hub
action_bias: knowledge-first | task-first
```

### Дефолты (если в SOUL.md не указано)

```yaml
capture_threshold: low        # Capture First, Filter Never
atomization_depth: fine       # один инсайт = один note
cross_domain_sensitivity: high # 30% threshold
texture_preservation: rich    # цитаты, эмоции, нарратив
hub_creation_threshold: low   # 3+ knowledge notes по теме → hub
action_bias: knowledge-first  # знания важнее задач
```

Дефолты оптимизированы под НАКОПЛЕНИЕ и СВЯЗИ, а не task management.
Задачи фиксируются, но не являются главной ценностью.
