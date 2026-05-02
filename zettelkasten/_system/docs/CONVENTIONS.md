# Documentation Conventions

> Правила для SKILL / system / around-system документации. Обязательны для любых
> изменений в этих файлах — как ручных, так и сделанных LLM-скиллами или
> Claude-сессиями.
>
> Цель: документация остаётся финальным описанием текущего состояния системы.
> Любой читатель через месяц / через год должен видеть «как оно работает сейчас»,
> а не «как оно эволюционировало до текущего состояния».

---

## Scope — к каким файлам применяется

**Применяется (timeless description required):**

- `.claude/skills/**/*.md` — SKILL.md + adjacent reference docs
- `zettelkasten/_system/docs/SYSTEM_CONFIG.md`
- `zettelkasten/_system/docs/batch-format.md`
- Frontmatter (`description`, `owned_by`, `read_by` fields) of `_system/state/log_*.md`
- `zettelkasten/5_skills/CLAUDE_ZETTELKASTEN.md`
- `zettelkasten/_system/docs/ARCHITECTURE.md` — системный дизайн
- `zettelkasten/_system/docs/CONVENTIONS.md` (этот файл)
- Note templates в `5_meta/templates/`

**НЕ применяется (history-bearing artifacts — keep as-is):**

- `_system/state/log_*.md` body entries — append-only audit trail, исторические записи
  суть и есть содержимое (operational facts of past runs)
- `_system/state/CLARIFICATIONS_ARCHIVE.md` — historical resolutions (split from CLARIFICATIONS.md on 2026-04-26 to keep active queue lean)
- Per-instance deployment journals (e.g., a `platform/` folder owners may keep
  alongside the engine) — phases are the content; such folders are out of the
  engine and not shipped to the skeleton
- `zettelkasten/_records/` and PARA notes — knowledge content itself
- Git history — commits preserve change-narrative naturally

---

## Запрещено в in-scope документации

### 1. Version references

- ❌ `ZTN v4.5`, `ZTN v4.6`, `v4.7 One-Shot Populator` в SKILL headers/descriptions
- ❌ `**Version:** 4.7` в SYSTEM_CONFIG или других system files
- ❌ `ztn:process v4.5` как processor identity
- ❌ `batch-format v2.0` в references (кроме самого `batch-format.md`, где spec version = content)

**Правило:** SKILL describes itself by name, не by version. Если контракт между
компонентами требует версию — это живёт только в `batch-format.md` frontmatter
как single-point spec version + Version History section. Per-version narratives
("в v2.0 добавилось X", "со времён v1.0...") НЕ цитируются в других файлах —
они уйдут в git log при следующем bump.

### 2. Phase references

- ❌ `(Phase 4)` как marker текущего статуса
- ❌ `Phase 4+` как synonym «when this was added»
- ❌ `per PHASE-4-SDD §Q8` как justification
- ❌ `§Q0 vocabulary`, `§Scan B.1 thresholds` как cross-ref
- ❌ `Phase 2 matching limited к idea pattern...` as narrative about когда что произошло
- ❌ `Phase 5+ /ztn:resolve-clarifications` — лучше просто `/ztn:resolve-clarifications`

**Правило:** SKILL describes current behavior. Если need to reference another
skill's responsibility — используй skill name (`/ztn:lint territory`,
`/ztn:maintain responsibility`). Если cross-ref к contract — использу канонич.
ссылку на SYSTEM_CONFIG или file path, не phase/section number.

**Исключение:** файлы в scope «NOT applies» выше (SDD, ROADMAP, SESSION-HANDOFF).

### 3. Rename / migration history

- ❌ `renamed from MAINTENANCE_LOG.md`
- ❌ `(previously LOG.md)`
- ❌ `migrated in first Phase 4 lint run`
- ❌ `legacy \`## Resolved Archive\` table removed during migration`

**Правило:** file is called what it's called. Rename history живёт в git log +
migration trail в `_system/state/log_lint.md` (body). Описание системы говорит о текущих
именах файлов, не о предыдущих.

### 4. Release notes / changelog narrative

- ❌ `V7 finalization closes Phase 4 contract`
- ❌ `[added 2026-04-20 V8 split]` на reason code entries
- ❌ `corrections addendum per REVIEW-*.md`
- ❌ `the owner's reversal on Q3` as justification
- ❌ «`**Compatibility notice.**` Recently extended folder structure»

**Правило:** system/SKILL files описывают invariants + behavior. Кто/когда/почему
добавил фичу — в git log + commit messages. Если decision имеет load-bearing
weight — переформулируй как invariant rule, не как historical narrative.

