# What counts (training-load-trend)

- `train_status` transitions on a specific date (DETRAINING →
  PRODUCTIVE, etc.) — quote both the date and the prior phase length.
- ACWR escapes from OPTIMAL into LOW (under-training risk) or HIGH /
  VERY_HIGH (overreaching risk).
- Sustained zones lasting > 2 weeks — surface with start date and
  duration.
- VO2max running trend (when `vo2max_running` is in Key Numbers
  consistently across the window) — `−` / `+` / flat over 28 days.
