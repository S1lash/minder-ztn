# Note Template

```markdown
---
id: YYYYMMDD-short-semantic-name
title: "Title на языке оригинала"
aliases:
  - alias1
  - alias2
created: YYYY-MM-DD
modified: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md
extracted_from: record-id  # optional — record-id of meeting or observation record this note was extracted from
related_to: primary-note-id  # optional — if not the primary note from a group
supersedes: previous-note-id  # optional — if this decision overrides a previous one

layer: knowledge

# Classification
types:
  - type1
  - type2
domains:
  - domain1
projects:
  - project-id
people:
  - person-id

# Content summary (OPTIONAL — include only when note has tasks/ideas/meetings)
# Omit entirely if all counts are 0 or if the only non-zero count is obvious from type.
# contains:
#   tasks: 0
#   ideas: 0

# Status
status: actionable|waiting|someday|reference|archived
priority: high|normal|low
# content_potential: high|medium  # OPTIONAL — set when note has public sharing value
# content_type: expert|reflection|story|insight|observation  # OPTIONAL — set with content_potential
# content_angle: "hook" or ["hook1", "hook2"]  # OPTIONAL — string or array of angle hooks
# mentions: N  # OPTIONAL — for idea notes, how many times this idea surfaced

# Tags
tags:
  - type/xxx
  - domain/xxx
  - project/xxx
  - person/xxx
---

# Title

## Ключевые мысли
- Мысль 1
- Мысль 2

## Задачи
- [ ] Задача 1 → [[связь]] ^task-id-1
- [ ] Задача 2 ^task-id-2

## Встречи / События
- 📅 **YYYY-MM-DD HH:MM** — Описание ^meeting-id

## Идеи
- 💡 Идея 1 ^idea-id-1

## Решения
- ✅ Решение 1

## Рефлексия
Текст...

## Связи
- [[note-id|Display Name]] — контекст
- [[person-id]] — роль

---

## Evidence Trail

- **{created-date}** | [[{source}]] — {что извлечено/подтверждено/опровергнуто/поставлено в 1-2 предложения}

---

## Source

**Transcript:** `_sources/processed/{source}/{timestamp}/transcript_with_summary.md`
**Recorded:** YYYY-MM-DDTHH:MM:SSZ
```
