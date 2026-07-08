"""Integration tests for the engine migrations 011-014.

These run the real migration shell scripts via subprocess against temp
fixtures. They regression-guard the load-bearing contracts discovered during
review: soft-nag `exit 0` on every path (a non-zero would abort `/ztn:update`
under `set -e`), correct detection counts, idempotency, ZERO owner-data
mutation, crash-honesty (a failed detector must not report a false "all clear"),
and 013's crash-safety on an unreadable HUB_INDEX.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
_SCRIPTS_DIR = _THIS.parents[1]          # zettelkasten/_system/scripts
_REPO_ROOT = _THIS.parents[4]            # repo root
_MIGRATIONS = _REPO_ROOT / "scripts" / "migrations"
_ENGINE_SCRIPTS = ("_common.py", "reconcile_tasks.py", "reconcile_calendar.py")


def _build_repo(tmp: str) -> Path:
    """Create a minimal repo skeleton with the real engine scripts copied in."""
    root = Path(tmp)
    (root / "scripts" / "migrations").mkdir(parents=True)
    zk_scripts = root / "zettelkasten" / "_system" / "scripts"
    zk_scripts.mkdir(parents=True)
    for name in _ENGINE_SCRIPTS:
        shutil.copy(_SCRIPTS_DIR / name, zk_scripts / name)
    for sub in ("_records/observations", "5_meta/mocs", "_system/views"):
        (root / "zettelkasten" / sub).mkdir(parents=True, exist_ok=True)
    return root


def _copy_migration(root: Path, name: str) -> Path:
    dst = root / "scripts" / "migrations" / name
    shutil.copy(_MIGRATIONS / name, dst)
    return dst


def _run(mig: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(mig)], capture_output=True, text=True)


def _tree_md5(root: Path) -> dict[str, str]:
    """md5 of every file under zettelkasten/ — to assert zero owner-data mutation.

    Skips Python bytecode caches (`__pycache__`/`.pyc`) — running the engine
    scripts writes those as a byproduct; they are engine artifacts, not owner data.
    """
    out: dict[str, str] = {}
    for p in sorted((root / "zettelkasten").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            out[str(p.relative_to(root))] = hashlib.md5(p.read_bytes()).hexdigest()
    return out


class Migration011TaskTests(unittest.TestCase):
    NAME = "011-backfill-task-aggregation.sh"

    def _seed(self, root: Path, tasks_md: str, notes: dict[str, str]) -> None:
        (root / "zettelkasten" / "_system" / "TASKS.md").write_text(tasks_md, encoding="utf-8")
        for fn, body in notes.items():
            (root / "zettelkasten" / "_records" / "observations" / fn).write_text(body, encoding="utf-8")

    def test_consistent_is_noop_exit0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            self._seed(root, "# Tasks\n\n## Action\n- [ ] A — [[a]] ^task-a\n", {"a.md": "- [ ] A ^task-a\n"})
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("consistent", r.stdout)

    def test_orphans_detected_soft_nag_exit0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            self._seed(root, "# Tasks\n\n## Action\n",
                       {"a.md": "- [ ] Orphan1 ^task-o1\n- [ ] Orphan2 ^task-o2\n"})
            mig = _copy_migration(root, self.NAME)
            before = _tree_md5(root)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)                       # soft-nag
            self.assertIn("Found 2 task", r.stderr)
            self.assertIn("--reconcile-tasks", r.stderr)
            self.assertEqual(before, _tree_md5(root))               # zero mutation

    def test_crashed_reconciler_not_reported_as_all_clear(self):
        # A broken reconciler must NOT be coerced into "consistent" (surface, don't decide).
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            self._seed(root, "# Tasks\n\n## Action\n", {"a.md": "- [ ] x ^task-x\n"})
            (root / "zettelkasten" / "_system" / "scripts" / "reconcile_tasks.py").write_text(
                "import sys\nsys.exit(1)\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("NOT assuming all-clear", r.stderr)
            self.assertNotIn("consistent", r.stdout)

    def test_fresh_clone_skips_exit0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            # no TASKS.md
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("skipping", r.stdout)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            self._seed(root, "# Tasks\n\n## Action\n", {"a.md": "- [ ] Orphan ^task-o\n"})
            mig = _copy_migration(root, self.NAME)
            r1, r2 = _run(mig), _run(mig)
            self.assertEqual((r1.returncode, r1.stdout, r1.stderr), (r2.returncode, r2.stdout, r2.stderr))


class Migration012CalendarTests(unittest.TestCase):
    NAME = "012-backfill-calendar-aggregation.sh"

    def test_consistent_noop_and_fresh_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "_system" / "CALENDAR.md").write_text(
                "# Calendar\n\n## Upcoming\n\n## Past\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("consistent", r.stdout)
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)  # no CALENDAR.md
            self.assertEqual(r.returncode, 0)
            self.assertIn("skipping", r.stdout)

    def test_crashed_reconciler_not_all_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "_system" / "CALENDAR.md").write_text(
                "# Calendar\n\n## Upcoming\n\n## Past\n", encoding="utf-8")
            (root / "zettelkasten" / "_system" / "scripts" / "reconcile_calendar.py").write_text(
                "import sys\nsys.exit(1)\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("NOT assuming all-clear", r.stderr)


class Migration013HubIndexTests(unittest.TestCase):
    NAME = "013-hub-index-completeness.sh"

    def test_missing_hub_detected_soft_nag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            mocs = root / "zettelkasten" / "5_meta" / "mocs"
            (mocs / "hub-a.md").write_text("x", encoding="utf-8")
            (mocs / "hub-b.md").write_text("x", encoding="utf-8")
            (root / "zettelkasten" / "_system" / "views" / "HUB_INDEX.md").write_text(
                "# Hub Index\n\n- [[hub-a]] listed\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            before = _tree_md5(root)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("missing 1 hub", r.stderr)
            self.assertEqual(before, _tree_md5(root))

    def test_complete_index_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "5_meta" / "mocs" / "hub-a.md").write_text("x", encoding="utf-8")
            (root / "zettelkasten" / "_system" / "views" / "HUB_INDEX.md").write_text(
                "# Hub Index\n\n- [[hub-a]]\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("no-op", r.stdout)

    def test_unreadable_hub_index_is_crash_safe_exit0(self):
        # Regression: an unreadable HUB_INDEX must not crash the migration and
        # abort the whole sync (013's inline python is internally crash-safe).
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "5_meta" / "mocs" / "hub-a.md").write_text("x", encoding="utf-8")
            hub_index = root / "zettelkasten" / "_system" / "views" / "HUB_INDEX.md"
            hub_index.write_text("# Hub Index\n", encoding="utf-8")
            hub_index.chmod(0o000)
            mig = _copy_migration(root, self.NAME)
            try:
                r = _run(mig)
                self.assertEqual(r.returncode, 0)
            finally:
                hub_index.chmod(0o644)


class Migration014FenceTests(unittest.TestCase):
    NAME = "014-repair-evidence-trail-fence.sh"

    def test_broken_note_detected_soft_nag_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "_records" / "observations" / "broken.md").write_text(
                "---\nid: x\nlayer: knowledge\n## Evidence Trail\n\n"
                "- **2026-05-05** | [[r]] — x\n---\n\nbody\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            before = _tree_md5(root)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("Found 1 note", r.stderr)
            self.assertIn("broken.md", r.stderr)
            self.assertEqual(before, _tree_md5(root))  # detection-only, no repair

    def test_clean_base_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _build_repo(tmp)
            (root / "zettelkasten" / "_records" / "observations" / "ok.md").write_text(
                "---\nid: x\nlayer: knowledge\n---\n\n## Body\n", encoding="utf-8")
            mig = _copy_migration(root, self.NAME)
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("no-op", r.stdout)

    def test_fresh_clone_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts" / "migrations").mkdir(parents=True)
            mig = _copy_migration(root, self.NAME)  # no zettelkasten/_records
            r = _run(mig)
            self.assertEqual(r.returncode, 0)
            self.assertIn("skipping", r.stdout)


if __name__ == "__main__":
    unittest.main()
