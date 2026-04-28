---
id: batch-format
layer: system
version: 1.0
modified: 2026-04-17
---

# Batch Format

> Контракт формата batch-отчётов `/ztn:process`. Все skill-потребители
> (`/ztn:maintain`, `/ztn:lint`) и `ztn-bridge` plugin ссылаются сюда.
> Изменение формата = bump `version:` во frontmatter + добавление row в Version History.

---

## Version History

- **v1.0**: initial markdown format.

---

## File Locations

- **Index:** `_system/state/BATCH_LOG.md` — append-only markdown table, one row per batch
- **Reports:** `_system/state/batches/{batch-id}.md` — one file per batch, full structured report

---

## batch-id Format

```
YYYYMMDD-HHmmss
```

- UTC timestamp начала обработки
- Уникален, монотонно возрастает
- Сортируется корректно как строка

**Пример:** `20260416-103000`

---

## BATCH_LOG.md Schema

Одна строка markdown-таблицы на каждый batch. Append-only, не перезаписывается.

| Column | Type | Description |
|---|---|---|
| `batch_id` | string | `YYYYMMDD-HHmmss` (UTC) |
| `timestamp` | ISO 8601 | начало обработки (UTC, с суффиксом `Z`) |
| `sources` | int | сколько файлов из inbox обработано в этом batch |
| `records` | int | создано записей в `_records/{meetings,observations}/` (обоих kind'ов суммарно) |
| `notes` | int | создано knowledge notes в PARA (`1_projects/` … `4_archive/`) |
| `tasks` | int | извлечено задач (inline `^task-*` в нотах) |
| `events` | int | извлечено событий (inline 📅) |
| `threads_open` | int | новых open threads за batch |
| `threads_close` | int | переведено в resolved за batch |

---

## batches/{batch-id}.md Schema

### Frontmatter (required)

```yaml
---
batch_id: YYYYMMDD-HHmmss
timestamp: YYYY-MM-DDTHH:MM:SSZ
processor: ztn:process v{version}
batch_format_version: 1.0
sources: N
records: N
notes: N
tasks: N
events: N
threads_opened: N
threads_resolved: N
clarifications_raised: N
people_candidates_appended: N
---
```

### Sections (in order)

1. `## Sources Processed`
2. `## Records Created`
3. `## Knowledge Notes Created`
4. `## Tasks Extracted`
5. `## Events Extracted`
6. `## People Updates`
7. `## Threads` → `### Opened` + `### Resolved`
8. `## Hubs Updated`
9. `## CLARIFICATIONS Raised`
10. `## People Candidates Appended` (added 2026-04-24) — per entry: `{candidate_id} | {name_as_transcribed} | {note-id} | {role_hint or —}`. Count MUST equal `people_candidates_appended` in frontmatter. Use `(none)` if empty. Rationale: bare-name mentions routed to `_system/state/people-candidates.jsonl` instead of CLARIFICATIONS — see `/ztn:process` Step 3.8 + `/ztn:lint` Scan C.5.

Пустые секции сохраняются с пометкой `(none)` — удобнее для diff и downstream consumer.

---

## Example Batch Report

```markdown
---
batch_id: 20260416-103000
timestamp: 2026-04-16T10:30:00Z
processor: ztn:process
batch_format_version: 1.0
sources: 1
records: 1
notes: 2
tasks: 2
events: 1
threads_opened: 1
threads_resolved: 0
clarifications_raised: 0
people_candidates_appended: 0
---

## Sources Processed
- _sources/inbox/plaud/2026-04-16T10-15-00/transcript_with_summary.md (plaud)

## Records Created
- [[20260416-meeting-petya-strategy]] | Встреча с Петей: стратегия инвестиций
  - People: petya-ivanov
  - Projects: —

## Knowledge Notes Created
- [[20260416-investment-approach]] | Подход к инвестиционной стратегии
  - Types: insight | Domains: work
  - Evidence Trail: started

## Tasks Extracted
- task-20260416-001 | Позвонить Пете до пятницы | deadline: 2026-04-18 | priority: high
  - From: [[20260416-meeting-petya-strategy]]

## Events Extracted
- 2026-04-18T14:00:00+04:00 | Follow-up с Петей | participants: petya-ivanov
  - From: [[20260416-meeting-petya-strategy]]

## People Updates
- petya-ivanov | new_context | mentions: 4→5 | tier: 2 (no change)

## Threads

### Opened
- thread-20260416-investment-proposal | Ожидаем proposal от Пети | status: waiting-for-response

### Resolved
(none)

## Hubs Updated
- [[hub-investment-strategy]]

## CLARIFICATIONS Raised
(none)
```

---

## Consumers

Формат потребляют:

- **`/ztn:process`** (writer) — генерирует `batches/{id}.md` + добавляет строку в `BATCH_LOG.md`
- **`/ztn:maintain`** (reader) — читает последний batch для incremental обновлений (mention counts, thread detection, CURRENT_CONTEXT regen)
- **`/ztn:lint`** (reader) — сканирует `BATCH_LOG.md` для detect stale threads, Evidence Trail gaps, content pipeline candidates
- **`ztn-bridge` plugin** (reader) — читает последний batch для session_end обогащения

При bump версии (v2.0+) — migration path документируется здесь же.
