---
id: stated-vs-lived
name: Stated vs Lived
type: psyche
input_type: records
cadence: biweekly
cadence_anchor: monday
self_history: longitudinal
status: active
---

# Stated vs Lived

## Intent

Notice the gap between what the owner **declares** (`0_constitution/` axioms, principles, rules; `_system/SOUL.md` Goals, Focus, Values; explicit "X matters to me" statements in records) and where attention **actually goes** (per the content of records).

**This is NOT a verdict.** Not "you are not doing what you said." Make the gap visible so the owner can decide which of three readings holds.

## Three readings — surface all three, do not choose

From ACT (values vs committed action) + MI (developing discrepancy) + Argyris/Schön (espoused theory vs theory-in-use):

- **(a) Action gap** — the declaration is current; behaviour has drifted. Owner's move: re-engage committed action. Marker: declaration is recent or recently reaffirmed; records show frustration or guilt about the gap.
- **(b) Priority shift** — actual priorities have reordered; the lived side reflects a newer truth not yet declared. Owner's move: update the declaration. Marker: lived-side topic shows growing engagement, positive affect, voluntary investment.
- **(c) Stale declaration** *(Argyris/Schön — espoused theory would update if revisited)* — the declaration was true at time-of-writing but went quiet. It does not contradict the lived side, but is not reaffirmed either. Owner's move: remove or rewrite. Marker: declaration is old, never revisited, no recent records reaffirm AND no records contradict.

Surface all three readings with their distinguishing markers. The owner decides which is true.

## Sources to read

**Declared side:**
- `0_constitution/` — axioms, principles, rules. The values layer.
- `_system/SOUL.md` — Goals, Focus, Values, Working Style.

**Lived side (where attention goes):**
- `_records/` — primary lived signal, raw. Match the window to the declaration's timescale (see below).
- `_records/activity/{source}/` (when non-empty) — the **direct, measured lived-attention ledger**: where the owner's computer hours actually went, in seconds, not inferred from mention-frequency. Read each day's Key Numbers (`work_h`/`personal_h`, `top_category`, `top_project`, `meeting_h`, `late_night_ratio`, `focus_score`/`productivity_score`) and, when present, the weekly rollup `_system/views/activity/{source}/weekly-{recent}.md`. This is the strongest lived-side evidence for any declaration about work focus, deep work, or a specific project: a goal declared in SOUL but whose category-time / `top_project` time is near-zero across the window is a hard **action-gap** signal; a project the owner rarely mentions yet spends hours in is a **priority-shift** signal. Activity n=1 framing applies — associations and measured time, never causation; cite the record/view path. Do NOT bulk-load raw event JSON; the Key Numbers + weekly view are the contract.
- `_system/TASKS.md` — work in flight, completion rate (declared next-actions → followed through, or not). Personal section ≠ work section — keep them separate.
- `_system/state/OPEN_THREADS.md` — what is consciously held as open.
- `1_projects/PROJECTS.md` + project files (`1_projects/{slug}.md` or `{slug}/` folders) — **project-handle layer**. A goal with no project-counterpart here is a strong signal of declaration-without-execution-handle.
- `5_meta/mocs/` + `_system/views/HUB_INDEX.md` — hubs are pre-aggregated attention signal: note-count + last-update + cross-domain tags compress what's in `_records/`. Useful when records are too dense for direct survey or when probing whether a topic has structured representation at all.
- `2_areas/`, `3_resources/` — areas of ongoing responsibility, resources for ongoing reference. Absence of a declared topic from these layers + absence from `1_projects/` = topic exists only in identity-document.
- git log on the base itself — engine/system evolution is also lived attention. `git log --since=<window>` over `0_constitution/`, `5_meta/`, `_system/registries/lenses/`, `1_projects/` shows what the owner is actually building.

**Self-history:**
- Your own past outputs at `_system/agent-lens/stated-vs-lived/` — as an index of **gap recurrence**, not as evidence (see Self-history). On first run no past outputs exist — say so; recurrence claim is impossible on the first run.

**Excluded from lived-side evidence:**
- `_sources/processed/describe-me/**` — bootstrap input INTO the system, written once during onboarding. Mentioning a topic / project name there is a SEED, not lived attention — do not count it as a record-side signal.
- `_sources/processed/` raw transcripts — covered by their derived `_records/` notes; don't double-count.

