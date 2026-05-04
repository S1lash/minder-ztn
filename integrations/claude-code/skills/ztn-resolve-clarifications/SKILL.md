---
name: ztn:resolve-clarifications
description: >
  Interactive facilitator for the owner's CLARIFICATIONS queue. Pre-syncs
  via /ztn:sync-data so the queue reflects state from all devices, then
  loads open items, clusters by Type, presents one theme at a time as a
  numbered batch (≤5 items, adaptive — 3 for heavy types, 5 for light),
  reminds full situation + verbatim quotes already stored in the file,
  pre-checks values-bearing items against the constitution, proposes
  resolution with labelled options, applies confirmed actions (silent
  for archival ops, diff-first for content edits), archives resolved
  items and re-prioritises deferred ones. After resolutions, refreshes
  derived views (/ztn:regen-constitution if principle accepts; /ztn:maintain
  if registries / hubs touched) and reminds owner to run /ztn:save when
  the working tree is dirty. Manual, owner-driven —
  never dumps the whole queue, never asks the owner to recall meeting
  context unaided.
disable-model-invocation: false
---

# /ztn:resolve-clarifications — Interactive Clarifications Facilitator

The owner's queue at `_system/state/CLARIFICATIONS.md` accumulates
ambiguities surfaced by producer skills. Reviewing it as a flat list is
high-friction: the owner has no fresh context for the underlying meeting,
items mix trivial (people-bare-name) with values-loaded (org-tension,
principle-candidate), and resolution mechanics differ per Type.

This skill turns review into a guided conversation: one theme per round,
numbered questions, full context reminded inline, decisions applied
mechanically, queue cleaned after.

**Documentation convention:** при любых edits этого SKILL соблюдай
`_system/docs/CONVENTIONS.md` — файл описывает current behavior без
version/phase/rename-history narratives.

## Arguments

`$ARGUMENTS` supports:
- `--theme <type>` — pick a specific Type cluster directly, skip the menu
- `--max <N>` — override adaptive batch size (default: 3 heavy / 5 light)
- `--dry-run` — render the round but do not apply any resolution
- `--no-constitution` — skip constitution lookup even for values-bearing items
- `--continue` — after closing one round, immediately offer the next theme
- `--no-sync` — skip Step 0 pre-sync (offline review, known-current state)
- `--no-refresh` — skip Step 9 post-resolution refresh (`/ztn:regen-constitution`,
  `/ztn:maintain`); owner promises to run them manually
- `--no-save` — skip the Step 9.5 save reminder (commit later by hand)

---

## Step 0: Pre-sync

Before acquiring the lock, invoke `/ztn:sync-data` inline. Owner may be
working from a multi-device setup (phone captures, server processing,
laptop A vs laptop B); reviewing a stale CLARIFICATIONS queue wastes the
owner's attention on items already resolved elsewhere.

Behaviour:
- Up-to-date or no `origin` → continue silently to the lock step.
- Pulled commits → report one-line recap («синхронизировался: pulled
  N commits, K new clarifications») then continue.
- Working tree dirty → `/ztn:sync-data` aborts with its own message;
  surface it verbatim to the owner and exit (owner runs `/ztn:save`
  first, then re-invokes this skill).
- Conflict during rebase → `/ztn:sync-data` aborts and prints recovery
  instructions; surface verbatim and exit.
- Unsupported in `--dry-run` mode → still run sync (read-mostly; only
  effect is moving local HEAD), since stale data poisons the dry-run
  preview too.

Skip the sync only when `--no-sync` is passed (escape hatch for offline
review or known-current state). The skill never auto-syncs after Step 0
— the owner's session works against the snapshot taken here.

## Concurrency Lock

This skill writes to CLARIFICATIONS.md and may edit profiles / records.
Producer skills (`/ztn:process`, `/ztn:lint`, `/ztn:maintain`) write to
the same files. Mutual exclusion required.

Read all three before starting:
- `_sources/.processing.lock` — abort «`/ztn:process` running»
- `_sources/.maintain.lock` — abort «`/ztn:maintain` running»
- `_sources/.lint.lock` — abort «`/ztn:lint` running»

1. Create `_sources/.resolve.lock` with `{ISO timestamp} — {session info}`
2. Delete it on every exit path (normal, error, abort, early exit)
3. Stale lock (>2h) — warn and offer to clear

