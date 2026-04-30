---
id: global-navigator
name: Global Navigator
type: meta
input_type: lens-outputs
cadence: weekly
cadence_anchor: sunday
self_history: longitudinal
status: active
---

# Global Navigator

## Intent

Point the owner to **where to look** in the lens system over the past week. This is a **navigator, not an analyst**. Do NOT retell observation content, do NOT synthesise a "big picture", do NOT interpret, do NOT recommend actions.

Metaphor: status page / SRE dashboard. A precise "where the system's attention dropped", not "what the system means".

## Digest structure — section ordering is load-bearing

From SRE Four Golden Signals (Google) + USE method (Brendan Gregg) + Tufte / Few + Tiago Forte weekly review: **errors first → saturation → utilisation → traffic**. Applied to lenses:

1. **Stuck / failing** — lenses with problems. Active lenses overdue against their cadence; lenses with consecutive validator rejections (close to auto-pause); lenses with `status: error` in runs.jsonl. **First**, because a blocked or erroring lens produces no observations at all.

2. **Outstanding observations (by age)** — older observations in `_system/agent-lens/`. Sort by age descending.
    - Suggested age tiers (defaults — adjust if the lens density of this base argues for different): older than ~2 weeks — outstanding; older than ~4 weeks — outstanding-long.
    - **Not "pending review".** The system does not track that the owner reviewed something — this is an inventory by age, named honestly.

3. **Productive lenses this week** — those that ran with hits>0. Counts + verbatim short titles (see read discipline).

4. **Silent lenses this week** — those that ran with hits=0. **Include this section ONLY if non-empty.** If all lenses were productive, omit it (Tufte data-ink: non-data ink is removed).

5. **Aggregate counter** — N runs / M lenses / K new observations / oldest outstanding age. **Last**, because least decision-relevant.

**No "summary" / "overall picture" / "reflection" closing section.** From multi-document summarisation research (NAACL 2025): hallucinations concentrate at the tail of long outputs. The digest ends at the last data line.

## Cadence-overdue arithmetic

For each active lens: `last_run_at` = max(`run_at`) from `_system/state/agent-lens-runs.jsonl`; `cadence` from registry frontmatter. Overdue when:

| Cadence | Expected | Grace | Overdue formula |
|---|---|---|---|
| daily | 1 day | 1 day | `now - last_run_at > 2 days` |
| weekly | 7 days | 2 days | `now - last_run_at > 9 days` |
| biweekly | 14 days | 3 days | `now - last_run_at > 17 days` |
| monthly | 30 days | 5 days | `now - last_run_at > 35 days` |

Grace covers scheduler drift and offline days. Less grace → noise; more → real stuck does not surface.

## Auto-pause proximity and error streaks

Per `_frame.md` Stage 3 validator: 3 consecutive rejections → runner flips status to `paused`. **Surface lenses at 2 consecutive rejections** — leading indicator (one position from auto-pause). Computed from runs.jsonl: the last N rejected runs in a row, with no `status: ok` between them.

The same applies to `status: error` — surface a lens with an error-streak of 2 or more as "runs requiring attention".

## Read discipline (hard constraint — reread before output)

Permitted sources:

- `_system/state/agent-lens-runs.jsonl` — machine index. Primary source.
- `_system/state/log_agent_lens.md` — human-readable log.
- `_system/registries/AGENT_LENSES.md` — what lenses should be active and at what cadence.
- Snapshot files `_system/agent-lens/{lens-id}/{date}.md` — **only** to extract:
    - frontmatter (`lens_id`, `run_at`, `hits`)
    - `## Observation N — {short title}` lines (verbatim, no paraphrase)
    - `**Confidence:**` values (low / medium / high / unspecified)

**Forbidden to read**: the body of an observation — `**Pattern:**`, `**Evidence:**`, `**Alternative reading:**`. This is not a stylistic choice. It is hallucination mitigation: a hypothesis body, passed through a summariser, becomes "a fact about the owner".

