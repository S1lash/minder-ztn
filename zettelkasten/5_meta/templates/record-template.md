# Record Template (Meeting)

Для **рабочих встреч** (multi-speaker). Для соло Plaud-записей —
см. `observation-record-template.md` (kind: observation).

## Frontmatter

```yaml
---
id: YYYYMMDD-meeting-{participants}-{topic}
title: "Встреча: {тема на языке оригинала}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md

layer: record
kind: meeting              # optional — отсутствие = meeting (backward compat). Для observation kind обязателен.
people:
  - person-id-1
  - person-id-2
projects:
  - project-id
tags:
  - record/meeting
  - project/{project}
  - person/{person}
---
```

## Content Structure

```markdown
# {Meeting Title}

## Summary
{2-3 предложения — суть встречи}

## Ключевые пункты
- {Каждый значимый пункт обсуждения}
- {Включая мимолётные упоминания — Принцип 1}

## Решения
- ✅ {Решение} — {почему выбрали это}

## Action Items
- [ ] {задача} → [[person-id]] ^task-{slug}
- [ ] {задача} ^task-{slug}

## Упоминания людей
- [[person-id]] — {роль в контексте встречи}

---

## Source

**Transcript:** `{relative path to _sources/processed/ file}`
**Recorded:** {timestamp from folder name}
**Duration:** {if available from transcript metadata}
```

### Особенности record-формата

- **Нет** `types`, `domains`, `contains`, `status`, `priority` — только `layer: record`
- **Нет** секций «Рефлексия», «Идеи», «Связи» — это knowledge-level content
- **Нет** `<details>` с полным транскриптом — оригинал живёт в `_sources/processed/`
- Секция `## Source` содержит ссылку на исходный файл для full-text search
- Если из record извлекается knowledge note, тот ссылается обратно:
  `extracted_from: {record-id}`