Views (`constitution-core.md`, `CURRENT_CONTEXT.md`, etc.) are read as-is
during Steps 1–7. Regeneration is deferred to Step 9 (post-resolution
refresh) and runs only when this session's resolutions actually touched
the underlying source of truth.

---

## Step 1: Load Context

Read these system files (in parallel where possible). Default-on for
all rounds, regardless of Type — owner context is a hard prerequisite
for sane hypothesis forming, not a values-only concern.

| File | Why |
|---|---|
| `_system/docs/ENGINE_DOCTRINE.md` | Operating philosophy, owner-LLM contract |
| `_system/docs/SYSTEM_CONFIG.md` | CLARIFICATIONS schema, note formats |
| `_system/views/constitution-core.md` | Tier-1 axioms — background frame for every hypothesis |
| `_system/SOUL.md` | Identity, focus, working style — drives hypothesis defaults |
| `3_resources/people/PEOPLE.md` | Mandatory for person-identity / people-bare-name resolution |
| `1_projects/PROJECTS.md` | Mandatory for project-identity |

Conditional / on-demand (load only when round contains relevant Types):

| File | Trigger |
|---|---|
| `_system/state/OPEN_THREADS.md` | `thread-closure-suggested` items |
| `_system/views/HUB_INDEX.md` | `thread-closure-suggested`, `cross-domain-link`, `hub-stale-vs-material` |
| `_system/views/INDEX.md` | `index-missing`, `index-stale`, `index-frontmatter-malformed` (heartbeat — usually resolves by running `/ztn:maintain`) |
| `_system/views/CURRENT_CONTEXT.md` | values-bearing rounds (org-tension, decisions) |
| `5_meta/PROCESSING_PRINCIPLES.md` | `principle-candidate-batch` rounds |
| `_system/scripts/query_constitution.py --domains <d>` | escalate when constitution-core lacks the principle needed to form a confident hypothesis (typically values-bearing items) |

**Concept and audience CLARIFICATIONs are never raised by the engine.**
The autonomous-resolution layer (`/ztn:lint` Scan A.7 +
`_system/scripts/lint_concept_audit.py` + `_common.py` normalisers)
auto-fixes or silent-drops every concept/audience format issue. This
skill therefore does NOT receive `concept-format-mismatch`,
`concept-type-prefix-in-name`, `concept-name-too-long`,
`audience-tag-unknown`, `audience-tag-reserved-conflict`, or
`audience-tag-format-mismatch` items — they don't exist as
CLARIFICATIONs. The Extensions table in `_system/registries/AUDIENCES.md`
remains owner-curated outside the pipeline; if owner wants to widen the
audience whitelist they edit AUDIENCES.md directly, no resolve flow.

**Context-only invariant.** Files in this section are read but never
written by this skill. The only writes go through the «Output Files
Touched» list in Step 7.

**Constitution as proposal accelerator, not validation gate.** The point
of loading the constitution is to let the skill pre-form a confident
hypothesis (option `a`) so the owner can one-click confirm instead of
recalling values from memory. Missing a relevant principle is not a
safety failure — at worst the skill proposes a weaker `a` and the owner
overrides. So default to cheap (`constitution-core.md` always-on); only
escalate to `query_constitution.py --domains <d>` when forming the
hypothesis genuinely needs the deeper tree (typically values-bearing
items). Skipped entirely under `--no-constitution`.

---

## Step 2: Load and Parse Queue

Read `_system/state/CLARIFICATIONS.md`. Parse all entries under
`## Open Items` (and any sub-section like `## maintain {batch-id}` /
`## lint {date}` — those are open by convention until archived).

Each entry is a `### {date} — {title}` block followed by labelled fields:
`**Type:**`, `**Subject:**`, `**Source:**`, `**Action taken:**`,
`**Quote:**`, `**Context:**`, `**Uncertainty:**`, `**To resolve:**`,
optionally `**Confidence tier:**`, `**Suggested action:**`, `**Status:**`.

Build an in-memory list of items with parsed fields and original raw
markdown block (for safe archiving later — never re-render, copy
verbatim).