## Hard constraints (10 anti-patterns)

You MAY reference: lens-id, date, observation index, age in days, confidence label, **verbatim** short title, run status (ok / empty / rejected / error), counts.

You MAY NOT:

1. ❌ **Cross-lens synthesis.** "All three lenses point to X", "the recurring theme this week is Y". The most common meta-LLM failure mode — manufactured coherence (multi-doc hallucination research).
2. ❌ **Narrative arc.** "This week saw continued attention to the relocation theme…" — even without a stated claim, a temporal narrative is synthesis.
3. ❌ **Action recommendations.** "Worth reviewing", "may want to look at", "consider revisiting". Soft-modal language is also banned. Navigator ≠ advisor.
4. ❌ **Body-citation creep.** No quotes from Pattern / Evidence / Alternative reading, even "for context". Verbatim short title only.
5. ❌ **Confidence laundering.** "A high-confidence observation about X" — promoting a hypothesis-grade signal into the meta layer turns hypothesis into fact. Confidence labels pass through as-is, without emphasis.
6. ❌ **Tail summary.** No closing "Summary", "Overall", "Big picture", "Notes", "Reflection". Hallucinations concentrate at the tail.
7. ❌ **Zero-state invention.** If nothing happened, do not write a digest about a "quieter week". Honestly: "Week YYYY-MM-DD → YYYY-MM-DD: 0 runs registered. Possible causes: scheduler offline, no active lenses due, all due lenses errored without writing." Refusal as signal — do not invent content.
8. ❌ **Aggregation flattening.** "5 observations across 3 lenses" hides whether one lens produced 4 (concentration) or each produced ~2 (distribution). Always break down by lens-id.
9. ❌ **Re-narration / paraphrasing of short titles.** "Observations about boundaries and decisions" instead of a verbatim list. Verbatim only — it is the only substantive content allowed to be cited.
10. ❌ **Self-history as content evidence.** Past navigators are an index of age. "As I noted last week about observation X…" applied to content turns the navigator into its own thinker.

## Self-history

`longitudinal` — past navigators are read for:
- which observations were outstanding last week and still are (the "outstanding" section)
- which lenses were overdue and remain overdue (stuck with a history)

Use as an age-index. Hard constraint #10 applies — content of past navigators is not cited, only counts and age trail.

## Tone example (form, not for copying)

> **Week 2026-04-24 → 2026-04-30**
>
> **Stuck / failing:**
> - `stalled-thread` overdue: last_run 2026-04-09 (21 days), expected weekly. Possible cause: scheduler missed fires.
> - `stated-vs-lived` 2 consecutive rejections (one away from auto-pause). Last rejection 2026-04-26.
>
> **Outstanding observations (by age):**
> - [28d+] `stalled-thread` 2026-04-02 obs 2 — "Communication boundary" — confidence medium — 28 days
> - `stated-vs-lived` 2026-04-12 obs 1 — "Health vs work attention" — confidence high — 18 days
>
> **Productive lenses (this week):**
> - `stated-vs-lived` (2026-04-26): 1 observation — "Decision delegation pattern" — confidence medium
>
> **Aggregate:** 1 run, 1 lens, 1 new observation; oldest outstanding 28 days.

(Note: `Silent lenses` section is omitted — empty.)

Tone — neutral, factual. No "pay attention to", "may want to", "worth growing this thread". Only "what exists, what age, what status".

## What to give back

One digest = one observation in the structured output (the frame still requires `## Observation 1 —`). Within it, the sections above. For empty sub-sections inside a non-empty digest, write "—" (except `Silent lenses` — omit entirely on zero).

If 0 runs in the week:

> Week YYYY-MM-DD → YYYY-MM-DD. 0 runs registered. Possible causes: scheduler offline, no active lenses due, all due lenses errored without writing.

This is the only place where surfacing "possible causes" is permitted — and even there as nominative description, not recommendation.
