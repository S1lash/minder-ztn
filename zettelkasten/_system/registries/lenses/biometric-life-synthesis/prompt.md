---
id: biometric-life-synthesis
name: Biometric × Life Synthesis
type: meta
input_type: multi-source
output_schema: synthesis-custom
cadence: weekly
cadence_anchor: monday
self_history: longitudinal
status: draft
---

# Biometric × Life Synthesis

**Mandatory pre-read:** [`_system/docs/biometric-lens-protocol.md`](../../../docs/biometric-lens-protocol.md).

## Intent

The flagship synthesis lens: answer **«what was this week about, and
how did biometrics reflect it?»** Reads weekly biometric output (Tier II
+ daily anomaly narrators) AND the broader life surface (week's
records, SOUL focus, OPEN_THREADS, INDEX) and produces a multi-source
synthesis.

This is the lens that bridges biometric pattern with life narrative —
the highest-value output of the pipeline. Run weekly Monday morning;
read by owner before week starts as orientation.

## Read scope

- All 4 biometric lens outputs from past 7 days
  (`biometric-anomaly-narrator` daily × 7,
  `biometric-cross-domain` weekly thursday,
  `training-load-trend` if not skipped).
- `_system/state/biometric/correlations-{recent}.json` (Phase 1 + Phase 2).
- `_system/views/biometric/weekly-{recent}.md`.
- `_system/views/INDEX.md` (week-faceted activity).
- `_records/observations/*<this-week>*.md`,
  `_records/meetings/*<this-week>*.md` (point-lookup with
  protocol discipline).
- `_system/state/OPEN_THREADS.md` `## Active`.
- `_system/SOUL.md` `## Focus`.
- Recent `stated-vs-lived` + `energy-pattern` outputs if fresh
  (≤ 7 days old).
- Own past outputs at `_system/agent-lens/biometric-life-synthesis/`
  for longitudinal awareness — don't repeat last week's synthesis on
  same data.

## Output structure

Synthesis-custom schema (the prompt owns its own structure; Stage 2
skipped per `_frame.md`).

```markdown
---
lens_id: biometric-life-synthesis
run_at: {ISO timestamp}
iso_week: {YYYY-Www}
hits: {count of substantive sections}
origin: personal
audience_tags: []
is_sensitive: true
---

# Biometric × Life — {iso_week}

## Week shape
- Meeting count: {N} (above / below / at {N-week median})
- Conflict markers: {N} (dates)
- Late-work markers: {N}
- Workout count: {N}
- Active SOUL Focus: {pulled from SOUL.md, verbatim}
- Active threads: {top 3 from OPEN_THREADS}

## Convergent / divergent patterns
- **Convergent:** {pattern that journal + biometric agree on}
- **Divergent:** {pattern where stated and lived differ — quote owner
   declaration; cite biometric evidence}

## Hypotheses (ranked)

1. **strong** (n={N}, r={...}) — {claim}. Counter: {date / observation}.
2. **medium** (n={N}, r_pb={...}) — {tentative claim}. Counter: ...
3. **weak** — {question form}.

## Counter-evidence summary
{bulleted list of where the week's biometric story breaks against
the journal narrative or vice versa}

## Suggested experiment for next week
{ONE behavioural change to test, falsifiable, observable next week.
NOT advice. Owner decides whether to try.}

## Memory note (only if strong-tier hypothesis emerged)
- **Title:** {title}
- **Observation:** {one paragraph}
- **Decision/experiment:** {what to test}
- **Review date:** {today + 14 days}
- **Links:** [[...]] [[...]]
```

## Anchoring constraint (multi-source)

Every numerical claim resolves to a primary biometric record path.
Every pattern claim cites Tier II finding identifier (`phase_1.top_strong[i]`
or `phase_2.top_findings[j]`). Every life-narrative claim cites a
specific observation / meeting. Lens output alone is hypothesis-grade,
NEVER the basis for a claim about the owner.

## Diagnostic gate

Per protocol: `n ≥ 10` AND `effect_size ≥ 0.5` to mark `strong`.
Memory note section emits ONLY when strong tier reached.

## Action hints

- `wikilink_add` — primary synthesis bridges (biometric record ↔ this
  week's primary meeting / observation).
- `open_thread_add` — if synthesis surfaces a strategic concern not
  already in OPEN_THREADS.
- `decision_update_section` — on a stated-vs-lived gap if owner has
  an active decision-record being contradicted by biometric pattern.
