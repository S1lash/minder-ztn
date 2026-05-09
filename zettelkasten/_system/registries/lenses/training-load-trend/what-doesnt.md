# What doesn't count (training-load-trend)

- Single rest day in a high-training week — that's noise, not a
  transition.
- Sub-threshold ACWR variability inside OPTIMAL band — Garmin's own
  feedback already covers it.
- Days with `acute_load == 0` for 14 days straight — this lens
  silent-skips per pre-check; do NOT emit content during that period.
- Generic fitness advice — not advice domain. The lens reports the
  signal, owner judges what to do.
