"""Parse Garmin metric-day source files into a normalised dict of numbers.

Pure deterministic. Reads `_sources/inbox/garmin/<date>.md`:
  - frontmatter (status / date / metrics_collected / metric_failures)
  - `## Summary` section (kept verbatim)
  - `## Detailed data` `### {metric}` YAML blocks (parsed)

Returns a dict suitable for downstream baseline / streak processing.
Missing fields stay missing (None / absent) — callers handle gracefully.

The extractor is universal across wearables-as-metric-day-source: the
shape is "frontmatter → metrics_collected → ### blocks → YAML". Apple
Watch, Whoop, Polar would slot in by re-using the same source family
contract; per-vendor field maps live in this module.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_METRIC_BLOCK_RE = re.compile(
    r"^###\s+(\S+)\s*$\n+```yaml\n(.*?)\n```",
    re.MULTILINE | re.DOTALL,
)


def _parse_frontmatter(text: str) -> dict[str, Any]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def _extract_summary_section(text: str) -> str:
    """Pull the body of `## Summary` up to the next `## ` heading."""
    body_start = text.find("\n## Summary")
    if body_start < 0:
        return ""
    after = text[body_start + 1 :]
    next_h = re.search(r"^##\s", after[len("## Summary") :], re.MULTILINE)
    if next_h:
        return after[: len("## Summary") + next_h.start()].rstrip()
    return after.rstrip()


def _parse_metric_blocks(text: str) -> dict[str, Any]:
    """Parse `### {metric}` ```yaml ... ``` blocks under `## Detailed data`.

    Returns dict mapping metric name → parsed YAML (dict / list / scalar).
    Duplicate sections (collector quirk) — first occurrence wins.
    """
    detail_start = text.find("\n## Detailed data")
    if detail_start < 0:
        return {}
    body = text[detail_start:]
    out: dict[str, Any] = {}
    for match in _METRIC_BLOCK_RE.finditer(body):
        name = match.group(1).strip()
        if name in out:
            continue
        raw = match.group(2)
        try:
            out[name] = yaml.safe_load(raw)
        except yaml.YAMLError:
            out[name] = None
    return out


def _hours(seconds: Optional[float]) -> Optional[float]:
    return None if seconds is None else round(seconds / 3600, 2)


def _first_device_data(latest_training_status_data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(latest_training_status_data, dict):
        return {}
    for _dev, data in latest_training_status_data.items():
        if isinstance(data, dict):
            return data
    return {}


def _extract_metrics(blocks: dict[str, Any]) -> dict[str, Any]:
    """Map vendor-specific YAML blocks to canonical metric keys.

    Canonical keys (subset, all optional — present only when source data is):
      sleep_h, deep_h, rem_h, light_h, awake_h, sleep_score, sleep_efficiency,
      hrv_ms, hrv_status,
      rhr,
      stress_avg, stress_max,
      bb_start, bb_end,
      readiness, readiness_lvl,
      train_status, acute_load, chronic_load, acwr, acwr_zone,
      intensity_moderate_min, intensity_vigorous_min,
      respiration_waking, respiration_sleeping,
      steps, vo2max_running,
    """
    m: dict[str, Any] = {}

    # sleep
    sleep_block = blocks.get("sleep") or {}
    if isinstance(sleep_block, dict):
        ds = sleep_block.get("dailySleepDTO") or {}
        m["sleep_h"] = _hours(ds.get("sleepTimeSeconds"))
        m["deep_h"] = _hours(ds.get("deepSleepSeconds"))
        m["rem_h"] = _hours(ds.get("remSleepSeconds"))
        m["light_h"] = _hours(ds.get("lightSleepSeconds"))
        m["awake_h"] = _hours(ds.get("awakeSleepSeconds"))
        scores = (ds.get("sleepScores") or {}).get("overall") or {}
        m["sleep_score"] = scores.get("value")
        # efficiency = asleep / (asleep + awake)
        sleep_s = ds.get("sleepTimeSeconds") or 0
        awake_s = ds.get("awakeSleepSeconds")
        if sleep_s and awake_s is not None and (sleep_s + awake_s) > 0:
            m["sleep_efficiency"] = round(sleep_s / (sleep_s + awake_s), 4)

    # hrv
    hrv_block = blocks.get("hrv") or {}
    if isinstance(hrv_block, dict):
        s = hrv_block.get("hrvSummary") or {}
        m["hrv_ms"] = s.get("lastNightAvg")
        m["hrv_status"] = s.get("status")

    # rhr — primary path: allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE
    rhr_block = blocks.get("rhr") or {}
    if isinstance(rhr_block, dict):
        mm = (rhr_block.get("allMetrics") or {}).get("metricsMap") or {}
        rhr_list = mm.get("WELLNESS_RESTING_HEART_RATE") or []
        if rhr_list and isinstance(rhr_list, list) and rhr_list[0].get("value") is not None:
            m["rhr"] = rhr_list[0]["value"]

    # stress
    stress_block = blocks.get("stress") or {}
    if isinstance(stress_block, dict):
        if stress_block.get("avgStressLevel") is not None:
            m["stress_avg"] = stress_block["avgStressLevel"]
        if stress_block.get("maxStressLevel") is not None:
            m["stress_max"] = stress_block["maxStressLevel"]

    # body_battery (top-level list with one element carrying charged/drained)
    bb_block = blocks.get("body_battery")
    if isinstance(bb_block, list) and bb_block:
        e = bb_block[0]
        if isinstance(e, dict):
            if e.get("charged") is not None:
                m["bb_charged"] = e["charged"]
            if e.get("drained") is not None:
                m["bb_drained"] = e["drained"]

    # The "steps" block in Garmin export carries user_summary fields,
    # including bb_start/bb_end and the canonical totalSteps.
    steps_block = blocks.get("steps") or {}
    if isinstance(steps_block, dict):
        if steps_block.get("totalSteps") is not None:
            m["steps"] = steps_block["totalSteps"]
        if steps_block.get("bodyBatteryHighestValue") is not None:
            m["bb_start"] = steps_block["bodyBatteryHighestValue"]
        # bb_end preference: bodyBatteryAtWakeTime > bodyBatteryMostRecentValue
        if steps_block.get("bodyBatteryAtWakeTime") is not None:
            m["bb_end"] = steps_block["bodyBatteryAtWakeTime"]
        elif steps_block.get("bodyBatteryMostRecentValue") is not None:
            m["bb_end"] = steps_block["bodyBatteryMostRecentValue"]
        # rhr fallback: prefer block "rhr" path; else user_summary's restingHeartRate
        if "rhr" not in m and steps_block.get("restingHeartRate") is not None:
            m["rhr"] = float(steps_block["restingHeartRate"])

    # training_readiness — list of one element
    tr_block = blocks.get("training_readiness")
    if isinstance(tr_block, list) and tr_block:
        tr = tr_block[0]
        if isinstance(tr, dict):
            if tr.get("score") is not None:
                m["readiness"] = tr["score"]
            if tr.get("level"):
                m["readiness_lvl"] = tr["level"]
            if tr.get("acuteLoad") is not None:
                m["acute_load"] = tr["acuteLoad"]

    # training_status — deeply nested
    ts_block = blocks.get("training_status") or {}
    if isinstance(ts_block, dict):
        mrt = ts_block.get("mostRecentTrainingStatus") or {}
        ltsd = mrt.get("latestTrainingStatusData") or {}
        device_data = _first_device_data(ltsd)
        phrase = device_data.get("trainingStatusFeedbackPhrase")
        if phrase:
            m["train_status"] = phrase
        atl = device_data.get("acuteTrainingLoadDTO") or {}
        if atl.get("dailyTrainingLoadAcute") is not None:
            m["acute_load"] = atl["dailyTrainingLoadAcute"]
        if atl.get("dailyTrainingLoadChronic") is not None:
            m["chronic_load"] = atl["dailyTrainingLoadChronic"]
        if atl.get("dailyAcuteChronicWorkloadRatio") is not None:
            m["acwr"] = atl["dailyAcuteChronicWorkloadRatio"]
        if atl.get("acwrStatus"):
            m["acwr_zone"] = atl["acwrStatus"]

    # intensity_minutes
    im = blocks.get("intensity_minutes") or {}
    if isinstance(im, dict):
        if im.get("moderateMinutes") is not None:
            m["intensity_moderate_min"] = im["moderateMinutes"]
        if im.get("vigorousMinutes") is not None:
            m["intensity_vigorous_min"] = im["vigorousMinutes"]

    # respiration
    r = blocks.get("respiration") or {}
    if isinstance(r, dict):
        if r.get("avgWakingRespirationValue") is not None:
            m["respiration_waking"] = r["avgWakingRespirationValue"]
        if r.get("avgSleepRespirationValue") is not None:
            m["respiration_sleeping"] = r["avgSleepRespirationValue"]

    # max_metrics → vo2max running
    mx = blocks.get("max_metrics")
    if isinstance(mx, list) and mx:
        first = mx[0]
        if isinstance(first, dict):
            running = first.get("running") or {}
            if isinstance(running, dict) and running.get("vo2MaxValue") is not None:
                m["vo2max_running"] = running["vo2MaxValue"]

    # Drop None values to keep keys tidy.
    return {k: v for k, v in m.items() if v is not None}


def extract(record_md_path: str | Path) -> dict[str, Any]:
    """Parse one metric-day source file into a structured dict.

    Returns:
      {
        "date": "YYYY-MM-DD",
        "status": "ok" | "collection-failed" | ...,
        "metrics_collected": [...],
        "metric_failures": [...],
        "metrics": {canonical_key: value, ...},
        "summary_text": "## Summary\\n- ...",
      }
    """
    text = Path(record_md_path).read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    blocks = _parse_metric_blocks(text)
    metrics = _extract_metrics(blocks)
    return {
        "date": fm.get("date"),
        "status": fm.get("status", "ok"),
        "metrics_collected": fm.get("metrics_collected", []) or [],
        "metric_failures": fm.get("metric_failures", []) or [],
        "metrics": metrics,
        "summary_text": _extract_summary_section(text),
    }
