#!/usr/bin/env python3
"""Per-role cumulative write budget — the anti-salami guard (CONTRACT §6.4,
DOCTRINE INV-20, INV-28).

A per-tool READ call cap (`PartSpec.tools[*].budget`, CONTRACT §1.6) may be
`unlimited` by owner grant — that is fine, per-tool call economy is not the
concern here. This module bounds a DIFFERENT, orthogonal surface: the
CUMULATIVE count of IRREVERSIBLE outward writes a role produces — acts
(§6.2/6.5) and inbox emissions (§4.2) — within a reset period, so a role can
never run away on the irreversible surfaces even when a read tool is
uncapped. It also carries the wall-clock tick budget (INV-28) so an uncapped
read tool cannot hold `.roles.lock` long enough to delay `/ztn:process`.

This is real per-role state (`_system/roles/{role_id}/budget.json`) that
MUST exist before any outward-write path ships (INV-20: "a prerequisite, not
a later add").

Schema (`budget.json`):
    {
      "period_start": "<ISO date>",     # when the current period began
      "period_days": 7,                   # reset cadence in days
      "max_writes_per_period": 20,        # cumulative ceiling: acts + inbox emissions
      "writes_this_period": 0,            # running count within the current period
      "max_tick_seconds": 120              # wall-clock tick budget (bounds the lock hold)
    }

Missing file → a fresh budget with the module defaults (a role that never
had a `budget.json` written is still bounded, not unbounded). A malformed
file is read tolerantly and falls back to defaults (fail-safe on read,
mirroring `roles_common.read_runs`) — a corrupt budget file must not crash a
tick; but any tick that WOULD have written past the ceiling still can't,
because `can_write` reads today's real remaining count from whatever state
was loaded, and a defaulted state starts at a full budget instead of
crashing (conservative: bounded-by-default, never unbounded-by-crash).

Reads (`load_budget`, `budget_remaining`, `can_write`) are pure — they never
mutate `budget.json`, not even to persist a rolled-over period. Only
`record_writes` persists, atomically (`.tmp` + `Path.replace`, LF-forced,
mirroring `roles_common._atomic_write`). The caller (TOOL STAGE / writer) is
responsible for raising the `role-budget-exhausted` CLARIFICATION when a
write is deferred — this module only tracks and reports the ceiling, it
never emits a CLARIFICATION itself (SRP: budget state vs. HITL surfacing are
different owners).

Deterministic, no LLM, no network. `today` parameters accept a
`datetime.date` (default `date.today()`) so callers and tests are
reproducible.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from roles_common import atomic_write_text, role_dir

DEFAULT_MAX_WRITES_PER_PERIOD = 20
DEFAULT_PERIOD_DAYS = 7
DEFAULT_MAX_TICK_SECONDS = 120

_BUDGET_FILENAME = "budget.json"


def _utc_today() -> date:
    """Today in UTC — the whole engine timestamps UTC (`now_iso_utc`); using local
    `date.today()` would skew the budget period boundary across timezones."""
    return datetime.now(timezone.utc).date()


def _default_state(today: date | None = None) -> dict[str, Any]:
    start = today or _utc_today()
    return {
        "period_start": start.isoformat(),
        "period_days": DEFAULT_PERIOD_DAYS,
        "max_writes_per_period": DEFAULT_MAX_WRITES_PER_PERIOD,
        "writes_this_period": 0,
        "max_tick_seconds": DEFAULT_MAX_TICK_SECONDS,
    }


def budget_path(role_id: str, base: Path | None = None) -> Path:
    """Absolute path to the role's budget file: `_system/roles/{role_id}/budget.json`."""
    return role_dir(role_id, base) / _BUDGET_FILENAME


