# Project Template

```markdown
---
id: project-id
title: "Project Name"
type: project
status: active|completed|on-hold
created: YYYY-MM-DD
deadline: YYYY-MM-DD
domains:
  - domain
# Concepts the project touches (snake_case per CONCEPT_NAMING.md).
# Owner-curated; do NOT include the project itself or its participants
# (those live in their own first-class fields).
concepts:
  - concept_name_1
# Privacy trio — pick `origin` matching the actual project context
# (work-employment project → `work`; personal side-project → `personal`;
# external/clipped → `external`). audience_tags default [] — widen
# explicitly when sharing intent is clear.
# See _system/registries/AUDIENCES.md + ENGINE_DOCTRINE §3.8.
origin: {personal|work|external}
audience_tags: []
is_sensitive: false
tags:
  - type/project
  - project/project-id
  - domain/domain
---

# Project Name

## Цель
[Описание цели проекта]

## Ключевые результаты
- [ ] KR1
- [ ] KR2
- [ ] KR3

## Прогресс
[Текущий статус и прогресс]

## Связанные заметки
- [[note-id|Description]]

## Ключевые решения
- [[decision-note|Decision 1]]

## Люди
- [[person-id]] — роль в проекте
```
