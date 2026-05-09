"""Threshold drift detection for biometric deviation thresholds.

Tier II Tier-2 calibration check: count threshold fire-rate over recent
weekly correlations + per-day records and propose new σ thresholds when
observed/expected ratio drifts outside [silent_drift_factor_threshold,
drift_factor_threshold] for ≥observation_window_weeks consecutive weeks.

Expected fire-rate per severity (one-sided, normal-ish distribution):
  light  (1.0σ low) ≈ 15.87%
  medium (1.5σ)     ≈ 6.68%
  strong (2.0σ)     ≈ 2.28%

State file: `_system/state/biometric/calibration-history.json`
  {"weeks": [{"iso_week": ..., "fire_rates": {metric: {sev: rate}}, "n_days": N}, ...]}
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


EXPECTED_FIRE_RATE = {
    "light":  0.1587,   # 1.0σ one-sided
    "medium": 0.0668,   # 1.5σ one-sided
    "strong": 0.0228,   # 2.0σ one-sided
}


@dataclass
class ThresholdProposal:
    metric: str
    severity: str
    current_sigma: float
    proposed_sigma: float
    observed_fire_rate: float
    expected_fire_rate: float
    weeks_observed: int
    direction: str        # 'too_loose' | 'too_tight'


def _load_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"weeks": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_history(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _sigma_for_one_sided_tail(target_rate: float) -> float:
    """Return σ-distance whose one-sided tail probability equals
    `target_rate` under standard-normal assumption."""
    if target_rate <= 0 or target_rate >= 1:
        return 2.0
    return _norm_inv(1 - target_rate)


def _proposed_sigma(current_sigma: float, observed_rate: float, expected_rate: float) -> float:
    """Recalibrate σ threshold to bring observed → expected fire rate.

    Model: assume current threshold at `current_sigma` produces
    `observed_rate` of one-sided crossings. The data's effective
    "noise scale" is therefore wider/narrower than the baseline σ
    assumed when the current threshold was set. To bring the fire
    rate back to `expected_rate` while leaving the data alone, the
    threshold must scale by the ratio of standard-normal critical
    values:

      new_σ = current_σ × Φ⁻¹(1-expected) / Φ⁻¹(1-observed)

    For too-loose drift (observed > expected) the ratio > 1 → σ goes
    UP (stricter, fewer fires). For too-tight (observed < expected)
    the ratio < 1 → σ goes DOWN (looser, more fires). This direction
    is correct.
    """
    if observed_rate <= 0 or expected_rate <= 0:
        return current_sigma
    sigma_for_observed = _sigma_for_one_sided_tail(observed_rate)
    sigma_for_expected = _sigma_for_one_sided_tail(expected_rate)
    if sigma_for_observed <= 0:
        return current_sigma
    return current_sigma * (sigma_for_expected / sigma_for_observed)


def _norm_inv(p: float) -> float:
    """Approximate inverse standard normal CDF (Acklam's algorithm — short form)."""
    a = [-39.6968302866538, 220.946098424521, -275.928510446969,
         138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887,
         66.8013118877197, -13.2806815528857]
    c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184,
         -2.54973253934373, 4.37466414146497, 2.93816398269878]
    d = [0.00778469570904146, 0.32246712907004, 2.445134137143,
         3.75440866190742]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return ((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5] / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
           ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)


def record_week(
    calibration_state_path: str | Path,
    iso_week: str,
    fire_rates: dict[str, dict[str, float]],
    n_days: int,
) -> dict[str, Any]:
    """Append per-week observation to history (idempotent on iso_week)."""
    p = Path(calibration_state_path)
    state = _load_history(p)
    weeks = state.setdefault("weeks", [])
    weeks = [w for w in weeks if w.get("iso_week") != iso_week]
    weeks.append({
        "iso_week": iso_week,
        "fire_rates": fire_rates,
        "n_days": n_days,
    })
    weeks.sort(key=lambda w: w.get("iso_week", ""))
    state["weeks"] = weeks
    _save_history(p, state)
    return state


def detect_drift(
    calibration_state: dict[str, Any],
    thresholds: dict[str, Any],
) -> list[ThresholdProposal]:
    """Scan history; propose new σ values where consistent drift exceeds
    factor for ≥ observation_window_weeks weeks."""
    cal_cfg = thresholds.get("calibration", {}) or {}
    if not cal_cfg.get("enabled", True):
        return []
    drift_high = float(cal_cfg.get("drift_factor_threshold", 2.0))
    drift_low = float(cal_cfg.get("silent_drift_factor_threshold", 0.5))
    win = int(cal_cfg.get("observation_window_weeks", 3))
    min_first = int(cal_cfg.get("min_weeks_before_first_check", 4))
    weeks = calibration_state.get("weeks", []) or []
    if len(weeks) < max(win, min_first):
        return []
    # Only inspect the last `win` consecutive weeks.
    recent = weeks[-win:]
    proposals: list[ThresholdProposal] = []
    dev_thr = thresholds.get("deviation_thresholds", {}) or {}

    # Aggregate fire-rates across `metric × severity` and require all
    # `win` weeks to be on the same drift side.
    by_pair: dict[tuple[str, str], list[float]] = {}
    for w in recent:
        for metric, by_sev in (w.get("fire_rates") or {}).items():
            for sev, rate in (by_sev or {}).items():
                by_pair.setdefault((metric, sev), []).append(rate)

    for (metric, sev), rates in by_pair.items():
        if len(rates) < win:
            continue
        expected = EXPECTED_FIRE_RATE.get(sev)
        if not expected:
            continue
        # Ratio = observed / expected. Trigger when ALL `win` rates
        # cross the same threshold side.
        ratios = [r / expected if expected > 0 else 0.0 for r in rates]
        if all(rr > drift_high for rr in ratios):
            avg_rate = sum(rates) / len(rates)
            current = float(dev_thr.get(metric, {}).get(sev) or 0.0)
            proposed = round(_proposed_sigma(current, avg_rate, expected), 2)
            proposals.append(ThresholdProposal(
                metric=metric, severity=sev,
                current_sigma=current,
                proposed_sigma=proposed,
                observed_fire_rate=round(avg_rate, 4),
                expected_fire_rate=expected,
                weeks_observed=len(rates),
                direction="too_loose",
            ))
        elif all(rr < drift_low for rr in ratios):
            avg_rate = max(sum(rates) / len(rates), 0.0001)
            current = float(dev_thr.get(metric, {}).get(sev) or 0.0)
            proposed = round(_proposed_sigma(current, avg_rate, expected), 2)
            proposals.append(ThresholdProposal(
                metric=metric, severity=sev,
                current_sigma=current,
                proposed_sigma=proposed,
                observed_fire_rate=round(avg_rate, 4),
                expected_fire_rate=expected,
                weeks_observed=len(rates),
                direction="too_tight",
            ))
    return proposals


def proposal_to_dict(p: ThresholdProposal) -> dict[str, Any]:
    return asdict(p)
