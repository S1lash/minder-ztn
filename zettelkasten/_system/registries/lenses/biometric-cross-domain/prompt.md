---
id: biometric-cross-domain
name: Biometric Cross-Domain
type: psyche
input_type: records
output_schema: synthesis-custom
cadence: weekly
cadence_anchor: thursday
self_history: longitudinal
status: draft
---

# Biometric Cross-Domain

**Mandatory pre-read:** [`_system/docs/biometric-lens-protocol.md`](../../../docs/biometric-lens-protocol.md).

## Intent

Pick the top 1–2 strongest cross-domain findings from Tier II
(`_system/state/biometric/correlations-{recent}.json` Phase 2 + Phase 1
cross-source) and narrate them with cited journal evidence.
Counter-evidence is mandatory. Falsifier («this would NOT be a real
pattern if I saw…») is mandatory.

This is a weekly thursday lens. Friday-shifted view: enough days into
the week to have signal; before Sunday's wrap-up by `biometric-life-synthesis`.

## Read scope

- `_system/state/biometric/correlations-{most-recent}.json` ←
  primary numerical surface (per protocol — no bulk timeseries access).
- `_system/state/biometric/correlations-{most-recent-2}.json` for
  comparison if recent week is anomalous.
- `_system/views/biometric/weekly-{most-recent}.md` for human-readable
  pre-narrative.
- Top 1–2 findings: cited journal record bodies (one-shot point
  lookup per cited record).
- `_system/state/biometric/streaks.json` (history of streaks
  spanning the window).
- Own past outputs at `_system/agent-lens/biometric-cross-domain/`
  for longitudinal awareness — don't repeat last week's framing on
  the same data.

## Calibration

Diagnostic gate per protocol: `n ≥ 10` AND `effect_size ≥ 0.5`.

- `strong` tier (gate met) → diagnostic statement permitted.
- `medium` (n=5-9 OR effect 0.2-0.5) → tentative claim with
  uncertainty named.
- `weak` (n<5 OR effect <0.2) → question form.

## Output structure

Per protocol §«Output structure (mandatory)»: Facts / Patterns /
Hypotheses (ranked) / Counter-evidence / Suggested experiment /
Memory note (only if strong tier reached).

**Anti-eye-roll guard:** if Tier II output has no findings at-or-above
medium, surface that explicitly («No cross-source findings this week
above noise») and stop. Empty output is a valid result, not failure.

## Action hints

- `wikilink_add` — bridge biometric record ↔ journal observation
  cited in the top hypothesis.
- `open_thread_add` — only if pattern is strong AND actionable AND
  not already in `OPEN_THREADS.md`.

## Frontmatter

```
---
lens_id: biometric-cross-domain
run_at: {ISO timestamp}
iso_week: {YYYY-Www}
hits: {count of substantive findings narrated}
origin: personal
audience_tags: []
is_sensitive: true
---
```
