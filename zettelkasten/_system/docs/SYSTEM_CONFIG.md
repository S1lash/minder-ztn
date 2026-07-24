# Zettelkasten System Configuration

> **Documentation convention (binding):** любые изменения в этом файле + SKILL.md
> файлы + `_system/docs/batch-format.md` + связанные system specs подчиняются правилам
> [CONVENTIONS.md](../_system/docs/CONVENTIONS.md). Файлы описывают IS — current
> behavior, timeless spec. Никаких version/phase/release-notes narratives — они
> живут в git log.

---

## Overview

Это персональная система управления знаниями. Claude Code автоматически обрабатывает source-файлы из `_sources/inbox/` (whitelist живёт в `_system/registries/SOURCES.md` — voice-recorder transcripts, hand-written notes, Claude session recaps, и любые источники, которые owner добавил через `/ztn:source-add`), создавая структурированные Zettelkasten-заметки с богатыми метаданными для автоматизаций. После обработки исходные файлы перемещаются в `_sources/processed/`. Reference-материал, который не должен попадать в очередь обработки (raw payloads, escape-hatch данные), живёт в подкаталогах, помеченных колонкой `Skip Subdirs` в SOURCES.md. Self-descriptions / identity-материал — отдельный source `describe-me`: его читает и `/ztn:bootstrap` (как primary seed для SOUL.md, через свой контракт), и `/ztn:process` (как обычный контент). Файлы `*.template.md` не обрабатываются нигде — engine-wide правило (`/ztn:process` §2.2).

### Будущие автоматизации (контекст)
- Психолог / эдвайзер по жизни
- Рабочий эксперт / коуч / твин / помощник
- Таск-менеджер + календарь
- Агент для публичных профессиональных постов

### Document Ownership

This file is the **runtime configuration** loaded by `/ztn:process` at Step 1.
It defines note formats, routing rules, entity types, naming conventions.

For philosophy and architecture: see `5_meta/CONCEPT.md`.
For processing principles: see `5_meta/PROCESSING_PRINCIPLES.md`.
For pipeline algorithm: see SKILL.md (`/ztn:process`).
For batch output format: see `_system/docs/batch-format.md` (markdown
report + JSON manifest emission per `emit_batch_manifest.py`).

---

## CLARIFICATIONS Safety Valve (HARD RULE)

**При `confidence < threshold` скилл НЕ принимает решение молча — пишет вопрос в
`_system/state/CLARIFICATIONS.md` и продолжает работу с conservative default.**

Применяется ко ВСЕМ скиллам системы:

| Скилл | Типичный trigger для CLARIFICATIONS |
|---|---|
| `/ztn:bootstrap` | Неоднозначный tier человека, неясный thread closure, двусмысленный current focus, person identity collision |
| `/ztn:process` | Роль упомянутого неясна, splitting решение неоднозначно, cross-domain mapping сомнителен, domain value не resolved cascade'ом (`domain-resolution`) |
| `/ztn:maintain` | Thread вероятно закрылся, но confidence < 90% |
| `/ztn:lint` | Вероятный дубль с similarity < 95%, Evidence Trail backfill — какая трактовка |

Цель: система автономна + аудитируема. Owner раз в неделю отвечает на вопросы,
скиллы применяют ответы при следующем прогоне. Никаких молчаливых compromise.

### Canonical CLARIFICATION types (append-only)

Reason codes used by skills when raising entries to
`_system/state/CLARIFICATIONS.md`. Append-only — new types are added
as the engine evolves; renames are breaking changes that require
migrating existing open items.

