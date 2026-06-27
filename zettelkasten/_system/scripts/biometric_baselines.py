"""Rolling baseline engine for biometric metrics.

Per-metric sliding window of recent values + computed μ, σ, n.
Atomic write. Idempotent on same-date re-runs (replaces same-date entry).

State file shape:
{
  "metrics": {
    "sleep_h": {
      "window": 28,
      "values": [{"date": "YYYY-MM-DD", "value": 7.05}, ...],
      "mu": 7.13, "sigma": 0.72, "n": 28
    }, ...
  },
  "last_updated": "ISO-8601"
}

Cold-start handling per `cold_start.full_disable_below_days` /
`reduced_mode_below_days` from thresholds yaml — handled by caller
in `flag_deviations`.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# Numeric metrics that participate in σ-deviation tracking. Categorical
# metrics (hrv_status, train_status, acwr_zone, readiness_lvl) are
# excluded — they go through transition detection in process_metric_day.
NUMERIC_METRICS: tuple[str, ...] = (
    "sleep_h", "deep_h", "rem_h", "light_h", "awake_h",
    "sleep_score", "sleep_efficiency",
    "hrv_ms",
    "rhr",
    "stress_avg", "stress_max",
    "bb_start", "bb_end", "bb_charged", "bb_drained",
    "readiness",
    "acute_load", "chronic_load", "acwr",
    "intensity_moderate_min", "intensity_vigorous_min",
    "respiration_waking", "respiration_sleeping",
    "steps", "vo2max_running",
    # Oura-specific numerics (present only on oura-source records; baselines
    # are per-source so these never mix with a Garmin device's distribution).
    "temp_deviation", "spo2_avg", "breathing_disturbance",
    "vascular_age", "pulse_wave_velocity",
    "activity_score", "active_calories",
    "stress_high", "recovery_high",
)


@dataclass(frozen=True)
class Deviation:
    metric: str
    severity: str           # 'light' | 'medium' | 'strong'
    direction: str          # 'low' | 'high'
    value: float
    sigma_distance: float   # signed
    baseline_mu: float
    baseline_sigma: float


def _empty_state() -> dict[str, Any]:
    return {"metrics": {}, "last_updated": None}


def load(baselines_path: str | Path) -> dict[str, Any]:
    p = Path(baselines_path)
    if not p.exists():
        return _empty_state()
    return json.loads(p.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _window_for(metric: str, thresholds: dict[str, Any]) -> int:
    bw = thresholds.get("baseline_windows", {}) or {}
    if metric in {"acute_load", "chronic_load"}:
        return int(bw.get("chronic_load", 42))
    return int(bw.get("default", 28))


def _recompute(values: list[dict[str, Any]]) -> tuple[float | None, float | None, int]:
    nums = [v["value"] for v in values if isinstance(v.get("value"), (int, float))]
    n = len(nums)
    if n < 2:
        return (nums[0] if nums else None, None, n)
    mu = statistics.fmean(nums)
    sigma = statistics.pstdev(nums)
    return (mu, sigma, n)


def update(
    baselines_path: str | Path,
    date: str,
    metrics_dict: dict[str, Any],
    thresholds: dict[str, Any],
    numeric_metrics: tuple[str, ...] = NUMERIC_METRICS,
) -> dict[str, Any]:
    """Append today's values into rolling windows, recompute μ/σ, write.

    Idempotent on same-date re-runs: replaces the existing same-date
    entry rather than appending a duplicate.

    `numeric_metrics` is the set of keys σ-tracked for this source. It
    defaults to the biometric set; the metric-day profile passes its own
    (e.g. the activity rhythm metrics) so the rolling engine stays
    source-agnostic.
    """
    state = load(baselines_path)
    by_metric = state.setdefault("metrics", {})

    for key in numeric_metrics:
        if key not in metrics_dict:
            continue
        val = metrics_dict[key]
        if not isinstance(val, (int, float)):
            continue
        window = _window_for(key, thresholds)
        m = by_metric.setdefault(key, {"window": window, "values": []})
        m["window"] = window
        # idempotent same-date handling
        m["values"] = [v for v in m["values"] if v.get("date") != date]
        m["values"].append({"date": date, "value": float(val)})
        # keep sorted by date, drop oldest beyond window
        m["values"].sort(key=lambda v: v["date"])
        if len(m["values"]) > window:
            m["values"] = m["values"][-window:]
        mu, sigma, n = _recompute(m["values"])
        m["mu"] = mu
        m["sigma"] = sigma
        m["n"] = n

    state["last_updated"] = date
    _atomic_write(Path(baselines_path), state)
    return state


def flag_deviations(
    baselines: dict[str, Any],
    today_metrics: dict[str, Any],
    thresholds: dict[str, Any],
) -> list[Deviation]:
    """Compute σ-deviation flags for today against each metric's baseline.

    Cold-start logic (per `cold_start` block of thresholds):
      n < full_disable_below_days → no flags
      n < reduced_mode_below_days → only `strong` severity emitted
      else → full thresholds (light / medium / strong)

    Direction (`low` | `high`) is one-sided where the other side is benign.
    `both` would allow either side; not currently used by spec.
    """
    out: list[Deviation] = []
    cs = thresholds.get("cold_start", {}) or {}
    full_disable = int(cs.get("full_disable_below_days", 14))
    reduced = int(cs.get("reduced_mode_below_days", 28))
    reduced_min = (cs.get("reduced_mode_min_severity") or "strong").lower()

    dev_thr: dict[str, Any] = thresholds.get("deviation_thresholds", {}) or {}
    by_metric: dict[str, Any] = baselines.get("metrics", {}) or {}

    for metric, conf in dev_thr.items():
        if metric not in today_metrics:
            continue
        val = today_metrics[metric]
        if not isinstance(val, (int, float)):
            continue
        m = by_metric.get(metric)
        if not m:
            continue
        n = m.get("n") or 0
        if n < full_disable:
            continue
        mu = m.get("mu")
        sigma = m.get("sigma") or 0.0
        if mu is None or sigma is None or sigma == 0:
            continue

        direction = (conf.get("direction") or "low").lower()
        light = conf.get("light")
        medium = conf.get("medium")
        strong = conf.get("strong")

        sigma_dist = (val - mu) / sigma  # signed

        # Pick severity based on side and thresholds.
        # 'low' direction → trigger when value below μ (sigma_dist negative)
        # 'high' direction → trigger when value above μ (sigma_dist positive)
        if direction == "low":
            magnitude = -sigma_dist  # positive when below baseline
        elif direction == "high":
            magnitude = sigma_dist
        else:
            magnitude = abs(sigma_dist)

        if magnitude <= 0:
            continue

        severity: Optional[str] = None
        # Check strong → medium → light (descending). Strong takes precedence.
        if strong is not None and magnitude >= float(strong):
            severity = "strong"
        elif medium is not None and magnitude >= float(medium):
            severity = "medium"
        elif light is not None and magnitude >= float(light):
            severity = "light"

        if severity is None:
            continue

        # Reduced mode: only emit at-or-above the reduced_min severity.
        if n < reduced:
            order = {"light": 1, "medium": 2, "strong": 3}
            if order.get(severity, 0) < order.get(reduced_min, 3):
                continue

        out.append(
            Deviation(
                metric=metric,
                severity=severity,
                direction=direction if direction in ("low", "high") else (
                    "low" if sigma_dist < 0 else "high"
                ),
                value=float(val),
                sigma_distance=float(sigma_dist),
                baseline_mu=float(mu),
                baseline_sigma=float(sigma),
            )
        )

    return out