## Health goal adherence (when biometric layer is active)

When `_records/biometric/` is non-empty AND SOUL.md `## Goals`
declarations include health-quantifiable goals (sleep ≥X hours, work
out N×/week, stress reduction), compute adherence as a parallel
reading of "stated vs lived". Biometric records + state are per
wearable device: `_records/biometric/{source}/<date>.md` and
`_system/state/biometric/{source}/` where `{source}` ∈ `garmin`,
`oura`. Read both devices when present and report one adherence
reading; if only one has data, use that one (never error on the
missing one):

- **sleep ≥X hours.** Read last 7d / 28d biometric records' Key
  Numbers (`sleep_h`) from each device present; count days meeting
  target. Report rate. If both devices cover the same day, compare
  inline and footnote any divergence (e.g. «sleep_h: Garmin 7.1 vs
  Oura 6.8 — Oura logs ~20 min less most nights»).
- **workout N×/week.** Count workout-days in declared window from
  Garmin (`acute_load > 0` OR `intensity_vigorous_min > 5`) — these
  are Garmin-only metrics; Oura does not track training load. Oura
  `activity_score` may corroborate active days when Garmin is absent.
- **stress reduction.** Trend `stress_avg` last 28d vs prior 28d
  from `_system/state/biometric/{source}/baselines.json` per device.

Read `_system/state/biometric/{source}/streaks.json` per device for
active deviation-streak concepts that contradict declarations (e.g.
owner declared «sleep matters» on 2026-04-15; `sleep_debt` streak
active since 2026-05-04 → action gap).

Bring biometric anchoring into the standard 3-reading output —
health adherence gap is one parallel reading, not a verdict. Per
biometric-lens-protocol n=1 caveat: phrase as «Garmin reports
adherence is X» / «Oura reports adherence is X», never «sleep
adherence is X».
- Other lens outputs in `_system/agent-lens/{other-lens}/` — that is meta-territory, belongs to lens-output-input lenses, not this one.

## Domain alignment

Engine doctrine (`ENGINE_DOCTRINE.md` §1.5): the work / personal axis is **owner-defined, not engine-imposed**. Some bases use a binary work + personal split; others use richer domain vocabularies (`identity`, `relationships`, `health`, `learning`, etc); some use blended freelance contexts; some have no work context at all.

**Match domains, do not cross them.** A declaration in domain X should be compared with records in domain X. Determine the domain of a record from `domains: [...]` in frontmatter, from people involved (Org column in PEOPLE.md), or from content. If the base uses a different domain vocabulary than you expect, follow what the base uses — do not impose a default.

A cross-domain axiom (`tier: 1`, often `domain: identity` or `ethics`) usually describes HOW to act, not WHERE to put attention — see the "method-axiom" anti-pattern below.

## Window selection

The lived-side window should match the declaration's timescale. Very short windows carry high variance (per ESM literature, Csikszentmihalyi) — a claim about a gap on a too-short window is weak. The table below lists **starting points only**; the frame's contract gives you free read access — if the pattern asks for longer history, take it.

| Declaration timescale | Suggested lived-side window |
|---|---|
| Annual goal / yearly focus | quarterly (~90 days) |
| Quarterly focus / monthly priority | 30-60 days |
| Weekly habit / weekly value | 14-21 days |
| Daily practice | a couple of weeks at minimum to see signal |

### Window-vs-data-density mismatch

The base may be **younger than the requested window**. If owner asks for 90д but `_records/` only has 6w of density, you cannot honestly claim 90-day patterns. Detection: scan filenames in `_records/meetings/` and `_records/observations/` — earliest date defines actual data start.

When mismatch detected:

1. **Surface it** in a methodological note (not silently use the shorter window).
2. **Calibrate confidence per claim by timescale match:**
   - Weekly-habit / monthly-priority claims fit even short data → keep nominal confidence.
   - Quarterly-focus claims on <8w data → downgrade by one step (high → medium, medium → low).
   - Annual-goal / long-term-goal claims on <12w data → mark as **window-undercalibrated**, not a hit. Suggest the owner re-run after more density accrues, or look at proxy lived-side (project-handle layer, hub note-count) instead of records density.
3. **Do not fabricate longer history** by reading bootstrap input or describe-me content as if it were records.

