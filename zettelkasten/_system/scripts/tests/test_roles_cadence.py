"""Tests for roles_cadence — the due/not-due arithmetic (CORE-SPEC §2).

This module has its own file because the previous engine buried this
arithmetic in prose and it silently killed the only live role for four days
while every surface reported success. So the suite is exhaustive: every
grammar form due and not-due, never-run per form, both sides of every
boundary, an unknown cadence raising rather than defaulting, no catch-up, and
the timezone contract that was the wrong half.

The timezone contract under test (§2 "Time contract"):
  - both datetimes must be timezone-AWARE; a naive one raises `CadenceError`;
  - anchors are the owner's LOCAL wall clock, while the log stores UTC;
  - so comparison happens after conversion to local.

"Local" is **the timezone carried by the injected `now`** (§2). The module
never resolves the host zone itself — that would be a clock read and would
break §0 determinism; the caller attaches the host zone to `now` and the
module converts `last_run` into that same zone. One definition, testable by
injection, which is what the tests below do.

Anchor dates used below (verified, not assumed):
    2026-07-13 mon · 2026-07-20 mon · 2026-07-21 tue · 2026-07-26 sun
    2026-07-27 mon · 2026-07-28 tue · 2026-07-29 wed · 2026-08-01 sat
    2026-02-28 sat
"""

from __future__ import annotations

import inspect
import unittest
from datetime import datetime, time, timedelta, timezone

import roles_cadence as cad  # type: ignore

UTC = timezone.utc
WEST = timezone(timedelta(hours=-5))    # fixed offset, no DST — deterministic
EAST = timezone(timedelta(hours=5, minutes=30))


def _at(text: str, tz: timezone = UTC) -> datetime:
    """Aware datetime from `YYYY-MM-DD HH:MM[:SS]` in `tz`."""
    fmt = "%Y-%m-%d %H:%M:%S" if text.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(text, fmt).replace(tzinfo=tz)


def _naive(text: str) -> datetime:
    fmt = "%Y-%m-%d %H:%M:%S" if text.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(text, fmt)


def _due(text: str, last_run, now):
    return cad.is_due(cad.parse_cadence(text), last_run, now)


ALL_VALID = (
    "every tick",
    "hourly",
    "daily",
    "daily 07:00",
    "weekly mon",
    "weekly sun 09:00",
    "monthly 1",
    "monthly 28 06:30",
)


# ==========================================================================
# parse_cadence
# ==========================================================================

