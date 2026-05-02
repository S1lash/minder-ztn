# Person Profile Template

ID format: `firstname-lastname` (транслит, lowercase). Фамилия ОБЯЗАТЕЛЬНА.

```markdown
---
id: firstname-lastname
name: "Имя Фамилия"
role: role-id
org: org-id
# Privacy trio. Person profiles default to owner-only — even a public
# colleague's profile aggregates owner-side context (mentions, opinions)
# that should not be re-shared without explicit widening.
# See _system/registries/AUDIENCES.md + ENGINE_DOCTRINE §3.8.
origin: personal
audience_tags: []
is_sensitive: false
tags:
  - person/firstname-lastname
  - org/org-id
  - role/role-id
---

# Имя Фамилия

**Role:** Role @ Org

## Контекст
[Описание роли, отношений, важной информации]

## Ключевые темы
- Тема 1
- Тема 2

## Упоминания
- [[note-id|Описание контекста]]
```
