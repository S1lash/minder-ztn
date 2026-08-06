#!/usr/bin/env python3
"""Is this role due — the whole of the due/not-due arithmetic, and nothing else.

This lives in its own module because the previous engine buried the same
arithmetic in prose, where it silently killed the only live role for four
days while every surface reported success.

The time contract is the half that was wrong:

- the log stores `ts` in UTC;
- a cadence anchor (`daily 07:00`, `weekly mon`) is what the owner means,
  i.e. their LOCAL wall clock;
- so `is_due` takes both datetimes timezone-AWARE and converts them to local
  before any date or time comparison. A naive datetime is refused rather
  than silently assumed: a naive/aware mix at a negative UTC offset makes a
  `daily` role due exactly once, ever.

"Local" means the timezone carried by the injected `now`. This module never
resolves the host zone itself — that would be a clock read, and the whole
subsystem depends on `now` being injected. The caller attaches the host zone
to `now`; this module converts `last_run` into that same zone. One
definition, testable by injection.

The grammar is closed on purpose. An unrecognised cadence raises — never a
default, because a default is what killed the previous engine. Extending it
is: add a row to the table below, add a branch, add a due/not-due test pair.
Nothing else.

    every tick          always
    hourly              never run, or at least an hour has elapsed
    daily               never run, or the local date advanced
    daily HH:MM         as `daily`, and the local time reached the anchor
    weekly <dow> [HH:MM]    the local weekday matches, once per local date
    monthly <1-28> [HH:MM]  the local day-of-month matches, once per date

Catch-up is deliberately NOT performed: a missed weekly anchor waits for the
next one rather than firing on the following day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

# `monthly 29..31` is refused so a monthly role can never skip February.
MAX_MONTH_DAY = 28
HOURLY_INTERVAL = timedelta(hours=1)

KIND_EVERY_TICK = "every-tick"
KIND_HOURLY = "hourly"
KIND_DAILY = "daily"
KIND_WEEKLY = "weekly"
KIND_MONTHLY = "monthly"

# Monday-first, matching `datetime.weekday()`.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class CadenceError(Exception):
    """A cadence string is outside the closed grammar, or a datetime is naive."""


@dataclass(frozen=True)
class Cadence:
    kind: str
    anchor_time: time | None = None
    anchor_day: int | str | None = None


def _parse_anchor_time(token: str) -> time:
    hh, _, mm = token.partition(":")
    if not hh.isdigit() or not mm.isdigit() or len(hh) != 2 or len(mm) != 2:
        raise CadenceError(f"time anchor {token!r} must be HH:MM")
    hour, minute = int(hh), int(mm)
    if hour > 23 or minute > 59:
        raise CadenceError(f"time anchor {token!r} is not a real time of day")
    return time(hour, minute)


def parse_cadence(text: str) -> Cadence:
    """The only door into the grammar. Raises `CadenceError`, never defaults."""
    if not isinstance(text, str):
        raise CadenceError("cadence must be a string")
    tokens = text.split()
    if not tokens:
        raise CadenceError("cadence is empty")

    head = tokens[0]
    if head == "every":
        if tokens != ["every", "tick"]:
            raise CadenceError(f"unknown cadence {text.strip()!r}")
        return Cadence(kind=KIND_EVERY_TICK)

    if head == KIND_HOURLY:
        if len(tokens) != 1:
            raise CadenceError(f"unknown cadence {text.strip()!r}")
        return Cadence(kind=KIND_HOURLY)

    if head == KIND_DAILY:
        if len(tokens) == 1:
            return Cadence(kind=KIND_DAILY)
        if len(tokens) == 2:
            return Cadence(kind=KIND_DAILY, anchor_time=_parse_anchor_time(tokens[1]))
        raise CadenceError(f"unknown cadence {text.strip()!r}")

    if head == KIND_WEEKLY:
        if len(tokens) not in (2, 3):
            raise CadenceError(f"unknown cadence {text.strip()!r}")
        if tokens[1] not in WEEKDAYS:
            raise CadenceError(
                f"unknown weekday {tokens[1]!r} — use one of {', '.join(WEEKDAYS)}"
            )
        anchor = _parse_anchor_time(tokens[2]) if len(tokens) == 3 else None
        return Cadence(kind=KIND_WEEKLY, anchor_time=anchor, anchor_day=tokens[1])

    if head == KIND_MONTHLY:
        if len(tokens) not in (2, 3):
            raise CadenceError(f"unknown cadence {text.strip()!r}")
        if not tokens[1].isdigit():
            raise CadenceError(f"day of month {tokens[1]!r} must be a number")
        day = int(tokens[1])
        if not 1 <= day <= MAX_MONTH_DAY:
            raise CadenceError(f"day of month must be 1..{MAX_MONTH_DAY}, got {day}")
        anchor = _parse_anchor_time(tokens[2]) if len(tokens) == 3 else None
        return Cadence(kind=KIND_MONTHLY, anchor_time=anchor, anchor_day=day)

    raise CadenceError(f"unknown cadence {text.strip()!r}")


def anchor_note(cadence: Cadence) -> str | None:
    """The unreachable-anchor warning for this cadence, or `None` (§2.1).

    An anchor is evaluated at the moment a tick runs, and the shipped
    scheduler tick is once a day. An anchor LATER than the tick's own time is
    therefore never satisfied: the role fires zero times, forever, silently —
    a not-due role writes nothing, so the log stays empty and every surface
    reports a role that has simply never run. Verified by execution: against
    a 07:00 tick over 28 consecutive days, `daily 14:00` and
    `weekly mon 09:00` each fired 0 times while `daily 07:00` and bare
    `daily` fired 28.

    It is a note and never a refusal: the grammar is correct, and an anchor
    is meaningful the moment the owner's scheduler ticks more than once a
    day. This module cannot see their cron, and a validator that refuses a
    shape working on someone else's schedule is worse than none.

    A cadence with no TIME anchor returns `None` — including `weekly mon`,
    whose day anchor carries no such hazard. A warning on every role is
    noise, and noise is what makes the one real warning invisible.
    """
    # The mirror image of the anchor hazard, and it fires just as silently in
    # the other direction. `hourly` and `every tick` promise a rhythm the tick
    # cannot deliver: against the shipped once-a-day scheduler they come due on
    # EVERY tick, so «summarise my day each hour» yields exactly one summary a
    # day. Nothing is wrong with the grammar, so this is a note like the other:
    # the shape is right the moment the owner's scheduler ticks more often, and
    # this module cannot see their cron.
    if cadence.kind in (KIND_HOURLY, KIND_EVERY_TICK):
        return (
            f"`{cadence.kind}`: this role comes due on every scheduler tick, so it "
            f"runs as often as the tick runs — once a day on the shipped schedule, "
            f"not hourly"
        )
    if cadence.anchor_time is None:
        return None
    at = cadence.anchor_time.strftime("%H:%M")
    return (
        f"time anchor {at}: this role only ever runs if a scheduler tick "
        f"fires at or after {at} local time"
    )


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CadenceError(
            f"{label} must be timezone-aware — a naive/aware mix silently "
            f"freezes a cadence at a negative UTC offset"
        )


def _to_local(value: datetime, now: datetime) -> datetime:
    """Convert into the zone carried by `now`. The one conversion helper."""
    return value.astimezone(now.tzinfo)


def _anchor_reached(cadence: Cadence, local_now: datetime) -> tuple[bool, str]:
    if cadence.anchor_time is not None and local_now.time() < cadence.anchor_time:
        return False, f"anchor {cadence.anchor_time.strftime('%H:%M')} not reached"
    return True, ""


def is_due(cadence: Cadence, last_run: datetime | None, now: datetime):
    """Return `(due, reason)`. `reason` is a short English log line."""
    if not isinstance(cadence, Cadence):
        raise CadenceError("is_due takes a parsed Cadence, not a string")
    _require_aware("now", now)
    if last_run is not None:
        _require_aware("last_run", last_run)

    # A log line stamped ahead of `now` — a clock skew, a restored backup, a
    # role that wrote its own future. It makes `now - last_run` NEGATIVE, and
    # a negative interval is never >= an hour, so an `hourly` role is frozen
    # and reports an ordinary wait while it happens.
    #
    # The safe answer is to RUN. A role that runs once too often is a
    # nuisance; one that never runs again is the defect this module exists to
    # prevent, and a not-due role writes no log line to reveal it. The skew
    # self-heals: the run overwrites `last_run` with the real time.
    #
    # It belongs to the elapsed-interval branch alone. The date-comparing
    # forms are already immune — a date in the future is not today, so they
    # fire — and their anchors still hold, because an unreachable anchor is
    # not made reachable by a wrong clock.
    skewed = last_run is not None and last_run > now

    if cadence.kind == KIND_EVERY_TICK:
        return True, "every tick"

    if cadence.kind == KIND_HOURLY:
        if last_run is None:
            return True, "never run"
        if skewed:
            return True, "last run is stamped ahead of now"
        if now - last_run >= HOURLY_INTERVAL:
            return True, "an hour has elapsed"
        return False, "less than an hour since the last run"

    local_now = _to_local(now, now)
    local_last = _to_local(last_run, now) if last_run is not None else None

    if cadence.kind == KIND_WEEKLY:
        if local_now.weekday() != WEEKDAYS.index(cadence.anchor_day):
            return False, "not the anchor weekday"
    elif cadence.kind == KIND_MONTHLY:
        if local_now.day != cadence.anchor_day:
            return False, "not the anchor day of the month"

    reached, why = _anchor_reached(cadence, local_now)
    if not reached:
        return False, why

    if local_last is None:
        return True, "never run"
    if local_last.date() == local_now.date():
        return False, "already ran on this local date"
    return True, "the local date advanced"
