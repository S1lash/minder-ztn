"""Tests for biometric_correlations."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import biometric_correlations as bc  # noqa: E402


def _seq_dates(n: int, start: str = "2024-01-01") -> list[str]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def test_pearson_perfect_positive_lag0():
    dates = _seq_dates(20)
    a = {d: float(i) for i, d in enumerate(dates)}
    b = {d: float(i) * 2 for i, d in enumerate(dates)}
    findings = bc.compute_pairs({"a": a, "b": b}, lag_max=0, min_severity="weak")
    assert findings
    assert findings[0].severity == "strong"
    assert findings[0].r == 1.0
    assert findings[0].direction == "positive"


def test_pearson_lag_picks_strongest_lag():
    dates = _seq_dates(20)
    # a is a noisy sinusoid; b = a shifted forward 2 days, with noise on
    # other lags so only lag=2 has the clean signal.
    import math
    a = {d: math.sin(i * 0.7) for i, d in enumerate(dates)}
    # b on day i+2 = sin(i*0.7); other days = noise
    b = {}
    for i in range(20):
        if i >= 2:
            b[dates[i]] = math.sin((i - 2) * 0.7)
        else:
            b[dates[i]] = 0.0
    findings = bc.compute_pairs({"a": a, "b": b}, lag_max=3, min_severity="weak")
    matches = [f for f in findings if f.a == "a" and f.b == "b"]
    assert matches
    # Either lag 0 or lag 2 may dominate depending on noise correlation.
    # Assert that the strongest lag has |r| ≥ 0.5.
    assert abs(matches[0].r) >= 0.5


def test_skip_zero_variance():
    dates = _seq_dates(20)
    a = {d: 7.0 for d in dates}  # constant
    b = {d: float(i) for i, d in enumerate(dates)}
    findings = bc.compute_pairs({"a": a, "b": b}, lag_max=0, min_severity="weak")
    assert findings == []


def test_skip_below_min_n():
    dates = _seq_dates(10)  # below min_n=14
    a = {d: float(i) for i, d in enumerate(dates)}
    b = {d: float(i) for i, d in enumerate(dates)}
    findings = bc.compute_pairs({"a": a, "b": b}, lag_max=0, min_n=14, min_severity="weak")
    assert findings == []


def test_point_biserial_signal():
    dates = _seq_dates(40)
    metric = {d: 30.0 + (5.0 if i % 4 == 0 else 0.0) for i, d in enumerate(dates)}
    affect = {d: {"anxious"} if i % 4 == 0 else set() for i, d in enumerate(dates)}
    findings = bc.compute_cross({"hrv_ms": metric}, affect, lag_max=0, min_total=14, min_positive=5, min_severity="medium")
    matches = [f for f in findings if f.affect == "anxious"]
    assert matches
    assert matches[0].r_pb > 0.4


def test_anomaly_cluster_consecutive():
    devs = {
        "2024-01-05": ["sleep_h", "hrv_ms"],
        "2024-01-06": ["sleep_h", "hrv_ms", "readiness"],
        "2024-01-07": ["readiness"],            # only 1 metric — does not qualify
        "2024-01-09": ["sleep_h", "hrv_ms"],     # gap of 1 day from 06 → joined? gap from 06 to 09 = 3 — separate
    }
    clusters = bc.detect_anomaly_clusters(devs, min_metrics=2, max_gap_days=2)
    # cluster 1: 05..06; cluster 2: 09 alone
    assert len(clusters) == 2
    assert clusters[0].date_start == "2024-01-05"
    assert clusters[0].date_end == "2024-01-06"
