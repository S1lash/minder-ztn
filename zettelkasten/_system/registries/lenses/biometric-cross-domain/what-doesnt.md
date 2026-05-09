# What doesn't count (biometric-cross-domain)

- Single-day events — handled by `biometric-anomaly-narrator`.
- Pure within-biometric correlations (sleep_h ↔ readiness, HRV ↔ RHR)
  — already in Tier II output, no value adding LLM narration to
  deterministic Pearson.
- Findings below effect_size 0.2 — survive the diagnostic gate by luck;
  not signal.
- Findings with n < 14 — sample too small for n=1 single-subject
  pattern claim.
- Multi-domain meta-synthesis (week shape + SOUL focus + biometric
  pattern) — that's `biometric-life-synthesis`'s territory.
- Causation. Association language only. Never «X causes Y».