## "Where attention goes" — multi-signal weight, not count

Record count is one signal among several. From ACT VLQ (Importance × Consistency) and ESM methodology: an honest claim rests on **multiple independent signals**, not on one count alone.

| Signal | What it captures | Textual cue |
|---|---|---|
| Mention frequency | Crude attention proxy | N records mentioning topic / window |
| Talk-vs-do ratio | Plans vs concrete actions taken | "I want to / I need to" vs "I did / I shipped / I called" |
| Completion rate | % of declared next-actions followed through | TASKS `[ ]` → `[x]` evolution over the window |
| Time-block evidence | Concrete duration markers | "3 hours on", "all morning", "weekend went to" |
| Recurring concrete actions | Rituals / repeats vs one-off bursts | Daily / weekly patterns |
| Emotional energy | Affect attached to the topic | excitement / dread / relief / guilt |
| Initiative locus | Self-driven vs reactive | "I started" vs "had to" / "got pulled into" |
| Cross-domain bleed | Topic colonises unrelated entries | A health-value reference inside a work-record indicates real centrality |
| Silence / displacement | What is NOT in records when it should be | A declared health priority + zero references over the matched window |
| Project handle absence | Declared mid-/long-term goal without a counterpart in `1_projects/PROJECTS.md` (active or idea), no project file, no hub | Goal "Достичь дохода от X" exists only in SOUL.md; no `1_projects/X.md`, no `hub-X` — declaration without execution handle |
| Hub aggregation | Hub note-count + last-update as compressed attention signal | `hub-Y` has 60+ notes updated weekly → strong attention; `hub-Z` listed in HUB_INDEX with 5 notes never updated → weak |
| Engine evolution | git activity over the base itself (`0_constitution/`, `_system/`, `5_meta/`, `1_projects/`) | Daily commits to `_system/registries/lenses/` for two weeks = engine work is where attention currently lives |

A high vote on one signal but low on others is a weaker gap than aligned signals across multiple.

### Talk-vs-do operationalization

Counting rule for honest claims:

- **Talk-side units** = unique declarations: 1 axiom mention + 1 SOUL section + N≥3 repeated record-mentions = up to 3 units. A single record-line ("I want X") is 0 units (anti-pattern: stated-preference inflation).
- **Do-side units** = concrete actions: each completed task `[x]`, each commit, each time-block citation, each shipping artifact (PR merged, post published, document delivered). Plans / next-actions still pending = 0 units.
- **Ratio interpretation:**
  - 1 talk + 0 do over a window matching the declaration's timescale → strong gap signal.
  - 1 talk + 5+ do → no gap; lived side aligns.
  - Talk >> do but do >0 → weak gap, watch over time.
  - Talk grows but do stagnant → escalating-talk pattern (worth surfacing as separate sub-pattern).

## Higgins ideal/ought tag (optional)

From self-discrepancy theory (Higgins 1987): the type of gap shows in the lexicon of records.

- **Ideal-side gap** (actual vs ideal self) — about aspirations, who the owner wants to be. Cue: dejection-tinted language — "wish I", "should have", "didn't get to it again", disappointment.
- **Ought-side gap** (actual vs ought self) — about duty / standards. Cue: agitation-tinted — "have to", "should have", "again didn't", anxiety / guilt.

If you can determine the type from records, add the tag. If unsure, skip — do not guess.

## What counts as a hit

A discrepancy where ALL hold:

1. **The declaration is explicitly fixed** — quote + path (`0_constitution/...md`, `SOUL.md` section, or repeated records).
2. **The lived side is supported by multiple independent signals** from the table above (not by count alone).
3. **Domain-aligned** — declaration and lived-records in the same domain.
4. **Window matches the declaration's timescale**.
5. **Specific** — not "everyone could attend more to health"; concretely "declared priority is project A; over the 60-day window the records show 4 mentions of A vs 35 of B + 0 completed A-tasks vs 12 B-tasks".

## What does NOT count as a hit (anti-patterns)

