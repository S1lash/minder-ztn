"""Source profiles for the metric-day pipeline.

A metric-day source is any feed that lands one deterministic file per
calendar day and benefits from rolling σ-baselines, streaks and a
per-day record (biometric wearables, computer-usage telemetry, …). The
shared engine (`process_metric_day`, `biometric_baselines`,
`biometric_streaks`) is profile-agnostic; everything that differs
between a physiological feed and a behavioural one lives in a
`MetricDayProfile`:

  • which extractor parses the source file → canonical metrics
  • the record's `kind` / `domains` / heading / namespace directory
  • the Key-Number vocabulary and which of those metrics are σ-tracked
  • categorical-transition pairs and the streak concept naming map
  • the thresholds file to layer, and privacy defaults

`biometric` and `activity` are the two shipped profiles. Adding another
daily-metric source is a new profile + a registry row here — no edits to
the orchestrator. Resolution is by source id (mirrors
`biometric_extractor._VENDOR_MAPS`); unknown sources fall back to the
biometric profile (historical default).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import activity_extractor
import biometric_extractor
from biometric_baselines import NUMERIC_METRICS as _BIOMETRIC_NUMERIC_METRICS


# Minimum active hours for a computer-usage day to feed the rolling
# baselines. A Mac-off / near-idle day is absence, not "low deep work";
# feeding its zeros would corrupt every behavioural baseline. The record
# is still emitted (the empty day is itself signal), only the baseline
# contribution is skipped.
_ACTIVITY_BASELINE_MIN_ACTIVE_H = 0.5


@dataclass(frozen=True)
class MetricDayProfile:
    name: str                              # "biometric" | "activity"
    kind: str                              # frontmatter `kind`
    family_dir: str                        # _records/{family_dir}/{source}
    domains: tuple[str, ...]
    heading: str                           # record H1 → "{heading} — {date}"
    manifest_primary_type: str
    extractor: Callable[[Any], dict[str, Any]]
    key_number_order: tuple[str, ...]
    numeric_metrics: tuple[str, ...]       # σ-tracked by baselines.update
    categorical_pairs: tuple[tuple[str, str], ...]   # (metric_key, label)
    thresholds_basename: str               # "{basename}.template.yaml" etc.
    is_sensitive: bool
    device_estimate: Optional[bool]        # True → emit field; None → omit
    concept_map: Optional[dict[tuple[str, str], str]]  # None → streak default
    baseline_min_active_h: Optional[float] = None      # gate; None → always

    def should_baseline(self, metrics: dict[str, Any]) -> bool:
        """Whether today's metrics should feed the rolling baselines."""
        if self.baseline_min_active_h is None:
            return True
        active = metrics.get("active_h")
        return isinstance(active, (int, float)) and active >= self.baseline_min_active_h


# --- Biometric Key Numbers (canonical render order) -------------------------
_BIOMETRIC_KEY_NUMBER_ORDER: tuple[str, ...] = (
    "sleep_h", "sleep_score",
    "deep_h", "rem_h", "light_h", "awake_h",
    "sleep_efficiency",
    "hrv_ms", "hrv_status",
    "rhr",
    "bb_start", "bb_end", "bb_charged", "bb_drained",
    "stress_avg", "stress_max",
    "readiness", "readiness_lvl",
    "train_status",
    "acute_load", "chronic_load", "acwr", "acwr_zone",
    "respiration_waking", "respiration_sleeping",
    "intensity_moderate_min", "intensity_vigorous_min",
    "steps", "vo2max_running",
    # Oura-specific (rendered only on oura-source records).
    "temp_deviation", "resilience_level",
    "activity_score", "active_calories",
    "spo2_avg", "breathing_disturbance",
    "vascular_age", "pulse_wave_velocity",
    "stress_high", "recovery_high",
)

_BIOMETRIC_CATEGORICAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("hrv_status",    "HRV status"),
    ("train_status",  "Training status"),
    ("acwr_zone",     "ACWR zone"),
    ("readiness_lvl", "Readiness"),
)


