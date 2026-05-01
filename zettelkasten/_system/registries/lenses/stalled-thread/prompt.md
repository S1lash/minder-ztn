---
id: stalled-thread
name: Stalled Thread Detector
type: mechanical
input_type: records
cadence: weekly
cadence_anchor: monday
self_history: fresh-eyes
status: active
---

# Stalled Thread Detector

## Intent

Find topics, questions, or decisions the owner keeps returning to without moving them forward. The goal is NOT to say "resolve this." The goal is to **make visible** that a thread is hanging, so the owner can either add it to `_system/state/OPEN_THREADS.md`, file a task with a next action, or consciously let it go.

This lens acts as a **feeder for OPEN_THREADS.md**: the hits you produce are candidates the owner reviews and either fixes as an open thread, accepts as just-a-stage-of-thinking, or drops as noise.

## What counts as a "thread" — the most important section

A thread is NOT a keyword that recurs in records. A thread is a **recurring object of attention** with stable shape. Signals of one thread:

- **Recurring question** — the same question ("should I move to X", "how do I delegate Y"), even if phrased differently across mentions.
- **Recurring person + topic pair** — an "X + specific topic" combination, not just X mentioned in the background of unrelated topics.
- **Recurring concrete entity / decision** — the same choice / project / context that the reasoning keeps returning to.
- **Recurring framing** — the same words and angle of attack on the problem, without the formulation evolving between mentions.

If you cannot name the thread in one phrase ("a thread about X" / "a thread of deciding Y") — it is probably ambient context, not a thread. Ambient context is NOT a hit, and it is the **most common LLM false-positive class**: co-occurrence reads as recurrence when it is not.

## The primary signal — framing similarity, not count

From research on repetitive thinking (Nolen-Hoeksema brooding/pondering 2008; Watkins level-of-construal 2008): the signal that thought **isn't moving** is **abstract framing without progress**:

- **Brooding-shape (signal of stalled):** "why haven't I…", "still can't…", "same thing again…", abstract nouns without concrete grounding ("delegation", "balance", "meaning"), "why"-questions without "how"-follow-ups, no specific people / dates / actions appearing across mentions.
- **Pondering-shape (signal of healthy incubation):** each return adds a new sub-question, a new constraint, or new evidence; the formulation evolves; concrete "if X then Y" structures appear.

**Pondering is NOT stalled.** It is healthy incubation. Matuschak (evergreen notes) describes this directly: reaching insight requires holding parallel partially-formed ideas in motion. Do not conflate incubation with being stuck.

## GTD next-action test

From David Allen — open-loop test: for the thread, mentally formulate "the next physical action" as the owner would. If you cannot (because the owner never named one across the records) — the thread is **open**. If any mention contains a committed next action or an explicit decision — it is NOT open; it is in-flight or resolved.

## What to read

Decide for yourself. The frame's contract gives you full base access — use it. Useful starting points:

- `_records/observations/` and `_records/meetings/` over the recent few months. If a thread's roots seem older, widen the window — there is no fixed limit; let the pattern dictate the depth.
- `_system/state/OPEN_THREADS.md` — already-fixed threads. Don't duplicate them (they are already visible to the owner).
- `_system/TASKS.md` — if a topic lives as a task with a clear next action, it is not stalled, it is an open task.
- `_system/views/HUB_INDEX.md` and `5_meta/mocs/` — if a topic has a hub, it has reached synthesis.
- `3_resources/people/PEOPLE.md` — when a candidate is person+topic-shaped, resolve the canonical person-id before treating different mentions as the same thread.
- When useful — `_sources/inbox/` for fresh transcripts not yet shaped into records (if a thread seems to continue there).

## Window calibration by base maturity

A fresh ZTN base surfaces stalled threads at relatively high frequency in short windows — most recurring topics still live in raw records. A mature base (HUB_INDEX with >10 active hubs absorbing common recurring topics + a populated `OPEN_THREADS.md`) moves the obvious patterns into curated layers, so the threads that escape curation tend to recur slowly: a few mentions per quarter, not weekly.

In a mature base, default to a 3-6 month sweep over `_records/` — the monthly window will systematically miss the very threads the lens exists to find (the slow-burn ones that did not reach a hub). Fresh bases (few hubs, thin OPEN_THREADS) work fine with a few weeks. Criterion #3 below («not already fixed») does the de-duplication regardless of window size, so widening only changes what is detectable, not what is double-counted.

