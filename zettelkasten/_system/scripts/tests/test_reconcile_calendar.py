"""Tests for reconcile_calendar — coarse calendar-aggregation reconciler."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import reconcile_calendar as rc  # type: ignore

TODAY = dt.date(2026, 7, 1)


def _base(tmp: str) -> Path:
    base = Path(tmp)
    (base / "_records" / "meetings").mkdir(parents=True)
    (base / "_system").mkdir(parents=True)
    return base


def _note(base: Path, name: str, body: str) -> None:
    (base / "_records" / "meetings" / name).write_text(body, encoding="utf-8")


def _cal(base: Path, body: str) -> Path:
    p = base / "_system" / "CALENDAR.md"
    p.write_text(body, encoding="utf-8")
    return p


class FutureDateTests(unittest.TestCase):
    def test_future_and_past_and_fuzzy(self):
        self.assertTrue(rc._first_future_date("2026-08-01", TODAY))
        self.assertFalse(rc._first_future_date("2026-06-01", TODAY))       # past
        self.assertTrue(rc._first_future_date("~середина 2026-08", TODAY))  # fuzzy but future month
        self.assertFalse(rc._first_future_date("~середина 2026-05", TODAY)) # fuzzy past month
        self.assertFalse(rc._first_future_date("когда-нибудь", TODAY))      # unparseable → not flagged
        self.assertTrue(rc._first_future_date("2026-08 – начало 2026-09", TODAY))  # range, first is future


class ReconcileTests(unittest.TestCase):
    def test_future_event_note_absent_from_calendar_is_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future event ^meeting-x\n")
            _note(base, "b.md", "- 📅 **2026-05-01** — Past event\n")  # past → ignored
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            r = rc.reconcile(base, p, TODAY)
            self.assertEqual(r["orphan_notes"], ["a"])  # b is past, not flagged
            self.assertFalse(r["consistent"])

    def test_note_linked_in_forward_section_is_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n- 📅 **2026-08-01** — Future — [[a]]\n\n## Past\n")
            r = rc.reconcile(base, p, TODAY)
            self.assertTrue(r["consistent"])
            self.assertEqual(r["orphan_note_count"], 0)

    def test_link_only_in_past_section_does_not_count_as_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n- 📅 **2026-06-01** — Old — [[a]]\n")
            r = rc.reconcile(base, p, TODAY)
            self.assertEqual(r["orphan_notes"], ["a"])  # Past link doesn't cover a future event

    def test_aliased_wikilink_covers_the_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n- 📅 **2026-08-01** — Future — [[a|My meeting]]\n\n## Past\n")
            r = rc.reconcile(base, p, TODAY)
            self.assertTrue(r["consistent"])  # [[a|alias]] must resolve to note 'a'

    def test_event_inside_code_fence_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "```markdown\n- 📅 **2026-08-01** — Example ^meeting-ex\n```\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            r = rc.reconcile(base, p, TODAY)
            self.assertTrue(r["consistent"])  # fenced example is not a real event

    def test_dayless_current_month_not_flagged(self):
        # today mid-month; a day-less current-month date is ambiguous (could be
        # past) → must NOT be flagged as a future orphan.
        today = dt.date(2026, 7, 25)
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **~середина 2026-07** — ambiguous\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            r = rc.reconcile(base, p, today)
            self.assertTrue(r["consistent"])

    def test_report_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            before = p.read_text(encoding="utf-8")
            rc.reconcile(base, p, TODAY)
            self.assertEqual(before, p.read_text(encoding="utf-8"))


class FuzzyDateTests(unittest.TestCase):
    def test_invalid_calendar_dates_do_not_crash_and_are_not_future(self):
        for bad in ("2026-13-01", "2026-02-30", "2026-00-10", "not a date"):
            self.assertFalse(rc._first_future_date(bad, TODAY), bad)  # no raise, not future

    def test_date_ranges_use_first_parseable_date(self):
        self.assertTrue(rc._first_future_date("2026-08-01 – 2026-09-05", TODAY))
        self.assertFalse(rc._first_future_date("2026-05-01 – 2026-05-10", TODAY))  # both past

    def test_fuzzy_prefix_and_wave_forms(self):
        self.assertTrue(rc._first_future_date("~середина 2026-08", TODAY))
        self.assertFalse(rc._first_future_date("~конец 2026-06", TODAY))
        self.assertFalse(rc._first_future_date("когда-нибудь в будущем", TODAY))  # unparseable


class RobustnessTests(unittest.TestCase):
    def test_non_utf8_note_in_scan_path_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            (base / "_records" / "meetings" / "binary.md").write_bytes(b"\xff\xfe\x00")
            _note(base, "ok.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            r = rc.reconcile(base, p, TODAY)  # must not raise
            self.assertEqual(r["orphan_notes"], ["ok"])

    def test_non_utf8_calendar_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            p = base / "_system" / "CALENDAR.md"
            p.write_bytes(b"\xff\xfe# Calendar")
            self.assertEqual(rc.calendar_forward_notes(p), set())  # must not raise


class CliTests(unittest.TestCase):
    def test_main_report_json(self):
        import contextlib
        import io
        import json
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- 📅 **2026-08-01** — Future ^meeting-x\n")
            _cal(base, "# Calendar\n\n## Upcoming\n\n## Past\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc_code = rc.main(["--base", str(base), "--report", "--json", "--today", "2026-07-01"])
            self.assertEqual(rc_code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["orphan_note_count"], 1)


if __name__ == "__main__":
    unittest.main()