| Type | Raised by | Trigger | Conservative default |
|---|---|---|---|
| `thread-hub-ambiguous` | `/ztn:maintain` | 2+ hubs pass topic filter with score ≥ 2 for the same thread | Skip linkage; thread stays without `hub:` |
| `tier-promote-suggested` | `/ztn:maintain` | Person mentions cross a tier-up threshold | No tier change applied |
| `principle-drift` | `/ztn:process` | `/ztn:check-decision` verdict violated at confidence ≥ 0.8 on a record from the current batch (typed `decision`, or `observation` with `tradeoff_framing` flag set by the subagent per §3.7.5) | Capture in trail; behaviour unchanged this batch |
| `principle-drift-retro` | `/ztn:lint` Scan F.2 | Same verdict + threshold as `principle-drift`, but on a historical decision-record re-checked against the current constitution tree. Trigger: explicit `--rescan-drift --days N` OR auto path on detecting `git log --since="${f2_last_ran_at}" -- 0_constitution/{axiom,principle,rule}/` non-empty | Capture in trail; owner reviews whether the principle edit was intentional |
| `domain-resolution` | `/ztn:process` (Step 3.4.5) | Domain value cannot be resolved by the cascade `normalize_domain` → whitelist → LLM remap → trivial-vs-material | Drop the unmatched value; remaining `domains:` entries kept (possibly `[]`) |
| `process-compatibility` | every skill writing manifests | Schema deviation that would break the manifest contract with downstream consumers | Suspend that section's manifest emission until owner resolves |
| `concept-drift-on-reprocess` | `/ztn:process --reprocess-corpus` (Step 3.5) | Matcher's new `concepts:` set differs from prior set by > 50 % of the union (symmetric-difference / union ratio) | Apply the new (matcher-canonical) set; surface for owner audit, do not gate the write |
| `archive-note-missing` | `/ztn:lint` | File-based entity in archived state without `## Archive Note` block (per Archive Contract Form A); forward-only — pre-contract archives ignored | Surface for owner to fill `reason` / `triggered_by`; do not auto-write |
| `archive-reason-missing` | `/ztn:lint` | Registry-row in archived section with empty `Reason` cell, OR queue-archival action without required reason field (per Archive Contract Forms B and C) | Surface for owner to populate; do not auto-write |
| `manifest-schema-violation` | `/ztn:lint` Scan H | A batch JSON manifest under `_system/state/batches/` fails validation against `_system/docs/manifest-schema/v{N}.json` for its declared `format_version` major | Do not rewrite the manifest (append-only); surface so owner can fix the producer or the schema |
| `manifest-schema-unknown-version` | `/ztn:lint` Scan H | Manifest's `format_version` major has no matching schema file in `manifest-schema/` | Surface; resolve by shipping the missing schema file or rolling back the producer |
| `validator-internal-error` | `/ztn:lint` Scan H | The schema validator raised an unexpected exception on a specific batch (json parse error, validator bug) | Lint continues other scans; owner reviews stack trace |
| `validator-helper-failed` | `/ztn:lint` Scan H | The `lint_manifest_schema.py` helper itself exited non-zero (jsonschema not installed, schemas-dir or batches-dir missing) | Lint continues other scans; owner restores the helper environment |
| `lens-action-proposed` | `/ztn:resolve-clarifications` (`--auto-mode` Step A.3) | Smart-resolve sweep judged a lens-emitted Action Hint as `queue` (not safe to auto-apply, not constitution-vetoed); the row carries `**Smart_resolve reasoning:**` + `**Action type:**` + `**Action params:**` for owner Class C review (apply / reject / modify / defer) | Queue stays as-is; auto-apply requires owner click |
| `lens-action-veto` | `/ztn:resolve-clarifications` (`--auto-mode` Step A.3) | Smart-resolve judged a lens-emitted Action Hint as `block-veto` against constitution / SOUL focus; row carries `**Smart_resolve reasoning:**` + `**Veto reason:**` naming the principle / SOUL element triggered. Step A.3.5 also routes here when an escalation `/ztn:check-decision` call returned `violated` at confidence ≥ 0.7 on a `queue` candidate; the row additionally carries `**Escalation-resolved by check-decision:**` annotation with the cited principle id | Owner reviews; can override per-class via `_system/state/insights-config.yaml::classes` |
| `lens-action-apply-failed` | `/ztn:resolve-clarifications` (`--auto-mode` Step A.3) | Handler validation failed inside apply (TOCTOU drift between Step A.1 stale-check and apply — e.g. another process created the hub target, or a cited note was renamed mid-tick) | Action is queued instead; owner reviews proposal + handler error reason |
| `metric-record-rerender` | `/ztn:process` metric-day branch | Existing `_records/biometric/<source>/<date>.md` + new content-hash differs (re-collected source) | Skip re-write; offer 3 alternatives via resolve (skip / append-update / recompute-baselines-forward). Apply via `metric_record_rerender_apply` action handler |
| `biometric-baseline-cold-start` | `/ztn:process` metric-day branch | First metric-day file for a source processed AND `_system/state/biometric/<source>/baselines.json` does not exist | Initialize empty baselines for that source; emit informational CLARIFICATION (one-time per source, expected). Resolution: dismiss as resolved with note "expected cold-start". No further action needed |
| `biometric-threshold-drift` | `/ztn:maintain` Tier II calibration check | ≥3 consecutive weeks observed/expected fire-rate ratio outside [0.5, 2.0] for a metric × severity pair | Skip auto-tune; surface proposal with current vs proposed σ; owner approves via resolve action `threshold_tune_proposal` (Class C) |
| `biometric-affect-lexicon-empty` | `/ztn:maintain` Tier II Phase 2 | Lexicon overlay loaded successfully but produces zero affect tags across the entire 56-day window | Skip Phase 2; surface so owner can audit lexicon entries (may indicate non-RU/EN owner needs lexicon localisation via `affect_lexicon.local.yaml`) |
| `portable-name-collision` | `/ztn:process` §0.0, `/ztn:save` Step 0.5, `/ztn:lint` A.10 | Non-portable (Windows-illegal) inbox name whose `normalize_portable_name()` form already exists in the same directory, or normalisation returned None | Skip the item this run (process) / exclude from staging (save); never guess a suffix |
| `portable-name-escape` | `/ztn:lint` A.10 | Non-portable tracked path outside `_sources/inbox/` and not grandfathered via PROCESSED.md — slipped past both ingestion gates | Surface only; rename + reference rewrite happens as an owner-reviewed resolve action, never autonomously |
| `content-type-canon-reviewed` | `/ztn:lint` A.11 | Judgment-row `content_type` drift mapped to its default canonical (weak × high) | Applied with the default; CLARIFICATION asks owner to validate (resolve action `canonicalize-content-type`) |
| `content-type-canon-surfaced` | `/ztn:lint` A.11 | Judgment-row `content_type` drift ambiguous between 2+ canonical types (weak × confident/unsure) | No apply; owner picks the canonical type with note excerpt in Context |
| `content-type-unknown` | `/ztn:lint` A.11 | `content_type` drift value not in `CANON_MAP` | No apply; owner picks a canonical mapping (optionally extends `CANON_MAP`) |
| `content-type-missing` | `/ztn:lint` A.11 | Note has `content_potential` but no `content_type` | No apply; owner sets the canonical type |
| `content-angle-missing` | `/ztn:lint` A.11 | Note has `content_potential` but empty/absent `content_angle` | Informational; the draft-maintainer proposes the hook on its next run |
| `frontmatter-unfixable-schema` | `/ztn:lint` A.2 | Frontmatter YAML does not parse and is not a repairable misplaced-fence case | Surface; owner fixes the schema by hand |
| `frontmatter-fence-misplaced` | `/ztn:lint` A.2, `/ztn:process` Step 4.5 | A `## ` body heading sits inside the YAML fence and `_common.repair_misplaced_fence` refused as ambiguous (multiple `---` in the displaced region) | Surface; owner relocates the closing `---` above the body |
| `task-aggregation-orphans` | `/ztn:lint` A.6.1 | `reconcile_tasks.py` finds open `- [ ]` task-ids in notes absent from every active/Stale section of TASKS.md | Surface count; owner runs `/ztn:process --reconcile-tasks` to classify + file them (read-only detection, no auto-write) |
| `hub-index-incomplete` | `/ztn:lint` A.6.2 | An on-disk `5_meta/mocs/hub-*.md` file is absent from HUB_INDEX.md | Surface missing ids; owner regenerates the index via `/ztn:maintain` |
| `calendar-aggregation-orphans` | `/ztn:lint` A.6.3 | `reconcile_calendar.py` finds a note with a future `📅` event whose link is absent from every forward-facing CALENDAR section | Surface count; owner runs `/ztn:process --reconcile-calendar` (read-only detection, no auto-write) |
| `role-cold-start` | `/ztn:roles` | First tick over an empty PART of a role (no prior content) — the body drafts that part's initial draft (aggregated per role across every pending part) | Hold each part's frozen draft in its `staging`; adopt into live state only on owner approval (never re-cluster; re-surfaced verbatim until resolved) |
| `role-new-key` | `/ztn:roles` | Unanchored new item in a tick (a ledger `add` with `anchor: null`) — minting a stable key is an LLM judgment, not deterministic. Only anchoring part-kinds raise it | Per `identity_strictness`: attach to nearest existing key; `strict` (cold-start / early ticks) → hold, do not mint |
| `role-churn-guard` | `/ztn:roles` | One tick's deltas to a PART would rewrite it wholesale (a ledger: touch/retire all its live keys, or exceed `churn_threshold` mutations; a narrative: exceed `churn_threshold` statements; a registry: exceed `churn_threshold` catalog mutations/retires, or sweep all its live entries — log appends are exempt) | Hold; do not persist that part's deltas; ask the owner (that part's run is held, siblings unaffected) |
| `role-identity-suggest` | `/ztn:roles` | The role proposes an edit to its own identity (persona / stance / remit) — owner-sovereign, the role never self-edits | Hold for owner; identity change applied only on approval |
| `role-auto-paused` | `/ztn:roles` | 3 consecutive validator rejects for a PART — the whole role auto-pauses with an Archive-Contract reason | Informational; role `status: paused`, needs owner to review the rejects and re-activate |
| `role-schema-version` | `/ztn:roles` | A role PART's `parts/{id}.json` schema version does not match the engine's current archetype version — newer (this engine is too old to read it) or older with no migration path | Newer → refuse the tick untouched (update the engine); older with no migration → proceed in degraded mode. Owner reviews the version gap |
| `role-unroutable` | `/ztn:roles` | One or more deltas in a tick addressed a `part` the role does not have (a stale / renamed part id in the body) — the work would otherwise vanish silently | Drop the unroutable deltas; if the tick had NO other work, degrade its run to `rejected` (retries, not a clean empty); surface the offending refs + the role's real part ids |
| `role-remit-changed` | `/ztn:role:edit` | The owner edited a role's remit (the zone it watches) — the tracked state was built against the OLD zone, so keys may now reference out-of-zone work or miss newly-in-zone work | Re-baseline: surface the shift, stage a re-validation of the tracked state against the new remit; never silently churn-tick a reshaped remit (that would orphan keys or trip the churn-guard) |
| `role-nudge` | `/ztn:roles` | A tick's PROACTIVE VOICE — the role surfaces a bounded, grounded concern the owner should act on now (a push, a cross-cutting blocker, «что горит», drift from the idea). origin `role:{id}` = non-personal, ALWAYS HITL, never auto-applied | Surface as an owner-facing item; write NOTHING canonical. Grounded (cites a real in-remit record) or dropped; cumulative anti-salami budget (`ROLE_NUDGE_OPEN_BUDGET` open per role) defers the rest; same nudge dedups across ticks. `/ztn:resolve-clarifications` triages it like any owner item |
| `role-orphaned-part` | `/ztn:roles` | A tick found part state on disk (`parts/{id}.json` + a `state.md` sub-zone) that the role's `config.yml` `parts:` no longer declares — a parts-shape change that slipped past `/ztn:role:edit` (which refuses one) or a hand-edited config. The tick processes only declared parts, so the orphan silently drifts stale | Surface the mismatch; DELETE NOTHING (surface, don't decide). Owner reconciles via `/ztn:role:edit` — restore the part to `parts:` to resume it, or retire + re-create the new shape via `/ztn:role:add`. Deduped: surfaced once while open |
| `role-owner-confirm` | `/ztn:roles` | An `owner-confirm` registry part proposed recording owner-fact(s) it has NO in-zone note to cite — the role wants to assert a fact about the owner's world (say an entry's location it was told but has no note for) it cannot ground in a record. A role NEVER asserts a fact on the owner's behalf | Surface the proposal; write NOTHING (the owner is the engine-authored anchor). Owner ratifies the true ones via `/ztn:role:edit`, or lets them become notes so the next tick cites them. A record-cited registry op writes normally; only the uncited proposal waits |
| `role-trigger-skip-streak` | `/ztn:roles` | A role's trigger-gate skipped it `SKIP_STREAK_LIMIT` (5) cadence-due ticks in a row (`gate:skip` every time) — the trigger may be mis-wired (a probe that never moves, a `match` that never fires) so the role never runs | Surface the streak + the last skip reasons; owner reviews the trigger config via `/ztn:role:edit`. The role is not paused — a genuinely quiet zone is valid; the streak only flags «is this wired right?» |
| `role-tool-reauth` | `/ztn:roles` | A tool call failed and the bounded runtime self-heal (retry transient / re-resolve secret / honest-degrade) could not recover — a HUMAN decision is required (expired credential needs re-auth, or the external scope changed) | Surface which tool + why the self-heal stopped; owner re-auths (re-runs the concierge's secret step) or adjusts scope. The tick honest-degrades (skips the tool, notes it) — never fabricates a result |
| `role-emission-confirm` | `/ztn:roles` | An inbox emission the engine cannot CERTIFY stayed in-remit — surfaced for owner confirmation before it reaches the base. Two triggers (OR): (1) the injection firewall (INV-17) — the tick ingested EXTERNAL TOOL content; (2) the un-caged body (INV-15 honesty) — the tick body ran without a verified no-FS cage (the shipped honor-system runtime), so it could have raw-read an out-of-remit note and paraphrased it into the note's free-form `text` (not corpus-checkable, unlike `evidence`). Autonomous write requires BOTH no external ingestion AND a verified cage | Surface the proposed note; owner approves (it becomes a base note) or discards. Nothing is written until confirmed. In PLAN 1 (no verified cage) EVERY emission is confirmed; the gate relaxes to firewall-only when the body cage is verified. A bounded-blast act to a fixed reversible surface (PLAN 2) is firewall-exempt |
| `role-budget-exhausted` | `/ztn:roles` | The role hit its cumulative per-period ceiling on outward writes (acts + inbox emissions — the anti-salami budget in `budget.json`); further writes this period defer rather than pile up | Informational; the deferred writes wait for the next budget period. Owner may raise the ceiling via `/ztn:role:edit` if the role is legitimately busier than the budget assumed |
| `role-act-confirm` | `/ztn:roles` | An outward ACT (a write to an external board under the role's mandate — CONTRACT §6.2) is STAGED for the owner's approval, not executed in-tick. In the harness every act is HITL (INV-16/PLAN-2 §1 — `autonomy: autonomous` degrades to advisory until a verified sandboxed runtime); the tick captures the TOCTOU baseline, stages the act(s) into `pending_acts.json`, and surfaces this | Surface the staged act(s) + the reconcile reason; owner approves via `/ztn:roles --approve-acts <id>` (executes idempotently, TOCTOU-revalidated, then emits the inbox close-events + advances the watermark) or discards. Nothing is written to the external system until approved |
| `role-act-drift` | `/ztn:roles` | TOCTOU (INV-16/28): at act execution the target had changed since it was staged (its version field moved) — the write was ABORTED, not applied over someone else's change | Informational + actionable: the next tick re-reconciles from fresh state (the pending acts were cleared to avoid a stale-baseline loop; the watermark did not advance, so the change is re-processed). No double-write, no silent overwrite |
| `role-act-failed` | `/ztn:roles` | An act's transport/HTTP call failed and the bounded self-heal could not recover (INV-28) — surfaced honestly; the reconcile did not fully succeed, so no inbox close-event was emitted and the watermark did not advance | Surface which act + why; the successful acts (idempotent) took effect and re-confirm on the next reconcile. Owner may re-auth / adjust, then the next tick re-reconciles |
| `role-tool-request` | `/ztn:roles` | A role asks for a NEW tool it would do its job better with (a colleague's «I'd do this better with access to X») — grounded in what it actually hit this tick, always HITL, NEVER a self-grant (a role can never give itself a tool — INV-3) | Surface the request + the grounding; owner grants via `/ztn:role:edit` (adds the tool to a part's grant / wires a new one) or dismisses. Nothing is granted until the owner acts |

Per-skill SKILL.md may add narrower types for skill-internal flows;
this table covers the cross-skill canonical set referenced in
ENGINE_DOCTRINE §3.1.

---

## Cross-platform — Windows + macOS + Linux (HARD RULE)

Every engine artifact — migration, script, command, hook, path, symlink, doc
instruction — MUST work identically on all three platforms friends run: Windows
(Git Bash + `python3`), macOS (system **bash 3.2** + `python3`), Linux. Shell
must be bash-3.2-safe (no `mapfile`/`readarray`/`declare -A`/`${x^^}`) and use
portable commands only (no `md5`/`md5sum` split; `sed -i.bak` not `sed -i`; no
`readlink -f`); prefer `python3` for logic; resolve paths from repo-root, never
hardcode `/` or `C:\`; run scripts via `bash`/`python3` (no exec-bit); keep
`.sh`/`.py` LF (`.gitattributes` enforces it). Full statement + rationale:
`ENGINE_DOCTRINE.md §3.9`.

## Data & Processing Rules

Canonical rules, разделяемые между скиллами. Single source of truth.

### Mention counting (применяется в `/ztn:process`, `/ztn:maintain`, `/ztn:bootstrap`)

- **1 mention = 1 file**, где person появляется в `people:` frontmatter array OR является subject of record/note
- Не per-utterance, не per-topic. Длинная встреча с 6 упоминаниями человека = +1 mention, не +6
- Monotonic — counts только растут при `/ztn:process`. Decrements только при удалении нот (редкий случай, делается manually или `/ztn:lint` при dedup)
- `last_mention` date = latest `created` date across files referencing person

### People inclusion in `people:` frontmatter (применяется в `/ztn:process`)

- **Inclusion-biased**: если person resolved и упомянут в content (не noise) — добавлять в `people:` array
- Не применять эвристику "central to note" — это subjective и source of gaps
- **Bare first name** (без фамилии, не резолвится в full ID) → **append в `_system/state/people-candidates.jsonl`** (buffer) через `python3 _system/scripts/append_person_candidate.py`. **НЕ добавлять** в `people:`, **НЕ** raise CLARIFICATION per mention. `/ztn:lint` Scan C.5 еженедельно агрегирует buffer и promotes только recurring/information-rich candidates в CLARIFICATIONS. Rationale: снижает friction для one-off mentions (redesigned 2026-04-24).
- **Escape hatch** — raise CLARIFICATION immediately только при одном из явных сигналов: (a) external/client meeting, (b) full surname присутствует elsewhere в transcript но не сматчился из-за STT artifact, (c) user tag `@resolve-now`, (d) role+context полностью specified в mention. Подробности — `/ztn:process` Step 3.8.

### OPEN_THREADS grain (применяется в `/ztn:bootstrap`, `/ztn:maintain`)

- **Strategic grain only**: один thread = umbrella topic покрывающий несколько related TASKS.md Waiting items
- НЕ делать 1:1 mapping с TASKS.md Waiting — это operational layer
- Каждый thread должен иметь поле `## Related Tasks` со ссылками на TASKS.md tasks (для auto-closure tracking)
- Auto-closure: если все related tasks done/stale → thread → Resolved

### Thread ↔ Hub linkage (применяется в `/ztn:maintain` + `/ztn:lint`)

- При создании/обновлении thread: искать hub по теме (match по people + keyword signals). Если найден — thread field `hub: [[hub-id]]`
- При apparence thread — добавить bullet в hub's `## Открытые вопросы`
- При closure thread — убрать из hub's Open Questions, добавить resolution в hub's `## Ключевые выводы`
- `/ztn:lint` nightly verifies consistency: для каждого thread с `hub:` проверить существование hub и отсутствие drift между thread state и hub content

### Tier assignment (применяется в `/ztn:bootstrap`, `/ztn:maintain`, `/ztn:lint`)

- **Tier 1** — profile существует в `3_resources/people/{id}.md` OR mentions ≥ 8
- **Tier 2** — mentions 3-7 (no profile)
- **Tier 3** — mentions 1-2 (no profile)
- **stale** — 0 mentions, no profile (candidate для archival, но не автоматически)
- `/ztn:process` при добавлении нового человека: если creates profile → Tier 1, else Tier 3. Не пересчитывает existing entries
- `/ztn:maintain` при incremental update: **предлагает** promote Tier (3→2, 2→1) через CLARIFICATION `tier-promote-suggested`. **Никогда не применяет автоматически** — apply через `/ztn:resolve-clarifications` (owner confirms, skill diffs PEOPLE.md tier column). Никогда не demote (это `/ztn:lint` territory)
- Profile creation: для new person — inline в `/ztn:process` при достаточном контексте. Для existing person crossing Tier 1 threshold без profile — `/ztn:lint` generates profile skeleton при reviewed tier

### Profile template (canonical — applied by `/ztn:process`, `/ztn:lint`)

Все profiles (existing + auto-generated) match canonical template:

```yaml
---
id: {person-id}
name: "{Name cyrillic}"
role: {role}
org: {org}
tags:
  - person/{id}
  - org/{org}
  - role/{role}
---

# {Name cyrillic}

**Role:** {role summary one line}

## Контекст

{Narrative — role, relationship, recent notable context}

## Мои наблюдения

{Private — owner's subjective opinions. Structurally required section. NEVER auto-generated content. Auto-generation emits placeholder `_(заполняется вручную)_`}

## Упоминания

- [[note-id]] — {brief hint, date}
```

Order mandatory: frontmatter → `# Name` → `**Role:**` → `## Контекст` → `## Мои наблюдения` → `## Упоминания`.

### Log file ownership

- `log_lint.md` — written ONLY by `/ztn:lint`
- `log_maintenance.md` — written ONLY by `/ztn:maintain` + `/ztn:bootstrap`
- `log_process.md` — written ONLY by `/ztn:process`
- `log_agent_lens.md` — written ONLY by `/ztn:agent-lens`
- `agent-lens-runs.jsonl` — written ONLY by `/ztn:agent-lens` (append-only machine index)
- `resolve-sessions/{date}-{sid}.md` — written ONLY by `/ztn:resolve-clarifications` (one file per session, owner-readable narrative; `is_sensitive: true` by default)
- `lens-resolution-history.jsonl` — written ONLY by `/ztn:resolve-clarifications` interactive owner clicks (append-only precedent index; auto-mode applies do NOT write here — engine never trains on engine)
- `last-resolve-tick.txt` — written ONLY by `/ztn:resolve-clarifications` (high-water marker for «modified since» lens-output scan)
- `insights-config.yaml` — owner-mutable; engine creates from `.template` on first resolve run when missing, never rewrites
- Cross-reads OK (activity detection, context sourcing)

### Skill Write Territory (HARD RULES)

Pipeline skills have well-defined write territories: **each write-mode of a file
has exactly one owning skill.** A few files carry more than one write-mode (e.g.
OPEN_THREADS.md `## Active` is opened by maintain at strategic grain and appended
by resolve for lens/owner additions) — that is not an overlap, it is distinct
lanes with distinct owners. Writing outside your lane is a schema violation —
audits check this via git diff scope. This table is the single source of truth for
write territory; ENGINE_DOCTRINE §4 and `.claude/CLAUDE.md` point here rather than
restating it.

| Operation | Authorised skill | Rationale |
|---|---|---|
| Create new records / notes / tasks / events | `/ztn:process` only | Extraction from sources is the process domain |
| Aggregate note `- [ ]` tasks → `TASKS.md`; note `📅` events → `CALENDAR.md` | `/ztn:process` only | Derived aggregates (views over note items), NOT owner-authored files. Owner owns only the `## Stale` task section (preserved across regens). Completeness is guaranteed by `reconcile_tasks.py` / `reconcile_calendar.py` (Step 4.1/4.2 gate), not a full re-walk each run |
| Create a **full** hub (3+ note threshold) / update hub content (`Текущее понимание`, chronological map, changelog) in `5_meta/mocs/` | `/ztn:process` (additive, non-destructive) | Process records a batch's contribution; it MUST NOT full-rewrite `Текущее понимание` (single-batch view would destroy cross-batch synthesis). From-scratch re-synthesis is surfaced by `/ztn:lint` D.4 (`hub-stale-vs-material`), applied by owner — the synthesis layer is never auto-rewritten. (A lens-proposed **stub** hub is the separate lane below — `/ztn:resolve-clarifications`.) |
| Regenerate `HUB_INDEX.md` | `/ztn:maintain` (full rebuild) + `/ztn:process` (additive: append a newly-created hub) | Derived index of hub files. Drift (index behind on-disk hubs) is caught deterministically by `/ztn:lint` A.6.2 (`hub-index-incomplete`) → owner regens via `/ztn:maintain` |
| Increment PEOPLE.md `Mentions` column | `/ztn:process` only | Per-file counting happens inline at batch write |
| Modify body of existing records/notes | `/ztn:process` (initial) + `/ztn:lint` (dedup merge only) | No other skill touches content |
| Append `threads:` back-ref to record/note frontmatter | `/ztn:maintain` only | Structural metadata — body never touched |
| Tier change in PEOPLE.md (promote or demote) | **via `/ztn:resolve-clarifications` only** | Never auto-applied — surfaces CLARIFICATION |
| Thread closure (Active → Resolved in OPEN_THREADS.md) | **via `/ztn:resolve-clarifications` only** | Never auto-applied regardless of signal strength |
| Append row to OPEN_THREADS.md `## Active` | `/ztn:maintain` (strategic-grain thread opening) + `/ztn:resolve-clarifications` (auto-mode or owner click on `open_thread_add` lens hint) | Two write-modes, one owner each: maintain opens threads it detects at strategic grain; resolve applies lens/owner additions. Both additive; provenance via inline `from_lens` comment. `/ztn:process` never writes here (context-only) |
| Create new hub stub in `5_meta/mocs/` | `/ztn:resolve-clarifications` (`hub_stub_create` lens hint) OR owner-curated | New hub carries `from_lens:` in frontmatter; lint_hub_integrity passes the stub |
| Add wikilink to `## Связи (auto)` section in a knowledge note | `/ztn:resolve-clarifications` (`wikilink_add` lens hint) | Distinct section from manually curated `## Связи` so owner edits and auto edits don't collide |
| Append `## Update {today}` section to a decision note | `/ztn:resolve-clarifications` (`decision_update_section` lens hint) | Scaffold only — owner fills the body |
| SOUL.md edits (Identity / Focus / Working Style — outside auto-zone) | **manual only** | Identity file; auto-zone is a separate write-lane |
| SOUL.md auto-zone (Values between markers) | `render_soul_values.py` only | Deterministic render from `0_constitution/` |
| Write `_system/state/batches/{id}.md` + `BATCH_LOG.md` row | `/ztn:process` only | One run = one batch; maintain reads, doesn't write |
| Hub linkage back-write (`hub:` field on thread, bullet in hub Open Questions) | `/ztn:maintain` only | Both sides updated atomically; lint verifies |
| Regenerate views (CONSTITUTION_INDEX, constitution-core, INDEX, HUB_INDEX, CURRENT_CONTEXT) | Scripts via `regen_all.py` / relevant skill | Views are derived — source is `0_constitution/` / knowledge notes / hubs |
| Create `_records/<family>/<source>/<date>.md` + update `_system/state/<family>/<source>/{baselines,streaks}.json` | `/ztn:process` metric-day branch only | Per-day deterministic emission from `_sources/inbox/<source>/<date>.md`, profile-driven (`<family>` = `biometric` for garmin/oura, `activity` for activitywatch). One source file → one record; records + baselines namespaced per source. Idempotent on re-run; CLARIFICATION on content-hash drift (`metric-record-rerender`). |
| Write `_system/state/biometric/<source>/{correlations-{week}.json, calibration-history.json, last_weekly_run.txt}` + `_system/views/biometric/<source>/weekly-{week}.md` | `/ztn:maintain` only (biometric Tier II weekly worker, after-batch with weekly idempotency gate, run once per active biometric source) | Derived state — recomputable from `_records/biometric/<source>/`. Weekly-gated per source by `<source>/last_weekly_run.txt` ISO-week comparison; runs at most once per ISO week per source per first /ztn:maintain invocation. |
| Write `_system/state/activity/<source>/{weekly-{week}.json, last_weekly_run.txt}` + `_system/views/activity/<source>/weekly-{week}.md` | `/ztn:maintain` only (activity weekly worker, Step 6.8 — symmetric to biometric, after-batch with weekly idempotency gate) | Derived state — recomputable from `_records/activity/<source>/`. Activity has no σ-correlations/calibration layer (the heavy aggregation is upstream in the collector); the worker produces a weekly Focus-Engineering rollup (median scores, category/rhythm/switching trend, top death loops). Weekly-gated per source by `<source>/last_weekly_run.txt`. |
| Write `## Health Snapshot` block in CURRENT_CONTEXT.md | `/ztn:maintain` only (via `render_health_snapshot.py`, integrated into CURRENT_CONTEXT regen chain) | Extension of existing CURRENT_CONTEXT regen — derived view, not new content. ≤15 lines, life-connection focused. |
| Write AUTO-GENERATED zone of `5_meta/mocs/hub-cognitive-model.md` | `/ztn:maintain` only (via `render_cognitive_model_hub.py`, Step 7.9 — post-loop, after Step 7.8) | Pure projection of constitution `cognitive_axes` fields + candidate buffer; only the zone between the `<!-- AUTO-GENERATED: cognitive-model-hub -->` markers, never the owner's «portrait» above them. |
| Write `_system/roles/{id}/{config.yml, hooks/{tick,ask}.md, brief.md?}` (role identity + hook bodies + optional owner brief) | `/ztn:role:add` (create) + `/ztn:role:edit` (change / lifecycle) — validate-before-write; owner-sovereign thereafter. NEITHER seeds part state | Role identity (persona / stance / remit / parts) is owner-sovereign — the tick NEVER self-edits it. A role's suggested identity change surfaces `role-identity-suggest`, applied only by the owner. `brief.md` is owner-written; the engine reads it as STEER, never writes it. |
| Write `_system/roles/{id}/{parts/*.json, state.md AUTO sub-zones, decisions.jsonl}` + `_system/state/{roles-runs.jsonl, log_roles.md}` | `/ztn:roles` via `roles_persist.py` (sole deterministic writer) | The tick body only proposes a part-addressed JSON delta; `roles_persist.py` runs each part's validator FIRST, then persists — the safety-by-construction control boundary. `state.md` writes touch only each part's AUTO sub-zone between its markers; the owner «portrait» above them is never touched. A tick's proactive `role-nudge` writes only to the owner-facing `CLARIFICATIONS.md`, never a canonical note. |
| Write `_system/roles/{id}/{triggers.json, budget.json, pending_acts.json}` (roles+tools cross-tick state) | `/ztn:roles` — `triggers.json` via `roles_triggers.py` (runner-owned trigger-gate watermark, keyed target+device, + skip-streak; advances only after a confirmed tick/act — INV-26); `budget.json` via `roles_budget.py` (cumulative act/inbox ceiling + wall-clock, per period — INV-20/28); `pending_acts.json` via `roles_persist.py` (the staged outward acts awaiting owner approval — their captured TOCTOU baselines, the coupled inbox close-events, the pending watermarks; written in Phase 1 by `_stage_acts`, consumed + cleared in Phase 2 by `--approve-acts` — CONTRACT §6.5. **Local + gitignored (per-clone):** staged on this clone's tick, approved on this clone; never committed, so it cannot split brain across clones sharing one external board) | Runner-owned deterministic state, NEVER body-authored (INV-1). `triggers.json`/`pending_acts.json` live beside `decisions.jsonl` (their own home, not smeared into a part). All are recomputable-conservative: a corrupt file falls back to a fresh default / empty so a tick never crashes; a cleared `pending_acts.json` re-derives from the next reconcile. |
| Write `_system/state/roles-tool-audit.jsonl` (tool-call audit) | `/ztn:roles` via `roles_tool_stage.py` (append-only) | Hash + one-line summary per tool call — NEVER the raw return (INV-10 — a tool return is ephemeral, never committed to the repo). Observability without bloat. |
| Write `_system/state/secrets.enc.json` (encrypted secrets blob) | `/ztn:role:add` concierge via `roles_secrets.py` (`store_secret`) | Per-value `cryptography.fernet`-encrypted credentials (INV-12/13). Committed to the owner's OWN private repo; the master key travels via `ZTN_SECRET_MASTER_KEY` (scheduler routine placeholder), NEVER git. A secret is resolved in memory at run time, never entering an LLM prompt / log / exception. Per-fork isolated. |
| Regenerate `_system/views/ROLES.md` | `/ztn:maintain` only (via `render_roles_registry.py`, Step 7.10 — post-loop) | Read-only projection over the role instance dirs — derived view, recomputable, holds no state of its own. |

**Supporting invariants:**
1. `/ztn:maintain` NEVER creates knowledge content — no records, notes, or hub
   synthesis prose. It writes only structural state: back-references and
   strategic-grain thread opening in `OPEN_THREADS.md ## Active` (a tracking
   entry, not synthesis). Hub `Текущее понимание` synthesis is explicitly NOT
   maintain's — that stays with process (additive) + owner via lint D.4.
2. `/ztn:lint` NEVER applies closure or tier changes — only surfaces CLARIFICATIONS.
3. Hub `topic_relevance ≥ 1` required for hub ↔ thread linkage — pure people-overlap never links (prevents hub bloat).
4. Dedup (similarity ≥ 95%) is the ONLY body-edit `/ztn:lint` performs — it merges, never deletes unilaterally.
5. CLARIFICATIONS are the universal human-in-the-loop gate — any ambiguity at skill confidence below threshold writes a question, not a decision.

### CLARIFICATIONS format

All CLARIFICATION items MUST include:
- `**Context:**` field (2-4 sentence paragraph) — self-contained для LLM review session (owner не читает CLARIFICATIONS глазами напрямую, обсуждает с LLM)
- `**Quote:**` field — verbatim fragment when source = транскрипт
- Parsable fields: `Type`, `Subject`, `Source`, `Suggested action`, `Confidence tier`

Optional fields (added by specific producers; loose-parsed by `/ztn:resolve-clarifications`):
- `**Smart_resolve reasoning:**` — written by `/ztn:resolve-clarifications --auto-mode` when an item passes through the auto-resolve sweep but lands in the queue (not auto-applied). 1-3 sentences referencing constitution / past sessions / SOUL focus. Renders in resolve interactive Step 5 «Procedural context» block. Append-only — never rewritten on subsequent sweeps (latest sweep adds a new line if reasoning evolves)
- `**Action type:**` + `**Action params:**` (YAML inline) — written for `lens-action-proposed` items only. Carry the structured proposal that Class C apply / reject / modify operate on
- `**Veto reason:**` — written for `lens-action-veto` items only. Names the specific axiom / principle / rule ID or SOUL-section that triggered the veto
- `**Precedent:**` — optional list of `_system/state/resolve-sessions/{date}-{sid}.md` links with one-line summaries of how owner decided substantively-similar past proposals. Resolver renders these in Step 5 to ground owner judgement

Resolved items use structured format with `**Applied:** no|yes` field + `**Context:**` + `**Rationale:**` + canonical `Resolution-action` vocabulary. Single format — `## Open Items` + `## Resolved Items` sections only.

Owner-facing review path: `/ztn:resolve-clarifications` — interactive walker that clusters items by theme, reminds context inline, pre-forms hypotheses against constitution, applies confirmed resolutions, and archives closed items.

**Canonical `Resolution-action` vocabulary** (append-only evolution — stable contract for `/ztn:resolve-clarifications` and any future automated consumer):

| Action | Target | Payload example |
|---|---|---|
| `close-thread` | thread-id | `resolution_text: "Решение принято, выкатили X"` |
| `keep-thread-open` | thread-id | `(none)` |
| `close-partial` | thread-id | `remaining_tasks: [ids], new_status: "needs-decision"` |
| `promote-tier` | person-id | `from: 2, to: 1` |
| `demote-tier` | person-id | `from: 1, to: 2, reason: "inactive"` |
| `merge-notes` | kept-note-id | `deleted: [ids], merge_strategy: "A superset of B"` |
| `dismiss-duplicate` | note-id | `(none)` |
| `backfill-evidence-trail` | note-id | `entries: [{date, source, action}]` |
| `resolve-bare-name` | subject-string | `person: person-id` OR `ignore: true` |
| `create-profile` | person-id | `from_tier: N, context_sources: [record-ids]` |
| `fix-process` | (free-form) | `suggestion: "process Step X.Y ..."` |
| `dismiss` | subject | `reason: noise | not-actionable | wontfix | stt-artifact` |
| `defer` | subject | `until: YYYY-MM-DD` |
| `validate-applied-fixes` | fix-id-range | `fix_ids: [ids], all_correct: bool, reverts: [ids]` |
| `pursue-or-close` | thread-id | `choice: pursue | close | keep-watching, note: "why"` |
| `review-soul` | soul-section | `edits_applied: bool, rationale: "..."` |
| `canonicalize-content-type` | note-id | `raw: "{drifted-value}", chosen: "{canonical-five}", applied: bool` — owner picked the canonical `content_type` for an A.11 judgment / unknown / reviewed item; note frontmatter rewritten + Evidence-Trail line |
| `decide-policy` | subject | `policy_chosen: "a|b|c|d", sdd_updated: bool` |
| `suppress-until` | subject | `date: YYYY-MM-DD, reason: "..."` — suppression cache entry |
| `update-hub-synthesis` | hub-id | `sections_updated: ["Текущее понимание", "Changelog"], notes_integrated: [ids]` — owner refreshed hub against fresh underlying material (D.4) |
| `split-hub` | hub-id | `new_hub_ids: [ids], theme_separation: "..."` — owner split a hub into ≥ 2 narrower hubs (D.4 split-mismatch resolution) |
| `archive-hub` | hub-id | `target_path: "4_archive/...", reason: "..."` — owner archived a hub whose theme is no longer active |
| `apply-lens-proposal` | `lens-action-proposed` item | `action_type: "wikilink_add | hub_stub_create | open_thread_add | decision_update_section", targets: [paths], from_lens: "{lens-id}/{date}", owner_modified: bool` — owner approved (and optionally modified) a queued lens-action proposal; resolver invokes `lens_action_handlers.APPLIERS[type]` and writes a row to `lens-resolution-history.jsonl` |
| `dismiss-lens-proposal` | `lens-action-proposed` / `lens-action-veto` item | `reason: "constitution-conflict | not-actionable | wrong-target | low-quality"` — owner rejected the proposal; row in history.jsonl marks the class_key as `reject` for future precedent grounding |

**Vocabulary governance:**
- Reason codes ending `-suggested` / `-resolved` / `-drift-warn` / `-promote-*` MUST use canonical vocabulary — feed `/ztn:resolve-clarifications` execution
- Reason codes ending `-reminder` / `-surfaced (policy-decision)` / `-advice` MAY use free-form Suggested action — conversational triggers, not executable operations
- New canonical verbs: append-only addition к this table. Removed / renamed verbs = breaking change requires migration of existing Resolved Items

### Cross-skill exclusion

All six pipeline skills (`/ztn:process`, `/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`, `/ztn:content`, `/ztn:roles`) mutually exclusive. Each reads all seven `.{skill}.lock` files в `_sources/` (the six pipelines + `.resolve.lock`) on start. Any other skill's lock exists → abort. `/ztn:content` acquires `.content.lock` when it writes (`--maintain` / `--draft`); its read-only status mode needs no lock. `.content.lock` matters because the maintainer reads `CONTENT_MAP.md` while `/ztn:maintain` Step 7.8 rewrites it. `/ztn:roles` acquires `.roles.lock` for a tick (`--all-due` / `--role` / `--approve-coldstart` / `--approve-acts`, all of which write role state via `roles_persist.py` — `--approve-acts` also executes the staged outward acts + advances the watermark, so it holds the lock through the network writes). The role-management family relates to that same `.roles.lock` in three tiers. `/ztn:role:edit` **acquires** it before writing a role's config / hooks / lifecycle — it mutates existing role state, so it must hold the lock for the write. `/ztn:role:add` **checks** it but never holds it: it aborts if a tick is mid-write (`.roles.lock` present and < 2h old → "roles system busy, try again"), then writes only a fresh role dir — no existing state to corrupt — so it needs the competitor-guard, not the lock itself. The read-only members — `/ztn:role:ask` (the 3-tier question ladder, extracted from the runner) and `/ztn:role:list` — take no lock and skip the check.

`/ztn:resolve-clarifications` acquires `.resolve.lock` for both interactive and `--auto-mode` runs. Interactive mode reads the six pipeline locks (process / maintain / lint / agent-lens / content / roles) and aborts on any. **`--auto-mode` exception for `.lint.lock`:** auto-mode is dispatched by `/ztn:lint` Step 7.5 (lint holds its own lock during dispatch); treating that lock as competitor would deadlock the nightly chain. Auto-mode therefore proceeds when `.lint.lock` exists (it is the dispatcher's signature), aborts silently on any other pipeline lock (those should have cleared at lint's own Step 0.1; presence here means something genuinely went wrong — let the next nightly tick retry).

**Nightly cadence:** two scheduler ticks. Agent-lens at 03:00 (lens production isolated), lint at 05:00 (invariant scans → Step 7.5 dispatches resolve --auto-mode inline → consumes fresh lens hints + new clarifications). The two-hour gap separates lens emission from resolve consumption at the scheduler-agent-context level — the agent that judges proposals in Step A.2/A.3 has not just produced lens body output, which prevents confirmation bias on its own emissions. Lint and resolve in one tick is acceptable because their reasoning shapes are ortogonal (invariant pattern-match vs experienced-owner judgement) — minor contextual bleed in exchange for operational simplicity (one tick consumes the CLARIFICATIONS lint just emitted).

`/ztn:agent-lens-add` (lens creation wizard) is owner-driven, not in the lock matrix. It respects `/ztn:agent-lens`'s lock at pre-flight (would race on registry writes) but does not acquire its own — uses concurrent-edit detection (snapshot at Step 0, re-validate at write) to defend against rare parallel owner invocations.

**`/ztn:bootstrap` не входит в lock matrix** — disposable one-shot skill (запускается при системной инициализации, disaster recovery, onboarding'е друга). User ensures system idle before running bootstrap (runs <1 раз в год после initial setup).

---

## Architecture — Three Layers

ZTN v4 использует три слоя обработки знаний:

| Слой | Путь | Назначение | Формат |
|------|------|-----------|--------|
| Records | `_records/{meetings,observations}/` | Операционные логи transcript-grounded событий: рабочих встреч (`kind: meeting`) и соло Plaud-записей (`kind: observation`) | Лёгкий: summary + key points (+ action items для meetings) |
| Knowledge | PARA (`1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`) | Атомарные инсайты, решения, идеи | Полный frontmatter + structured content |
| Hubs | `5_meta/mocs/` | Синтез и эволюция мышления по теме | Living document с chronological map |

**Принципы обработки:** `5_meta/PROCESSING_PRINCIPLES.md` (source of truth для LLM-суждений)
**Архитектура:** `5_meta/CONCEPT.md` (философия, ADR, примеры)
**Pipeline:** SKILL.md (`/ztn:process`) — полный алгоритм обработки

---

## Repository Structure

```
zettelkasten/
├── _sources/                         # ВСЕ сырые данные (input + processed)
│   ├── inbox/                        # Новые, необработанные файлы
│   │   └── {source-id}/              # Whitelist живёт в _system/registries/SOURCES.md.
│   │                                 # Layout каждой папки определяется колонкой Layout
│   │                                 # на её row: flat-md (*.md в корне) | dir-per-item
│   │                                 # ({folder}/transcript.md) | dir-with-summary
│   │                                 # ({folder}/transcript_with_summary.md preferred).
│   │                                 # Подкаталоги, объявленные в Skip Subdirs, исключены.
│   └── processed/                    # Обработанные файлы (зеркальная иерархия)
│       └── {source-id}/{id}/...
├── _records/                         # Слой 1: Records (операционная память)
│   ├── meetings/                     # Логи многосторонних встреч (kind: meeting)
│   └── observations/                 # Соло-записи: рефлексии, идеи, терапия (kind: observation)
├── _system/                          # Системные файлы (Phase 4.75 layout)
│   ├── SOUL.md                       # Identity + Focus + Working Style
│   ├── TASKS.md                      # Автогенерируемый список задач
│   ├── CALENDAR.md                   # Автогенерируемый календарь
│   ├── POSTS.md                      # Реестр опубликованных постов
│   ├── docs/                         # Платформенные документы (binding)
│   │   ├── SYSTEM_CONFIG.md          # Этот файл — runtime config
│   │   ├── ARCHITECTURE.md           # Системный дизайн
│   │   ├── CONVENTIONS.md            # Documentation style rules (binding)
│   │   ├── batch-format.md           # Контракт batch формата
│   │   ├── constitution-capture.md   # Global hook (symlinked from ~/.claude/rules/)
│   │   └── harness-setup.md          # Per-machine install guide
│   ├── views/                        # Авто-генерируемые представления (read-only)
│   │   ├── CONSTITUTION_INDEX.md     # Registry активных principles
│   │   ├── constitution-core.md      # Harness view (symlinked from ~/.claude/rules/)
│   │   ├── HUB_INDEX.md              # Индекс всех hub-заметок
│   │   ├── INDEX.md                  # Surface catalog (knowledge + archive + constitution + hubs, faceted)
│   │   ├── CURRENT_CONTEXT.md        # Live state snapshot
│   │   └── CONTENT_MAP.md            # Content pipeline interface — view over hubs (writer: /ztn:maintain)
│   ├── state/                        # Pipeline state (write-heavy)
│   │   ├── content-pipeline-state.json  # Content ledger (drafts) — writer: /ztn:content --maintain
│   │   ├── BATCH_LOG.md              # Index всех batch-операций
│   │   ├── PROCESSED.md              # Source → Note маппинг
│   │   ├── CLARIFICATIONS.md         # Human-in-the-loop вопросы от скиллов
│   │   ├── OPEN_THREADS.md           # Незакрытые темы и ожидания
│   │   ├── principle-candidates.jsonl  # Append-only candidate buffer
│   │   ├── log_process.md            # Хронологический лог /ztn:process
│   │   ├── log_maintenance.md        # Append-only лог /ztn:maintain + /ztn:bootstrap
│   │   ├── log_lint.md               # Append-only лог /ztn:lint runs
│   │   ├── batches/                  # Полные batch-отчёты
│   │   └── lint-context/             # Lint Context Store: daily/ (30d rolling) + monthly/ (forever)
│   ├── scripts/                      # Python pipeline (см. scripts/README.md)
│   └── registries/                   # Реестры сущностей и форматные спеки
│       ├── TAGS.md                   # Реестр `tags:` namespace labels
│       ├── SOURCES.md                # Реестр источников
│       ├── FOLDERS.md                # Структура папок (этот layout)
│       ├── CONCEPT_NAMING.md         # Канонический формат concept-имён (snake_case)
│       ├── AUDIENCES.md              # Whitelist `audience_tags` privacy labels
│       ├── AGENT_LENSES.md           # Agent-lens registry
│       └── lenses/                   # Per-lens prompts + frame contract
├── 0_constitution/                   # Behavioural principles layer (Phase 4.5)
│   ├── CONSTITUTION.md               # Root doc — scope, invariants, tree
│   ├── axiom/                        # Tier-1 axioms
│   ├── principle/                    # Tier-2 principles
│   └── rule/                         # Tier-3 rules
├── 1_projects/                       # Активные проекты
│   └── PROJECTS.md                   # Реестр проектов (co-located here since 4.75)
├── 2_areas/                          # Области ответственности
│   ├── work/
│   │   ├── company/
│   │   ├── meetings/
│   │   ├── planning/
│   │   ├── reflection/
│   │   ├── technical/
│   │   └── team/
│   ├── career/
│   └── personal/
│       ├── reflection/
│       ├── health/
│       └── relationships/
├── 3_resources/                      # Ресурсы
│   ├── tech/
│   │   ├── ai-agents/
│   │   ├── architecture/
│   │   ├── fintech/
│   │   └── payments/
│   ├── ideas/
│   │   ├── business/
│   │   └── products/
│   └── people/                       # Профили людей
│       └── PEOPLE.md                 # Реестр людей (co-located with profiles since 4.75)
├── 4_archive/                        # Архив
├── 5_meta/                           # Мета-система
│   ├── CONCEPT.md                    # Архитектурный документ (source of truth)
│   ├── PROCESSING_PRINCIPLES.md      # 8 принципов обработки + values profile
│   ├── templates/
│   ├── workflows/
│   └── mocs/                         # Слой 3: Hubs (синтез и эволюция)
├── 5_skills/                         # Skills
└── 6_posts/                          # Опубликованный контент
```

---

## Naming Conventions

### Files
```
YYYYMMDD-short-semantic-name.md
```
- Дата в начале для сортировки
- Короткое смысловое имя на английском
- Lowercase, дефисы

**Примеры:**
- `20260125-meeting-ivan-petrov-restructuring.md`
- `20260113-idea-game-payment-gateway.md`
- `20260120-reflection-work-life-balance.md`

### Tags
```
category/specific-tag
```
- Lowercase
- Дефисы внутри слов
- Иерархия через `/`

**Примеры:**
- `type/meeting`
- `project/learning-goal`
- `person/ivan-petrov`

### Folders
- Lowercase
- Дефисы
- Без пробелов

### Entity IDs (people, projects)
- Lowercase
- Короткое имя
- `ivan-petrov`, `john-doe`, `acme-payments`, `project-alpha`

---

## Note Formats (v4)

ZTN v4 использует два формата: Record (лёгкий) и Knowledge Note (полный).
Шаблоны: `5_meta/templates/record-template.md`, `5_meta/templates/note-template.md`

### Record Frontmatter (layer: record)

Records have two kinds. `kind: meeting` для multi-speaker встреч; `kind: observation` для solo Plaud-записей. Поле `kind:` обязательно для observation; для meeting опционально (отсутствие = meeting для backward compat).

**Meeting record:**

```yaml
---
id: YYYYMMDD-meeting-{person}-{topic}
title: "Встреча: {тема}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md

layer: record
kind: meeting              # optional — absence implies meeting (backward compat)
people:
  - person-id
projects:
  - project-id
concepts:                  # canonical concept names per CONCEPT_NAMING.md (snake_case ASCII)
  - concept_name_1
origin: work               # privacy trio per ENGINE_DOCTRINE §3.8 — defaults: work / [] / false on meeting
audience_tags: []
is_sensitive: false
tags:
  - record/meeting
  - person/{id}
  - project/{id}
---
```

Body: `## Summary`, `## Ключевые пункты`, `## Решения`, `## Action Items`, `## Упоминания людей`, `## Source`.

**Observation record:**

```yaml
---
id: YYYYMMDD-observation-{topic-slug}
title: "Наблюдение: {тема}"
created: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript_with_summary.md
recorded_at: {ISO timestamp}

layer: record
kind: observation          # mandatory
speaker: {person-id of the owner from SOUL.md Identity; "unknown" если ambiguous}
people:
  - {упомянутые по имени}
projects:
  - {если затронуты}
concepts:                  # canonical concept names per CONCEPT_NAMING.md
  - concept_name_1
origin: personal           # privacy trio — defaults: personal / [] / false on solo Plaud capture
audience_tags: []
is_sensitive: false        # set true on therapy / health / family / financial content
tags:
  - record/observation
  - person/{speaker}
  - topic/{topic}
---
```

Body: `## Summary`, `## Ключевые пункты`, `## Контекст / настроение` (опц.), `## Упоминания людей` (опц.), `## Source`. NO `## Решения` / `## Action Items` (живут в knowledge notes c `extracted_from:`).

Полный шаблон observation: `5_meta/templates/observation-record-template.md`.

### Biometric Record (kind: biometric)

Auto-emitted by `/ztn:process` metric-day branch from
`_sources/inbox/{source-id}/<date>.md` (e.g. `garmin`). One file per
calendar day. NO LLM in the emission path — pure deterministic Python
(`process_metric_day.py`). Owner never hand-edits.

```yaml
---
date: '<YYYY-MM-DD>'
kind: biometric
domains: [health]
people: []
audience_tags: []          # owner-only by family default
is_sensitive: true         # health data → friction on share
origin: personal
device: <source>           # which wearable feed this record belongs to (garmin, oura)
device_estimate: true      # wearable numbers are device estimates, not ground truth
concepts:                  # streak / event concepts emitted by Tier I
  - low_hrv_streak
  - sleep_debt
metric_failures: [...]     # only present when the source carried metric_failures
source: <source>/<date>.md
created: '<YYYY-MM-DDTHH:MM:SSZ>'
source_hash: <16-hex>      # hash of source content; drives metric-record-rerender drift detection
---
```

Body sections (only emit when non-empty):

- `# Biometric — <date>`
- `## Summary` — verbatim from source's `## Summary`
- `## Key Numbers` — extracted top-level YAML (sleep_h, hrv_ms,
  rhr, bb_end, stress_avg, readiness, train_status, acwr, steps,
  vo2max_running, …)
- `## Baseline Deviations` — σ-distance flags (light / medium / strong)
- `## Categorical Events` — status transitions (HRV, training, ACWR, readiness)
- `## Active Streaks` — current streak concepts with day count + start date
- `## Streak Transitions` — start / end events on this date
- `## Source` — wikilink to processed source for traceability

**Family-default privacy trio.** Set declaratively in
`process_metric_day.py` from the SOURCES.md row's `Family: metric-day`:
`is_sensitive: true`, `audience_tags: []`, `origin: personal`. Per-record
override is NOT a normal path — biometric data is owner-only by design.

**Idempotency.** Re-running `/ztn:process` on an already-processed source
is a no-op log line. Content-hash drift between source and existing
record raises `metric-record-rerender` CLARIFICATION (default: skip;
owner picks alternative via resolve).

### Activity Record (kind: activity)

The behavioural sibling of the biometric record — same metric-day pipeline,
the **activity** profile. Auto-emitted by `/ztn:process` from
`_sources/inbox/activitywatch/<date>.md`. One file per calendar day, pure
deterministic Python, owner never hand-edits. Computer-usage / attention
telemetry, NOT physiology — so a distinct `kind` and namespace
(`_records/activity/<source>/`), never under `biometric/`. The heavy
aggregation (Focus-Engineering metrics) runs upstream in the collector
(`minder-activity-collector`); ZTN ingests clean facts and σ-tracks them.

```yaml
---
date: '<YYYY-MM-DD>'
kind: activity
domains: [time, work]      # the meta-practice of running the day + work context
people: []
audience_tags: []          # owner-only by profile default
is_sensitive: true         # window titles / URLs captured verbatim → leak work/client identifiers
origin: personal
device: <source>           # activitywatch
concepts:                  # activity streak concepts (no device_estimate field — measured, not estimated)
  - late_night_work_streak
  - focus_drop_streak
source: <source>/<date>.md
created: '<YYYY-MM-DDTHH:MM:SSZ>'
source_hash: <16-hex>
---
```

Body sections (only emit when non-empty):

- `# Activity — <date>`
- `## Summary` — verbatim from source (scores, switching split, top death loop, categories, rhythm)
- `## Key Numbers` — focus / productivity / combined scores, `sustained_focus_h`,
  `human_switches`/`human_switches_per_active_hour` (genuine fragmentation — AI-coding
  churn split into `ai_assisted_*`), `top_death_loop(s)`, `late_night_ratio`,
  `early_morning_h`, `meeting_h`, work/personal split, `top_category`, `top_project`, …
- `## Baseline Deviations` — σ-flags on the non-sparse metrics only (focus/productivity/
  human-switch-rate/late-night/meeting/longest-block; sparse metrics like
  `early_morning_h` are tracked but never σ-flagged)
- `## Active Streaks` / `## Streak Transitions` — activity streak state
- `## Source` — wikilink to processed source

(No `## Categorical Events` — the activity profile carries no categorical pairs.)
Privacy + idempotency identical to the biometric record. Near-idle days
(`active_h < 0.5`) emit a record but are excluded from baselines and carry no
scores (the collector nulls them).

### Knowledge Note Frontmatter (layer: knowledge)

```yaml
---
id: YYYYMMDD-{type}-{topic}
title: "{Title}"
created: YYYY-MM-DD
modified: YYYY-MM-DD
source: _sources/processed/{source}/{timestamp}/transcript*.md
extracted_from: {record-id}  # если извлечён из record
related_to: {primary-note-id}  # если не primary note из группы (optional)
supersedes: {previous-note-id}  # если пересматривает предыдущее решение (optional)

layer: knowledge
types:
  - decision|insight|reflection|idea|technical
domains:
  - work|career|personal
projects:
  - project-id
people:
  - person-id

# contains: (OPTIONAL — include only when note has tasks/ideas/meetings)
# Omit entirely if all counts are 0 or if the only non-zero count is obvious from type.
#   tasks: N
#   ideas: N

status: actionable|reference|archived
archived_at: YYYY-MM-DD  # REQUIRED when status: archived (per Archive Contract Form A); equals `## Archive Note` date
priority: high|normal|low
content_potential: high|medium  # OPTIONAL — set by pipeline when note has public value
content_type: expert|reflection|story|insight|observation  # OPTIONAL — set with content_potential
content_angle: ["hook1", "hook2"]  # OPTIONAL — ALWAYS a list (single angle = 1-element list); lint A.11 normalizes a stray string
mentions: N  # OPTIONAL — for idea notes, counts how many times idea surfaced across transcripts

concepts:                                 # canonical concept names per CONCEPT_NAMING.md
  - concept_name_1
  - concept_name_2

# Privacy trio per ENGINE_DOCTRINE §3.8.
# `origin` ∈ {personal, work, external}; `audience_tags[]` from
# canonical 5 + AUDIENCES.md extensions; `is_sensitive` is bool.
# Defaults are conservative-safe (`personal` / `[]` / `false`).
origin: personal
audience_tags: []
is_sensitive: false

tags:
  - type/{type}
  - domain/{domain}
  - person/{id}
  - project/{id}
---
```

Knowledge note content: structured по теме (контекст, ключевая мысль, применение, связи).

### Hub Frontmatter (layer: hub)

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
  - work|personal|career
projects: []
people: []

# Privacy trio — auto-derived by `_common.py::recompute_hub_trio()`
# from member-note trios. `_engine_derived` lists fields the engine
# currently owns and re-derives on every touch. Owner takes over a
# field by removing its name from `_engine_derived`; the value is then
# preserved permanently. Hub frontmatter does NOT carry `concepts:` —
# `member_concepts` is manifest-only, derived at emission time.
origin: personal|work|external
audience_tags: []
is_sensitive: false
_engine_derived:
  - origin
  - audience_tags
  - is_sensitive

related_notes: N
first_mention: YYYY-MM-DD
last_mention: YYYY-MM-DD
cadence: daily|weekly|sporadic

status: active|dormant|resolved
priority: high|normal|low

tags:
  - hub
  - domain/{domain}
  - topic/{topic}
---
```

Hub content structure: `## Текущее понимание` (с подсекциями `### Ключевые выводы`,
`### Открытые вопросы`, `### Активные риски`), `## Хронологическая карта`,
`## Связанные знания` (с подсекциями `### Решения`, `### Инсайты`, `### Cross-Domain связи`),
`## Changelog`.

Шаблон: `5_meta/templates/hub-template.md`

### Source Section (вместо `<details>`)

Оригинальный транскрипт НЕ дублируется в заметках — он живёт в `_sources/processed/`.
Записи и заметки содержат `## Source` секцию со ссылкой:

```markdown
## Source

**Transcript:** `_sources/processed/plaud/{timestamp}/transcript_with_summary.md`
**Recorded:** YYYY-MM-DDTHH:MM:SSZ
```

Full-text search по raw content: `grep -r "keyword" zettelkasten/_sources/`

---

## Types (type:)

| Type | Description | Папка по умолчанию |
|------|-------------|-------------------|
| meeting | Встреча, совещание | **DEPRECATED** — новые встречи → `_records/meetings/` как records. Legacy notes в `2_areas/work/meetings/` сохраняются |
| reflection | Рефлексия, размышления | 2_areas/personal/reflection/ |
| task | Задача (редко отдельно) | по контексту |
| idea | Идея | 3_resources/ideas/ |
| decision | Решение | по контексту |
| log | Дневник, отчёт | 2_areas/personal/ |
| planning | Планирование | 2_areas/work/planning/ |
| technical | Техническое | 2_areas/work/technical/ или 3_resources/tech/ |
| reference | Справка | 3_resources/ |
| person | Профиль человека | 3_resources/people/ |
| project | Описание проекта | 1_projects/ |
| record | Операционный лог transcript-grounded события (kind: meeting или observation) | `_records/meetings/` (встречи) или `_records/observations/` (соло Plaud) |
| hub | Hub — синтез и эволюция по теме | 5_meta/mocs/ |

---

## Domains (domain:)

| Domain | Description |
|--------|-------------|
| work | Работа (проекты, команда, планирование) |
| career | Карьера (повышение, развитие) |
| personal | Личное (рефлексия, здоровье) |

---

## Statuses (status:)

| Status | Description |
|--------|-------------|
| actionable | Требует действий |
| waiting | Ждёт чего-то |
| someday | Когда-нибудь |
| reference | Просто информация |
| archived | В архиве |

---

## Archive Contract

**Invariant:** every archival event captures a reason. The reason lives **with the entity** — never in a parallel log, never as derived state. One source of truth per archived entity.

Archival event = transition where an entity stops being part of the active surface: knowledge-note moved to `4_archive/`, frontmatter `status: archived`, principle `status: archived`, registry row moved to a Deprecated/Stale section, lens `status: paused|archived`, person tier dropped to `stale`, candidate dismissed via CLARIFICATION resolution.

This contract applies **forward-only**: every archival event from contract adoption onward MUST carry a reason. Pre-existing archived entities are not backfilled.

### Form by entity shape

Three forms — pick by shape, not by skill. Every archival pathway falls into exactly one.

#### Form A — Inline `## Archive Note` (file-based entities)

For knowledge notes, hubs, principles (axiom / principle / rule), and any other entity that exists as a standalone `.md` file. Append-only block at the **end** of the file (after Evidence Trail, before any other trailing sections):

```markdown
## Archive Note

- date: YYYY-MM-DD
- reason: "<one-sentence rationale in owner's natural language>"
- triggered_by: owner | /ztn:lint F.3 | /ztn:resolve-clarifications | <skill-id>
- superseded_by: [[wikilink]]   # optional — when archival is due to replacement
```

Plus frontmatter flags for machine-readable state:

```yaml
status: archived
archived_at: YYYY-MM-DD
```

Frontmatter `archived_at` MUST equal `## Archive Note` `date`. Skill enforcement: any writer that flips `status: archived` MUST append `## Archive Note` in the same atomic write. Writing one without the other = contract violation; surfaces as `archive-note-missing` CLARIFICATION on next `/ztn:lint`.

`triggered_by` value is the agent of the archival event — `owner` for direct hand-edits, the skill id (`/ztn:lint`, `/ztn:resolve-clarifications`, etc.) for engine-driven archivals. When a skill applies a CLARIFICATION resolution, the skill id wins (not `owner`); the resolution text is what carries the owner's reasoning into `reason`.

**Constitution-principle exception (single-source-of-truth guard).** Files under `0_constitution/{axiom,principle,rule}/` already use the Evidence Trail pattern. Per `0_constitution/CONSTITUTION.md` §9, archiving a principle appends a `deprecated` entry of the form `deprecated — reason: {reason}; status: archived` to the Evidence Trail. **That entry IS the Form A storage for principles** — do not also append a `## Archive Note` block. The `deprecated` Evidence Trail entry is the contract-required reason for principles; frontmatter `status: archived` is the machine flag (no `archived_at` — Evidence Trail entry date is the authoritative date).

#### Form B — `Reason` column (registry-row entities)

For entities whose canonical form is a row in a registry table — PEOPLE.md, PROJECTS.md, SOURCES.md, AGENT_LENSES.md, TASKS.md.

**Canonical pattern: split table.** Each registry holds active rows and archived rows in **separate tables / sections**. The archived sub-table carries a `Reason` column; the active table does not. Archival = move the row from the active table to the archived sub-table and populate `Reason`. This keeps active rows clean (no empty trailing cells) and makes archival a discrete writer operation.

Where the archived sub-table lives per registry:

| Registry | Active section | Archived sub-table |
|---|---|---|
| `3_resources/people/PEOPLE.md` | `## People` (tier 1 / 2 / 3) | `## Stale People` (tier `stale`) |
| `1_projects/PROJECTS.md` | `## Active Projects`, `## Completed Projects` | `## Archived Projects` (status `archived` — dropped before completion; completed projects are not an archival event and do not require Reason) |
| `_system/registries/SOURCES.md` | `## Active Sources`, `## Reserved Sources` | `## Deprecated Sources` |
| `_system/registries/AGENT_LENSES.md` | `## Active Lenses`, `## Draft Lenses` | `## Paused/Archived Lenses` (status `paused` / `archived`) |

**Bullet-list variant for `_system/TASKS.md`.** Tasks live in bullet lists, not tables. The Stale section MUST carry a trailing `*(reason)*` italic suffix on every bullet — this is the bullet-list equivalent of the `Reason` column. Example: `- [ ] Подготовить презентацию для встречи в Баку — [[20260114-baku-presentation]] ^task-prepare-baku-presentation *(Баку прошло)*`.

Skill enforcement: any writer that moves a row into an archived sub-table (or a bullet into TASKS Stale) MUST populate `Reason` / `*(reason)*`. Empty cell or missing italic surfaces as `archive-reason-missing` CLARIFICATION on next `/ztn:lint`.

#### Form C — Existing structured field (queue-based archival)

For archival driven by a CLARIFICATIONS resolution or by a candidate-buffer dismissal, the reason already lives in an existing structured field. The contract does not invent new fields — it makes existing ones **required** for the archival sub-set of actions.

| Source | Field | Required for actions |
|---|---|---|
| `_system/state/CLARIFICATIONS.md` Resolved Items | `**Rationale:**` | every action whose effect is archival: `dismiss`, `dismiss-duplicate`, `archive-hub`, `close-thread`, `demote-tier`, `merge-notes` (the merged-away side), `pursue-or-close` with `choice: close` |
| `_system/state/people-candidates.jsonl` weekly-dismissed archive | `dismissal_reason` | every line written to `lint-context/weekly/{YYYY-WW}-people-candidates-dismissed.jsonl` |
| `_system/state/OPEN_THREADS.md` Resolved section | `resolution_text` (already required by `close-thread` action) | every entry under `## Resolved` |
| `_system/roles/{id}/parts/{part_id}.json` | `paused_reason` | a role part's auto-pause (`status: paused`) — `roles_persist.py` writes the reason (3 consecutive rejects) into this structured field; the `config.yml` `status: paused` inline comment is a redundant human-visible mirror, and the `role-auto-paused` CLARIFICATION surfaces it. The `paused_reason` field IS the contract-required reason |

Skill enforcement: any resolution that triggers archival without populating the required field surfaces as `archive-reason-missing` CLARIFICATION.

**Out of scope for Form C:** weekly bulk-archive of `principle-candidates.jsonl` via `archive_buffer.py` is a buffer-rollover snapshot, not a per-line rejection event — it preserves history of all candidates (promoted and rejected alike). Per-candidate rejection reason lives in the CLARIFICATIONS resolution that disposed of that candidate (Form C row 1).

### Cross-cutting rules

- **Atomic write.** The archival flag (`status: archived` / row move / tier change) and the reason (`## Archive Note` / `Reason` column / required field) MUST land in the same write. No two-stage archival.
- **Append-only.** Archive Notes and Reason cells are written once at archival time. Owner can later edit free-form text but never deletes the structure. Re-archival of an already-archived entity is a no-op (idempotency); a second `## Archive Note` block is forbidden.
- **No parallel log.** There is no `log_archival.md`. Cross-entity «what was archived in period X» is a derived view, generated on demand by reading the entities themselves.
- **Lint enforcement.** `/ztn:lint` adds an Archive-contract scan that emits `archive-note-missing` / `archive-reason-missing` CLARIFICATIONs for entities found in archived state without the required reason. Forward-only: pre-contract archived entities are not flagged.
- **Suggested-action vocabulary stays unchanged.** The canonical `Resolution-action` table above already carries `reason` payload examples (`dismiss`, `demote-tier`, `archive-hub`); this contract elevates them from documented-payload to enforced-required for the archival subset.

---

## Concepts (concepts:)

Open-vocabulary semantic anchors — every "thing-in-the-world" the
knowledge base tracks. Format and rules: `_system/registries/CONCEPT_NAMING.md`.

- **Field on:** records (meeting + observation), knowledge notes,
  project profiles. NOT on hubs (hubs carry `member_concepts[]` only
  in the manifest, derived from members) and NOT on person profiles
  (people are first-class entities; their identifier is `firstname-lastname`).
- **Format:** snake_case ASCII `[a-z0-9_]`, length 1–64, no forbidden
  type prefix, English-only (translate non-English source terms; never
  transliterate).
- **Type lives in metadata, not in name.** The 18-enum
  (`theme`/`tool`/`decision`/`idea`/`event`/`organization`/`skill`/
  `location`/`emotion`/`goal`/`value`/`preference`/`constraint`/
  `algorithm`/`fact`/`other` — `person` and `project` reserved but
  not emitted by ZTN) lives in manifest `concepts.upserts[].type`.
- **Autonomous resolution.** Engine resolves every format issue via
  `_system/scripts/_common.py::normalize_concept_name()`; never raises
  CLARIFICATIONs (see ENGINE_DOCTRINE §3.1 layer-specific exception).

## Privacy Trio (origin / audience_tags / is_sensitive)

Three orthogonal slots on every entity per ENGINE_DOCTRINE §3.8.
Spec: `_system/registries/AUDIENCES.md` for `audience_tags`.

| Field | Type | Default | Spec |
|---|---|---|---|
| `origin` | enum `personal \| work \| external` | path-derived (see Lint Step 1.D); else `personal` | Source provenance — does NOT determine sharing scope |
| `audience_tags` | `text[]` | `[]` (owner-only) | Whitelist: canonical 5 (`family`/`friends`/`work`/`professional-network`/`world`) ∪ active extensions in AUDIENCES.md |
| `is_sensitive` | bool | `false` | Friction modifier on share — orthogonal to audience |

- **On records, knowledge notes, hubs, person profiles, project
  profiles, principles, every Tier 1/2 typed object.**
- **Hub auto-derivation:** `recompute_hub_trio()` fills MISSING fields
  from members (dominant origin / audience intersection / sensitivity
  contagion); never overwrites owner-set values.
- **Lint Step 1.D backfill** fills missing trio on existing entities
  (one-time migration on first lint run after the engine adopts the
  trio). `origin` derives from path:
  `_records/meetings/*` and `2_areas/work/*` → `work`; everything else
  → `personal`. `audience_tags` defaults to `[]` (sharing intent is
  owner-curated, never auto-assigned). `is_sensitive` defaults to
  `false` (content-driven, owner refines).

## Content Potential Fields

Three optional fields set together when a note has public sharing value.
Omit all three if note is purely operational, private, or context-free.

### content_potential: high|medium

| Value | When to set |
|-------|------------|
| high | Personal experience illustrating professional principle; specific technical insight/decision; industry opinion; career/leadership reflection; original business/product angle; useful workflow/process; personal reflection with universal resonance |
| medium | Interesting kernel not fully developed; public topic but private context needs rework; fragment that could combine with other notes into a post |
| (omit) | Purely operational, private, or context-free content |

### content_type: expert|reflection|story|insight|observation

| Type | What it is |
|------|-----------|
| expert | Professional/technical knowledge, architectural decisions, domain expertise |
| reflection | Personal introspection, psychology, self-analysis, therapy insights |
| story | Narrative arc — career journey, personal experience, life event |
| insight | Non-obvious connection, counter-intuitive observation, pattern recognition |
| observation | Lightweight seed thought, casual noticing, not yet developed |

Closed set — `/ztn:process` emits exactly one of these five; lint Scan A.11 heals
any drift (`CANON_MAP` in `lint_content_markup.py`).

### content_angle: ALWAYS a YAML list of strings

Each angle is one sentence — the "why would someone read this?" framing.
Written in the owner's language (the draft is conceptual; platform/translation
are publish-time choices).

**Always a list** (single angle = 1-element list) — uniform shape so consumers
never branch on string-vs-list. Lint Scan A.11 normalizes a stray bare string
(`content-angle-format` autofix).

```yaml
# Single angle (most notes) — still a list
content_angle:
  - "Why delegation is hard for tech leads"

# Multiple angles (each becomes a distinct post candidate)
content_angle:
  - "Childhood perfectionism → adult control patterns"
  - "Why delegation is hard for tech leads — it's not about trust"
```

**content_type drift → canonical mapping.** The non-canonical values producers
sometimes emit (technical, idea, decision, …) are mapped to the canonical five by
lint Scan A.11. The mapping table is owned in one place —
`_system/scripts/lint_content_markup.py::CANON_MAP` (synonym rows autofix; judgment
rows surface as CLARIFICATIONs). See `/ztn:lint` SKILL Scan A.11 for the method.

---

## Folder Routing Logic

При определении папки для заметки:

1. **По layer (приоритет v4):**
   - record + `kind: meeting` (или kind отсутствует) → `_records/meetings/`
   - record + `kind: observation` (solo Plaud: reflection / idea / therapy) → `_records/observations/`
   - hub → `5_meta/mocs/`

2. **Несколько types** → выбираем по приоритету:
   - project → 1_projects/
   - meeting → 2_areas/work/meetings/ [DEPRECATED в v4 для новых заметок, используй _records/meetings/]
   - planning → 2_areas/work/planning/
   - technical + domain/work → 2_areas/work/technical/
   - technical + ideas → 3_resources/tech/
   - idea → 3_resources/ideas/
   - reflection → 2_areas/personal/reflection/
   - person → 3_resources/people/

3. **По domain если неясно:**
   - work → 2_areas/work/
   - career → 2_areas/career/
   - personal → 2_areas/personal/

4. **По контенту:**
   - проекты, команда, планирование → 2_areas/work/
   - AI, LLM, архитектура → 3_resources/tech/
   - Бизнес-идеи → 3_resources/ideas/business/
   - Продуктовые идеи → 3_resources/ideas/products/

---

## Processing Workflow (/ztn:process)

Pipeline обработки определён в SKILL.md (`/ztn:process`).

Краткая последовательность:
0. Pre-Scan — People Resolution Map (three-tier: RESOLVED / NEW / AMBIGUOUS), hub signal matching
1. Load Context — SYSTEM_CONFIG, PROCESSING_PRINCIPLES, registries, hubs, CLARIFICATIONS
2. Find New Files — scan `_sources/inbox/`, sort chronologically, move to `_sources/processed/`
3. **Process Files (per-batch full-pipeline subagents)** —
   Orchestrator partitions chronologically-sorted file list into batches
   (T = 250k input tokens, N = 6 transcripts max per batch, max 3 parallel
   subagents). Each subagent runs 3.1–3.7 for every transcript in its
   batch in shared context, returns manifest with notes + coverage data.
   - 3.1 Read transcript (two formats: with/without summary) — *in subagent*
   - 3.2 LLM Noise Gate (genuine vs noise, inclusion-biased) — *in subagent*
   - 3.3 Semantic Context Loading (resolve people, load hubs from briefing) — *in subagent*
   - 3.4 LLM Classification (14 questions) — *in subagent*
   - 3.5 Create Outputs (records, knowledge notes, hub updates/creates, cross-domain) — *in subagent*
   - 3.6 Structural Verification — *in subagent*
   - 3.7 **Self-Review** — producer-side coverage manifest (PEOPLE / TOPICS / DECISIONS / ACTIONS) reconciled against produced notes, fixes applied in place — *in subagent*
   - 3.7.5 Constitution Alignment Check — *in orchestrator, post-aggregate*
   - 3.8 People Profiles (create/update, CLARIFICATIONS for uncertain) — *in orchestrator, post-aggregate*
   - 3.9 System updates (PROCESSED, LOG) — *in orchestrator*
   - 3.10 Verify source integrity (file completeness invariant: union of subagent-processed paths = enumerated source set) — *in orchestrator*
4. Post-Processing — TASKS, CALENDAR, HUB_INDEX, content potential verification, batch verification
5. Completion Gate — mandatory checklist, halt-on-error, no deferring
6. Report — summary with coverage fix rate and clarifications

Принципы обработки: `5_meta/PROCESSING_PRINCIPLES.md`
Архитектура: `5_meta/CONCEPT.md`

---

## Entity Matching

### Before creating any new entity:

```
1. Normalize name (lowercase, dashes, transliterate if needed)
2. Search in registry:
   - Exact match
   - Fuzzy match (similar names)
3. If found → use existing
4. If not found → create new → add to registry
```

### Name normalization:
- "Иван Петров" → "ivan-petrov"
- "Acme Payments" → "acme-payments"
- "Learning Goal" → "learning-goal"
- "AI Agents" → "ai-agents"

---

## People Profiles

When a person is mentioned:

1. Check PEOPLE.md registry
2. If exists → add mention link to their profile
3. If not exists:
   - Create profile in 3_resources/people/{id}.md
   - Add to PEOPLE.md registry

### Profile format:
```markdown
---
id: ivan-petrov
name: "Иван Петров"
role: CEO
org: acme
tags:
  - person/ivan-petrov
  - org/acme
  - role/ceo
---

# Иван Петров

**Role:** CEO @ Acme

## Контекст
[Описание роли и отношений]

## Упоминания
- [[20260125-meeting-ivan-petrov|Встреча 25 января]] — example link
```

---

## Task Format

### Inline в заметках (source)

```markdown
- [ ] Описание задачи → [[связь]] ^task-unique-id
- [x] Завершённая задача ✅ YYYY-MM-DD ^task-id
```

Task IDs: уникальные в рамках файла, формат `^task-short-description`.
Примеры: `^task-write-letter-ivan-petrov`, `^task-prepare-presentation`.

### Aggregate в TASKS.md (maintained by /ztn:process — incremental merge + reconciler backstop)

**Структура (6 секций):**

1. **Action — я делаю** — owner is the executor
2. **Waiting — жду от других** — другой человек должен прислать/дать результат owner'у
3. **Delegate — контролирую выполнение** — owner назначил/эскалировал, отслеживает
4. **Someday** — низкий приоритет / идеи на будущее
5. **Personal** — не связано с работой
6. **Stale** — кандидаты на удаление (устарели, поглощены, потерян контекст)

Внутри каждой секции — группировка по **потоку** (`### Stream Name`).
Потоки органические: создавай по мере появления кластеров задач —
кластеризация по теме / проекту / области ответственности; имена потоков
определяются органически из контента, а не предзаданы.

**Форматы по типу:**
```markdown
# Action:
- [ ] Description — [[note-link]] ^task-id

# Waiting:
- [ ] **@person-id** What I'm waiting for — deadline — [[note-link]] ^task-id

# Delegate:
- [ ] **@person-id** What they're doing — deadline — [[note-link]] ^task-id
```

**Правила классификации (Action / Waiting / Delegate):**

Owner-first-name = first name from SOUL.md `## Identity` `Name:` line. Skill resolves it at runtime.

| Признак | Тип |
|---------|-----|
| Источник: «{owner-first-name}: ...» / first-person speech (`I:` / `я:`) / задача явно для исполнения owner'ом | Action |
| Источник: «@person: ...» и owner — получатель результата (ответ, документ, данные) | Waiting |
| Owner поставил задачу / эскалировал / ведёт как owner-of-tracking, output нужен команде/процессу, не лично owner'у | Delegate |
| Не ясно кто исполнитель | Action (безопасный дефолт) |

**Практический маркер Waiting vs Delegate:**
- Waiting = «owner не может двигаться, пока X не ответит» (блокер для owner'а)
- Delegate = «X работает над задачей, owner следит за прогрессом» (owner как менеджер)

**Stale preservation (важно):**
При регенерации TASKS.md **секция Stale сохраняется** — прочитай текущий файл,
извлеки task-id из секции Stale, при записи новой версии положи их обратно в Stale
(не возвращай в активные секции, даже если в source note всё ещё `- [ ]`).
Stale — это результат ручного ревью пользователя, машина его не переопределяет.

**Шапка TASKS.md (обновляется каждую регенерацию):**
```markdown
**Last Updated:** YYYY-MM-DD
**Open:** N action / N waiting / N delegated / N someday / N personal
**Stale candidates:** N
**Total unique:** N
```

---

## Event/Meeting Format

### Inline в заметках (source)

```markdown
- 📅 **YYYY-MM-DD HH:MM** — Описание события ^meeting-id
```

### Aggregate в CALENDAR.md (maintained by /ztn:process — incremental merge; best-effort reconciler)

**Структура (4 секции):**

1. **Recurring** — регулярные встречи (маркер 🔄)
2. **Upcoming** — будущие одноразовые события owner'а (маркер 📅)
3. **Deadlines** — чужие дедлайны которые owner отслеживает (маркер ⏰, префикс `**@person**`)
4. **Past** — **только последние 2 недели**; более старые удаляются при регенерации

**Форматы:**
```markdown
# Recurring:
- 🔄 **День недели ЧЧ:ММ МСК** — Описание — [[note-link]]

# Upcoming:
- 📅 **YYYY-MM-DD** — Описание события — [[note-link]]

# Deadlines:
- ⏰ **YYYY-MM-DD** — **@person-id**: что они должны сделать — [[note-link]]

# Past:
- 📅 **YYYY-MM-DD** — Описание — [[note-link]]
```

---

## Language Rules

1. **Tags, types, IDs** → English
2. **Note content (title, text)** → Same language as source
3. **Folder names** → English
4. **Frontmatter keys** → English

---

## Quality Checklist

Before saving each note:
- [ ] ID matches filename
- [ ] All mentioned people exist in registry
- [ ] All mentioned projects exist in registry
- [ ] Tags follow naming convention
- [ ] Source section links to raw transcript in `_sources/processed/`
- [ ] Links use [[wikilink]] format
- [ ] Tasks have unique ^task-id
- [ ] Contains section exists if note has tasks/ideas/meetings (optional otherwise)

---

## Files Reference

| File | Purpose | Updated |
|------|---------|---------|
| _system/docs/SYSTEM_CONFIG.md | This file — runtime config (formats, routing, types) | Manual |
| _system/SOUL.md | Identity + Focus + Working Style | Manual + /ztn:bootstrap (once) |
| _system/state/OPEN_THREADS.md | Active open threads + resolved history | /ztn:bootstrap, /ztn:maintain, /ztn:resolve-clarifications (writers per Skill Write Territory) |
| _system/views/CURRENT_CONTEXT.md | Live state snapshot for thin orientation | /ztn:maintain, /ztn:lint |
| _system/views/INDEX.md | Surface catalog of knowledge + archive + constitution + hubs (PARA / domains / cross-domain / hubs facets); records and posts intentionally out of scope | /ztn:bootstrap Step 5.5, /ztn:maintain Step 7.6, regen_all.py — all via `_system/scripts/render_index.py` |
| _system/state/log_lint.md | Append-only log of /ztn:lint runs | Each /ztn:lint |
| _system/state/log_maintenance.md | Append-only log of /ztn:maintain + /ztn:bootstrap runs | Each /ztn:maintain / /ztn:bootstrap |
| _system/state/log_process.md | Chronological log of /ztn:process operations | Each /ztn:process |
| _system/state/log_agent_lens.md | Append-only log of /ztn:agent-lens runs | Each /ztn:agent-lens |
| _system/state/agent-lens-runs.jsonl | Machine index of every agent-lens run (one JSON line per run) | Each /ztn:agent-lens |
| _system/state/check-decision-runs.jsonl | Append-only audit substrate of `/ztn:check-decision` invocations. Two `kind`'s per line — `run` (mechanical fields always; optional self-report `intent` / `pre_confidence` / `expected_verdict` when caller supplies) and `followup` (post-action signal). Sensitive runs omit `situation_text` + `rationale`, keep `situation_hash`. Consumers: `decision-review` lens (Layer A enrichment via `record_ref` exact match; Layer B aggregate observations on rolling 30-day window). Schema is forward-additive — unknown fields treated as no-signal by consumers, never fail. Substrate is never compacted / aggregated; rotation by year only when volume warrants. | Each /ztn:check-decision (run + optional followup) |
| _system/state/.check-decision-telemetry.lock | Advisory `flock` serialising telemetry emission (run + followup) from concurrent /ztn:check-decision invocations. Narrow scope — does NOT cover Evidence Trail edits to `0_constitution/` (existing pre-emission race surface, out of telemetry scope). | /ztn:check-decision (helper acquires + releases) |
| _system/state/agent-lens-rejected/{lens}/{ts}.md | Raw Stage 2 outputs that failed structural validator | On validator rejection |
| _system/agent-lens/{lens}/{date}.md | Structured agent-lens observation outputs | Each successful /ztn:agent-lens lens run |
| _system/registries/AGENT_LENSES.md | Agent-lens registry (active/draft/paused, cadence, schema) | /ztn:agent-lens-add (table row append on creation) + Manual (owner edits) + /ztn:agent-lens (status updates only on auto-pause) |
| _system/registries/lenses/{id}/prompt.md | Per-lens prompt + frontmatter | /ztn:agent-lens-add (creates new lens) + Manual (owner edits) |
| _system/registries/lenses/_frame.md | Two-stage frame (thinker + structurer) + validator rules | Manual (engine-shipped) |
| _system/state/lint-context/daily/*.md | 30-day rolling daily summaries | Each /ztn:lint |
| _system/state/lint-context/monthly/*.md | Append-forever monthly summaries | First /ztn:lint of new UTC month |
| _system/state/BATCH_LOG.md | Append-only index of batch operations | Each /ztn:process |
| _system/state/batches/{id}.md | Full batch reports (one per /ztn:process run) | Each /ztn:process |
| _system/docs/batch-format.md | Batch format contract — markdown report + JSON manifest; per-entity privacy trio + concept fields; sections `## Concepts Upserted` + `## Sensitive Entities` | Manual (bump version on change) |
| _system/state/PROCESSED.md | Source → Note mapping | Each /ztn:process |
| _system/TASKS.md | All open tasks | Regenerated |
| _system/CALENDAR.md | All events | Regenerated |
| _system/POSTS.md | Published posts archive + content strategy | Manual or /ztn:content |
| _system/views/CONTENT_MAP.md | Content pipeline interface — compact view over hubs + content notes + POSTS.md (ripeness, posts-on-theme) | /ztn:maintain Step 7.8 (canonical writer; regenerable, read-only) |
| 5_meta/mocs/hub-cognitive-model.md | Cognitive-model hub — per-axis projection of `cognitive_axes`-tagged principles + candidate buffer (axis set is the SoT in `lenses/cognitive-model/prompt.md`); AUTO-GENERATED zone between markers, owner «portrait» above | /ztn:maintain Step 7.9 via `render_cognitive_model_hub.py` (owner-data; managed zone regenerable) |
| _system/state/content-pipeline-state.json | Content ledger — per-draft state (theme_ids[], ripeness, draft_status, owner_touched) | /ztn:content --maintain (NOT regenerable) |
| _system/state/CLARIFICATIONS.md | Non-blocking human-in-the-loop questions | All skills (safety valve) |
| _system/registries/TAGS.md | Tag registry (`tags:` namespace labels) | When new tags |
| _system/registries/CONCEPT_NAMING.md | Spec — canonical concept-name format (engine-shipped) | Manual (engine maintainer) |
| _system/registries/AUDIENCES.md | Spec + extensions for `audience_tags` privacy labels | /ztn:resolve-clarifications (extension append on owner approval) + Manual (owner edits) |
| 1_projects/PROJECTS.md | Project registry | When new projects |
| 3_resources/people/PEOPLE.md | People registry | When new people |
| _system/registries/FOLDERS.md | Folder structure | Rarely |
| _system/views/HUB_INDEX.md | Index of all hub notes | /ztn:maintain (rebuild) + /ztn:process (additive on hub create) — writers per Skill Write Territory |
| 5_meta/CONCEPT.md | Architecture, philosophy, ADRs (human reference) | Manual |
| 5_meta/PROCESSING_PRINCIPLES.md | 8 principles + values profile (LLM guidance) | Manual |
