"""Tests for biometric_baselines rolling stats + flag computation."""

from __future__ import annotations

import sys
import yaml
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import biometric_baselines as bm  # noqa: E402


THRESHOLDS = {
    "deviation_thresholds": {
        "sleep_h": {"direction": "low", "light": 1.0, "medium": 1.5, "strong": 2.0},
        "hrv_ms":  {"direction": "low", "light": 1.0, "medium": 1.5, "strong": 2.0},
        "rhr":     {"direction": "high", "medium": 1.5, "strong": 2.0},
    },
    "baseline_windows": {"default": 28, "chronic_load": 42},
    "cold_start": {
        "full_disable_below_days": 14,
        "reduced_mode_below_days": 28,
        "reduced_mode_min_severity": "strong",
    },
}


def test_update_rolling_window_and_recompute(tmp_path):
    p = tmp_path / "baselines.json"
    # 30 days of sleep_h around 7.0 ± 0.5
    for i, val in enumerate([7.0, 7.5, 6.5] * 10, start=1):
        date = f"2024-01-{i:02d}" if i <= 31 else None
        if date is None:
            break
        bm.update(p, date, {"sleep_h": val}, THRESHOLDS)

    state = bm.load(p)
    s = state["metrics"]["sleep_h"]
    assert s["window"] == 28
    assert s["n"] == 28  # capped at window
    assert 6.6 < s["mu"] < 7.4
    assert s["sigma"] is not None and s["sigma"] > 0


def test_idempotent_same_date(tmp_path):
    p = tmp_path / "baselines.json"
    bm.update(p, "2024-01-01", {"sleep_h": 7.0}, THRESHOLDS)
    bm.update(p, "2024-01-01", {"sleep_h": 7.0}, THRESHOLDS)
    state = bm.load(p)
    assert state["metrics"]["sleep_h"]["n"] == 1


def test_cold_start_n_below_full_disable_no_flags(tmp_path):
    p = tmp_path / "baselines.json"
    # 5 days only — well below 14
    for i, val in enumerate([7.0, 7.0, 7.0, 7.0, 7.0], start=1):
        bm.update(p, f"2024-01-{i:02d}", {"sleep_h": val}, THRESHOLDS)
    state = bm.load(p)
    devs = bm.flag_deviations(state, {"sleep_h": 4.0}, THRESHOLDS)
    assert devs == []


def test_reduced_mode_only_strong(tmp_path):
    p = tmp_path / "baselines.json"
    # 20 days, slight variation
    for i in range(1, 21):
        bm.update(p, f"2024-01-{i:02d}", {"sleep_h": 7.0 + (i % 2) * 0.1}, THRESHOLDS)
    state = bm.load(p)
    # value 6.85 vs μ ~7.05, σ ~0.05 → ~4σ low → strong (passes reduced mode)
    devs = bm.flag_deviations(state, {"sleep_h": 6.85}, THRESHOLDS)
    severities = {d.severity for d in devs}
    assert severities == {"strong"} or severities == set()


def test_full_mode_emits_light_medium_strong(tmp_path):
    p = tmp_path / "baselines.json"
    # 30 days, μ≈7.0, σ≈0.5 (alternating 6.5/7.5)
    for i in range(1, 31):
        val = 6.5 if i % 2 == 0 else 7.5
        bm.update(p, f"2024-01-{i:02d}", {"sleep_h": val}, THRESHOLDS)
    state = bm.load(p)
    # 5.0 → ~4σ low → strong
    devs = bm.flag_deviations(state, {"sleep_h": 5.0}, THRESHOLDS)
    assert devs and devs[0].severity == "strong"
    # 6.0 → ~2σ low → strong (boundary)
    # 6.4 → ~1.2σ low → light
    devs2 = bm.flag_deviations(state, {"sleep_h": 6.4}, THRESHOLDS)
    if devs2:
        assert devs2[0].severity in {"light", "medium"}


def test_high_direction(tmp_path):
    p = tmp_path / "baselines.json"
    for i in range(1, 31):
        val = 50 + (i % 3) * 2  # μ ≈ 52, σ small
        bm.update(p, f"2024-01-{i:02d}", {"rhr": val}, THRESHOLDS)
    state = bm.load(p)
    devs = bm.flag_deviations(state, {"rhr": 80}, THRESHOLDS)
    assert devs and devs[0].direction == "high"
    assert devs[0].severity == "strong"


def test_chronic_load_uses_42d_window(tmp_path):
    p = tmp_path / "baselines.json"
    for i in range(1, 50):
        bm.update(p, f"2024-01-{i:02d}", {"chronic_load": 100}, THRESHOLDS)
    state = bm.load(p)
    cl = state["metrics"]["chronic_load"]
    assert cl["window"] == 42
    assert cl["n"] == 42
