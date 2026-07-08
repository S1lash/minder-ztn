"""Tests for reconcile_tasks — the deterministic task-aggregation reconciler."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import reconcile_tasks as rt  # type: ignore


def _base(tmp: str) -> Path:
    base = Path(tmp)
    (base / "_records" / "observations").mkdir(parents=True)
    (base / "_system").mkdir(parents=True)
    return base


def _note(base: Path, name: str, body: str) -> None:
    (base / "_records" / "observations" / name).write_text(body, encoding="utf-8")


def _tasks(base: Path, body: str) -> Path:
    p = base / "_system" / "TASKS.md"
    p.write_text(body, encoding="utf-8")
    return p


_TASKS_HEADER = (
    "# Tasks\n\n"
    "**Last Updated:** 2026-07-01\n\n"
    "---\n\n"
)


class ScanTests(unittest.TestCase):
    def test_scans_open_tasks_ignores_done_and_dedups_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] Do X → [[ivan-petrov]] ^task-x\n- [x] Done ✅ 2026-06-01 ^task-old\n")
            _note(base, "b.md", "- [ ] Do X again ^task-x\n- [ ] Do Y ^task-y\n")
            found = rt.scan_note_tasks(base)
            self.assertEqual(set(found), {"task-x", "task-y"})  # task-old (done) excluded
            # first-seen (sorted path a.md) wins for the shared id
            self.assertEqual(found["task-x"].note_id, "a")

    def test_parse_active_vs_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            p = _tasks(base, _TASKS_HEADER +
                       "## Action — я делаю\n- [ ] A — [[n1]] ^task-a\n\n"
                       "## Stale — кандидаты\n- [ ] S — [[n2]] ^task-s\n")
            active, stale = rt.parse_tasks_md(p)
            self.assertEqual(active, {"task-a"})
            self.assertEqual(stale, {"task-s"})


class FenceTests(unittest.TestCase):
    def test_task_inside_code_fence_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md",
                  "- [ ] Real ^task-real\n\n"
                  "```markdown\n- [ ] Example syntax ^task-example\n```\n")
            found = rt.scan_note_tasks(base)
            self.assertIn("task-real", found)
            self.assertNotIn("task-example", found)  # fenced example is not a task


class OrphanTests(unittest.TestCase):
    def test_note_task_absent_from_tasks_is_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] Aggregated ^task-a\n- [ ] Missing ^task-m\n")
            p = _tasks(base, _TASKS_HEADER + "## Action\n- [ ] A — [[a]] ^task-a\n")
            orphans = rt.find_orphans(base, p)
            self.assertEqual([o.task_id for o in orphans], ["task-m"])

    def test_stale_task_is_not_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] Stale one still open in note ^task-s\n")
            p = _tasks(base, _TASKS_HEADER + "## Stale — кандидаты\n- [ ] S — [[a]] ^task-s\n")
            self.assertEqual(rt.find_orphans(base, p), [])

    def test_reconcile_consistent_flag_and_dangling(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] A ^task-a\n")
            p = _tasks(base, _TASKS_HEADER +
                       "## Action\n- [ ] A — [[a]] ^task-a\n- [ ] Ghost — [[gone]] ^task-ghost\n")
            r = rt.reconcile(base, p)
            self.assertTrue(r["consistent"])
            self.assertEqual(r["orphan_count"], 0)
            self.assertEqual(r["dangling_active"], ["task-ghost"])  # in aggregate, not in notes


class ReadOnlyTests(unittest.TestCase):
    def test_report_never_mutates_tasks_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] Orphan ^task-orphan\n- [ ] A ^task-a\n")
            p = _tasks(base, _TASKS_HEADER + "## Action\n- [ ] A — [[a]] ^task-a\n")
            before = p.read_text(encoding="utf-8")
            r = rt.reconcile(base, p)
            self.assertFalse(r["consistent"])
            self.assertEqual([o["task_id"] for o in r["orphans"]], ["task-orphan"])
            # reconciler is read-only — the file is untouched
            self.assertEqual(before, p.read_text(encoding="utf-8"))


class RobustnessTests(unittest.TestCase):
    def test_non_utf8_file_in_scan_path_does_not_crash(self):
        # Regression for the UnicodeDecodeError crash: a binary/non-utf-8 note
        # must be skipped, real tasks still found, no exception.
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            (base / "_records" / "observations" / "binary.md").write_bytes(b"\xff\xfe\x00bad")
            _note(base, "ok.md", "- [ ] Real ^task-real\n")
            p = _tasks(base, _TASKS_HEADER + "## Action\n")
            r = rt.reconcile(base, p)  # must not raise
            self.assertEqual([o["task_id"] for o in r["orphans"]], ["task-real"])

    def test_non_utf8_tasks_md_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] A ^task-a\n")
            p = base / "_system" / "TASKS.md"
            p.write_bytes(b"\xff\xfe# Tasks")
            active, stale = rt.parse_tasks_md(p)  # must not raise
            self.assertEqual((active, stale), (set(), set()))


class RegexEdgeTests(unittest.TestCase):
    def test_task_text_with_link_wikilink_and_stray_caret(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md",
                  "- [ ] see [text](url) and [[note]] and a^b decoy ^task-tricky\n")
            found = rt.scan_note_tasks(base)
            self.assertIn("task-tricky", found)
            self.assertIn("[[note]]", found["task-tricky"].text)

    def test_done_and_non_task_lines_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md",
                  "- [x] Done ✅ 2026-06-01 ^task-done\n"
                  "* [ ] wrong bullet ^task-star\n"
                  "-  [ ] double space ^task-dbl\n"
                  "- [ ] tab-indented\t^task-ok\n")
            found = rt.scan_note_tasks(base)
            self.assertEqual(set(found), {"task-ok"})

    def test_stale_heading_real_form_and_no_false_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] S ^task-s\n- [ ] St ^task-st\n")
            p = _tasks(base, _TASKS_HEADER +
                       "## Staleness note\n- [ ] St — [[a]] ^task-st\n\n"
                       "## Stale — кандидаты на удаление/архивацию\n- [ ] S — [[a]] ^task-s\n")
            active, stale = rt.parse_tasks_md(p)
            self.assertIn("task-st", active)   # '## Staleness' is NOT the Stale section
            self.assertIn("task-s", stale)     # real Stale heading matched


class CliTests(unittest.TestCase):
    def test_main_report_json_and_missing_file(self):
        import contextlib
        import io
        import json
        with tempfile.TemporaryDirectory() as tmp:
            base = _base(tmp)
            _note(base, "a.md", "- [ ] Orphan ^task-orphan\n")
            _tasks(base, _TASKS_HEADER + "## Action\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = rt.main(["--base", str(base), "--report", "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["orphan_count"], 1)
            self.assertFalse(payload["consistent"])
            # missing TASKS.md → exit 2
            rc2 = rt.main(["--base", str(base), "--tasks", str(base / "nope.md"), "--report"])
            self.assertEqual(rc2, 2)


if __name__ == "__main__":
    unittest.main()