If the schema deviates (missing fields, unexpected sub-section names) —
continue best-effort. Surface anomalies in the round-close report;
never delete an item that didn't parse cleanly.

**Early exit:** zero open items → report «Очередь пуста — ничего разбирать»
and stop (release lock).

**Pre-resolve scan:** any item whose title or Confidence tier already
contains `RESOLVED` — these were marked done by the producer but not yet
archived. Auto-archive them silently in Step 7 without asking the owner.
Report count in the menu («3 уже-RESOLVED закрою без вопроса»).

---

## Step 3: Cluster by Type

Group remaining items by `**Type:**`. Compute per-cluster size and
weight. Standard Types (extend as new ones appear in producer skills):

| Type | Weight | Default batch |
|---|---|---|
| `people-bare-name` | light | 5 |
| `person-identity` | light | 5 |
| `content-pipeline-reminder` | light | 5 |
| `process-compatibility` | light | 5 |
| `thread-closure-suggested` | medium | 4 |
| `idea-ambiguous-match` | medium | 4 |
| `evidence-trail-anomaly` | medium | 4 |
| `topic-classification` | medium | 4 |
| `cross-domain-link` | medium | 4 |
| `project-identity` | medium | 4 |
| `org-structure-tension` | heavy | 3 |
| `principle-candidate-batch` | heavy | 3 |
| `decision-*` | heavy | 3 |
| unknown / new | medium | 4 |

`--max N` overrides. Light = quick approve/dismiss; heavy = each item
demands reading + values-judgment.

---

## Step 4: Theme Menu

Render single screen — numbered list with weight hints and recency:

```
Очередь CLARIFICATIONS — {N} open ({M} уже-RESOLVED закрою тихо)

Темы (выбери номер):
  1. people-bare-name (4)        — лёгкая · ~5 мин · самое старое 2026-04-23
  2. person-identity (1)          — лёгкая · ~2 мин · 2026-04-27
  3. principle-candidate-batch (4) — тяжёлая · требует размышления · 2026-04-27
  4. content-pipeline-reminder (1) — лёгкая · можно одной командой
  5. process-compatibility (1)    — техника · 2026-04-27

Введи номер темы (или `q` — выйти).
```

If `--theme <type>` was passed → skip menu, jump to Step 5 with that
cluster.

If owner picks `q` → release lock, exit. Pre-resolved items stay
archived (Step 7 already ran for them).

---

## Step 5: Render Round

Take the chosen cluster. Slice to batch size (heavy 3 / light 5 / `--max N`).
If cluster larger than batch → first N items by recency (oldest first —
fresh items fade later); subsequent rounds will pick up the rest.

For each item in the batch, render with the **mandatory seven blocks**.
Order matters — owner reads top-down without prior session context, so
the *essence* must come first, then files for direct access, then
procedural context, citations, and proposals.

