# Person Profile Template

ID format: `firstname-lastname` (транслит, lowercase). Фамилия ОБЯЗАТЕЛЬНА.

```markdown
---
id: firstname-lastname
name: "Имя Фамилия"
role: role-id
org: org-id
# Privacy trio. `origin` inherits from the record that first creates
# the profile (work-meeting → `work`; personal-context capture →
# `personal`). audience_tags ALWAYS `[]` — even a public colleague's
# profile aggregates owner-side context (mentions, opinions) that
# should not be re-shared without explicit widening. is_sensitive:
# true on people whose profile contains health / legal / personal-risk
# context. See _system/registries/AUDIENCES.md + ENGINE_DOCTRINE §3.8.
origin: {personal|work|external}
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
