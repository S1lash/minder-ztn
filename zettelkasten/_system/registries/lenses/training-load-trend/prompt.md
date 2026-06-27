---
id: training-load-trend
name: Training Load Trend
type: mechanical
input_type: records
output_schema: synthesis-custom
cadence: weekly
cadence_anchor: monday
self_history: longitudinal
status: draft
---

# Training Load Trend

**Mandatory pre-read:** [`_system/docs/biometric-lens-protocol.md`](../../../docs/biometric-lens-protocol.md).

## Garmin-specific lens

Training load (`acute_load`, `chronic_load`, `acwr`, `train_status`)
is a Garmin-only metric — Oura does not track it. This lens is
pinned to the `garmin/` namespace: `_records/biometric/garmin/<date>.md`
and `_system/state/biometric/garmin/`. Do not look for these metrics
under `oura/` and never fabricate a training-load reading from Oura
data. Per `device_estimate: true` honesty, phrase findings as «Garmin
reports X», never «X is true».

## Pre-check (mandatory first step)

Read last 14 days of `_records/biometric/garmin/<date>.md`
`## Key Numbers`. **If `acute_load == 0` for ALL 14 days (or the
`garmin/` namespace has no records in the window), output exactly:**

```markdown
---
lens_id: training-load-trend
run_at: {ISO timestamp}
hits: 0
origin: personal
audience_tags: []
is_sensitive: true
status: skipped
---

# Training Load Trend — skipped

No training activity in window — skipping.
```

**…and return immediately.** Do NOT continue to analysis. This is the
conditional execution rule that prevents weekly noise during sedentary
periods. The `global-navigator` lens treats this skipped state as
normal, not failure.

## Intent (only if pre-check passes)

Surface training-load trends across the last 28 days:

- Detect transitions: DETRAINING → MAINTAINING → PRODUCTIVE → PEAKING
  → OVERREACHING (or reverse).
- Track ACWR drift: escapes from OPTIMAL into LOW / HIGH / OVERREACHING.
- Quote dates of training events (acute_load > 0 days).
- Sustained zone observations: «detraining for >2 weeks» or
  «overreaching for ≥ 3 days».

## Read scope

- Last 28 days of `_records/biometric/garmin/<date>.md` Key Numbers
  (`acute_load`, `chronic_load`, `acwr`, `acwr_zone`, `train_status`).
- `_system/state/biometric/garmin/correlations-{most-recent}.json`
  for context if any phase 1 finding involves training metrics.
- Own past outputs at `_system/agent-lens/training-load-trend/` for
  longitudinal continuity.

## Action hints

- `open_thread_add` — only if overreaching OR sustained
  detraining ≥ 3 weeks AND not already an open thread.