```
── Q{n} ── {date} — {short title from the entry header}

🧩 Суть:
{1–2 plain-language sentences: what is this about, what is the problem,
what decision is being asked. No jargon, no wikilinks, no file paths.
A reader who has never seen this item should grasp the question from
this block alone. MANDATORY on every item — light or heavy.

For person-identity: «В записи X (про Y) неизвестно кто Z. Нужно
подтвердить identity или dismiss.»
For thread-closure: «Thread X открыт N дней; есть/нет signals что
закрылся. Решаем — закрыть или нет.»
For principle-candidate: «N кандидатов в принципы накопилось. Решаем по
каждому — accept в constitution / reject / defer.»
For policy/values: «N records carry inconsistent state for {field};
решаем policy A/B/C про N.»}

📂 Files:
{Exact file paths the owner can open directly: record path, source
transcript path, any related profile / hub / view. Use repo-relative
paths. Include `:line` anchors when there is a specific line. Wikilinks
are fine ALONGSIDE paths but never instead of them.}

📍 Где это случилось:
{2–3 sentence procedural context derived from **Context:** field — when,
what meeting / call / pipeline run, what action the producer took. If
Context is absent, summarise Source path + Action taken. This is the
«timeline» block, not the «what is the problem» block — that's «Суть»
above.}

💬 Цитаты (verbatim):
{copy **Quote:** field as-is — already verbatim by item-format
contract. If Quote is `_(none — pipeline-level issue)_`, show that
literally.}

🧭 Конституция / soul:
{Render this block when there is an actual hit that strengthens the
hypothesis — not gated by Type. Procedure: scan constitution-core
(always loaded) for relevance to the item; for values-bearing items
where core has nothing or is too coarse, escalate to
query_constitution.py --domains <d>. If no principle is relevant —
omit the block entirely (do not render an empty header). When
rendering: list 1–3 principles with id + 1-line statement + verdict
(aligned / violated / tradeoff / no-match) + one-line rationale tying
the item to the principle. Goal of this block is to make option `a`
more confident, not to gatekeep the resolution.}

🎯 Гипотеза:
{Skill's pre-formed proposal — what the owner most likely wants to do,
with reasoning. For person-identity: best-match candidate from PEOPLE.md
+ alternatives. For thread-closure: signals fired vs not. For principle-
candidate: own assessment of whether it clears the bar. Always state
the reasoning ground; never just "I think X".}

✅ Варианты:
  {For HEAVY items (cluster weight «heavy» per Step 3 — org-structure-tension,
  principle-candidate-batch, decision-*, semantic-drift / policy), each
  primary option (a/b/c) MUST include three micro-sections:}

  a) {one-line label}
     - **Что меняется:** {2–3 specifics — files, behaviour, schema, prompt}
     - **Что приносит:** {2–3 positive outcomes — clarity, correctness, perf}
     - **Риски / потери:** {1–2 things owner has to accept / things that may break}
  b) {one-line label}
     - **Что меняется:** ...
     - **Что приносит:** ...
     - **Риски / потери:** ...
  c) {one-line label}
     - ...

  {For LIGHT items (person-identity, people-bare-name, process-compatibility,
  content-pipeline-reminder): one-line options are sufficient; add a 1-line
  clarifier only when the action is non-obvious.}

  d) skip — оставить открытым в текущей форме (показать снова в следующий раз)
  e) defer — оставить открытым с пометкой `**Last reviewed:** {today} — deferred`,
     уйдёт в конец очереди при следующем выборе темы
  f) dismiss — закрыть как not-actionable, в архив с пометкой `Resolution: dismissed`

  Skip / defer / dismiss are universal escape hatches — never expanded with
  micro-sections; they have fixed semantics.
```

Always include c/d/e on every item — they are universal escape hatches.
Number questions Q1, Q2, … sequentially across the batch (not per-cluster
restart). Owner answers like:

```
Q1: a
Q2: b — собеседник Ivan Petrov, добавь как primary speaker
Q3: dismiss
Q4: skip
```

Multi-line answers per question are normal — parse loosely.

---

## Step 6: Apply Resolutions

For each answered question, classify the action:

**Class A — silent ops (no diff, just do):**
- `c` skip — no-op, item stays as-is
- `d` defer — append `**Last reviewed:** {today} — deferred` line to
  the item block (in-place edit, append-only line)
- `e` dismiss — move item to `CLARIFICATIONS_ARCHIVE.md` with
  `**Resolution:** {today} — dismissed: {one-line owner rationale or
  "not actionable"}` appended to the block; remove from open file
- `a/b` for `process-compatibility`, `content-pipeline-reminder`,
  `evidence-trail-anomaly` archival cases (no content edit needed) —
  same as dismiss but with substantive `Resolution:` text

**Class B — content edits (diff-first):**
- Profile creation (person-identity → `3_resources/people/{slug}.md` +
  PEOPLE.md row + people-frontmatter backfill in cited records)
- Note frontmatter edits (people:, projects:, threads:)
- Hub edits (open questions, current understanding bullets)
- OPEN_THREADS.md state changes (open → resolved)
- Decision-note creation (typically already created by the producer
  skill; here only when owner explicitly requests)
- Constitution edits — **never auto**. Principle-candidate accepts
  always render the proposed `0_constitution/{type}/{domain}/{slug}.md`
  body and ask for explicit confirm before write.

For Class B: render unified diff or new-file body, ask `[y/N]` per file.
On `y` → write. On `N` → re-prompt with the original options (a/b/c/d/e)
for that question. The diff gate is friction — but it's the only gate
where the owner can catch the skill misreading their answer.

**Archive Contract enforcement (cross-cutting, applies to any Class A or Class B action whose effect is archival):**

