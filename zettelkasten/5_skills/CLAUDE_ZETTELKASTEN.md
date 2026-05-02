---
id: claude-zettelkasten
title: 'Claude Code: Zettelkasten Quick Reference'
created: 2025-01-01
tags:
- type/reference
- topic/zettelkasten
- topic/claude-code
modified: '2026-04-26'
---

# Claude Code: Zettelkasten Quick Reference

---

## При каждом вызове /ztn:process

### Обязательно прочитать:

```
1.  _system/docs/SYSTEM_CONFIG.md         ← Runtime config (форматы, routing, типы)
2.  5_meta/PROCESSING_PRINCIPLES.md  ← 8 принципов обработки + values profile
3.  _system/SOUL.md                  ← Identity + Current Focus + Working Style
4.  _system/views/CURRENT_CONTEXT.md       ← Live state — что актуально сейчас
5.  _system/state/OPEN_THREADS.md          ← Незакрытые стратегические нити
6.  3_resources/people/PEOPLE.md     ← Реестр людей (Tier/Mentions/Last)
7.  1_projects/PROJECTS.md   ← Реестр проектов
8.  _system/registries/TAGS.md       ← Реестр тегов
9.  _system/registries/CONCEPT_NAMING.md   ← Concept-name format spec (autonomous resolution)
10. _system/registries/AUDIENCES.md        ← `audience_tags` whitelist (canonical 5 + extensions)
11. _system/views/HUB_INDEX.md             ← Индекс хабов
12. _system/views/INDEX.md                 ← Content catalog (knowledge + hubs, faceted)
13. _system/state/PROCESSED.md             ← Что обработано
14. _system/state/CLARIFICATIONS.md        ← Pending clarifications
```

### Pipeline (Steps 0-6):

```
0. Pre-Scan — People Resolution Map + Hub Signal Matching
1. Load Context — system files (see above)
2. Find New Files — scan _sources/inbox/, process all found files
3. Process Each File (sequential):
   3.1 Read transcript
   3.2 LLM Noise Gate
   3.3 Semantic Context Loading
   3.4 16-Question Classification (incl. Q14 content potential, Q15 CONCEPTS — translate non-English / never transliterate, Q16 PRIVACY TRIO inference)
   3.5 Create Outputs (records, knowledge notes, hubs, ideas as living docs)
   3.6 Structural Verification (concept format autofix, trio defaults)
   3.7 Adversarial Source Audit
   3.8 People Profile Enrichment
   3.9 System Updates
4. Post-Processing — TASKS, CALENDAR, HUB_INDEX, content potential verification, concepts.upserts aggregation, sensitive_entities aggregation
5. Completion Gate — mandatory checklist
5.5 Batch Artifacts — emit `{batch-id}.md` (markdown) + `{batch-id}.json` (manifest via emit_batch_manifest.py)
6. Report — текстовый отчёт о processed files + audit stats + clarifications
```

---

## Три слоя

| Слой | Путь | Формат |
|------|------|--------|
| Records | `_records/{meetings,observations}/` | Лёгкий: summary + key points (+ action items только в meetings) |
| Knowledge | PARA (`1_projects/` — `4_archive/`) | Полный frontmatter + structured content |
| Hubs | `5_meta/mocs/` | Living document с chronological map |

---

## Ключевые правила

1. **Обрабатывать ВСЕ** новые файлы, не спрашивать
2. **Язык контента** = язык оригинала
3. **Теги/ID** = English, lowercase-with-dashes
4. **Проверять registry** перед созданием сущностей
5. **Обновлять registry** при создании новых
6. **Source section** — ссылка на `_sources/processed/`, НЕ дублирование транскрипта
7. **Рабочие встречи** → `_records/meetings/` (kind: meeting); **соло Plaud** → `_records/observations/` (kind: observation). НЕ `2_areas/work/meetings/`
8. **Adversarial audit** — обязателен для КАЖДОГО транскрипта
9. **Идеи** — living documents (поиск существующих перед созданием)
10. **Люди** — обязательное обогащение профиля при новом контексте
11. **CLARIFICATIONS HARD RULE** — при `confidence < threshold` не принимать решение молча; писать вопрос в `_system/state/CLARIFICATIONS.md`, использовать conservative default, продолжать работу. **Layer-specific exception:** concept-name format issues и `audience_tags` whitelist mismatches resolves autonomously через `_common.py` нормализаторы — никогда не raise CLARIFICATION (см. ENGINE_DOCTRINE §3.1)
12. **Privacy trio per entity** — каждый record / knowledge note / hub / person profile / project profile несёт `origin` (personal/work/external) + `audience_tags[]` (canonical 5 + AUDIENCES.md extensions, default `[]`) + `is_sensitive` (bool). Hub trio auto-derived через `recompute_hub_trio` (preserve owner edits)