## What counts as a hit

A candidate where ALL hold:

1. **Multiple mentions** in `_records/` on different days, with meaningful spacing (consecutive-day mentions are usually one continued thinking session, not recurrence).
2. **Each mention leaves the topic open** by the GTD test above — no committed next action, no explicit decision.
3. **Not already fixed** in `OPEN_THREADS.md`, `TASKS.md` (as an active task), `5_meta/mocs/`, or closed inside a knowledge note in `1_projects/`, `2_areas/`, `3_resources/`.
4. **Brooding-shape** by the test above — abstract framing, no new sub-questions or constraints between mentions. If framing evolves between mentions, it is pondering, probably NOT a hit.

## Confidence calibration

State your confidence honestly:

- **high** = several mentions with the same abstract framing, no committed next action in any of them, span on the order of a month or more, option-set / question-shape does not narrow between mentions.
- **medium** = a few mentions with the same framing; OR more mentions with slowly-evolving framing but no resolution.
- **low** = two mentions with framing that differs or evolves — surface as "thread in motion, watching, not yet stalled" rather than as stalled.

Low confidence is a normal output. Better to surface low with a clear note than not surface at all, or surface with false high confidence.

## What does NOT count as a hit

1. **Cyclical / scheduled topics** — quarterly review, monthly 1:1 prep, weekly retro, sprint planning. Recurrence by design, not stuckness.
2. **Reference mentions** — person X or project Y appears as background across unrelated threads. This is ambient context, not one thread. The most common false-positive class — do not confuse co-occurrence with recurrence.
3. **Pondering with evolution** — same topic, but each mention adds a sub-question, a constraint, a new person involved. Healthy incubation (Matuschak), not stuckness. If you surface, label as "pondering, watching".
4. **Emotional texture without a question** — "tired of X", "frustrated with Y" without a question or topic behind it. A signal of state, not a thread.
5. **External-blocker waits** — the owner is waiting on someone else's reply, an event, a deadline. Stalled in the environment, not in the owner. NOT a hit.
6. **Identity-level long arcs** — "who do I want to be", "where am I going". These live at `0_constitution/` / `_system/SOUL.md`, not at record level. Surfacing them as stalled is a category error.
7. **Resolved-elsewhere** — closed inside a knowledge note or hub you didn't cross-check. Verify before surfacing.

## Self-history

`fresh-eyes` — past outputs are not read. If a thread was flagged before and is still stalled, you will flag it again — repetition in outputs is itself a signal to the owner. If it resolved, you won't find it on this pass because the criteria won't hold.

## Tone

Descriptive, never evaluative. Naming repetitive thought as "pathological" or "avoided" **increases** brooding (clinical literature, Nolen-Hoeksema 2008). Use:

- ✅ "Topic X appeared in records on {date1}, {date2}, {date3}. Each mention leaves it without a committed next action."
- ❌ "You are avoiding the decision on X."
- ✅ "Thread in motion — each mention adds a new angle. Surfacing as watching, not stalled."
- ❌ "Stuck thread." (used as a label)

Vocabulary: "thread in motion" (Matuschak idiom: ideas in motion) for pondering; "open thread" for stalled. No "avoiding", "stuck", "failing to". No second-person evaluative verbs.

## What to give back

For each hit, in free form:

- **What the thread is** — 1-2 sentences. Name it as one phrase.
- **Specific record references** — path + date + a short quote or paraphrase showing the framing.
- **Brooding-shape evidence** — what specifically shows the framing isn't moving (repeated phrasing, abstract language, absence of sub-questions).
- **What is visible in the system as a next move** for the owner — NOT advice, but a statement of what is available: "could be fixed in OPEN_THREADS.md", "could become a task with a next action", "could be consciously released".
- **Alternative reading** — why this might NOT be stalled (it's a reference, or pondering, or external-blocker). If unsure, note that the thread may be weak and worth waiting another pass.
- **Confidence** — high / medium / low.

If 0 hits — say so plainly: "Over the window I examined, no threads met the criteria. Topics I considered and dismissed: …" That is also a signal.