Per `_system/docs/SYSTEM_CONFIG.md → Archive Contract`, every archival event MUST carry a reason captured **with the entity**. When applying the actions below, the skill is responsible for writing the contract-required field in the same atomic operation as the archival flag. Skipping the field is a contract violation; a follow-up `/ztn:lint` Archive-contract scan will surface it as `archive-note-missing` / `archive-reason-missing` CLARIFICATION.

| Resolution-action | Archive Contract form | Required write |
|---|---|---|
| `archive-hub` | Form A (file-based) | Move hub `.md` from `5_meta/mocs/` to `4_archive/` per `target_path` payload AND append `## Archive Note` block at the end of the hub file with `date: today`, `reason: {payload.reason}`, `triggered_by: /ztn:resolve-clarifications`, optional `superseded_by` if the resolution mentioned one. Frontmatter `status: archived` + `archived_at: today` flipped if the hub file uses the `archived` status (knowledge-style); for hub-status `resolved` the Archive Note alone is the canonical record. |
| `dismiss` | Form C (queue) | The `**Rationale:**` line on the resolved CLARIFICATION block (what Step 7 already writes). Required for archival-effect dismissals — never leave the rationale empty for these. |
| `dismiss-duplicate` | Form C (queue) | Same as `dismiss`. |
| `merge-notes` (the merged-away note) | Form A (file-based) | Append `## Archive Note` to the merged-away note BEFORE removing it from active surface, with `reason: "merged into [[kept-note-id]]"`, `triggered_by: /ztn:resolve-clarifications`, `superseded_by: [[kept-note-id]]`. Move the merged-away file to `4_archive/` (do not delete). |
| `close-thread` | Form C (queue) | The `resolution_text` payload populates the Resolved-section entry in `OPEN_THREADS.md`. Required for every `close-thread` and `pursue-or-close` with `choice: close`. |
| `demote-tier` (to `stale`) | Form B (registry-row) | Move the row from `## People` to `## Stale People` in `PEOPLE.md` and populate the `Reason` cell with `payload.reason`. Same atomic write — never leave the row half-moved. |

For all other Resolution-actions whose effect is non-archival (promotion, refresh, restructure), no Archive Contract write is required.

**Class C — auto-invoked refresh (Step 9):**

Some resolutions invalidate derived views or registries. Track which
classes of writes happened during the session (counters, not file lists):

| Counter | Incremented by | Triggers in Step 9 |
|---|---|---|
| `constitution_writes` | principle-candidate accept (new file under `0_constitution/{type}/{domain}/`) | `/ztn:regen-constitution` |
| `registry_writes` | person-identity (new profile + PEOPLE.md row), project-identity (PROJECTS.md), thread-closure (OPEN_THREADS.md), hub edits (`5_meta/mocs/`) | `/ztn:maintain` |
| `content_pipeline_writes` | `content-pipeline-reminder` accept | suggest `/ztn:check-content` (do NOT auto-invoke — content review is a separate owner gesture) |

These are surfaced + acted on by Step 9. The skill no longer leaves
them as text suggestions in the round-close report.

---

## Step 7: Archive and Clean

Rewrite `CLARIFICATIONS.md` in place:

1. Read current file fresh.
2. Remove blocks for: pre-resolved items (Step 2 scan), all dismissed
   items, all `a/b`-resolved items.
3. Update in-place: deferred items get `**Last reviewed:**` line
   appended; skipped items unchanged.
4. Update top-of-file `**Last reviewed:**` field to today's date with
   short summary: `(YYYY-MM-DD — resolve session: closed N, deferred
   M, dismissed K, skipped S)`.
5. Append removed blocks to `CLARIFICATIONS_ARCHIVE.md` under a new
   `## Archived YYYY-MM-DD (resolve session)` section, in original order,
   each with `**Resolution:**` line appended.

On any error during this step: do not leave the file half-written.
Restore via `git checkout -- _system/state/CLARIFICATIONS.md` and
report the failure. Owner is responsible for working from a clean tree;
git is the rollback mechanism.

---

## Step 8: Round Close + Continue

Per-round report (printed after Step 7 each round, BEFORE Step 9):