### 5. Supersedes / Draft status on finalized docs

- ❌ `**Status:** Draft v2` на completed SDDs
- ❌ `**Supersedes:** v1 (initial draft ...)`
- ❌ `## Изменения по сравнению с v1` delta tables

**Правило:** если файл currently authoritative (описывает current state system),
никаких «Draft», «Supersedes», «delta from previous version» — это всё git log
territory.

### 6. Stage-of-evolution qualifiers

- ❌ `ZTN v4.5 three-layer architecture`
- ❌ `post-Phase-4 items`
- ❌ `pre-v4.5 notes`
- ❌ «Phase 3 additions to thread struct»

**Правило:** describe what IS. Evolution stories belong в git log + SDDs.

---

## Разрешено / нужно

### 1. Skill name references

- ✓ `/ztn:lint territory`, `/ztn:maintain responsibility`
- ✓ `Ownership: /ztn:process writes, /ztn:lint reads`
- ✓ `Handled by /ztn:resolve-clarifications`

### 2. Canonical contract references (by name, not section)

- ✓ `per _system/docs/SYSTEM_CONFIG.md Data & Processing Rules`
- ✓ `per _system/docs/batch-format.md`
- ✓ `canonical Resolution-action vocabulary (see _system/docs/SYSTEM_CONFIG.md)`

### 3. Spec-file version references (only in that spec itself)

- ✓ `batch-format.md` carries `version: N.M` в frontmatter + Version History section
  (this is the one place version-bump rules are appropriate — spec evolution is
  the document's own metadata; everywhere else describe behaviour, not version)

### 4. Operational historical data в logs

- ✓ `log_lint.md` body entries describing what a lint run DID: fix-ids, operation
  counts, files modified. This is audit data, not changelog narrative.
- ✓ `log_process.md` body: Processing Run на 2026-04-17 обработал 5 transcripts —
  operational fact.
- ✓ Frontmatter `migration_completed:` map — structural flag, authoritative marker.

### 5. Invariants / rules / HARD RULES

- ✓ `HARD RULE: closure never auto-apply regardless of signal strength`
- ✓ `Invariant: frontmatter lists union — no deletion of tags/people/projects`

Formulate as timeless rule, не как «decided in Phase 3 after the owner's feedback».

---

## Checklist для любого edit в in-scope file

Before committing, grep свежеизменённые места:

```bash
# Must return 0 hits in in-scope files (except SDDs/logs-body per scope):
grep -n "Phase [0-9]\|§Q[0-9]\|v4\.[0-9]\|post-V[0-9]\|per PHASE-\|renamed from\|Supersedes:\|Status:.*Draft"
```

Если hit found — переформулируй в timeless описание current behavior. Если
информация реально load-bearing (например rename причина важна для troubleshooting) —
подумай: может это принадлежит git commit body, не файлу?

---

## Rationale

1. **Trust boundary.** Reader через 3 месяца без session context должен видеть
   спецификацию, а не историю. Release-notes-style content заставляет LLM review
   session загружать context «that this used to be X before» — cognitive waste.

2. **Searchability.** `grep "v4.5"` finds noise. `grep "process"` finds signal.
   Version/phase litter poisons codebase search.

3. **Git is the changelog.** Commit messages + git log + diff tooling exist
   для показа evolution. Дублирование в файл делает дублирование рассинхронным
   (файл stale, git current) → confusion.

4. **Final-state mental model.** Skill files = specs, not journals. System
   config = current rules, not rule evolution. Separation of concerns: files
   describe IS, git describes BECAME.

5. **Friend onboarding (Phase 9+).** Когда template repo раздаётся друзьям, нет
   need для них знать что «Phase 4 renamed X к Y» — им нужна текущая спецификация.
   Clean files = clean onboarding.

---

## Enforcement

**Manual.** Этот файл — binding convention. Любая сессия Claude, modifying
in-scope files, обязана соблюдать правило. Если видит violation в существующем
файле — fix при касании (touch-it-fix-it rule).

**Review triggers:** adversarial review pass (like REVIEW-PHASE-*.md artifacts)
включает этот checklist. Finding violations → part of review findings → fix
before merge.

**Tooling-level enforcement** (potential Phase 5+): pre-commit hook running grep
pattern above. Fails commit if in-scope file contains banned patterns. Deferred
until manual discipline proves insufficient.

---

## Changes to this convention itself

If rules need to evolve — edit this file + document rationale в commit message.
Не добавляй «Version History» секцию в этот файл (recursive application of its
own rule). Git log is the changelog.