# --- Activity (computer-usage) vocabulary -----------------------------------
# Headline scores first (Focus Engineering), then focus depth, then the
# switching family, rhythm, categories, and the death-loop summary.
_ACTIVITY_KEY_NUMBER_ORDER: tuple[str, ...] = (
    "combined_score", "productivity_score", "focus_score",
    "active_h",
    "sustained_focus_h", "longest_focus_block_min", "focus_blocks_ge_25min",
    # `human_switches*` are genuine fragmentation (AI-coding churn removed);
    # `context_switches*` stay as raw reference only (never baselined).
    "human_switches", "human_switches_per_active_hour",
    "context_switches", "switches_per_active_hour",
    "ai_assisted_switch_share", "ai_assisted_h",
    "meeting_h",
    "late_night_h", "late_night_ratio", "early_morning_h",
    "work_h", "personal_h", "unclassified_h",
    "top_category", "top_death_loop", "top_death_loops", "distracting_loop_count",
    "top_project", "top_app",
)

# Numeric metrics that feed σ-baselines — the VALID signals only. Raw
# `context_switches` / `switches_per_active_hour` are deliberately excluded
# (they conflate productive AI-assisted churn with real fragmentation —
# `human_switches*` is the clean signal). `combined_score` is excluded too
# (it is 0.6·productivity + 0.4·focus — baselining it would triple-count the
# same deviation). Categorical / context keys are never baselined.
_ACTIVITY_NUMERIC_METRICS: tuple[str, ...] = (
    "productivity_score", "focus_score",
    "active_h",
    "sustained_focus_h", "longest_focus_block_min", "focus_blocks_ge_25min",
    "human_switches", "human_switches_per_active_hour",
    "ai_assisted_h",
    "meeting_h",
    "late_night_h", "late_night_ratio", "early_morning_h",
    "work_h", "personal_h", "unclassified_h",
)

# (metric, direction) → streak concept. Named to the owner's stated work-
# rhythm goals: less GENUINE switching, more deep work / focus, higher
# productivity, less night work, earlier starts. Unmapped combos fall back
# to `<metric>_<direction>_streak`.
# Only metrics that actually σ-flag appear here (sparse metrics like
# sustained_focus_h / early_morning_h are excluded from deviation_thresholds, so
# their would-be streaks can never fire — the focus-drought signal is carried by
# `longest_focus_block_min` low → fragmented_focus_streak instead).
_ACTIVITY_CONCEPT_MAP: dict[tuple[str, str], str] = {
    ("human_switches_per_active_hour", "high"): "context_switch_spike_streak",
    ("focus_score", "low"):                     "focus_drop_streak",
    ("productivity_score", "low"):              "low_productivity_streak",
    ("late_night_ratio", "high"):               "late_night_work_streak",
    ("longest_focus_block_min", "low"):         "fragmented_focus_streak",
    ("meeting_h", "high"):                      "meeting_overload_streak",
}


BIOMETRIC = MetricDayProfile(
    name="biometric",
    kind="biometric",
    family_dir="biometric",
    domains=("health",),
    heading="Biometric",
    manifest_primary_type="biometric",
    extractor=biometric_extractor.extract,
    key_number_order=_BIOMETRIC_KEY_NUMBER_ORDER,
    numeric_metrics=_BIOMETRIC_NUMERIC_METRICS,
    categorical_pairs=_BIOMETRIC_CATEGORICAL_PAIRS,
    thresholds_basename="biometric_thresholds",
    is_sensitive=True,
    device_estimate=True,
    concept_map=None,            # biometric_streaks default map
    baseline_min_active_h=None,  # every wearable day counts
)

ACTIVITY = MetricDayProfile(
    name="activity",
    kind="activity",
    family_dir="activity",
    domains=("time", "work"),
    heading="Activity",
    manifest_primary_type="activity",
    extractor=activity_extractor.extract,
    key_number_order=_ACTIVITY_KEY_NUMBER_ORDER,
    numeric_metrics=_ACTIVITY_NUMERIC_METRICS,
    categorical_pairs=(),        # no categorical-transition events (yet)
    thresholds_basename="activity_thresholds",
    is_sensitive=True,           # verbatim titles/URLs leak work/client context
    device_estimate=None,        # measured, not estimated → omit the field
    concept_map=_ACTIVITY_CONCEPT_MAP,
    baseline_min_active_h=_ACTIVITY_BASELINE_MIN_ACTIVE_H,
)


_BY_SOURCE: dict[str, MetricDayProfile] = {
    "garmin": BIOMETRIC,
    "oura": BIOMETRIC,
    "activitywatch": ACTIVITY,
}


def for_source(source_id: str) -> MetricDayProfile:
    """Resolve the profile for a source id. Unknown → biometric default."""
    return _BY_SOURCE.get((source_id or "").split("/", 1)[0].strip().lower(), BIOMETRIC)