```
Раунд закрыт — тема: {type}

  ✅ Закрыто: {N}     {one-line list of what got resolved}
  ⏸  Deferred: {M}    {short list}
  ⏭  Skip: {S}        {short list}
  🗑  Dismiss: {K}    {short list}
  🔁 Pre-resolved: {auto}

Осталось в очереди: {remaining} items в {remaining-themes} темах.

{If --continue passed: jump to Step 4 with refreshed counts.}
{Else: «Запустить ещё круг? — `y` или укажи тему: …». Wait for owner.}
```

When the owner declines further rounds (or queue empties) → proceed to
Step 9. Lock is held through Step 9 and released at the end.

---

## Step 9: Post-resolution refresh + save reminder

Always runs after the rounds end (even pure defer/skip/dismiss sessions
leave CLARIFICATIONS.md / ARCHIVE.md dirty and need a save reminder).
Sub-steps gate independently on what actually happened.

### 9.1 — Release lock first

Delete `_sources/.resolve.lock` before any Step 9.2 / 9.3 invocation
and before printing the save reminder. Two reasons:
- `/ztn:save` checks `_sources/.resolve.lock` and refuses if held —
  the owner running save next would hit a confusing abort.
- Cleanliness — the session's writes are committed in CLARIFICATIONS.md
  by Step 7 already; the lock has no further purpose.

`/ztn:maintain` and `/ztn:regen-constitution` do NOT check
`.resolve.lock` today, so the order of 9.1 vs 9.2/9.3 is not load-
bearing for them — but releasing first keeps the invariant simple
(no producer skill ever sees a stranded lock from this skill).

### 9.2 — Constitution refresh

Fires only if `constitution_writes > 0` and `--no-refresh` not passed.
- Print: «Записал N новых принципов — обновляю constitution-core view…»
- Invoke `/ztn:regen-constitution` inline.
- On failure → print the skill's error verbatim, continue to 9.3 (don't
  block other refreshes on one failure).

### 9.3 — Registry / hub refresh

Fires only if `registry_writes > 0` and `--no-refresh` not passed.
- Print: «Тронул N registries / hubs — запускаю /ztn:maintain для
  пересборки HUB_INDEX / INDEX / CONCEPTS…»
- Invoke `/ztn:maintain --no-sync-check` inline (Step 0 already synced;
  double-sync is wasteful and may surprise the owner with a second
  rebase preview).
- On failure → print the skill's error verbatim, continue.

### 9.4 — Content pipeline reminder

If `content_pipeline_writes > 0`:
- Print suggestion only, do NOT auto-invoke: «можешь прогнать
  `/ztn:check-content` — есть свежие content candidates».

### 9.5 — Save reminder

`/ztn:save` per its contract is **never auto-fired by other skills** —
it stays an explicit owner gesture. This step only reminds, never
invokes.

Compute `git status --porcelain` to detect dirty files (any of:
CLARIFICATIONS.md / ARCHIVE.md from Step 7, profile / record edits
from Class B, regen / maintain outputs from 9.2 / 9.3).

If dirty and `--no-save` not passed:
```
Сессия закрыта. Изменено файлов: <K>

  Закоммить и пушни когда готов:
    /ztn:save
```
If clean → print «Working tree clean — nothing to commit». Exit.

### 9.6 — Final recap

```
Сессия завершена.
  Резолюций: <closed>     Deferred: <M>     Dismissed: <K>
  Refreshes: constitution=<y/n/skipped>  maintain=<y/n/skipped>
  Working tree: <dirty K files | clean>
```

---

## Constraints

- **Essence first, never optional.** Every Q opens with `🧩 Суть:` —
  1–2 plain-language sentences. Owner is reading without session context
  on items often a week+ old; without «суть» up-front the procedural
  blocks below require mental reconstruction of «о чём это вообще» on
  every item. This rule is load-bearing on round friction.
- **Never recall meeting context unaided.** Every Q also renders the
  `📍 Где это случилось:` block. If the entry has no Context field and
  Source path leads to a missing file — say so explicitly, do not
  fabricate context.
- **Quotes are verbatim.** Never paraphrase the `**Quote:**` field. If
  it's empty / `_(none)_` — render that as-is.
- **Numbered questions across the whole round** — Q1..Qn, not Q1..Qm
  per cluster.
- **One theme per round.** No bulk operations across themes. Owner
  decides whether to chain via `--continue`.
