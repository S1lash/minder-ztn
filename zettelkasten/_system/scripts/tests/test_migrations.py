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
import json
import re
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
    return subprocess.run(["bash", str(mig)], capture_output=True, text=True, encoding="utf-8")


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


# ---------------------------------------------------------------------------
# 018 — carrying a previous-shape role across
# ---------------------------------------------------------------------------


class PreviousShapeConfigTests(unittest.TestCase):
    """`_018_plan.listed` reads BOTH YAML list forms.

    Previous-shape `config.yml` files were written by a concierge, not against a
    schema, so `tools: [notion]` and a `- notion` block are both real. Reading
    only the block form made a tool-bearing role look like it used none — and
    its conversion plan then told the owner that no credentials carry across,
    when they do. Silence about a credential is the exact class of miss this
    migration exists to prevent.
    """

    @staticmethod
    def _listed(text: str, key: str = "tools") -> list:
        import sys

        sys.path.insert(0, str(_MIGRATIONS))
        from _018_plan import listed  # type: ignore

        return listed(text, key)

    def test_block_form(self):
        self.assertEqual(self._listed("id: x\ntools:\n  - notion\n  - calendar\n"),
                         ["notion", "calendar"])

    def test_inline_flow_form(self):
        self.assertEqual(self._listed("id: x\ntools: [notion, calendar]\n"),
                         ["notion", "calendar"])

    def test_inline_quoted_items(self):
        self.assertEqual(self._listed("id: x\ntools: ['notion', \"calendar\"]\n"),
                         ["notion", "calendar"])

    def test_empty_forms_are_empty(self):
        for text in ("id: x\ntools: []\n", "id: x\n", "id: x\ntools:\n"):
            with self.subTest(text=text):
                self.assertEqual(self._listed(text), [])

    def test_a_following_key_does_not_leak_into_the_list(self):
        self.assertEqual(
            self._listed("id: x\ntools:\n  - notion\ncadence: daily\n"), ["notion"]
        )

    def test_tool_bearing_role_gets_the_store_names_in_its_plan(self):
        """End-to-end: the plan must name what carries across, in either form."""
        import json
        import sys

        sys.path.insert(0, str(_MIGRATIONS))
        import _018_plan as plan  # type: ignore

        for cfg in ("id: r\ncadence: daily\ntools: [notion]\n",
                    "id: r\ncadence: daily\ntools:\n  - notion\n"):
            with self.subTest(cfg=cfg), tempfile.TemporaryDirectory() as tmp:
                prev = Path(tmp) / "_previous"
                (prev / "r").mkdir(parents=True)
                (prev / "r" / "config.yml").write_text(cfg, encoding="utf-8")
                (prev / "r" / "hooks").mkdir()
                (prev / "r" / "hooks" / "tick.md").write_text("do a thing\n", encoding="utf-8")

                # argv[0] is the program name, as when the shell invokes it.
                plan.main(["_018_plan.py", str(prev), json.dumps(["NOTION_TOKEN"])])

                built = json.loads((prev / "r.plan.json").read_text(encoding="utf-8"))
                self.assertEqual(built["proposed"]["secrets"], ["NOTION_TOKEN"])
                self.assertIn("ZTN_ROLES_KEY", built["proposed"]["secrets_note"])