def _parse_period_start(state: dict[str, Any], today: date) -> date:
    raw = state.get("period_start")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return today


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def load_budget(role_id: str, base: Path | None = None) -> dict[str, Any]:
    """Return the role's budget state — the existing file, or fresh defaults.

    Tolerant of a missing or malformed `budget.json` (fail-safe, best-effort
    like `roles_common.read_runs`): a corrupt file never crashes a tick, it
    just falls back to a fresh, fully-available default budget. Pure read —
    never writes.
    """
    path = budget_path(role_id, base)
    if not path.exists():
        return _default_state()
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, dict):
        return _default_state()

    defaults = _default_state()
    state = dict(defaults)
    if isinstance(raw.get("period_start"), str):
        try:
            date.fromisoformat(raw["period_start"])
            state["period_start"] = raw["period_start"]
        except ValueError:
            pass
    state["period_days"] = _coerce_int(raw.get("period_days"), defaults["period_days"])
    state["max_writes_per_period"] = _coerce_int(
        raw.get("max_writes_per_period"), defaults["max_writes_per_period"]
    )
    state["writes_this_period"] = _coerce_int(
        raw.get("writes_this_period"), defaults["writes_this_period"]
    )
    state["max_tick_seconds"] = _coerce_int(
        raw.get("max_tick_seconds"), defaults["max_tick_seconds"]
    )
    if state["period_days"] <= 0:
        state["period_days"] = defaults["period_days"]
    if state["max_writes_per_period"] < 0:
        state["max_writes_per_period"] = defaults["max_writes_per_period"]
    if state["writes_this_period"] < 0:
        state["writes_this_period"] = 0
    if state["max_tick_seconds"] <= 0:
        state["max_tick_seconds"] = defaults["max_tick_seconds"]
    return state


def _rolled(state: dict[str, Any], today: date) -> dict[str, Any]:
    """Return `state` as it reads TODAY, rolling the period forward if elapsed.

    Pure — does not mutate the input dict or persist anything. A period that
    has elapsed (`period_start + period_days <= today`) reads as freshly
    reset (`period_start=today`, `writes_this_period=0`) without a file
    write; only `record_writes` actually persists a roll.
    """
    period_start = _parse_period_start(state, today)
    period_days = _coerce_int(state.get("period_days"), DEFAULT_PERIOD_DAYS)
    if period_days <= 0:
        period_days = DEFAULT_PERIOD_DAYS
    if today >= period_start + timedelta(days=period_days):
        out = dict(state)
        out["period_start"] = today.isoformat()
        out["writes_this_period"] = 0
        return out
    return dict(state)


def budget_remaining(state: dict[str, Any], today: date | None = None) -> int:
    """Writes left in the current period, accounting for a rolled-over period.

    Pure read — never mutates `state` or any file.
    """
    day = today or _utc_today()
    current = _rolled(state, day)
    ceiling = _coerce_int(current.get("max_writes_per_period"), DEFAULT_MAX_WRITES_PER_PERIOD)
    used = _coerce_int(current.get("writes_this_period"), 0)
    remaining = ceiling - used
    return remaining if remaining > 0 else 0


def can_write(state: dict[str, Any], today: date | None = None) -> bool:
    """`True` when the role still has cumulative write budget this period."""
    return budget_remaining(state, today) > 0


def record_writes(
    role_id: str,
    n: int,
    base: Path | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Atomically account for `n` writes (acts + inbox emissions) and persist.

    Rolls the period first if elapsed, then adds `n`, clamped at the
    ceiling (never counts past `max_writes_per_period` — a caller that
    over-reports never corrupts the ledger into an unrecoverable negative
    headroom). Writes `budget.json` atomically (`.tmp` + `Path.replace`,
    UTF-8, LF-forced) and returns the new persisted state.
    """
    day = today or _utc_today()
    path = budget_path(role_id, base)
    state = load_budget(role_id, base) if path.exists() else _default_state(day)
    rolled = _rolled(state, day)
    ceiling = _coerce_int(rolled.get("max_writes_per_period"), DEFAULT_MAX_WRITES_PER_PERIOD)
    used = _coerce_int(rolled.get("writes_this_period"), 0)
    increment = n if n > 0 else 0
    new_used = used + increment
    if new_used > ceiling:
        new_used = ceiling
    new_state = dict(rolled)
    new_state["writes_this_period"] = new_used

    atomic_write_text(path, json.dumps(new_state, indent=2, sort_keys=True) + "\n")
    return new_state


def max_tick_seconds(state: dict[str, Any]) -> int:
    """Wall-clock tick budget (seconds) — bounds the `.roles.lock` hold (INV-28)."""
    return _coerce_int(state.get("max_tick_seconds"), DEFAULT_MAX_TICK_SECONDS)