- **Diff-gate is non-negotiable for Class B.** Even on unambiguous `a`
  answers, show the proposed write before applying.
- **Constitution lookup is opt-out (`--no-constitution`), default-on**
  via the always-loaded `constitution-core.md`. Deeper queries
  (`query_constitution.py`) escalate when needed — typically on
  values-bearing items, but the trigger is «hypothesis would benefit
  from more context», not Type. The skill renders the `🧭 Конституция`
  block only when there is a real hit; omits silently otherwise.
- **Non-personal-origin principle candidates always require manual
  review.** Items tagged `origin: work` or `origin: bootstrap-raw-scan`
  go through the diff gate even if the round logic could otherwise
  auto-archive them. Constitution stays signal-only.
- **No re-render of stored blocks.** When archiving, the block markdown
  is copied verbatim plus a `**Resolution:**` line. Never normalise
  fields, never strip whitespace — preserves audit trail.
- **Sync before review (`--no-sync` to opt out).** Reviewing a stale
  queue wastes attention on items already resolved on another device.
  Step 0 always fronts the session unless owner opts out explicitly.
- **Refresh fires only on material writes.** Sub-steps 9.2 / 9.3 run
  `/ztn:regen-constitution` / `/ztn:maintain` only when this session
  produced principle accepts / registry edits respectively. Pure
  defer/skip/dismiss sessions still trigger 9.1 (lock release) and
  9.5 (save reminder) — the working tree is dirty either way.
- **Save is never auto-invoked.** Step 9.5 prints a reminder; the
  owner runs `/ztn:save` themselves. This preserves `/ztn:save`'s
  contract («never auto-fired by other skills»).
- **Lock released before any 9.2/9.3/9.5 step.** `/ztn:save` checks
  `.resolve.lock` and would refuse if held; releasing in 9.1 keeps
  the invariant simple regardless of which sub-steps fire.

---

## Output Files Touched

Direct writes by this skill (Steps 1–8):
- `_system/state/CLARIFICATIONS.md` — items removed / deferred-line appended
- `_system/state/CLARIFICATIONS_ARCHIVE.md` — resolved blocks appended
- `_sources/.resolve.lock` — created/deleted
- `3_resources/people/{slug}.md` — when person-identity → create-profile
- `3_resources/people/PEOPLE.md` — registry rows added/updated
- `_records/{meetings,observations}/{note}.md` — frontmatter `people:` / `projects:` / `threads:` updates
- `5_meta/mocs/{hub}.md` — open questions / current understanding edits when thread-closure
- `_system/state/OPEN_THREADS.md` — thread state moves
- `0_constitution/{type}/{domain}/{slug}.md` — principle accepts (creates only)

Indirect writes via Step 9 chained skills:
- `/ztn:sync-data` (Step 0) — `git fetch` + rebase / fast-forward against `origin`
- `/ztn:regen-constitution` (Step 9.2) — `_system/views/constitution-core.md`,
  `_system/SOUL.md` Values zone, `_system/views/CONSTITUTION_INDEX.md`
- `/ztn:maintain` (Step 9.3) — `_system/views/HUB_INDEX.md`,
  `_system/views/INDEX.md`, `_system/registries/CONCEPTS.md`, registry hygiene
- `/ztn:save` (Step 9.5) — NOT invoked by this skill; reminder only,
  owner runs explicitly per save's contract

(Concept/audience format issues do NOT pass through this skill —
autonomous resolution by `/ztn:lint` Scan A.7 handles them
upstream. AUDIENCES.md Extensions table is owner-curated outside
the pipeline.)

## What This Skill Does NOT Do

- Does not invent new ambiguities — only resolves what producers wrote.
- Does not edit principle bodies in `0_constitution/` (only creates new
  files on accept).
- Does not invoke `/ztn:save` — Step 9.5 reminds, owner runs.
- Does not reorder or rewrite open items beyond the deferred-line append.
- Does not auto-resolve Class B without diff confirmation, even on
  unambiguous owner answers.
- Does not back up CLARIFICATIONS.md before writing — git is the
  rollback mechanism.
- Does not auto-invoke `/ztn:check-content` — content review is a
  separate owner gesture; Step 9.4 only suggests it.
