# Biometric Lens Protocol

Mandatory pre-read for every lens prompt that touches biometric data
(`biometric-anomaly-narrator`, `biometric-cross-domain`,
`training-load-trend`, `biometric-life-synthesis`, plus patched
`stated-vs-lived`, `energy-pattern`, `weekly-insights`,
`global-navigator`).

This document describes (1) n=1 caveats lenses must respect, (2)
numerical access policy, (3) content access policy. Lens prompts cite
this file at the top and rely on it instead of repeating the rules.

---

## n=1 caveats

The owner is a single subject. Statistical conclusions are
single-subject design (n=1) — strong on within-person patterns,
unable to support population claims.

1. **Garmin estimates, not ground truth.** Sleep stages, HRV, body
   battery, training readiness are vendor-derived estimates from
   noisy sensors. Phrase findings as "Garmin reports X" or "the
   record shows X", never "X is true".
2. **No causation in single-subject.** Phrase as "associated with",
   "predictive of", "co-occurs with". Never "X causes Y".
3. **Always include counter-evidence and a falsifier.** "This would
   NOT be a real pattern if I saw…". Mandatory in every output.
4. **Effect sizes calibrated to single-subject design.** Cohen's
   r=0.5 is "large effect" here; Tier II worker computes per-pair
   effect size and surfaces only |r| ≥ 0.2 (medium) and ≥ 0.5
   (strong). Below that, signals stay below the diagnostic gate.

---

## Numerical access policy

The pipeline produces deterministic Tier II artefacts so lenses
never need to load bulk timeseries.

Tier II state is namespaced per wearable device under `<source>/`
(e.g. `garmin`, `oura`) — each device's records and σ-baselines are
isolated. A lens reads across **both** device namespaces present under
`_system/state/biometric/*/` to build a unified picture; it never pools
two devices' raw metrics into one baseline (the pipeline already keeps
them separate by design).

### Allowed

- **Tier II pre-computed correlations** — `_system/state/biometric/{source}/correlations-{week}.json`.
  Top-N findings per pair, lag analysis, anomaly clusters, streak history.
  This is the canonical numerical surface.
- **Tier II weekly view** — `_system/views/biometric/{source}/weekly-{week}.md`.
  Human-readable narrative summary.
- **Per-day Key Numbers point-lookup** — read `## Key Numbers`
  section of one biometric record when investigating one specific
  day's signal. Single-day OK.
- **Streak state** — `_system/state/biometric/{source}/streaks.json`. Active
  + recent streaks. Compact, structural.
- **Baselines metadata** — `_system/state/biometric/{source}/baselines.json`
  μ / σ / n for each metric. Compact.

### Forbidden

- **Bulk numerical series.** No multi-day Key Numbers loops to
  build a series in lens context. Tier II already did the math.
- **Raw minute-level data.** Do not load `_sources/inbox/garmin/raw/{date}.json`
  by default. Token-explosive and pre-computed signals dominate.

### Escape hatch

- For minute-level investigation of one specific incident (rare —
  e.g. lens hypothesizes a sleep disturbance at a specific hour):
  read `_sources/inbox/garmin/raw/{date}.json` for that one day.
  Document the access in the lens output. Single-day point lookup
  only — never as a sweep.

---

## Content access policy

Cross-domain lenses bridge biometric records with journal records
(observations + meetings). Token discipline matters.

### Allowed

- **Frontmatter on any record.** Title, date, people, tags,
  `is_sensitive`, `audience_tags`. Cheap and structural.
- **Body of a journal record cited by hypothesis.** When a finding
  names a specific record (`biometric/2026-05-04` ↔
  `meetings/20260504-…`), read the cited record's body to ground
  the claim. One-shot per cited record.
- **Streak / cluster narrative context.** When discussing a multi-day
  streak, read the bodies of journal records on the streak days
  to extract narrative context — not numbers.

### Forbidden

- **Bulk body sweeps.** No "load all observations of past 56 days
  bodies into context to look for patterns". Tier II's affect lexicon
  did the binary tagging deterministically; lens reads the tag
  presence + the cited record bodies for the top hypotheses only.

### Bilingual quoting

When citing journal text, **preserve original language**. The owner
writes in mixed RU+EN. Do NOT translate Russian to English (or vice
versa) in cited evidence. Lens output may mix languages if the
source material does.

---

## Output structure (mandatory for biometric lenses)

Every biometric lens output (Tier III) carries these sections:

1. **Facts** — what happened (flags, transitions, cited dates).
2. **Patterns** — what repeats (from Tier II output + streak state).
3. **Hypotheses (ranked)** — graded by evidence:
   - **strong** (n≥10 supporting days AND effect_size ≥ 0.5):
     diagnostic statement permitted ("X is the pattern, here is the
     mechanism").
   - **medium** (5-9 supporting days OR effect_size 0.2-0.5):
     tentative claim ("looks like X — uncertainty Y").
   - **weak** (1-4 supporting days OR effect_size < 0.2): question
     form ("вчера был X — связано с Y?").
4. **Counter-evidence** — where the hypothesis fails. Mandatory,
   even if brief.
5. **Suggested experiment** — one behavioural change to test.
   NOT advice.
6. **Memory note** (only if a strong-tier hypothesis emerged) —
   title / observation / decision-or-experiment / review-date /
   links-to-cited-records.

Each lens prompt MAY add lens-specific guidance on top of this frame
but never relaxes it.

---

## Privacy contract for lens outputs

Every biometric lens output frontmatter:

- `origin: personal`
- `audience_tags: []`
- `is_sensitive: true`

Lens prompts hard-set these at write time. The Stage 3 validator
accepts (per `output_schema: synthesis-custom`) frontmatter privacy
trio + non-empty body.
