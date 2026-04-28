# Observation Record Template

Для соло-транскриптов (personal-reflection / idea-brainstorm / therapy).
Якорь, к которому привязываются knowledge notes через `extracted_from:` и Evidence Trail.

## Frontmatter

```yaml
---
id: YYYYMMDD-observation-{topic-slug}
title: "Наблюдение: {тема на языке оригинала}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript_with_summary.md
recorded_at: {ISO timestamp from folder name when known}

layer: record
kind: observation
speaker: {person-id владельца базы из SOUL.md Identity; "unknown" если неизвестно}
people:
  - {любой упомянутый по имени}
projects:
  - {проекты, если затронуты}
tags:
  - record/observation
  - person/{speaker}
  - topic/{key-topic}
---
```

## Content Structure

```markdown
# {Observation Title}

## Summary
{2-3 предложения — суть записи}

## Ключевые пункты
- {Каждый значимый пункт — Принцип 1: Capture First}
- {Включая мимолётные упоминания}

## Контекст / настроение
{Опционально: где/когда записывалось, эмоциональный фон, триггер.
 Опускать если не существенно. Примеры: «в машине после встречи с Димой»,
 «после терапии», «утром, перед стендапом»}

## Упоминания людей
{Опционально, только если назывались имена}
- [[person-id]] — {роль / контекст в этой записи}

---

## Source

**Transcript:** `{relative path to _sources/processed/ file}`
**Recorded:** {timestamp from folder name}
**Duration:** {if available}
```

## Особенности

- `kind: observation` — обязательно в frontmatter (отличает от `kind: meeting`)
- `speaker:` — обязательное поле (одно лицо, не список — отличие от `people:` в meeting)
- **Нет** `## Решения` / `## Action Items` — эти секции живут в knowledge notes,
  которые ссылаются на этот record через `extracted_from:`
- **Нет** `<details>` с полным транскриптом — оригинал в `_sources/processed/`
- Knowledge notes, извлечённые из этого record:
  - `extracted_from: {observation-record-id}` в frontmatter
  - `## Evidence Trail` содержит `[[{observation-record-id}]]`
