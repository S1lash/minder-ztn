---
name: ztn:resolve-clarifications
description: >
  Interactive facilitator for the owner's CLARIFICATIONS queue. Loads
  open items, clusters by Type, presents one theme at a time as a
  numbered batch (≤5 items, adaptive — 3 for heavy types, 5 for light),
  reminds full situation + verbatim quotes already stored in the file,
  pre-checks values-bearing items against the constitution, proposes
  resolution with labelled options, applies confirmed actions (silent
  for archival ops, diff-first for content edits), archives resolved
  items and re-prioritises deferred ones. Manual, owner-driven —
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

---

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

Views (`constitution-core.md`, `CURRENT_CONTEXT.md`, etc.) are read as-is.
This skill does NOT regenerate them — that is the producer skills'
responsibility. If the owner edited `0_constitution/` directly and wants
fresh views before reviewing, they run `/ztn:regen-constitution` first.

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
| `_system/views/HUB_INDEX.md` | `thread-closure-suggested`, `cross-domain-link` |
| `_system/views/CURRENT_CONTEXT.md` | values-bearing rounds (org-tension, decisions) |
| `5_meta/PROCESSING_PRINCIPLES.md` | `principle-candidate-batch` rounds |
| `_system/registries/CONCEPT_NAMING.md` | `concept-format-mismatch`, `concept-type-prefix-in-name`, `concept-name-too-long` items — the spec defines proposed-canonical computation and resolutions |
| `_system/registries/AUDIENCES.md` | `audience-tag-unknown`, `audience-tag-reserved-conflict`, `audience-tag-format-mismatch` items — the spec defines reserved-keyword test, format rules, and the **add-extension** flow (append a row under `<!-- BEGIN extensions -->` marker on owner approval, never silently rewrite) |
| `_system/scripts/query_constitution.py --domains <d>` | escalate when constitution-core lacks the principle needed to form a confident hypothesis (typically values-bearing items) |

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

For each item in the batch, render with the **mandatory five blocks**:

```
── Q{n} ── {date} — {short title from the entry header}

📍 Где это случилось:
{2–3 sentence summary derived from **Context:** field. If Context is
absent, summarise Source path + Action taken. Goal: owner reads this
once and knows what meeting/call this is about without opening any
file.}

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
  a) {primary action — the hypothesis above as one-click confirm}
  b) {alternative action}
  c) skip — оставить открытым в текущей форме (показать снова в следующий раз)
  d) defer — оставить открытым с пометкой `**Last reviewed:** {today} — deferred`,
     уйдёт в конец очереди при следующем выборе темы
  e) dismiss — закрыть как not-actionable, в архив с пометкой `Resolution: dismissed`
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

**Class C — propose follow-up command (do not invoke):**
- `content-pipeline-reminder` → suggest «запустить `/ztn:check-content`?»
- `principle-candidate` accept → suggest «`/ztn:regen-constitution` после
  записи принципа?»

The skill prints the suggestion alongside the round-close report; owner
runs the command (or not) at their discretion.

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

Final report:

```
Раунд закрыт — тема: {type}

  ✅ Закрыто: {N}     {one-line list of what got resolved}
  ⏸  Deferred: {M}    {short list}
  ⏭  Skip: {S}        {short list}
  🗑  Dismiss: {K}    {short list}
  🔁 Pre-resolved: {auto}

Осталось в очереди: {remaining} items в {remaining-themes} темах.

{Class C suggestions, if any: «можно запустить /ztn:check-content для
закрытия content-pipeline-reminder»}

{If --continue passed: jump to Step 4 with refreshed counts.}
{Else: «Запустить ещё круг? — `y` или укажи тему: …». Wait for owner.}
```

If owner declines or queue is empty → release lock, exit clean.

---

## Constraints

- **Never recall meeting context unaided.** Every Q renders the
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

---

## Output Files Touched

- `_system/state/CLARIFICATIONS.md` — items removed / deferred-line appended
- `_system/state/CLARIFICATIONS_ARCHIVE.md` — resolved blocks appended
- `_sources/.resolve.lock` — created/deleted
- `3_resources/people/{slug}.md` — when person-identity → create-profile
- `3_resources/people/PEOPLE.md` — registry rows added/updated
- `_records/{meetings,observations}/{note}.md` — frontmatter `people:` / `projects:` / `threads:` updates
- `5_meta/mocs/{hub}.md` — open questions / current understanding edits when thread-closure
- `_system/state/OPEN_THREADS.md` — thread state moves
- `0_constitution/{type}/{domain}/{slug}.md` — principle accepts (creates only)
- `_system/registries/AUDIENCES.md` — append row to Extensions table on `audience-tag-unknown` → add-to-registry resolution; status updates to `deprecated:{date}` on retire flow; spec sections never edited by this skill
- `_records/**/*.md`, `_sources/processed/**/*.md`, knowledge-note frontmatter — `concepts:` and `audience_tags:` value rewrites on map-to-existing / drop / format-fix resolutions of concept and audience CLARIFICATION codes

## What This Skill Does NOT Do

- Does not invent new ambiguities — only resolves what producers wrote.
- Does not regenerate derived views — that is the producer skills' job.
  Owner runs `/ztn:regen-constitution` manually if they edited
  `0_constitution/` directly between sessions.
- Does not edit principle bodies in `0_constitution/` (only creates new
  files on accept).
- Does not invoke other skills — proposes follow-up commands; owner runs.
- Does not reorder or rewrite open items beyond the deferred-line append.
- Does not auto-resolve Class B without diff confirmation, even on
  unambiguous owner answers.
- Does not back up CLARIFICATIONS.md before writing — git is the
  rollback mechanism.
