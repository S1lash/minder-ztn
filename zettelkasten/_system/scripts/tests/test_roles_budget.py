"""Tests for roles_budget.py — the per-role cumulative write budget.

Isolated to a tempdir base (`_system/roles/{role_id}/budget.json`) — no env
mutation, no LLM, no network. `today` is always passed explicitly so period
rollover is deterministic and reproducible.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_budget as rb  # noqa: E402


class RolesBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.role_id = "minder-pm"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _path(self) -> Path:
        return rb.budget_path(self.role_id, self.base)

    # -- defaults when file absent -----------------------------------------

    def test_load_defaults_when_file_absent(self) -> None:
        self.assertFalse(self._path().exists())
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(state["max_writes_per_period"], rb.DEFAULT_MAX_WRITES_PER_PERIOD)
        self.assertEqual(state["period_days"], rb.DEFAULT_PERIOD_DAYS)
        self.assertEqual(state["writes_this_period"], 0)
        self.assertEqual(state["max_tick_seconds"], rb.DEFAULT_MAX_TICK_SECONDS)
        self.assertTrue(rb.can_write(state))
        self.assertEqual(
            rb.budget_remaining(state), rb.DEFAULT_MAX_WRITES_PER_PERIOD
        )

    def test_absent_file_role_is_still_bounded(self) -> None:
        # A role with no budget.json at all still gets a real ceiling, not
        # an unbounded pass.
        state = rb.load_budget("brand-new-role", self.base)
        self.assertEqual(state["max_writes_per_period"], rb.DEFAULT_MAX_WRITES_PER_PERIOD)

    # -- record_writes persists + returns updated ---------------------------

    def test_record_writes_persists_and_returns_updated(self) -> None:
        today = date(2026, 1, 1)
        new_state = rb.record_writes(self.role_id, 3, self.base, today=today)
        self.assertEqual(new_state["writes_this_period"], 3)
        self.assertTrue(self._path().exists())

        on_disk = json.loads(self._path().read_text(encoding="utf-8"))
        self.assertEqual(on_disk["writes_this_period"], 3)
        self.assertEqual(on_disk["period_start"], today.isoformat())

        reloaded = rb.load_budget(self.role_id, self.base)
        self.assertEqual(reloaded["writes_this_period"], 3)

    def test_record_writes_accumulates_across_calls(self) -> None:
        today = date(2026, 1, 1)
        rb.record_writes(self.role_id, 2, self.base, today=today)
        state = rb.record_writes(self.role_id, 5, self.base, today=today)
        self.assertEqual(state["writes_this_period"], 7)

    # -- ceiling clamps + can_write flips false at ceiling -------------------

    def test_ceiling_clamps_and_can_write_flips_false(self) -> None:
        today = date(2026, 1, 1)
        # Seed a small ceiling directly on disk.
        seed = rb._default_state(today)
        seed["max_writes_per_period"] = 3
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seed), encoding="utf-8")

        state = rb.record_writes(self.role_id, 2, self.base, today=today)
        self.assertEqual(state["writes_this_period"], 2)
        self.assertTrue(rb.can_write(state, today=today))
        self.assertEqual(rb.budget_remaining(state, today=today), 1)

        # Over-report past the ceiling — must clamp, never go negative headroom.
        state = rb.record_writes(self.role_id, 10, self.base, today=today)
        self.assertEqual(state["writes_this_period"], 3)
        self.assertFalse(rb.can_write(state, today=today))
        self.assertEqual(rb.budget_remaining(state, today=today), 0)

    # -- period rollover resets the count ------------------------------------

    def test_period_rollover_resets_count_on_record_writes(self) -> None:
        start = date(2026, 1, 1)
        rb.record_writes(self.role_id, 5, self.base, today=start)

        # Past period_start + period_days (default 7) → rollover on next record.
        later = date(2026, 1, 9)
        state = rb.record_writes(self.role_id, 1, self.base, today=later)
        self.assertEqual(state["writes_this_period"], 1)
        self.assertEqual(state["period_start"], later.isoformat())

    def test_budget_remaining_reflects_rollover_without_mutating_file(self) -> None:
        start = date(2026, 1, 1)
        rb.record_writes(self.role_id, 5, self.base, today=start)
        before = self._path().read_text(encoding="utf-8")

        later = date(2026, 1, 9)
        state = rb.load_budget(self.role_id, self.base)
        remaining = rb.budget_remaining(state, today=later)
        self.assertEqual(remaining, rb.DEFAULT_MAX_WRITES_PER_PERIOD)
        self.assertTrue(rb.can_write(state, today=later))

        # Pure read — file on disk is untouched.
        after = self._path().read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_budget_remaining_no_rollover_within_period(self) -> None:
        start = date(2026, 1, 1)
        state = rb.record_writes(self.role_id, 5, self.base, today=start)
        still_within = date(2026, 1, 6)  # period_days=7, not yet elapsed
        self.assertEqual(
            rb.budget_remaining(state, today=still_within),
            rb.DEFAULT_MAX_WRITES_PER_PERIOD - 5,
        )

    # -- malformed budget.json -> defaults ------------------------------------

    def test_malformed_json_falls_back_to_defaults(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(state["max_writes_per_period"], rb.DEFAULT_MAX_WRITES_PER_PERIOD)
        self.assertEqual(state["writes_this_period"], 0)

    def test_non_dict_json_falls_back_to_defaults(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(state["max_writes_per_period"], rb.DEFAULT_MAX_WRITES_PER_PERIOD)

    def test_bad_field_types_fall_back_field_by_field(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "period_start": "not-a-date",
                    "period_days": "seven",
                    "max_writes_per_period": -5,
                    "writes_this_period": -1,
                    "max_tick_seconds": 0,
                }
            ),
            encoding="utf-8",
        )
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(state["period_days"], rb.DEFAULT_PERIOD_DAYS)
        self.assertEqual(state["max_writes_per_period"], rb.DEFAULT_MAX_WRITES_PER_PERIOD)
        self.assertEqual(state["writes_this_period"], 0)
        self.assertEqual(state["max_tick_seconds"], rb.DEFAULT_MAX_TICK_SECONDS)

    def test_malformed_file_does_not_crash_can_write(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("garbage", encoding="utf-8")
        state = rb.load_budget(self.role_id, self.base)
        self.assertTrue(rb.can_write(state))

    # -- max_tick_seconds -----------------------------------------------------

    def test_max_tick_seconds_reads_value(self) -> None:
        today = date(2026, 1, 1)
        seed = rb._default_state(today)
        seed["max_tick_seconds"] = 45
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seed), encoding="utf-8")
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(rb.max_tick_seconds(state), 45)

    def test_max_tick_seconds_default(self) -> None:
        state = rb.load_budget(self.role_id, self.base)
        self.assertEqual(rb.max_tick_seconds(state), rb.DEFAULT_MAX_TICK_SECONDS)

    # -- budget_path resolves via role_dir ------------------------------------

    def test_budget_path_under_role_dir(self) -> None:
        path = rb.budget_path(self.role_id, self.base)
        self.assertEqual(path.name, "budget.json")
        self.assertEqual(path.parent.name, self.role_id)


if __name__ == "__main__":
    unittest.main()
