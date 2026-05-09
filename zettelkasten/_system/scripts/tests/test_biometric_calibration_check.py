"""Tests for biometric_calibration_check drift detection."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import biometric_calibration_check as bcc  # noqa: E402


THR = {
    "deviation_thresholds": {
        "sleep_h": {"direction": "low", "light": 1.0, "medium": 1.5, "strong": 2.0},
    },
    "calibration": {
        "enabled": True,
        "observation_window_weeks": 3,
        "drift_factor_threshold": 2.0,
        "silent_drift_factor_threshold": 0.5,
        "min_weeks_before_first_check": 4,
    },
}


def test_no_drift_with_normal_rates(tmp_path):
    p = tmp_path / "calibration.json"
    for w in [11, 12, 13, 14, 15]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.07}}, n_days=7)
    state = bcc.record_week(p, "2024-W16", {"sleep_h": {"medium": 0.06}}, n_days=7)
    proposals = bcc.detect_drift(state, THR)
    assert proposals == []


def test_drift_too_loose_emits_proposal(tmp_path):
    p = tmp_path / "calibration.json"
    # First load enough history to satisfy min_weeks_before_first_check
    for w in [10, 11]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.07}}, n_days=7)
    # 3 consecutive weeks with rate well over 2× expected (~0.0668)
    for w in [12, 13, 14]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.20}}, n_days=7)
    import json
    state = json.loads(p.read_text(encoding="utf-8"))
    proposals = bcc.detect_drift(state, THR)
    assert proposals
    assert proposals[0].metric == "sleep_h"
    assert proposals[0].severity == "medium"
    assert proposals[0].direction == "too_loose"
    assert proposals[0].observed_fire_rate >= 2 * proposals[0].expected_fire_rate
    # too_loose means firing too often → proposed σ must be HIGHER (stricter)
    assert proposals[0].proposed_sigma > proposals[0].current_sigma


def test_drift_too_tight_emits_proposal(tmp_path):
    p = tmp_path / "calibration.json"
    for w in [10, 11]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.07}}, n_days=7)
    for w in [12, 13, 14]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.01}}, n_days=7)
    import json
    state = json.loads(p.read_text(encoding="utf-8"))
    proposals = bcc.detect_drift(state, THR)
    too_tight = [p for p in proposals if p.direction == "too_tight"]
    assert too_tight
    # too_tight means firing too rarely → proposed σ must be LOWER (looser)
    assert too_tight[0].proposed_sigma < too_tight[0].current_sigma


def test_min_weeks_gate(tmp_path):
    p = tmp_path / "calibration.json"
    # only 3 weeks total — below min_weeks_before_first_check=4
    for w in [10, 11, 12]:
        bcc.record_week(p, f"2024-W{w:02d}", {"sleep_h": {"medium": 0.30}}, n_days=7)
    import json
    state = json.loads(p.read_text(encoding="utf-8"))
    proposals = bcc.detect_drift(state, THR)
    assert proposals == []
