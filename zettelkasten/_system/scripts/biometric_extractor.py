"""Parse Garmin metric-day source files into a normalised dict of numbers.

Pure deterministic. Reads `_sources/inbox/garmin/<date>.md`:
  - frontmatter (status / date / metrics_collected / metric_failures)
  - `## Summary` section (kept verbatim)
  - `## Detailed data` `### {metric}` YAML blocks (parsed)

Returns a dict suitable for downstream baseline / streak processing.
Missing fields stay missing (None / absent) — callers handle gracefully.

The extractor is universal across wearables-as-metric-day-source: the
shape is "frontmatter → metrics_collected → ### blocks → YAML". Each
vendor maps its raw blocks to a shared canonical metric vocabulary via a
per-vendor field map in this module, dispatched on the `source`
frontmatter. Apple Watch, Whoop, Polar slot in by adding a map. Garmin
and Oura are implemented; an unknown source falls back to the Garmin map
(historical default).
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


def _extract_garmin_metrics(blocks: dict[str, Any]) -> dict[str, Any]:
    """Map Garmin YAML blocks to canonical metric keys.

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


def _oura_first(block: Any) -> dict[str, Any]:
    """First record of an Oura list endpoint (daily endpoints have one), or
    the object itself for singletons."""
    if isinstance(block, list):
        for r in block:
            if isinstance(r, dict):
                return r
        return {}
    return block if isinstance(block, dict) else {}


def _oura_main_sleep(block: Any) -> dict[str, Any]:
    """Pick the night's main sleep period from Oura's per-day `sleep` list.

    Oura returns nap fragments + the main night; the main night is
    `type == "long_sleep"`, falling back to the period with the most total
    sleep. (Mirrors the collector's `select_main_sleep` so a record reflects
    the real night, not a few-minute fragment.)
    """
    if not isinstance(block, list):
        return block if isinstance(block, dict) else {}
    periods = [r for r in block if isinstance(r, dict)]
    if not periods:
        return {}
    longs = [r for r in periods if r.get("type") == "long_sleep"]

    def _asleep(r: dict[str, Any]) -> int:
        total = r.get("total_sleep_duration")
        if total is not None:
            return total
        return sum((r.get(k) or 0) for k in
                   ("deep_sleep_duration", "light_sleep_duration", "rem_sleep_duration"))

    return max(longs or periods, key=_asleep)


def _extract_oura_metrics(blocks: dict[str, Any]) -> dict[str, Any]:
    """Map Oura YAML blocks to canonical metric keys.

    Oura is score-centric and adds signals Garmin lacks — readiness,
    resilience, body-temperature deviation, SpO2, vascular age. Shared keys
    (sleep_h, rhr, hrv_ms, steps, sleep_score, sleep_efficiency, the sleep
    stages, respiration_sleeping) line up with Garmin's vocabulary so the
    deviation engine treats them uniformly; baselines stay per-source so the
    different scales (e.g. Oura efficiency 0-100 vs Garmin's ratio) never mix.

    Oura-only canonical keys: temp_deviation, resilience_level, activity_score,
    active_calories, spo2_avg, breathing_disturbance, vascular_age,
    pulse_wave_velocity, stress_high, recovery_high.
    """
    m: dict[str, Any] = {}

    sleep = _oura_main_sleep(blocks.get("sleep"))
    if sleep:
        m["sleep_h"] = _hours(sleep.get("total_sleep_duration"))
        m["deep_h"] = _hours(sleep.get("deep_sleep_duration"))
        m["rem_h"] = _hours(sleep.get("rem_sleep_duration"))
        m["light_h"] = _hours(sleep.get("light_sleep_duration"))
        m["awake_h"] = _hours(sleep.get("awake_time"))
        if sleep.get("efficiency") is not None:
            m["sleep_efficiency"] = sleep["efficiency"]   # Oura: 0-100 integer
        if sleep.get("average_hrv") is not None:
            m["hrv_ms"] = sleep["average_hrv"]
        if sleep.get("lowest_heart_rate") is not None:
            m["rhr"] = float(sleep["lowest_heart_rate"])
        if sleep.get("average_breath") is not None:
            m["respiration_sleeping"] = sleep["average_breath"]

    if (score := _oura_first(blocks.get("daily_sleep")).get("score")) is not None:
        m["sleep_score"] = score

    readiness = _oura_first(blocks.get("daily_readiness"))
    if readiness.get("score") is not None:
        m["readiness"] = readiness["score"]
    if readiness.get("temperature_deviation") is not None:
        m["temp_deviation"] = readiness["temperature_deviation"]

    if (level := _oura_first(blocks.get("daily_resilience")).get("level")):
        m["resilience_level"] = level

    activity = _oura_first(blocks.get("daily_activity"))
    if activity.get("steps") is not None:
        m["steps"] = activity["steps"]
    if activity.get("active_calories") is not None:
        m["active_calories"] = activity["active_calories"]
    if activity.get("score") is not None:
        m["activity_score"] = activity["score"]

    spo2 = _oura_first(blocks.get("daily_spo2"))
    if spo2:
        pct = spo2.get("spo2_percentage")
        avg = pct.get("average") if isinstance(pct, dict) else pct
        if avg is not None:
            m["spo2_avg"] = avg
        if spo2.get("breathing_disturbance_index") is not None:
            m["breathing_disturbance"] = spo2["breathing_disturbance_index"]

    cardio = _oura_first(blocks.get("daily_cardiovascular_age"))
    if cardio.get("vascular_age") is not None:
        m["vascular_age"] = cardio["vascular_age"]
    if cardio.get("pulse_wave_velocity") is not None:
        m["pulse_wave_velocity"] = round(float(cardio["pulse_wave_velocity"]), 2)

    stress = _oura_first(blocks.get("daily_stress"))
    if stress.get("stress_high") is not None:
        m["stress_high"] = stress["stress_high"]
    if stress.get("recovery_high") is not None:
        m["recovery_high"] = stress["recovery_high"]

    if (vo2 := _oura_first(blocks.get("vO2_max")).get("vo2_max")) is not None:
        m["vo2max_running"] = vo2

    return {k: v for k, v in m.items() if v is not None}


_VENDOR_MAPS = {
    "garmin": _extract_garmin_metrics,
    "oura": _extract_oura_metrics,
}


def _extract_metrics(blocks: dict[str, Any], source: str | None) -> dict[str, Any]:
    """Dispatch to the per-vendor field map by `source` frontmatter.

    `source` is the bare source id on inbox files (`oura`) or `id/filename` on
    emitted records — take the leading segment. Unknown sources fall back to
    the Garmin map (historical default)."""
    src = (source or "garmin").split("/", 1)[0].strip().lower()
    mapper = _VENDOR_MAPS.get(src, _extract_garmin_metrics)
    return mapper(blocks)


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
    metrics = _extract_metrics(blocks, fm.get("source"))
    return {
        "date": fm.get("date"),
        "status": fm.get("status", "ok"),
        "metrics_collected": fm.get("metrics_collected", []) or [],
        "metric_failures": fm.get("metric_failures", []) or [],
        "metrics": metrics,
        "summary_text": _extract_summary_section(text),
    }
