# Hub Template

## Frontmatter

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
  - {work|personal|career}
projects: []
people: []

# Hub privacy trio. Auto-derived by `_common.py::recompute_hub_trio()`
# from member-note trios on every /ztn:process and /ztn:maintain touch.
# `_engine_derived` enumerates fields the engine currently owns and
# re-derives. Owner takes over a field by removing its name from
# `_engine_derived`; engine then preserves the owner-set value
# permanently. `member_concepts[]` is NOT stored here — derived at
# manifest-emission time from member knowledge notes' `concepts:` lists.
# See _system/registries/AUDIENCES.md + ENGINE_DOCTRINE §3.8.
origin: {personal|work|external}
audience_tags: []
is_sensitive: false
_engine_derived:
  - origin
  - audience_tags
  - is_sensitive

related_notes: N
first_mention: YYYY-MM-DD
last_mention: YYYY-MM-DD
cadence: {daily|weekly|sporadic}

status: {active|dormant|resolved}
priority: {high|normal|low}

tags:
  - hub
  - domain/{domain}
  - topic/{topic}
---
```

## Content Structure

```markdown
# Hub: {Topic Name}

## Текущее понимание

{Living summary — текущее состояние знания по теме.
 Перезаписывается при КАЖДОМ обновлении.
 Написано от первого лица, как summary для будущего себя.
 1-3 абзаца. Может содержать открытые вопросы и неуверенность.}

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
| YYYY-MM-DD | [[note-id\|title]] | record/decision/insight | Что эта заметка добавила |

---

## Связанные знания

### Решения
- **YYYY-MM-DD**: [[note-id\|title]] — {почему выбрали это}

### Инсайты
- [[note-id\|title]] — {инсайт, не очевидный из отдельных заметок}

### Cross-Domain связи
- [[note-id\|title]] — {связь с другим доменом}

---

## Changelog

| Дата | Что изменилось |
|------|---------------|
| YYYY-MM-DD | {Как изменилось понимание и почему} |
```

### Четыре секции хаба

1. **Текущее понимание** — ПЕРЕЗАПИСЫВАЕТСЯ при каждом обновлении. «Что я знаю СЕЙЧАС».
2. **Хронологическая карта** — APPEND-ONLY таймлайн. Все связанные заметки с датами.
3. **Связанные знания** — Организованные по типу. Cross-domain связи особенно ценны.
4. **Changelog** — Как менялось «Текущее понимание». Newest first.
