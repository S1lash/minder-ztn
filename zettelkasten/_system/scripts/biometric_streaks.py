"""Streak state machine for biometric deviations.

A streak is a run of consecutive days where a (metric, direction)
deviation of at least `min_severity` (default `medium`) repeats.
When a streak hits `min_consecutive_days` (default 3), a state-concept
is emitted (`low_hrv_streak`, `sleep_debt`, `rhr_elevation_streak`,
…). When the streak breaks, a recovery-concept is emitted on the
break day (`recovery_after_low_hrv_streak`).

State file shape:
{
  "active": {
    "low_hrv_streak": {
      "concept": "low_hrv_streak",
      "metric": "hrv_ms", "direction": "low",
      "started": "YYYY-MM-DD", "last_seen": "YYYY-MM-DD",
      "days": N,
      "emitted_state_concept": bool
    }, ...
  },
  "history": [
    {"concept": "low_hrv_streak", "metric": "hrv_ms", "direction": "low",
     "started": "...", "ended": "...", "days": N}, ...
  ],
  "last_date": "YYYY-MM-DD"
}
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date as date_cls, timedelta
from pathlib import Path
from typing import Any, Iterable

# Concept naming map: (metric, direction) → state-concept name.
# Recovery concept = "recovery_after_<state-concept>".
# Other (metric, direction) combos still produce streaks but use a
# generic name `<metric>_<direction>_streak`.
_CONCEPT_MAP: dict[tuple[str, str], str] = {
    ("hrv_ms", "low"):     "low_hrv_streak",
    ("sleep_h", "low"):    "sleep_debt",
    ("rhr", "high"):       "rhr_elevation_streak",
    ("readiness", "low"):  "low_readiness_streak",
    ("stress_avg", "high"):"stress_elevation_streak",
    ("bb_end", "low"):     "low_bb_streak",
    ("steps", "low"):      "low_activity_streak",
}

_SEVERITY_ORDER = {"light": 1, "medium": 2, "strong": 3}


def _empty_state() -> dict[str, Any]:
    return {"active": {}, "history": [], "last_date": None}


def load(streaks_path: str | Path) -> dict[str, Any]:
    p = Path(streaks_path)
    if not p.exists():
        return _empty_state()
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("active", {})
    data.setdefault("history", [])
    data.setdefault("last_date", None)
    return data


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


def concept_for(metric: str, direction: str) -> str:
    return _CONCEPT_MAP.get((metric, direction), f"{metric}_{direction}_streak")


@dataclass(frozen=True)
class StreakEvent:
    kind: str           # 'state' | 'recovery'
    concept: str        # e.g. 'low_hrv_streak' or 'recovery_after_low_hrv_streak'
    metric: str
    direction: str
    started: str
    days: int


def advance(
    streaks_path: str | Path,
    date: str,
    deviations: list,
    min_consecutive: int = 3,
    min_severity: str = "medium",
) -> tuple[dict[str, Any], list[StreakEvent]]:
    """Advance streak state by one day.

    Args:
        streaks_path: state file path.
        date: 'YYYY-MM-DD' for today.
        deviations: list of `Deviation` objects from baselines.flag_deviations.
        min_consecutive: streak length to emit a state-concept.
        min_severity: minimum severity that counts toward a streak.

    Returns:
      (updated_state, emitted_events).
      Caller is responsible for treating events as per-day output. State
      is persisted atomically.

    Idempotent on same-date re-runs: if `date == state['last_date']`,
    today's bucket is replayed (active streak day-counts revert to the
    state-before-today, then advance again).
    """
    state = load(streaks_path)
    min_sev_rank = _SEVERITY_ORDER.get(min_severity, 2)

    # Same-date replay → revert one day. Active streaks that started
    # today get dropped; longer streaks decrement by one day.
    if state.get("last_date") == date:
        active_keys = list(state["active"].keys())
        for key in active_keys:
            entry = state["active"][key]
            if entry.get("started") == date:
                del state["active"][key]
                continue
            entry["days"] = max(0, entry.get("days", 1) - 1)
            # last_seen rolls back: we don't know the prior date precisely
            # but mostly it's date - 1
            try:
                d = date_cls.fromisoformat(date)
                entry["last_seen"] = (d - timedelta(days=1)).isoformat()
            except ValueError:
                pass
        # also revert any history rows ended on this date
        state["history"] = [h for h in state["history"] if h.get("ended") != date]

    # Eligible (metric, direction) deviations passing severity gate.
    today_keys: dict[tuple[str, str], Any] = {}
    for dev in deviations:
        if _SEVERITY_ORDER.get(dev.severity, 0) < min_sev_rank:
            continue
        key = (dev.metric, dev.direction)
        # Take strongest deviation per (metric, direction)
        prev = today_keys.get(key)
        if prev is None or _SEVERITY_ORDER.get(dev.severity, 0) > _SEVERITY_ORDER.get(prev.severity, 0):
            today_keys[key] = dev

    events: list[StreakEvent] = []

    # 1) Extend or start streaks for today's deviations.
    seen_concepts_today: set[str] = set()
    for (metric, direction), dev in today_keys.items():
        concept = concept_for(metric, direction)
        seen_concepts_today.add(concept)
        if concept in state["active"]:
            entry = state["active"][concept]
            entry["days"] = entry.get("days", 1) + 1
            entry["last_seen"] = date
        else:
            entry = {
                "concept": concept,
                "metric": metric,
                "direction": direction,
                "started": date,
                "last_seen": date,
                "days": 1,
                "emitted_state_concept": False,
            }
            state["active"][concept] = entry

        # Emit state-concept on the day the streak crosses the threshold,
        # only once per active streak.
        if not entry.get("emitted_state_concept") and entry["days"] >= min_consecutive:
            entry["emitted_state_concept"] = True
            events.append(StreakEvent(
                kind="state",
                concept=concept,
                metric=metric,
                direction=direction,
                started=entry["started"],
                days=entry["days"],
            ))

    # 2) Streaks not seen today end. Emit recovery if the streak had
    # actually crossed the threshold (state-concept was emitted).
    ended_keys = [k for k in list(state["active"].keys()) if k not in seen_concepts_today]
    for concept in ended_keys:
        entry = state["active"].pop(concept)
        # log into history
        state["history"].append({
            "concept": concept,
            "metric": entry["metric"],
            "direction": entry["direction"],
            "started": entry["started"],
            "ended": date,
            "days": entry.get("days", 1),
            "emitted_state_concept": entry.get("emitted_state_concept", False),
        })
        if entry.get("emitted_state_concept"):
            events.append(StreakEvent(
                kind="recovery",
                concept=f"recovery_after_{concept}",
                metric=entry["metric"],
                direction=entry["direction"],
                started=entry["started"],
                days=entry.get("days", 1),
            ))

    state["last_date"] = date
    _atomic_write(Path(streaks_path), state)
    return state, events