class _PreviousShapeFixture:
    """A repo holding one previous-shape role, and the helpers to drive it.

    Shared by the 018 and 020 suites as a MIXIN rather than by inheritance:
    a subclass of a TestCase inherits its tests too, and 020 parks nothing on
    its own, so every inherited test would have exercised a no-op while
    reporting green.
    """

    NAME = "018-roles-previous-shape-handoff.sh"

    def _repo(self, tmp: str) -> Path:
        root = _build_repo(tmp)
        shutil.copytree(_REPO_ROOT / "scripts" / "lib", root / "scripts" / "lib")
        for helper in ("_018_handoff.py", "_018_plan.py",
                       "_018_selfcheck.py", "_018_memory.py"):
            shutil.copy(_MIGRATIONS / helper, root / "scripts" / "migrations" / helper)
        _copy_migration(root, self.NAME)
        return root

    @staticmethod
    def _role(root: Path, rid: str, *, parts: dict | None = None,
              decisions: int = 0, rendered: str = "") -> Path:
        d = root / "zettelkasten" / "_system" / "roles" / rid
        (d / "hooks").mkdir(parents=True)
        (d / "config.yml").write_text(
            f"id: {rid}\nname: '{rid}'\ncadence: weekly\ncadence_anchor: monday\n"
            "status: active\nemit_inbox: false\n", encoding="utf-8")
        (d / "hooks" / "tick.md").write_text("следи за доской\n", encoding="utf-8")
        if rendered:
            (d / "state.md").write_text(rendered, encoding="utf-8")
        if decisions:
            (d / "decisions.jsonl").write_text(
                "".join('{"at":"2026-01-0%d"}\n' % (i + 1) for i in range(decisions)),
                encoding="utf-8")
        if parts:
            (d / "parts").mkdir()
            for name, payload in parts.items():
                (d / "parts" / f"{name}.json").write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return d

    def _run(self, root: Path):
        return subprocess.run(["bash", str(root / "scripts" / "migrations" / self.NAME)],
                              cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8")

    @staticmethod
    def _plan(root: Path, rid: str) -> dict:
        return json.loads((root / "zettelkasten" / "_system" / "roles" / "_previous"
                           / f"{rid}.plan.json").read_text(encoding="utf-8"))

    @staticmethod
    def _handoff(root: Path) -> str:
        return (root / "zettelkasten" / "_system" / "roles" / "_previous"
                / "HANDOFF.md").read_text(encoding="utf-8")


class PreviousShapeMemoryTests(_PreviousShapeFixture, unittest.TestCase):
    """018 must carry the memory a role built up, not just its assignment.

    A standing role that ran for months is half assignment and half accumulated
    state — a board of work in flight, a reading of where it stands, a verdict
    per item, a log of what it decided. The previous shape kept that in
    `state.md`, `parts/*.json` and `decisions.jsonl`.

    The migration used to name those files only as proof that the role had run,
    and the conversion plan did not mention them at all. Every byte survived the
    move and nothing pointed at it, so the owner re-created the role from its
    assignment alone and it woke up remembering nothing. Present-but-
    unreferenced is lost in every way that matters to the person who needs it.
    """

    # -- the plan --------------------------------------------------------

    def test_plan_locates_every_piece_of_accumulated_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=7, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": f"k-{i}"} for i in range(19)]},
                "critical": {"part_id": "critical", "archetype": "assessment",
                             "assessments": [{"key": "k-1"}, {"key": "k-2"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)

            mem = self._plan(root, "steward")["memory"]
            self.assertTrue(mem["has_memory"])
            self.assertEqual(mem["rendered"]["path"], "steward/state.md")
            self.assertEqual(mem["decisions"], {"path": "steward/decisions.jsonl",
                                                "count": 7})
            self.assertEqual(mem["records"], 21)
            self.assertEqual(
                {p["id"]: p["holds"][0]["count"] for p in mem["parts"]},
                {"workstreams": 19, "critical": 2})
            self.assertTrue(mem["instruction"])

    def test_every_located_path_actually_exists(self):
        """A pointer that does not resolve is worse than no pointer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=3, parts={
                "purpose": {"part_id": "purpose", "archetype": "narrative",
                            "entries": [{"text": "a"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            parked = root / "zettelkasten" / "_system" / "roles" / "_previous"

            mem = self._plan(root, "steward")["memory"]
            for rel in ([mem["rendered"]["path"], mem["decisions"]["path"]]
                        + [p["path"] for p in mem["parts"]]):
                with self.subTest(rel=rel):
                    self.assertTrue((parked / rel).is_file(), rel)

    def test_unknown_archetype_is_still_counted(self):
        """Counting by SHAPE, not by a list of known key names.

        A role could carry a part archetype this code has never seen. Keying off
        "a list of records" means an unknown one is still counted, rather than
        reported as empty — which would be the same silence in a new costume.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", parts={
                "odd": {"part_id": "odd", "archetype": "something-new",
                        "whatever_it_called_them": [{"a": 1}, {"a": 2}, {"a": 3}]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            mem = self._plan(root, "steward")["memory"]
            self.assertEqual(mem["records"], 3)
            self.assertEqual(mem["parts"][0]["holds"],
                             [{"of": "whatever_it_called_them", "count": 3}])

    def test_a_role_that_never_ran_is_not_dressed_up_as_one_that_did(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "fresh")
            self.assertEqual(self._run(root).returncode, 0)
            mem = self._plan(root, "fresh")["memory"]
            self.assertFalse(mem["has_memory"])
            self.assertEqual(mem["instruction"], "")
            self.assertIn("Накопленной памяти нет", self._handoff(root))

    def test_malformed_part_file_does_not_abort_the_migration(self):
        """The schema is gone; a part file may be anything. Never fatal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            d = self._role(root, "steward", rendered="# board\n")
            (d / "parts").mkdir()
            (d / "parts" / "broken.json").write_text("{not json", encoding="utf-8")
            r = self._run(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            mem = self._plan(root, "steward")["memory"]
            self.assertTrue(mem["has_memory"])
            self.assertEqual(mem["parts"][0]["holds"], [])

    # -- the hand-off ----------------------------------------------------

    def test_handoff_tells_the_owner_the_memory_carries_across(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=7, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": f"k-{i}"} for i in range(19)]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            text = self._handoff(root)
            self.assertIn("workstreams — 19", text)
            self.assertIn("решений в журнале — 7", text)
            self.assertIn("steward/state.md", text)
            self.assertIn("переносится", text)

    # -- the self-check --------------------------------------------------

    def test_selfcheck_fails_when_a_plan_forgets_the_memory(self):
        """The regression guard proper: silence about memory must not pass."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=2, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)

            check = ["python3", str(root / "scripts" / "migrations" / "_018_selfcheck.py")]
            passing = subprocess.run(check, cwd=str(root), capture_output=True,
                                     text=True, encoding="utf-8")
            self.assertEqual(passing.returncode, 0, passing.stdout + passing.stderr)

            plan_path = (root / "zettelkasten" / "_system" / "roles" / "_previous"
                         / "steward.plan.json")
            regressed = json.loads(plan_path.read_text(encoding="utf-8"))
            regressed["memory"] = {"has_memory": True}
            plan_path.write_text(json.dumps(regressed, ensure_ascii=False),
                                 encoding="utf-8")

            failing = subprocess.run(check, cwd=str(root), capture_output=True,
                                     text=True, encoding="utf-8")
            self.assertEqual(failing.returncode, 1)
            self.assertIn("carries the memory it built up", failing.stdout)

    # -- the contract the whole migration rests on -----------------------

    def test_nothing_is_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=4, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
            })
            before = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                      for p in (root / "zettelkasten" / "_system" / "roles"
                                / "steward").rglob("*") if p.is_file()}
            self.assertEqual(self._run(root).returncode, 0)
            after = {p.name: hashlib.md5(p.read_bytes()).hexdigest()
                     for p in (root / "zettelkasten" / "_system" / "roles"
                               / "_previous" / "steward").rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=4, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            first = self._plan(root, "steward")
            second_run = self._run(root)
            self.assertEqual(second_run.returncode, 0)
            self.assertEqual(self._plan(root, "steward"), first)

    def test_a_rerun_heals_a_handoff_and_plan_written_before_the_memory_work(self):
        """The repair has to reach a clone that already ran the older 018.

        A `heal` migration is retried only while it keeps failing; one that
        SUCCEEDED is recorded and never runs again. So the repair reaches an
        already-parked clone on exactly one path — a re-run — and it must leave
        both artifacts current when it takes it. The plans rebuild on every run;
        the hand-off did not, and a generated file left asserting something no
        longer true is the same silence in a quieter form.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=2, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}, {"key": "k-2"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)

            parked = root / "zettelkasten" / "_system" / "roles" / "_previous"
            # Rewind both artifacts to what the pre-repair migration produced.
            stale = json.loads((parked / "steward.plan.json").read_text(encoding="utf-8"))
            stale.pop("memory")
            (parked / "steward.plan.json").write_text(json.dumps(stale, ensure_ascii=False),
                                                      encoding="utf-8")
            (parked / "HANDOFF.md").write_text(
                "# Роли, собранные на прежней форме\n\n## steward\n\n"
                "**Эта роль успела отработать** — рядом лежат `state.md`.\n"
                "Текущий движок их не читает; они твои, смотри при желании.\n",
                encoding="utf-8")

            result = self._run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("hand-off refreshed", result.stdout)

            self.assertEqual(self._plan(root, "steward")["memory"]["records"], 2)
            healed = self._handoff(root)
            self.assertIn("workstreams — 2 зап.", healed)
            self.assertIn("переносится", healed)
            self.assertNotIn("смотри при желании", healed)

            # And it settles: a further run finds nothing left to heal.
            again = self._run(root)
            self.assertEqual(again.returncode, 0)
            self.assertNotIn("hand-off refreshed", again.stdout)
            self.assertEqual(self._handoff(root), healed)

    def test_a_rerun_never_re_parks_or_disturbs_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=2, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            parked = root / "zettelkasten" / "_system" / "roles" / "_previous" / "steward"
            before = {str(p.relative_to(parked)): hashlib.md5(p.read_bytes()).hexdigest()
                      for p in parked.rglob("*") if p.is_file()}
            self.assertEqual(self._run(root).returncode, 0)
            after = {str(p.relative_to(parked)): hashlib.md5(p.read_bytes()).hexdigest()
                     for p in parked.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    # -- point 2: one owner for a path ------------------------------------

    def test_every_path_in_the_handoff_resolves_from_the_repository_root(self):
        """The owner opens the hand-off from the repository root. So must its paths.

        The hand-off used to carry two bases one line apart — a repo-relative
        `<base>/_system/roles/_previous/{id}/` for the role's directory, and a
        bare `_previous/{id}/state.md` for everything the memory work added.
        Both looked right beside the code that wrote each; the second resolved
        nowhere, because the hand-off lives INSIDE `_previous/`. That is a path
        with two owners, and this is the test that keeps it at one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=3, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
                "purpose": {"part_id": "purpose", "archetype": "narrative",
                            "entries": [{"text": "a"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)

            # Fenced blocks first: a ``` fence throws single-backtick pairing
            # off for everything after it, and the scan then reports zero paths
            # on a hand-off full of them — a green test proving nothing.
            body = re.sub(r"```.*?```", "", self._handoff(root), flags=re.DOTALL)
            quoted = re.findall(r"`([^`\n]+)`", body)
            paths = [q for q in quoted if "_previous/" in q]
            self.assertTrue(paths, "the hand-off names no parked path at all")
            for rel in paths:
                with self.subTest(path=rel):
                    self.assertTrue((root / rel).exists(), f"dead path in HANDOFF.md: {rel}")

    # -- point 3: memory means content, not the presence of a file --------

    def test_empty_part_files_are_not_reported_as_accumulated_memory(self):
        """The previous shape wrote empty part files on a tick that found nothing.

        Keying `has_memory` off «the file exists» made such a role announce that
        it «успела наработать память» and then list nothing — and let the
        self-check wave it through as carried, which is the same false all-clear
        in a smaller costume.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            d = self._role(root, "quiet", parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": []},
                "purpose": {"part_id": "purpose", "archetype": "narrative",
                            "entries": []},
            })
            (d / "state.md").write_text("\n\n", encoding="utf-8")
            (d / "decisions.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(self._run(root).returncode, 0)

            mem = self._plan(root, "quiet")["memory"]
            self.assertFalse(mem["has_memory"])
            self.assertEqual(mem["records"], 0)
            self.assertEqual(mem["instruction"], "")
            # The files are still reported as present — the inventory is factual.
            self.assertEqual(mem["rendered"]["chars"], 0)
            self.assertEqual(mem["decisions"]["count"], 0)
            self.assertIn("Накопленной памяти нет", self._handoff(root))

    def test_one_real_record_anywhere_is_memory(self):
        """The floor is content, and one record of it clears the floor."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "barely", parts={
                "purpose": {"part_id": "purpose", "archetype": "narrative",
                            "entries": [{"text": "a"}]},
            })
            self.assertEqual(self._run(root).returncode, 0)
            self.assertTrue(self._plan(root, "barely")["memory"]["has_memory"])

    # -- point 1: the plan is a view, rebuildable by its consumer ---------

    def test_the_plan_builder_runs_standalone_and_finds_the_credentials_itself(self):
        """`/ztn:role:add --from-previous` rebuilds the plan before reading it.

        That is what removes the «this artifact was written before we knew
        better» class rather than one instance of it: a migration records itself
        applied and never runs again, so a plan trusted from disk can be
        arbitrarily old. It therefore has to work from the parked directory
        alone — including reading the credential store, which used to be the
        calling shell's job and so had two owners.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            zk = root / "zettelkasten"
            (zk / "_system" / "state").mkdir(parents=True, exist_ok=True)
            (zk / "_system" / "state" / "secrets.enc.json").write_text(
                json.dumps({"NOTION_TOKEN": "ciphertext"}), encoding="utf-8")
            d = self._role(root, "outward", rendered="# board\n")
            (d / "config.yml").write_text(
                "id: outward\nname: 'Outward'\ncadence: weekly\nstatus: active\n"
                "tools: [notion]\n", encoding="utf-8")
            self.assertEqual(self._run(root).returncode, 0)

            parked = zk / "_system" / "roles" / "_previous"
            (parked / "outward.plan.json").write_text('{"stale": true}\n', encoding="utf-8")

            rebuilt = subprocess.run(
                ["python3", str(root / "scripts" / "migrations" / "_018_plan.py"),
                 str(parked)],
                cwd=str(root), capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)

            plan = self._plan(root, "outward")
            self.assertNotIn("stale", plan)
            self.assertEqual(plan["proposed"]["secrets"], ["NOTION_TOKEN"])
            self.assertTrue(plan["memory"]["has_memory"])


class Migration020Tests(_PreviousShapeFixture, unittest.TestCase):
    """020 is how the repair reaches a clone that already applied 018.

    `heal` retries a migration that keeps FAILING; one recorded `applied` never
    runs again, of any kind. So 018's own improvement is unreachable for every
    clone that already ran it, and the ledger is the only mechanism that reaches
    them — which means a new entry.

    Takes the fixture as a mixin, so it inherits no test: 020 parks nothing on
    its own, and an inherited 018 test would exercise a no-op while reporting
    green.
    """

    NAME = "020-roles-previous-shape-memory.sh"

    def _repo(self, tmp: str) -> Path:
        root = super()._repo(tmp)
        _copy_migration(root, "018-roles-previous-shape-handoff.sh")
        return root

    def _run_018(self, root: Path):
        return subprocess.run(
            ["bash", str(root / "scripts" / "migrations"
                         / "018-roles-previous-shape-handoff.sh")],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8")

    def test_it_heals_a_clone_that_already_applied_018(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=2, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}, {"key": "k-2"}]},
            })
            self.assertEqual(self._run_018(root).returncode, 0)

            # Rewind both artifacts to what the pre-repair 018 left behind, and
            # record 018 applied — the exact state of a clone that took 0.54.0.
            parked = root / "zettelkasten" / "_system" / "roles" / "_previous"
            stale = json.loads((parked / "steward.plan.json").read_text(encoding="utf-8"))
            stale.pop("memory")
            (parked / "steward.plan.json").write_text(json.dumps(stale, ensure_ascii=False),
                                                      encoding="utf-8")
            (parked / "HANDOFF.md").write_text(
                "# Роли, собранные на прежней форме\n\n## steward\n\n"
                "**Эта роль успела отработать** — рядом лежат `state.md`.\n"
                "Текущий движок их не читает; они твои, смотри при желании.\n",
                encoding="utf-8")
            (root / ".engine-migrations-applied").write_text(
                "018-roles-previous-shape-handoff.sh\n", encoding="utf-8")

            result = self._run(root)
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(self._plan(root, "steward")["memory"]["records"], 2)
            healed = self._handoff(root)
            self.assertIn("workstreams — 2 зап.", healed)
            self.assertNotIn("смотри при желании", healed)

    def test_it_is_reached_by_the_runner_on_a_clone_that_already_applied_018(self):
        """The mechanism, not just the script: 020 must be PENDING there.

        This is the check that would have caught the original mistake — a repair
        placed in a branch the ledger can never execute.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            shutil.copy(_REPO_ROOT / "scripts" / "run_migrations.py",
                        root / "scripts" / "run_migrations.py")
            self._role(root, "steward", rendered="# board\n")
            self.assertEqual(self._run_018(root).returncode, 0)
            (root / ".engine-migrations-applied").write_text(
                "018-roles-previous-shape-handoff.sh\n", encoding="utf-8")

            listed = subprocess.run(
                ["python3", str(root / "scripts" / "run_migrations.py"),
                 "--dry-run", "--json"],
                cwd=str(root), capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            names = [r["name"] for r in json.loads(listed.stdout)["ran"]]
            self.assertIn(self.NAME, names)
            self.assertNotIn("018-roles-previous-shape-handoff.sh", names)

    def test_it_says_so_and_exits_clean_on_a_clone_that_never_had_a_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            result = self._run(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("nothing to refresh", result.stdout)

    def test_it_settles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._role(root, "steward", rendered="# board\n", decisions=1, parts={
                "workstreams": {"part_id": "workstreams", "archetype": "ledger",
                                "items": [{"key": "k-1"}]},
            })
            self.assertEqual(self._run_018(root).returncode, 0)
            self.assertEqual(self._run(root).returncode, 0)
            first = self._handoff(root), self._plan(root, "steward")
            self.assertEqual(self._run(root).returncode, 0)
            self.assertEqual((self._handoff(root), self._plan(root, "steward")), first)