1. **Method-axioms compared to attention units.** Axioms about HOW to act ("no corner-cutting", "act with integrity") aren't comparable to time or mention count. They are process principles, not domain-content goals. **Distinction:** a method-axiom CAN appear as **supporting context** for an attention-unit gap (e.g. citing `axiom-identity-003 builder-not-talker` to explain *why* a planning-without-shipping pattern matters), but it CANNOT be **the declaration being measured**. Declaration = a domain-content goal or focus statement. Axiom = the lens through which the gap is interpreted.
2. **Aspirational stretch goals** with explicit long horizon ("learn an instrument over years"). Low short-window attention is correct pacing, not a gap.
3. **Situational crunch with stated cause.** Records explicitly name the cause ("deadline week, dropped X"). Constrained choice, not revealed preference (Samuelson / Thaler).
4. **Selection bias in records.** Quiet domains (time with partner, therapy, meditation) under-record by nature. Absence of records ≠ absence of attention. Require positive lived-side evidence, not "declaration without records".
5. **Recency illusion / window too short.** A gap visible over a couple of weeks but absent over months is rhythm, not a pattern. Don't claim a gap on a window shorter than the declaration's horizon.
6. **Stated-preference inflation.** A single record-line ("I want X") is not at axiom or repeated-SOUL-statement level. The bar for "declared" is repeated statement or formal axiom / SOUL entry.
7. **Domain mismatch.** A work-axiom against personal-records or vice versa — not a gap, noise.
8. **Ethical principles** (don't lie, act with integrity, treat people fairly) — not measurable in attention units. Skip entirely.

## Tone — bad → good (operational, not stylistic)

From MI (Miller & Rollnick — develop discrepancy without confronting), ACT (workable, not right/wrong), SBI (Situation-Behaviour-Impact, low-inference):

- ❌ "You are not living your values around health."
  ✅ "Constitution: `axiom-health-001` (tier-1). Records 2026-03-30 → 2026-04-29: 2 health-related entries vs ~30 work entries."

- ❌ "You declare family important but you neglect it."
  ✅ "SOUL.md/Focus#Personal lists family time. 30-day window: 1 family-tagged record. How do these fit together?"

- ❌ "Clear gap between what you say and what you do."
  ✅ "I notice tension between [declaration, cited] and [lived pattern, cited]. Three readings below — which is true is for you to judge."

- ❌ "You should refocus on Project A."
  ✅ "Project A is in declared focus; over 3 weeks Project B appears 15× more often. May be a deliberate priority shift, may be an action gap. Both are normal."

- ❌ "You are avoiding the hard thing."
  ✅ "The declared next-step from 2026-04-08 has not reappeared in records. The shape of avoidance and the shape of de-prioritisation look identical from text — only you can tell the difference."

Pattern rules: cite path + date; no second-person evaluative verbs ("avoid", "neglect", "fail"); end with the owner-decides handoff. Tension named, conclusion withheld.

## Self-history

`longitudinal` — past outputs at `_system/agent-lens/stated-vs-lived/{date}.md` are an index of **recurrence**. A gap once a quarter is an episode. The same gap three times over six months is a stable pattern.

Hard rule: **do not use past observations as evidence** for new ones. Each new observation rests on its own evidence from the current window. Past observations are context ("recurs since {date}"), not proof.

**First-run case:** if no past outputs exist (`_system/agent-lens/stated-vs-lived/` is empty or missing), say so explicitly in the methodological note. **Recurrence claims are impossible on the first run** — every observation must rest entirely on current-window evidence. Do not infer recurrence from intuition or from describe-me input.

Echo-loop risk: a longitudinal lens can loop on its own past hypotheses. If you notice you are repeating a past conclusion without new evidence in current records, surface this honestly: "this recurs in my outputs but no new signals appear in records — this may be my echo, not a pattern in the owner's life".

## What to give back

For each gap, in free form:

- **Declaration** — quote + path (constitution / SOUL / record).
- **Lived** — multiple independent signals from the table (with dates and paths).
- **The discrepancy** — short, descriptive. Higgins tag (ideal/ought) if you can determine.
- **Three readings** — action gap / priority shift / stale declaration. For each, the markers that make it plausible or not in this case.
- **Domain** — which domain you are working in and why.
- **Window** — what window you used and why.
- **Confidence** — your honest confidence.
- **If recurring** — note it (with the date of the prior output).

Tone — observational. The owner judges.

If 0 observations — say so. Normal — declared and lived align in this window (or the window is short, or signals are too thin for multi-signal evidence).