---

## Naming

- **Files**: `YYYYMMDD-short-semantic-name.md`
- **Tags**: `category/specific-tag` (kebab-case OK; **distinct axis** from `concepts:`)
- **Concepts**: `snake_case_ascii` (English-only; per CONCEPT_NAMING.md). Translation, never transliteration; engine drops on impossibility
- **People**: `firstname-lastname` (transliterated, lowercase, dash). Bare first name = CLARIFICATION
- **Projects**: `short-descriptive-name`

---

## Folder Routing

| Type | Folder |
|------|--------|
| record (kind: meeting — work meeting) | `_records/meetings/` |
| record (kind: observation — solo Plaud) | `_records/observations/` |
| hub | `5_meta/mocs/` |
| planning | `2_areas/work/planning/` |
| technical (work) | `2_areas/work/technical/` |
| technical (ideas) | `3_resources/tech/` |
| idea | `3_resources/ideas/` |
| reflection | `2_areas/personal/reflection/` |
| person | `3_resources/people/` |

---

## ZTN Skills

| Skill | Purpose |
|-------|---------|
| `/ztn:process` | Обработка транскриптов → records + notes + batch report |
| `/ztn:maintain` | After-batch integrator: threads, hub linkage, CURRENT_CONTEXT regen |
| `/ztn:lint` | Nightly consistency, dedup, profile gen, Lint Context Store |
| `/ztn:bootstrap` | One-shot populator системных файлов. Disposable. Три режима: established / fresh-onboarding / mixed |
| `/ztn:recap` | Session recap → raw source в `_sources/inbox/claude-sessions/` |
| `/ztn:search` | Поиск по базе |
| `/ztn:check-content` | Review контент-кандидатов, кластеризация, drafts, CONTENT_OVERVIEW |
| `/ztn:resolve-clarifications` | Interactive разбор очереди CLARIFICATIONS — кластеризация по темам, numbered questions, hypothesis pre-forming против constitution-core, archive resolved |
| `/ztn:save` | Категоризованный commit + push в `origin`. Owner-friendly обёртка над git, без auto-chain из других скиллов |
| `/ztn:sync-data` | Pull данных из `origin` с rebase (мульти-девайс). Refuses auto-merge на конфликтах прозы — escalates owner |
| `/ztn:update` | Pull engine updates из `upstream` (skeleton). Detects local divergence на engine paths, asks per-file, runs migrations. Никогда не трогает data |

---

## Documentation conventions (binding)

Перед любым edit SKILL файлов + `_system/docs/SYSTEM_CONFIG.md` + `_system/docs/batch-format.md`
+ связанных spec files → читай [`_system/docs/CONVENTIONS.md`](../_system/docs/CONVENTIONS.md).

**Короткое правило:** файлы = final spec of current behavior. Никаких version
tags (`v4.5`, `v4.7`), phase references (`Phase 4+`, `per PHASE-4-SDD §Q8`),
rename history (`renamed from X`), release-notes narratives (`V7 closes Phase 4
contract`). Всё это живёт в git log. Файл описывает IS, git описывает BECAME.

---

## Full Documentation

→ `_system/docs/SYSTEM_CONFIG.md` — runtime config
→ `_system/docs/batch-format.md` — batch output contract
→ `5_meta/CONCEPT.md` — архитектура + ADRs
→ `5_meta/PROCESSING_PRINCIPLES.md` — 8 принципов обработки
→ `~/.claude/skills/ztn-process/SKILL.md` — pipeline /ztn:process
→ `~/.claude/skills/ztn-maintain/SKILL.md` — pipeline /ztn:maintain
→ `~/.claude/skills/ztn-lint/SKILL.md` — pipeline /ztn:lint
→ `~/.claude/skills/ztn-bootstrap/SKILL.md` — bootstrap logic
→ `_system/docs/ARCHITECTURE.md` — system design
→ `_system/docs/CONVENTIONS.md` — documentation style rules (binding)
