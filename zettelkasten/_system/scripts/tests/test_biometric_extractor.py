"""Tests for biometric_extractor."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from biometric_extractor import extract  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "garmin"


def test_extract_full_metrics():
    r = extract(FIXTURES / "2024-01-01.md")
    assert r["date"] == "2024-01-01"
    assert r["status"] == "ok"
    m = r["metrics"]
    # core sleep
    assert m["sleep_h"] == 7.05
    assert m["sleep_score"] == 82
    assert m["deep_h"] == 2.2
    assert m["rem_h"] == 1.55
    assert m["awake_h"] == 0.1
    # recovery
    assert m["hrv_ms"] == 30
    assert m["hrv_status"] == "BALANCED"
    assert m["rhr"] == 53.0
    # stress
    assert m["stress_avg"] == 32
    assert m["stress_max"] == 90
    # body battery
    assert m["bb_charged"] == 52
    assert m["bb_drained"] == 50
    assert m["bb_start"] == 60
    assert m["bb_end"] == 52
    # readiness + training
    assert m["readiness"] == 88
    assert m["readiness_lvl"] == "HIGH"
    assert m["train_status"] == "DETRAINING"
    assert m["acute_load"] == 0
    assert m["chronic_load"] == 100
    assert m["acwr"] == 0.0
    assert m["acwr_zone"] == "LOW"
    # intensity + steps + respiration
    assert m["intensity_moderate_min"] == 0
    assert m["intensity_vigorous_min"] == 0
    assert m["steps"] == 3200
    assert m["respiration_waking"] == 14.5
    assert m["respiration_sleeping"] == 15.0


def test_extract_failure_stub():
    r = extract(FIXTURES / "2024-01-02-failure.md")
    assert r["status"] == "collection-failed"
    assert r["metrics_collected"] == []
    assert r["metrics"] == {}


def test_summary_section_preserved():
    r = extract(FIXTURES / "2024-01-01.md")
    s = r["summary_text"]
    assert "## Summary" in s
    assert "slept 7.05h" in s


def test_sleep_efficiency_computed():
    r = extract(FIXTURES / "2024-01-01.md")
    # asleep 25380 / (25380 + 360) = 0.986
    assert abs(r["metrics"]["sleep_efficiency"] - 0.986) < 0.005


def test_partial_metric_failures_kept_in_metric_failures():
    r = extract(FIXTURES / "2024-01-04-partial-failure.md")
    assert r["status"] == "ok"
    failures = r["metric_failures"]
    assert any("body_composition" in str(f) for f in failures)
    # body_composition not in metrics_collected → not extracted
    assert "rhr" in r["metrics"]
    assert "training_status" not in [k for k in r["metrics"]]


def test_workout_day_extraction():
    r = extract(FIXTURES / "2024-01-05-workout.md")
    m = r["metrics"]
    assert m["acute_load"] == 45
    assert m["acwr_zone"] == "OPTIMAL"
    assert m["train_status"] == "PRODUCTIVE"
    assert m["intensity_vigorous_min"] == 35
    assert m["vo2max_running"] == 47.0


def test_sleep_deprived_unbalanced_hrv():
    r = extract(FIXTURES / "2024-01-03-sleep-deprived.md")
    m = r["metrics"]
    assert m["sleep_h"] == 4.5
    assert m["sleep_score"] == 55
    assert m["hrv_status"] == "UNBALANCED"
    assert m["readiness_lvl"] == "LOW"


def test_oura_source_routes_to_oura_map(tmp_path):
    """An oura-source file maps Oura blocks to canonical keys, selects the
    main night (long_sleep) over nap fragments, and surfaces Oura-only
    signals (readiness score, temp deviation, resilience, SpO2, vascular age)."""
    src = tmp_path / "2026-06-07.md"
    src.write_text(
        "---\n"
        "date: '2026-06-07'\n"
        "source: oura\n"
        "status: ok\n"
        "metrics_collected: [daily_sleep, daily_readiness, daily_activity, "
        "daily_spo2, daily_cardiovascular_age, daily_resilience, sleep]\n"
        "metric_failures: []\n"
        "---\n\n"
        "## Summary\n- oura day.\n\n"
        "## Detailed data\n\n"
        "### daily_sleep\n\n```yaml\n- {day: '2026-06-07', score: 82}\n```\n\n"
        "### daily_readiness\n\n```yaml\n"
        "- {day: '2026-06-07', score: 85, temperature_deviation: -0.01}\n```\n\n"
        "### daily_activity\n\n```yaml\n"
        "- {day: '2026-06-07', score: 63, steps: 4882, active_calories: 391}\n```\n\n"
        "### daily_spo2\n\n```yaml\n"
        "- {day: '2026-06-07', spo2_percentage: {average: 96.6}, "
        "breathing_disturbance_index: 9}\n```\n\n"
        "### daily_cardiovascular_age\n\n```yaml\n"
        "- {day: '2026-06-07', vascular_age: 27, pulse_wave_velocity: 6.1583}\n```\n\n"
        "### daily_resilience\n\n```yaml\n- {day: '2026-06-07', level: adequate}\n```\n\n"
        "### sleep\n\n```yaml\n"
        "- {day: '2026-06-07', type: sleep, total_sleep_duration: 600, "
        "average_heart_rate: 0.0, deep_sleep_duration: 60, light_sleep_duration: 540, "
        "rem_sleep_duration: 0, awake_time: 810, efficiency: 43}\n"
        "- {day: '2026-06-07', type: long_sleep, total_sleep_duration: 25650, "
        "average_heart_rate: 57.375, lowest_heart_rate: 54, average_hrv: 25, "
        "average_breath: 15.0, deep_sleep_duration: 3930, light_sleep_duration: 14910, "
        "rem_sleep_duration: 6810, awake_time: 2250, efficiency: 92}\n```\n",
        encoding="utf-8",
    )
    m = extract(src)["metrics"]
    # main-night selection (not the 0.0-HR fragment)
    assert m["sleep_h"] == 7.12
    assert m["rhr"] == 54.0
    assert m["hrv_ms"] == 25
    assert m["sleep_efficiency"] == 92        # Oura 0-100 integer, kept as-is
    assert m["respiration_sleeping"] == 15.0
    # scores + Oura-only signals
    assert m["sleep_score"] == 82
    assert m["readiness"] == 85
    assert m["temp_deviation"] == -0.01
    assert m["resilience_level"] == "adequate"
    assert m["activity_score"] == 63
    assert m["steps"] == 4882
    assert m["spo2_avg"] == 96.6
    assert m["breathing_disturbance"] == 9
    assert m["vascular_age"] == 27
    assert m["pulse_wave_velocity"] == 6.16   # rounded
    # garmin-only keys never leak onto an oura record
    assert "bb_start" not in m
    assert "train_status" not in m


def test_robust_to_missing_metrics(tmp_path):
    """A source with only sleep should still parse cleanly."""
    src = tmp_path / "2024-02-01.md"
    src.write_text(
        "---\n"
        "date: '2024-02-01'\n"
        "source: garmin\n"
        "status: ok\n"
        "metrics_collected: [sleep]\n"
        "metric_failures: []\n"
        "---\n\n"
        "## Summary\n- minimal day.\n\n"
        "## Detailed data\n\n"
        "### sleep\n\n"
        "```yaml\n"
        "dailySleepDTO:\n"
        "  sleepTimeSeconds: 21600\n"
        "  deepSleepSeconds: 5400\n"
        "  remSleepSeconds: 3600\n"
        "  lightSleepSeconds: 12000\n"
        "  awakeSleepSeconds: 600\n"
        "```\n",
        encoding="utf-8",
    )
    r = extract(src)
    assert r["metrics"]["sleep_h"] == 6.0
    # all other keys absent
    assert "hrv_ms" not in r["metrics"]
    assert "rhr" not in r["metrics"]
