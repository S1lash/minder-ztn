"""Tests for biometric_streaks state machine."""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from biometric_streaks import advance, concept_for  # noqa: E402


@dataclass
class FakeDev:
    metric: str
    severity: str
    direction: str
    value: float = 0.0
    sigma_distance: float = 0.0
    baseline_mu: float = 0.0
    baseline_sigma: float = 0.0


def test_streak_starts_only_on_third_consecutive_day(tmp_path):
    p = tmp_path / "streaks.json"
    devs = [FakeDev("hrv_ms", "medium", "low")]
    s1, ev1 = advance(p, "2024-01-01", devs)
    assert ev1 == []  # day 1
    s2, ev2 = advance(p, "2024-01-02", devs)
    assert ev2 == []  # day 2
    s3, ev3 = advance(p, "2024-01-03", devs)
    # day 3 — state-concept emitted
    assert any(e.kind == "state" and e.concept == "low_hrv_streak" for e in ev3)


def test_recovery_on_break_after_streak_emitted(tmp_path):
    p = tmp_path / "streaks.json"
    devs = [FakeDev("hrv_ms", "medium", "low")]
    advance(p, "2024-01-01", devs)
    advance(p, "2024-01-02", devs)
    advance(p, "2024-01-03", devs)
    # streak now emitted; break it
    _state, ev = advance(p, "2024-01-04", [])
    assert any(e.kind == "recovery" and e.concept == "recovery_after_low_hrv_streak" for e in ev)


def test_no_recovery_if_streak_never_crossed_threshold(tmp_path):
    p = tmp_path / "streaks.json"
    devs = [FakeDev("hrv_ms", "medium", "low")]
    advance(p, "2024-01-01", devs)
    advance(p, "2024-01-02", devs)
    # break before day 3
    _state, ev = advance(p, "2024-01-03", [])
    assert all(e.kind != "recovery" for e in ev)


def test_severity_gate_default_medium(tmp_path):
    p = tmp_path / "streaks.json"
    light = [FakeDev("sleep_h", "light", "low")]
    advance(p, "2024-01-01", light)
    advance(p, "2024-01-02", light)
    s3, ev3 = advance(p, "2024-01-03", light)
    # light deviations don't count toward streak
    assert ev3 == []
    assert s3["active"] == {}


def test_concept_naming_known_pairs():
    assert concept_for("hrv_ms", "low") == "low_hrv_streak"
    assert concept_for("rhr", "high") == "rhr_elevation_streak"
    assert concept_for("sleep_h", "low") == "sleep_debt"
    # unknown pair → generic
    assert concept_for("bb_charged", "low") == "bb_charged_low_streak"


def test_idempotent_same_date_replay(tmp_path):
    p = tmp_path / "streaks.json"
    devs = [FakeDev("hrv_ms", "medium", "low")]
    advance(p, "2024-01-01", devs)
    advance(p, "2024-01-02", devs)
    s_a, _ = advance(p, "2024-01-03", devs)
    days_first = s_a["active"]["low_hrv_streak"]["days"]
    # replay same date — should NOT increment to 4
    s_b, _ = advance(p, "2024-01-03", devs)
    days_second = s_b["active"]["low_hrv_streak"]["days"]
    assert days_first == days_second == 3
