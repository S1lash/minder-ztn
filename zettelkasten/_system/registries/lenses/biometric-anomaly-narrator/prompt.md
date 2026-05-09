---
id: biometric-anomaly-narrator
name: Biometric Anomaly Narrator
type: mechanical
input_type: records
output_schema: synthesis-custom
cadence: daily
cadence_anchor: daily
self_history: fresh-eyes
status: draft
---

# Biometric Anomaly Narrator

**Mandatory pre-read:** [`_system/docs/biometric-lens-protocol.md`](../../../docs/biometric-lens-protocol.md)
— n=1 caveats, numerical access policy, content access policy. Apply
throughout. The protocol's «Output structure (mandatory for biometric
lenses)» is binding — Facts / Patterns / Hypotheses (ranked) /
Counter-evidence / Suggested experiment / Memory note.

## Intent

Surface yesterday's biometric signal in narrative form, bridged with
journal context where available. **Single-day frame** — most outputs
will be questions or weak hypotheses, not diagnostic statements.
Strong tier requires consistent multi-day pattern; that lives in
`biometric-cross-domain` and `biometric-life-synthesis`. Here we
narrate one day.

## When to produce content

Read `_records/biometric/<yesterday>.md`. Proceed only if at least
one of these is non-empty:

- `## Baseline Deviations`
- `## Categorical Events`
- `## Active Streaks` (any concept active on yesterday's date)
- `## Streak Transitions` (start or recovery on yesterday's date)

If all are empty / absent, output: «Yesterday clean — no signal.»
and return. This is normal and expected on most days.

## Read scope

- `_records/biometric/<yesterday>.md` (primary)
- `_records/observations/*<yesterday>*.md`,
  `_records/meetings/*<yesterday>*.md` — journal context for the
  same date
- `_system/state/biometric/streaks.json` (active streak state)
- Cited record bodies for the top hypothesis (one-shot, per
  protocol)

## Calibration

- Single-day frame → most hypotheses tier `weak` (question form).
- A streak ≥ 4 days strong + actionable journal context can reach
  `medium`.
- `strong` is rare here (n=1 day). Reserve for streak ≥ 5 days
  with effect_size ≥ 0.5 from Tier II Phase 1 / Phase 2 cited
  inline.

## Action hints (optional trailer)

May append `## Action Hints` per `_frame.md` Action Hints contract:

- `wikilink_add` — bridge biometric record ↔ specific journal
  observation when both cite the same date and a hypothesis names
  the connection.
- `open_thread_add` — only if a streak ≥ 4 days strong with
  actionable journal context is observed. Rare.

NEVER emits `hub_stub_create` or `decision_update_section` — out of
scope for daily narrator.

## Frontmatter (mandatory)

```
---
lens_id: biometric-anomaly-narrator
run_at: {ISO timestamp}
date: {YYYY-MM-DD of yesterday}
hits: {count of substantive sections — 0 if 'Yesterday clean'}
origin: personal
audience_tags: []
is_sensitive: true
---
```

## Bilingual quoting

Quote journal text verbatim — preserve original language. Lens output
may mix RU + EN if the source does.
