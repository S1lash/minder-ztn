# What doesn't count (biometric-anomaly-narrator)

- Light deviations alone (1.0σ–1.4σ on sleep_h or hrv_ms) — too noisy
  for daily lens. Surface only if accompanied by another signal.
- Days with no flags / no streak state / no categorical event — the
  lens silent-exits with «Yesterday clean — no signal.»
- Long-history pattern claims spanning ≥ 3 days — those belong to
  `biometric-cross-domain` and `biometric-life-synthesis`.
- Within-biometric correlation findings — already in Tier II output;
  no value adding LLM narration to a deterministic Pearson result.
- Causation claims — single-subject n=1 design forbids them. Phrase as
  «co-occurs with», «predictive of», «associated with».
- Advice. Suggested experiment is one behavioural change to test —
  never «you should…».
