"""Tests for the activitywatch metric-day path: extractor + profile wiring.

The shared baseline/streak statistics are covered by the biometric suites;
here we test the NEW surface — the activity field map, the profile-driven
record (namespace / kind / domains / vocabulary), the empty-day baseline
gate, and that the activity concept map names streaks to the owner's goals.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import activity_extractor  # noqa: E402
import biometric_streaks as streaks  # noqa: E402
import metric_day_profiles as profiles  # noqa: E402
import process_metric_day as pmd  # noqa: E402
from biometric_baselines import Deviation  # noqa: E402


def _aw_file(date: str, agg: dict, status: str = "ok") -> str:
    # Build with column-0 fences exactly like the collector's renderer emits —
    # no textwrap/f-string raggedness, so the `\n```` closing-fence anchor holds.
    fm = (
        "---\n"
        f"date: {date}\n"
        "source: activitywatch\n"
        "user: john-doe\n"
        "hostname: laptop.local\n"
        "timezone: system\n"
        f'collected_at: "{date}T00:00:00+00:00"\n'
        f"status: {status}\n"
        "is_sensitive: true\n"
        "event_count: 4200\n"
        "---\n"
    )
    return (
        f"{fm}\n"
        f"# ActivityWatch daily — {date}\n\n"
        "## Summary\n\n"
        "- **Active (not-AFK):** 7h 20m\n"
        "- **Context switches:** 312 (43/active-hr)\n\n"
        "## Detailed aggregates\n\n"
        "```json\n"
        f"{json.dumps(agg, indent=2)}\n"
        "```\n\n"
        f"_Full raw events: `raw/{date}.json`._\n"
    )


def _full_agg() -> dict:
    return {
        "schema_version": 3,
        "active_seconds": 26400.0,          # 7.33 h
        "first_active": "2026-06-23T06:00:00+00:00",
        "last_active": "2026-06-23T22:00:00+00:00",
        "active_seconds_by_app": {"Slack": 8000.0, "PyCharm": 5400.0},
        "web_seconds_by_domain": {"jira.example.com": 2000.0},
        "top_titles": [["PR #1168", 1200.0]],
        "seconds_by_project_raw": {"paymentgate": 360.0},
        "event_counts": {"currentwindow": 3000},
        "context_switches": 312,
        "switches_per_active_hour": 42.5,
        "longest_focus_block_seconds": 2700.0,   # 45 min
        "sustained_focus_seconds": 5400.0,       # 1.5 h (blocks ≥25min)
        "focus_blocks_ge_25min": 2,
        "late_night_active_seconds": 3600.0,     # 1.0 h
        "late_night_ratio": 0.14,
        "early_morning_active_seconds": 1800.0,  # 0.5 h
        "meeting_seconds": 4200.0,               # 1.17 h
        "work_seconds": 20000.0,
        "personal_seconds": 3000.0,
        "unclassified_seconds": 3400.0,
        "window_seconds_by_app_raw": {"loginwindow": 33000.0},
        "input": {"presses": 0, "clicks": 0},
        # --- v3 ---
        "seconds_by_category": {"deep_work": 9000.0, "communication_work": 8000.0,
                                "work_acme": 4000.0, "uncategorized": 5400.0},
        "productivity_score": 72.0,
        "focus_score": 65.0,
        "combined_score": 69.0,
        "ai_assisted_seconds": 5400.0,           # 1.5 h
        "ai_assisted_switches": 100,
        "human_switches": 212,
        "human_switches_per_active_hour": 28.9,
        "ai_agents": {"claude_code": {"seconds": 5400.0, "switches": 100}},
        "death_loops": [
            {"pair": "PyCharm <-> Терминал", "count": 80, "verdict": "ai_assisted"},
            {"pair": "Google Chrome <-> Slack", "count": 60, "verdict": "mixed"},
            {"pair": "Mail <-> Slack", "count": 30, "verdict": "distracting"},
        ],
    }


# --- extractor ---------------------------------------------------------------

def test_extractor_maps_seconds_to_hours_and_counts(tmp_path):
    p = tmp_path / "2026-06-23.md"
    p.write_text(_aw_file("2026-06-23", _full_agg()), encoding="utf-8")
    parsed = activity_extractor.extract(p)

    assert parsed["date"] == "2026-06-23"
    assert parsed["status"] == "ok"
    m = parsed["metrics"]
    assert m["active_h"] == 7.33
    assert m["context_switches"] == 312
    assert m["switches_per_active_hour"] == 42.5
    assert m["longest_focus_block_min"] == 45
    assert m["sustained_focus_h"] == 1.5
    assert m["focus_blocks_ge_25min"] == 2
    assert m["late_night_h"] == 1.0
    assert m["late_night_ratio"] == 0.14
    assert m["meeting_h"] == 1.17
    assert m["top_app"] == "Slack"        # max active_seconds_by_app
    assert parsed["metric_failures"] == []
    # v3 metrics
    assert m["productivity_score"] == 72.0
    assert m["focus_score"] == 65.0
    assert m["combined_score"] == 69.0
    assert m["human_switches"] == 212
    assert m["human_switches_per_active_hour"] == 28.9
    assert m["ai_assisted_h"] == 1.5
    assert m["ai_assisted_switch_share"] == round(100 / 312, 2)
    assert m["top_category"] == "deep_work"        # uncategorized excluded
    # top death loop = first mixed/distracting (ai_assisted PyCharm↔Терминал skipped)
    assert m["top_death_loop"] == "Google Chrome <-> Slack ×60 (mixed)"
    # top-3 leak string preserves 2nd/3rd (ai_assisted excluded)
    assert m["top_death_loops"] == "Google Chrome <-> Slack ×60 (mixed); Mail <-> Slack ×30 (distracting)"
    assert m["distracting_loop_count"] == 2         # mixed + distracting, not ai_assisted
    assert m["top_project"] == "paymentgate"        # max seconds_by_project_raw


def test_death_loop_summary_skips_ai_assisted_and_productive():
    import activity_extractor as ax
    # only ai_assisted/productive loops → no attention-leak loop surfaced
    agg = {"death_loops": [
        {"pair": "IDE <-> Term", "count": 90, "verdict": "ai_assisted"},
        {"pair": "IDE <-> Browser", "count": 40, "verdict": "productive"},
    ]}
    label, count, top3 = ax._death_loop_summary(agg)
    assert label is None and count == 0 and top3 is None


def test_extractor_flags_unparsed_aggregate(tmp_path):
    p = tmp_path / "2026-06-23.md"
    # status ok but no aggregate block
    p.write_text("---\ndate: 2026-06-23\nstatus: ok\n---\n\n## Summary\n\nx\n", encoding="utf-8")
    parsed = activity_extractor.extract(p)
    assert "detailed_aggregates_unparsed" in parsed["metric_failures"]


# --- profile-driven record ---------------------------------------------------

def _setup_base(tmp_path: Path) -> Path:
    base = tmp_path / "base"
    (base / "_sources" / "inbox" / "activitywatch").mkdir(parents=True)
    (base / "_sources" / "processed" / "activitywatch").mkdir(parents=True)
    scripts = base / "_system" / "scripts"
    scripts.mkdir(parents=True)
    (base / "_system" / "state").mkdir(parents=True, exist_ok=True)
    # Provide the activity thresholds the profile asks for.
    shutil.copy(
        SCRIPTS_DIR / "activity_thresholds.template.yaml",
        scripts / "activity_thresholds.template.yaml",
    )
    return base


def _stage(base: Path, date: str, agg: dict, status: str = "ok") -> Path:
    target = base / "_sources" / "inbox" / "activitywatch" / f"{date}.md"
    target.write_text(_aw_file(date, agg, status), encoding="utf-8")
    return target


def test_activity_record_lands_in_activity_namespace(tmp_path):
    base = _setup_base(tmp_path)
    src = _stage(base, "2026-06-23", _full_agg())
    res = pmd.run(src, base_dir=base, source_id="activitywatch")

    assert res.outcome == "emitted"
    rec = base / "_records" / "activity" / "activitywatch" / "2026-06-23.md"
    assert rec.exists()                                   # NOT under biometric/
    assert not (base / "_records" / "biometric").exists()
    text = rec.read_text(encoding="utf-8")
    assert "kind: activity" in text
    assert "# Activity — 2026-06-23" in text
    assert "- time" in text and "- work" in text          # domains
    assert "device_estimate" not in text                  # measured, not estimated
    assert "is_sensitive: true" in text
    assert "context_switches: 312" in text
    assert "sustained_focus_h: 1.5" in text
    # baselines namespaced under activity/
    assert (base / "_system" / "state" / "activity" / "activitywatch" / "baselines.json").exists()
    assert res.manifest_entry["primary_type"] == "activity"
    assert res.manifest_entry["section_extras"]["domains"] == ["time", "work"]


def test_empty_day_emits_record_but_skips_baseline(tmp_path):
    base = _setup_base(tmp_path)
    empty = {
        "schema_version": 2, "active_seconds": 0.0, "first_active": None,
        "last_active": None, "active_seconds_by_app": {}, "web_seconds_by_domain": {},
        "top_titles": [], "seconds_by_project_raw": {}, "event_counts": {},
        "context_switches": 0, "switches_per_active_hour": 0.0,
        "longest_focus_block_seconds": 0.0, "sustained_focus_seconds": 0.0,
        "focus_blocks_ge_25min": 0, "late_night_active_seconds": 0.0,
        "late_night_ratio": 0.0, "early_morning_active_seconds": 0.0,
        "meeting_seconds": 0.0, "work_seconds": 0.0, "personal_seconds": 0.0,
        "unclassified_seconds": 0.0, "window_seconds_by_app_raw": {},
        "input": {"presses": 0, "clicks": 0},
    }
    src = _stage(base, "2026-06-14", empty)
    res = pmd.run(src, base_dir=base, source_id="activitywatch")
    assert res.outcome == "emitted"
    # record exists, but the near-idle day did NOT seed the baselines
    bl = base / "_system" / "state" / "activity" / "activitywatch" / "baselines.json"
    if bl.exists():
        state = json.loads(bl.read_text(encoding="utf-8"))
        for m in state.get("metrics", {}).values():
            assert all(v.get("date") != "2026-06-14" for v in m.get("values", []))


# --- concept map wiring ------------------------------------------------------

def test_activity_concept_map_names_goal_streaks(tmp_path):
    """A late-night-ratio high deviation, via the activity concept map, must
    produce the owner-goal-named streak — not the generic fallback."""
    dev = Deviation(
        metric="late_night_ratio", severity="strong", direction="high",
        value=0.6, sigma_distance=2.3, baseline_mu=0.15, baseline_sigma=0.1,
    )
    streaks_path = tmp_path / "streaks.json"
    cmap = profiles.ACTIVITY.concept_map
    # three consecutive days → state concept emitted
    for d in ("2026-06-21", "2026-06-22", "2026-06-23"):
        state, events = streaks.advance(streaks_path, d, [dev], concept_map=cmap)
    assert "late_night_work_streak" in state["active"]
    assert any(e.concept == "late_night_work_streak" for e in events)