class ParseTests(unittest.TestCase):
    def test_accepts_every_form_in_the_closed_grammar(self):
        """SIBLING to every rejection below — the whole legal set parses."""
        for text in ALL_VALID:
            with self.subTest(cadence=text):
                self.assertIsInstance(cad.parse_cadence(text), cad.Cadence)

    def test_accepts_all_seven_weekday_tokens(self):
        """SIBLING — pins the closed dow set positively, so a narrowing typo
        in the implementation is caught rather than silently killing Sunday."""
        for dow in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            with self.subTest(dow=dow):
                self.assertIsNotNone(cad.parse_cadence(f"weekly {dow}"))

    def test_accepts_monthly_day_boundaries_1_and_28(self):
        """SIBLING — both ends of the legal range."""
        self.assertEqual(cad.parse_cadence("monthly 1").anchor_day, 1)
        self.assertEqual(cad.parse_cadence("monthly 28").anchor_day, 28)

    def test_accepts_midnight_and_last_minute_time_anchors(self):
        """SIBLING — `00:00` and `23:59` are legal HH:MM and a plausible ask."""
        self.assertEqual(cad.parse_cadence("daily 00:00").anchor_time, time(0, 0))
        self.assertEqual(cad.parse_cadence("daily 23:59").anchor_time, time(23, 59))

    def test_weekly_and_monthly_carry_the_same_optional_anchor(self):
        """SIBLING — offering `daily 07:00` while making `weekly mon 09:00`
        unexpressible is the asymmetry §2 explicitly refuses."""
        self.assertEqual(cad.parse_cadence("weekly mon 09:00").anchor_time, time(9, 0))
        self.assertEqual(cad.parse_cadence("monthly 28 06:30").anchor_time, time(6, 30))
        self.assertIsNone(cad.parse_cadence("weekly mon").anchor_time)
        self.assertIsNone(cad.parse_cadence("monthly 28").anchor_time)

    def test_unanchored_forms_have_no_anchor_time(self):
        for text in ("every tick", "hourly", "daily"):
            with self.subTest(cadence=text):
                self.assertIsNone(cad.parse_cadence(text).anchor_time)

    def test_accepts_surrounding_whitespace(self):
        """SIBLING — GRAY ZONE (§2 does not say). Tested as accepted: a stray
        trailing space must never silently make a role undue forever."""
        self.assertIsNotNone(cad.parse_cadence("  daily 07:00 "))

    def test_rejects_manual_which_the_grammar_no_longer_has(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("manual")

    def test_rejects_unknown_word(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("fortnightly")

    def test_rejects_empty_and_whitespace_only(self):
        for text in ("", "   "):
            with self.subTest(cadence=text):
                with self.assertRaises(cad.CadenceError):
                    cad.parse_cadence(text)

    def test_rejects_weekly_without_a_day(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("weekly")

    def test_rejects_weekly_with_an_unknown_day(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("weekly funday")

    def test_rejects_monthly_day_zero(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("monthly 0")

    def test_rejects_monthly_day_29_30_31(self):
        """Above 28 is refused so a role can never skip February."""
        for n in (29, 30, 31):
            with self.subTest(day=n):
                with self.assertRaises(cad.CadenceError):
                    cad.parse_cadence(f"monthly {n}")

    def test_rejects_monthly_without_a_day(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("monthly")

    def test_rejects_impossible_time_anchor(self):
        for text in ("daily 25:00", "daily 07:61", "daily noon", "weekly mon 24:00"):
            with self.subTest(cadence=text):
                with self.assertRaises(cad.CadenceError):
                    cad.parse_cadence(text)

    def test_rejects_trailing_garbage_after_a_valid_form(self):
        with self.assertRaises(cad.CadenceError):
            cad.parse_cadence("daily 07:00 and also hourly")

    def test_cadence_is_frozen(self):
        c = cad.parse_cadence("daily 07:00")
        with self.assertRaises(Exception):
            c.kind = "hourly"  # type: ignore[misc]


# ==========================================================================
# timezone contract
# ==========================================================================

class TimezoneContractTests(unittest.TestCase):
    def test_rejects_naive_now(self):
        with self.assertRaises(cad.CadenceError):
            _due("daily", _at("2026-07-27 07:00"), _naive("2026-07-28 07:00"))

    def test_rejects_naive_last_run(self):
        with self.assertRaises(cad.CadenceError):
            _due("daily", _naive("2026-07-27 07:00"), _at("2026-07-28 07:00"))

    def test_rejects_both_naive(self):
        with self.assertRaises(cad.CadenceError):
            _due("daily", _naive("2026-07-27 07:00"), _naive("2026-07-28 07:00"))

    def test_accepts_aware_utc_datetimes(self):
        """SIBLING — the ordinary case the tick produces."""
        due, _ = _due("daily", _at("2026-07-27 07:00"), _at("2026-07-28 07:00"))
        self.assertTrue(due)

    def test_accepts_aware_non_utc_datetimes(self):
        """SIBLING — an owner outside UTC is the normal case, not an edge."""
        due, _ = _due(
            "daily", _at("2026-07-27 07:00", WEST), _at("2026-07-28 07:00", WEST)
        )
        self.assertTrue(due)

    def test_accepts_never_run_with_only_now_aware(self):
        """SIBLING — `last_run=None` is not a naive datetime and must not trip
        the aware check."""
        due, _ = _due("daily", None, _at("2026-07-28 07:00"))
        self.assertTrue(due)

    def test_negative_offset_daily_is_due_when_utc_comparison_would_say_no(self):
        """The bug the contract exists for. Log ts is UTC; the owner lives at
        UTC-5. Last run 2026-07-28T03:00Z is local 2026-07-27 22:00, so the
        local date HAS advanced by local 2026-07-28 07:00 — but both UTC dates
        read 2026-07-28, and a UTC comparison would report not-due."""
        last = _at("2026-07-28 03:00", UTC)
        now = _at("2026-07-28 07:00", WEST)
        due, _ = _due("daily", last, now)
        self.assertTrue(due)

    def test_positive_offset_daily_is_not_due_when_utc_comparison_would_say_yes(self):
        """SIBLING / mirror — at UTC+05:30 a UTC comparison would over-fire.
        Last run 2026-07-27T20:00Z is local 2026-07-28 01:30, the same local
        date as now, so the role is NOT due."""
        last = _at("2026-07-27 20:00", UTC)
        now = _at("2026-07-28 04:00", EAST)
        due, _ = _due("daily", last, now)
        self.assertFalse(due)

    def test_anchor_is_compared_in_local_time_not_utc(self):
        """`daily 07:00` means the owner's 07:00. At UTC-5, local 07:00 is
        12:00Z; a UTC comparison would fire five hours early."""
        last = _at("2026-07-27 12:05", UTC)          # local 07:05 on 07-27
        before = _at("2026-07-28 06:30", WEST)       # local 06:30 — too early
        at_anchor = _at("2026-07-28 07:00", WEST)    # local 07:00 — due
        self.assertFalse(_due("daily 07:00", last, before)[0])
        self.assertTrue(_due("daily 07:00", last, at_anchor)[0])


# ==========================================================================
# every tick / hourly
# ==========================================================================

class EveryTickTests(unittest.TestCase):
    def test_every_tick_is_due_when_never_run(self):
        due, reason = _due("every tick", None, _at("2026-07-28 07:00"))
        self.assertTrue(due)
        self.assertTrue(reason)

    def test_every_tick_is_due_one_second_after_the_last_run(self):
        due, _ = _due(
            "every tick", _at("2026-07-28 07:00:00"), _at("2026-07-28 07:00:01")
        )
        self.assertTrue(due)

    def test_every_tick_is_due_even_when_last_run_equals_now(self):
        due, _ = _due("every tick", _at("2026-07-28 07:00"), _at("2026-07-28 07:00"))
        self.assertTrue(due)


class HourlyTests(unittest.TestCase):
    def test_hourly_is_due_when_never_run(self):
        due, reason = _due("hourly", None, _at("2026-07-28 07:00"))
        self.assertTrue(due)
        self.assertIn("never", reason.lower())

    def test_hourly_is_due_at_exactly_one_hour(self):
        """Boundary: §2 says `>= 1h`, so the tick at exactly +60m runs."""
        due, _ = _due("hourly", _at("2026-07-28 07:00"), _at("2026-07-28 08:00"))
        self.assertTrue(due)

    def test_hourly_is_not_due_one_second_before_one_hour(self):
        due, reason = _due(
            "hourly", _at("2026-07-28 07:00:00"), _at("2026-07-28 07:59:59")
        )
        self.assertFalse(due)
        self.assertTrue(reason)

    def test_hourly_is_an_elapsed_interval_so_offsets_cancel(self):
        """SIBLING — hourly is the one form with no local-date component; a
        UTC last-run and a UTC-5 now that are 90 minutes apart are due."""
        due, _ = _due("hourly", _at("2026-07-28 12:00", UTC), _at("2026-07-28 08:30", WEST))
        self.assertTrue(due)

    def test_hourly_is_due_across_midnight(self):
        """SIBLING — an interval straddling a date change is normal."""
        due, _ = _due("hourly", _at("2026-07-27 23:30"), _at("2026-07-28 00:35"))
        self.assertTrue(due)

    def test_hourly_is_due_after_a_long_outage(self):
        """SIBLING — days since the last run is still just due, never an error."""
        due, _ = _due("hourly", _at("2026-07-01 07:00"), _at("2026-07-28 07:00"))
        self.assertTrue(due)


# ==========================================================================
# daily / daily HH:MM
# ==========================================================================

class DailyTests(unittest.TestCase):
    def test_daily_is_due_when_never_run(self):
        due, reason = _due("daily", None, _at("2026-07-28 03:00"))
        self.assertTrue(due)
        self.assertIn("never", reason.lower())

    def test_daily_is_due_on_a_new_local_date(self):
        due, _ = _due("daily", _at("2026-07-27 23:00"), _at("2026-07-28 01:00"))
        self.assertTrue(due)

    def test_daily_is_due_two_minutes_later_across_midnight(self):
        """The rule is calendar-date based, not 24h based — and deliberately."""
        due, _ = _due("daily", _at("2026-07-27 23:59"), _at("2026-07-28 00:01"))
        self.assertTrue(due)

    def test_daily_is_not_due_twice_on_the_same_local_date(self):
        due, reason = _due("daily", _at("2026-07-28 00:01"), _at("2026-07-28 23:59"))
        self.assertFalse(due)
        self.assertTrue(reason)

    def test_daily_is_due_after_a_multi_day_gap(self):
        """SIBLING — a missed week is due, never an error."""
        due, _ = _due("daily", _at("2026-07-20 07:00"), _at("2026-07-28 07:00"))
        self.assertTrue(due)


class DailyAnchorTests(unittest.TestCase):
    CAD = "daily 07:00"

    def test_never_run_is_not_due_before_the_anchor(self):
        due, reason = _due(self.CAD, None, _at("2026-07-28 06:59"))
        self.assertFalse(due)
        self.assertTrue(reason)

    def test_never_run_is_due_at_the_anchor(self):
        """Boundary: local time >= anchor, so exactly 07:00 runs."""
        due, _ = _due(self.CAD, None, _at("2026-07-28 07:00"))
        self.assertTrue(due)

    def test_never_run_is_due_after_the_anchor(self):
        due, _ = _due(self.CAD, None, _at("2026-07-28 22:00"))
        self.assertTrue(due)

    def test_new_date_before_the_anchor_is_not_due(self):
        due, _ = _due(self.CAD, _at("2026-07-27 07:05"), _at("2026-07-28 06:59"))
        self.assertFalse(due)

    def test_new_date_exactly_at_the_anchor_is_due(self):
        due, _ = _due(self.CAD, _at("2026-07-27 07:05"), _at("2026-07-28 07:00"))
        self.assertTrue(due)

    def test_same_date_after_the_anchor_is_not_due_again(self):
        due, _ = _due(self.CAD, _at("2026-07-28 07:01"), _at("2026-07-28 18:00"))
        self.assertFalse(due)

    def test_midnight_anchor_degenerates_to_daily(self):
        """SIBLING — `daily 00:00` must not be mishandled as a falsy time."""
        due, _ = _due("daily 00:00", _at("2026-07-27 12:00"), _at("2026-07-28 00:00"))
        self.assertTrue(due)

    def test_late_anchor_is_not_due_earlier_in_the_day(self):
        due, _ = _due("daily 23:30", _at("2026-07-27 23:35"), _at("2026-07-28 22:00"))
        self.assertFalse(due)

    def test_late_anchor_is_due_at_the_anchor(self):
        due, _ = _due("daily 23:30", _at("2026-07-27 23:35"), _at("2026-07-28 23:30"))
        self.assertTrue(due)

    def test_reason_mentions_the_anchor_when_not_reached(self):
        _, reason = _due(self.CAD, _at("2026-07-27 07:05"), _at("2026-07-28 06:00"))
        self.assertIn("07:00", reason)


# ==========================================================================
# weekly
# ==========================================================================

class WeeklyTests(unittest.TestCase):
    def test_never_run_is_due_on_the_anchor_weekday(self):
        due, reason = _due("weekly mon", None, _at("2026-07-27 09:00"))
        self.assertTrue(due)
        self.assertTrue(reason)

    def test_never_run_is_not_due_off_the_anchor_weekday(self):
        due, reason = _due("weekly mon", None, _at("2026-07-28 09:00"))
        self.assertFalse(due)
        self.assertTrue(reason)

    def test_is_due_on_the_anchor_weekday_a_week_later(self):
        due, _ = _due("weekly mon", _at("2026-07-20 09:00"), _at("2026-07-27 09:00"))
        self.assertTrue(due)

    def test_is_not_due_twice_on_the_same_anchor_day(self):
        due, _ = _due("weekly mon", _at("2026-07-27 09:00"), _at("2026-07-27 21:00"))
        self.assertFalse(due)

    def test_is_not_due_off_the_anchor_weekday(self):
        due, _ = _due("weekly mon", _at("2026-07-20 09:00"), _at("2026-07-29 09:00"))
        self.assertFalse(due)

    def test_sunday_anchor_works(self):
        """SIBLING — `sun` is weekday 6 in python and index 0 in some locales;
        an off-by-one here silently kills a whole role."""
        self.assertTrue(_due("weekly sun", None, _at("2026-07-26 09:00"))[0])
        self.assertFalse(_due("weekly sun", None, _at("2026-07-27 09:00"))[0])

    def test_saturday_anchor_works(self):
        """SIBLING — the other end of the week."""
        self.assertTrue(_due("weekly sat", None, _at("2026-08-01 09:00"))[0])

    def test_anchored_weekly_is_not_due_before_the_time_on_the_right_day(self):
        due, _ = _due("weekly mon 09:00", _at("2026-07-20 09:05"), _at("2026-07-27 08:59"))
        self.assertFalse(due)

    def test_anchored_weekly_is_due_at_the_time_on_the_right_day(self):
        due, _ = _due("weekly mon 09:00", _at("2026-07-20 09:05"), _at("2026-07-27 09:00"))
        self.assertTrue(due)

    def test_anchored_weekly_is_not_due_at_the_right_time_on_the_wrong_day(self):
        due, _ = _due("weekly mon 09:00", _at("2026-07-20 09:05"), _at("2026-07-28 09:00"))
        self.assertFalse(due)

    def test_no_catch_up_after_a_missed_weekly_anchor(self):
        """§2: catch-up is explicitly NOT performed. The Monday 2026-07-20 tick
        never ran; Tuesday must not fire in its place — it waits for 07-27."""
        due, _ = _due("weekly mon 09:00", _at("2026-07-13 09:05"), _at("2026-07-21 09:00"))
        self.assertFalse(due)

    def test_is_due_on_the_next_anchor_weekday_after_a_missed_week(self):
        """SIBLING of the no-catch-up rule — waiting is not locking out."""
        due, _ = _due("weekly mon 09:00", _at("2026-07-13 09:05"), _at("2026-07-27 09:00"))
        self.assertTrue(due)


# ==========================================================================
# monthly
# ==========================================================================

class MonthlyTests(unittest.TestCase):
    def test_never_run_is_due_on_the_anchor_day(self):
        due, reason = _due("monthly 15", None, _at("2026-07-15 09:00"))
        self.assertTrue(due)
        self.assertTrue(reason)

    def test_never_run_is_not_due_off_the_anchor_day(self):
        due, _ = _due("monthly 15", None, _at("2026-07-16 09:00"))
        self.assertFalse(due)

    def test_is_due_on_the_anchor_day_next_month(self):
        due, _ = _due("monthly 15", _at("2026-06-15 09:00"), _at("2026-07-15 09:00"))
        self.assertTrue(due)

    def test_is_not_due_twice_on_the_same_anchor_day(self):
        due, _ = _due("monthly 15", _at("2026-07-15 09:00"), _at("2026-07-15 23:00"))
        self.assertFalse(due)

    def test_day_28_is_due_in_february(self):
        """SIBLING — the reason the range stops at 28: day 28 exists in every
        month, so a monthly role can never be skipped for a whole year."""
        due, _ = _due("monthly 28", _at("2026-01-28 09:00"), _at("2026-02-28 09:00"))
        self.assertTrue(due)

    def test_day_1_is_due_on_the_first(self):
        """SIBLING — the other boundary of the legal range."""
        due, _ = _due("monthly 1", _at("2025-12-01 09:00"), _at("2026-01-01 09:00"))
        self.assertTrue(due)

    def test_anchored_monthly_is_not_due_before_the_time(self):
        due, _ = _due("monthly 28 06:30", _at("2026-06-28 06:35"), _at("2026-07-28 06:00"))
        self.assertFalse(due)

    def test_anchored_monthly_is_due_at_the_time(self):
        due, _ = _due("monthly 28 06:30", _at("2026-06-28 06:35"), _at("2026-07-28 06:30"))
        self.assertTrue(due)

    def test_no_catch_up_after_a_missed_monthly_anchor(self):
        due, _ = _due("monthly 28", _at("2026-05-28 09:00"), _at("2026-07-29 09:00"))
        self.assertFalse(due)


# ==========================================================================
# §2.1 — the unreachable anchor
# ==========================================================================

def _simulate(cadence_text: str, tick_local: str, days: int, tz=UTC) -> int:
    """Fire count over `days` consecutive ticks, all at the same local time.

    Models what the scheduler actually does: one tick a day at a fixed hour,
    `last_run` advanced only when the role fires. Nothing here reads a clock.
    """
    cadence = cad.parse_cadence(cadence_text)
    last_run = None
    fires = 0
    start = _at(f"2026-07-01 {tick_local}", tz)
    for day in range(days):
        now = start + timedelta(days=day)
        due, _ = cad.is_due(cadence, last_run, now)
        if due:
            fires += 1
            last_run = now
    return fires


class UnreachableAnchorTests(unittest.TestCase):
    """§2.1 — an anchor LATER than the tick's own time is never satisfied, so
    the role fires zero times forever, and because a not-due role writes no log
    line every surface reports a role that has simply «never run».

    This is the arithmetic the `validate` note exists to warn about, pinned
    here independently of `validate` so that a future change to `is_due` which
    quietly fixed or worsened it could not pass unnoticed. The grammar is not
    at fault — an anchor is meaningful when the owner's tick runs more than
    once a day — so these tests assert the behaviour, they do not demand it
    change.

    Numbers verified by execution against a 07:00 tick over 28 days.
    """

    TICK = "07:00"
    DAYS = 28

    def test_a_daily_anchor_after_the_tick_time_never_fires(self):
        self.assertEqual(_simulate("daily 14:00", self.TICK, self.DAYS), 0)

    def test_a_weekly_anchor_after_the_tick_time_never_fires(self):
        self.assertEqual(_simulate("weekly mon 09:00", self.TICK, self.DAYS), 0)

    def test_a_monthly_anchor_after_the_tick_time_never_fires(self):
        self.assertEqual(_simulate("monthly 3 18:30", self.TICK, self.DAYS), 0)

    def test_an_anchor_one_minute_after_the_tick_never_fires(self):
        """The boundary: unreachability is not about being far away."""
        self.assertEqual(_simulate("daily 07:01", self.TICK, self.DAYS), 0)

    def test_an_anchor_equal_to_the_tick_time_fires_every_day(self):
        """SIBLING — `>=` means the anchor AT the tick time is reachable, and
        that one minute is the whole difference."""
        self.assertEqual(_simulate("daily 07:00", self.TICK, self.DAYS), self.DAYS)

    def test_an_anchor_before_the_tick_time_fires_every_day(self):
        """SIBLING — the shape an owner actually wants from an anchor."""
        self.assertEqual(_simulate("daily 06:00", self.TICK, self.DAYS), self.DAYS)

    def test_a_bare_daily_fires_every_day(self):
        """SIBLING — the anchor-free form the concierge emits instead."""
        self.assertEqual(_simulate("daily", self.TICK, self.DAYS), self.DAYS)

    def test_a_bare_weekly_fires_once_a_week(self):
        """SIBLING — dropping the anchor keeps the schedule, not just the
        firing: four Mondays in 28 days."""
        self.assertEqual(_simulate("weekly mon", self.TICK, self.DAYS), 4)

    def test_a_reachable_weekly_anchor_fires_once_a_week(self):
        """SIBLING — `weekly mon 06:00` under a 07:00 tick is perfectly
        reachable, so the anchor is not the defect; its relation to the tick is."""
        self.assertEqual(_simulate("weekly mon 06:00", self.TICK, self.DAYS), 4)

    def test_a_bare_monthly_fires_once_a_month(self):
        """SIBLING — one 3rd of the month falls inside a 28-day window."""
        self.assertEqual(_simulate("monthly 3", self.TICK, self.DAYS), 1)

    def test_an_unreachable_anchor_becomes_reachable_under_a_later_tick(self):
        """The grammar is sound: the SAME cadence that never fires at 07:00
        fires every day when the owner's scheduler ticks at 15:00. This is why
        §2.1 is a note and not a blocker — the engine cannot know the cron."""
        self.assertEqual(_simulate("daily 14:00", "07:00", self.DAYS), 0)
        self.assertEqual(_simulate("daily 14:00", "15:00", self.DAYS), self.DAYS)

    def test_an_hourly_tick_reaches_an_anchor_a_daily_tick_cannot(self):
        """SIBLING — the same point from the other side: what makes an anchor
        reachable is tick FREQUENCY, so a role on an hourly schedule is fine."""
        cadence = cad.parse_cadence("daily 14:00")
        last_run, fires = None, 0
        start = _at("2026-07-01 00:00")
        for hour in range(24 * 7):
            now = start + timedelta(hours=hour)
            due, _ = cad.is_due(cadence, last_run, now)
            if due:
                fires += 1
                last_run = now
        self.assertEqual(fires, 7)

    def test_the_unreachable_reason_is_reported_every_tick(self):
        """The role is not silent to the ENGINE — `is_due` says why each time.
        The silence is downstream, because a not-due role writes no log line.
        Pinning the reason keeps the diagnosis available to `due`."""
        cadence = cad.parse_cadence("daily 14:00")
        due, reason = cad.is_due(cadence, None, _at("2026-07-28 07:00"))
        self.assertFalse(due)
        self.assertIn("14:00", reason)


class DaylightSavingTests(unittest.TestCase):
    """A fixed UTC offset is not a timezone.

    §2 converts `last_run` into the zone carried by `now`. If that zone is a
    fixed offset — which is what `datetime.now(timezone.utc).astimezone()`
    produces — then a `last_run` recorded on the other side of a DST
    transition is converted at TODAY's offset, not the one in force when it
    was written. An hour of local time is misplaced, and on the days it
    matters the role reports `already ran on this local date` when it did not.

    A real `ZoneInfo` carries the rule rather than one instant's offset, so
    the conversion lands on the right local date.

    Skipped where the platform has no tz database (a bare Windows install
    without `tzdata`), because the alternative is a test that fails for a
    reason that is not the engine's.
    """

    ZONE = "America/New_York"

    def _zone(self):
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(self.ZONE)
        except Exception as exc:            # noqa: BLE001 — missing tzdata
            self.skipTest(f"no tz database for {self.ZONE}: {exc}")

    def test_daily_is_due_across_the_spring_forward_boundary(self):
        """2026-03-08 is the US spring-forward. The last run was 23:30 local
        on 03-07 (EST, -05:00); now is 07:00 local on 03-08 (EDT, -04:00). The
        local date advanced, so the role is due."""
        zone = self._zone()
        last_run = datetime(2026, 3, 8, 4, 30, tzinfo=UTC)          # 03-07 23:30 EST
        now = datetime(2026, 3, 8, 7, 0, tzinfo=zone)               # 03-08 07:00 EDT
        self.assertEqual(last_run.astimezone(zone).date().isoformat(), "2026-03-07")
        due, reason = cad.is_due(cad.parse_cadence("daily"), last_run, now)
        self.assertTrue(due, f"the local date advanced but the role was held: {reason}")

    def test_the_same_instants_under_a_fixed_offset_get_it_wrong(self):
        """The defect, stated as a fact about the inputs rather than a demand
        on the engine: with a fixed -04:00 the same `last_run` lands on
        03-08, so any correct date comparison against it must say not-due.
        This is why the zone has to survive into `now`."""
        fixed = timezone(timedelta(hours=-4))
        last_run = datetime(2026, 3, 8, 4, 30, tzinfo=UTC)
        self.assertEqual(last_run.astimezone(fixed).date().isoformat(), "2026-03-08")
        now = datetime(2026, 3, 8, 7, 0, tzinfo=fixed)
        due, _ = cad.is_due(cad.parse_cadence("daily"), last_run, now)
        self.assertFalse(due, "a fixed offset cannot see that the date advanced")

    def test_daily_is_not_due_twice_on_one_local_date_across_the_boundary(self):
        """SIBLING — the fix must not make the role fire twice on the day the
        clocks change. Both instants are 03-08 local."""
        zone = self._zone()
        last_run = datetime(2026, 3, 8, 12, 30, tzinfo=UTC)         # 03-08 08:30 EDT
        now = datetime(2026, 3, 8, 22, 0, tzinfo=zone)              # 03-08 18:00 EDT
        self.assertFalse(cad.is_due(cad.parse_cadence("daily"), last_run, now)[0])

    def test_an_anchor_is_compared_against_local_time_after_the_shift(self):
        """SIBLING — `daily 07:00` still means the owner's 07:00 on both sides
        of the transition, not 07:00 at a frozen offset."""
        zone = self._zone()
        last_run = datetime(2026, 3, 7, 12, 5, tzinfo=UTC)          # 03-07 07:05 EST
        before = datetime(2026, 3, 8, 6, 30, tzinfo=zone)           # 03-08 06:30 EDT
        at_anchor = datetime(2026, 3, 8, 7, 0, tzinfo=zone)         # 03-08 07:00 EDT
        cadence = cad.parse_cadence("daily 07:00")
        self.assertFalse(cad.is_due(cadence, last_run, before)[0])
        self.assertTrue(cad.is_due(cadence, last_run, at_anchor)[0])

    def test_daily_is_due_across_the_autumn_fall_back_boundary(self):
        """SIBLING — the other transition, where the offset moves the other
        way and a naive implementation double-counts an hour."""
        zone = self._zone()
        last_run = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)         # 10-31 23:30 EDT
        now = datetime(2026, 11, 1, 12, 0, tzinfo=zone)             # 11-01 07:00 EST
        self.assertEqual(last_run.astimezone(zone).date().isoformat(), "2026-10-31")
        self.assertTrue(cad.is_due(cad.parse_cadence("daily"), last_run, now)[0])

    def test_a_zoneinfo_now_is_accepted_like_any_other_aware_datetime(self):
        """SIBLING — a real zone must not trip the aware/naive check."""
        zone = self._zone()
        now = datetime(2026, 7, 28, 7, 0, tzinfo=zone)
        self.assertTrue(cad.is_due(cad.parse_cadence("daily"), None, now)[0])


class FutureLastRunTests(unittest.TestCase):
    """A `last_run` in the future must never freeze a role.

    It happens for ordinary reasons: the host clock was wrong and got
    corrected, a laptop resumed with a stale RTC, a log was copied from
    another machine, or a tick ran under a mistaken `--now`. The arithmetic
    then computes a NEGATIVE elapsed time, `now - last_run >= 1h` is false,
    and an `hourly` role stops firing — silently and forever, because a
    not-due role writes no log line to reveal it. Exactly §2.1's failure
    shape, reached from the other direction.

    The safe answer is to run: a role that runs once too often is a nuisance,
    one that never runs again is the defect this subsystem exists to prevent.
    """

    NOW = _at("2026-07-28 07:00")

    def test_hourly_is_due_when_the_last_run_is_in_the_future(self):
        future = self.NOW + timedelta(hours=5)
        due, reason = cad.is_due(cad.parse_cadence("hourly"), future, self.NOW)
        self.assertTrue(due, "a future timestamp froze the role")
        self.assertTrue(reason.strip())

    def test_hourly_is_due_when_the_last_run_is_days_in_the_future(self):
        future = self.NOW + timedelta(days=30)
        self.assertTrue(cad.is_due(cad.parse_cadence("hourly"), future, self.NOW)[0])

    def test_daily_is_due_when_the_last_run_is_in_the_future(self):
        future = self.NOW + timedelta(days=3)
        self.assertTrue(cad.is_due(cad.parse_cadence("daily"), future, self.NOW)[0])

    def test_an_anchored_daily_is_due_when_the_last_run_is_in_the_future(self):
        future = self.NOW + timedelta(days=3)
        due, _ = cad.is_due(cad.parse_cadence("daily 06:00"), future, self.NOW)
        self.assertTrue(due)

    def test_every_tick_is_unaffected_by_a_future_last_run(self):
        """SIBLING — the form with no arithmetic at all must stay simple."""
        future = self.NOW + timedelta(days=3)
        self.assertTrue(cad.is_due(cad.parse_cadence("every tick"), future, self.NOW)[0])

    def test_a_future_last_run_does_not_make_an_unreachable_anchor_reachable(self):
        """SIBLING — unfreezing must not become «always due». A 14:00 anchor
        under a 07:00 tick stays not-due; the clock skew is not a licence to
        ignore the anchor."""
        future = self.NOW + timedelta(days=3)
        due, _ = cad.is_due(cad.parse_cadence("daily 14:00"), future, self.NOW)
        self.assertFalse(due)

    def test_a_normal_recent_last_run_still_suppresses_an_hourly_role(self):
        """SIBLING — the fix must not turn `hourly` into `every tick`."""
        recent = self.NOW - timedelta(minutes=30)
        self.assertFalse(cad.is_due(cad.parse_cadence("hourly"), recent, self.NOW)[0])

    def test_a_future_last_run_recovers_rather_than_repeating_forever(self):
        """Once the role runs, `last_run` is overwritten with the real time,
        so the skew self-heals: one catch-up fire, then the normal cadence."""
        cadence = cad.parse_cadence("hourly")
        last_run = self.NOW + timedelta(hours=5)
        fires = 0
        for minute in range(0, 240, 30):
            now = self.NOW + timedelta(minutes=minute)
            due, _ = cad.is_due(cadence, last_run, now)
            if due:
                fires += 1
                last_run = now
        self.assertEqual(fires, 4, "expected the catch-up fire then hourly")


class AnchorNoteTests(unittest.TestCase):
    """`anchor_note` — the §2.1 warning text, owned by the cadence module.

    It lives here and not in `roles_run` because `roles_run` composes and owns
    no domain logic (§0): whether a cadence carries an anchor, and how to say
    so, is grammar knowledge. `validate` renders what this returns.
    """

    def test_returns_a_note_for_every_anchored_form(self):
        for text, anchor in (("daily 14:00", "14:00"),
                             ("weekly mon 09:00", "09:00"),
                             ("monthly 3 18:30", "18:30")):
            with self.subTest(cadence=text):
                note = cad.anchor_note(cad.parse_cadence(text))
                self.assertIsNotNone(note)
                self.assertIn(anchor, note)

    def test_returns_none_for_every_unanchored_form(self):
        """SIBLING — the note must not fire on a cadence that cannot suffer
        from the defect, or it becomes noise and hides the real one."""
        for text in ("daily", "weekly mon", "monthly 3"):
            with self.subTest(cadence=text):
                self.assertIsNone(cad.anchor_note(cad.parse_cadence(text)))


    def test_a_tick_rate_form_carries_its_own_note(self):
        """SIBLING to the above, and the reason those two left that list."""
        for text in ("hourly", "every tick"):
            with self.subTest(cadence=text):
                note = cad.anchor_note(cad.parse_cadence(text))
                self.assertIsNotNone(note)
                self.assertIn("every scheduler tick", note)

    def test_the_note_states_the_requirement_not_just_the_fact(self):
        """An owner reading it must learn what has to be true for the role to
        run at all — naming the anchor alone would not tell them anything they
        did not write themselves."""
        note = cad.anchor_note(cad.parse_cadence("daily 14:00"))
        self.assertIn("14:00", note)
        self.assertGreater(len(note.split()), 8, "one line, but a whole sentence")

    def test_the_note_is_english_only(self):
        """§0 — the engine emits no owner-language prose."""
        note = cad.anchor_note(cad.parse_cadence("daily 14:00"))
        self.assertTrue(all(ord(ch) < 0x400 for ch in note))

    def test_a_midnight_anchor_still_produces_a_note(self):
        """SIBLING and a falsy-value trap: `time(0, 0)` is falsy, so an
        `if anchor_time:` test would silently drop the one anchor that is
        reachable from any tick — and the owner would never be told why a
        `daily 00:00` role behaves like a bare `daily`."""
        self.assertIsNotNone(cad.anchor_note(cad.parse_cadence("daily 00:00")))

    def test_anchor_note_takes_a_parsed_cadence(self):
        """One grammar, one parse path — the same rule as `is_due`."""
        params = list(inspect.signature(cad.anchor_note).parameters)
        self.assertEqual(params[0], "cadence")


# ==========================================================================
# contract / purity / SRP
# ==========================================================================

class ContractTests(unittest.TestCase):
    def test_is_due_takes_a_parsed_cadence_not_a_string(self):
        """One grammar, one parse path (§2)."""
        with self.assertRaises(Exception):
            cad.is_due("daily", None, _at("2026-07-28 07:00"))  # type: ignore[arg-type]

    def test_is_due_returns_a_bool_and_a_short_english_reason(self):
        for text in ALL_VALID:
            with self.subTest(cadence=text):
                due, reason = _due(text, None, _at("2026-07-28 07:00"))
                self.assertIsInstance(due, bool)
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip())
                self.assertLess(len(reason), 120, "reason is a log line, not prose")
                self.assertTrue(
                    all(ord(ch) < 0x400 for ch in reason),
                    "§0: the engine emits no owner-language prose",
                )

    def test_never_run_reason_says_never_run(self):
        for text in ("hourly", "daily", "daily 07:00"):
            with self.subTest(cadence=text):
                due, reason = _due(text, None, _at("2026-07-28 07:00"))
                self.assertTrue(due)
                self.assertIn("never", reason.lower())

    def test_no_wall_clock_dependency(self):
        """`now` is always injected — a date decades in the past produces the
        same answer from the arithmetic alone."""
        old = _due("daily", _at("1999-12-31 23:00"), _at("2000-01-01 00:30"))
        new = _due("daily", _at("2026-07-27 23:00"), _at("2026-07-28 00:30"))
        self.assertEqual(old[0], new[0])
        self.assertTrue(old[0])

    def test_is_due_is_pure_and_repeatable(self):
        args = (cad.parse_cadence("daily 07:00"),
                _at("2026-07-27 07:05"), _at("2026-07-28 07:00"))
        self.assertEqual(cad.is_due(*args), cad.is_due(*args))

    def test_is_due_takes_no_status_argument(self):
        """SRP: a paused role is the caller's filter, not this module's
        concern. A `status` parameter here would be the boundary leaking."""
        params = list(inspect.signature(cad.is_due).parameters)
        self.assertNotIn("status", params)
        self.assertEqual(params[:3], ["cadence", "last_run", "now"])

    def test_module_reads_no_module_level_clock(self):
        src = inspect.getsource(cad)
        for banned in ("datetime.now()", "datetime.utcnow()", "time.time()"):
            with self.subTest(call=banned):
                self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
