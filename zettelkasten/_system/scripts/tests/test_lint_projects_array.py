"""Tests for lint_projects_array.py — Scan A.8 projects-array drift.

Focus: the existence check resolves a project ID to a PROJECTS.md row OR a
hub file (OR semantics), so a registered project without a hub yet is not a
false `projects-array-unknown-id`. Also covers the PROJECTS.md parser
(section exclusions, placeholder rows) and safe degradation.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import lint_projects_array as lp  # type: ignore


def _scaffold(root: Path) -> None:
    for sub in (
        "_records/meetings", "1_projects", "2_areas", "3_resources",
        "4_archive", "5_meta/mocs",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _write_projects_md(root: Path, body: str) -> None:
    (root / "1_projects" / "PROJECTS.md").write_text(body, encoding="utf-8")


def _write_note(root: Path, name: str, projects: list[str]) -> Path:
    arr = "".join(f"  - {p}\n" for p in projects)
    path = root / "_records" / "meetings" / name
    path.write_text(
        f"---\nid: {name}\nprojects:\n{arr}---\nbody\n", encoding="utf-8"
    )
    return path


def _write_hub(root: Path, slug: str, hub_kind: str | None = None) -> None:
    fm = f"hub_kind: {hub_kind}\n" if hub_kind else ""
    (root / "5_meta" / "mocs" / f"hub-{slug}.md").write_text(
        f"---\n{fm}---\nhub\n", encoding="utf-8"
    )


_REGISTRY = """# Project Registry

## Active Projects

| ID | Name | Description | Folder | Status |
|----|------|-------------|--------|--------|
| alpha-app | Alpha | desc | 1_projects/alpha-app/ | active |
| beta-service | Beta | desc | 1_projects/beta-service/ | active |

## Trajectories (not projects)

| ID | Name | Hub | Status |
|----|------|-----|--------|
| growth-arc | Growth arc | [[hub-growth-arc]] | active |

## Consolidated / superseded

| Old ID | Status | Now part of |
|--------|--------|-------------|
| legacy-thing | consolidated | [[hub-alpha-app]] |

## Archived Projects

| ID | Name | Description | Folder | Status | Archived | Reason |
|----|------|-------------|--------|--------|----------|--------|
| _(empty)_ | | | | | | |

## Project Template

| ID | placeholder |
|----|-------------|
| project-id | example |
"""


def _run(root: Path) -> list[dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        lp.main(["--root", str(root)])
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


class LoadProjectIdsTests(unittest.TestCase):
    def test_parses_active_and_archived_excludes_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            ids = lp._load_project_ids(root)
            self.assertEqual(ids, {"alpha-app", "beta-service"})
            # excluded: trajectory, consolidated, template, placeholders
            self.assertNotIn("growth-arc", ids)
            self.assertNotIn("legacy-thing", ids)
            self.assertNotIn("project-id", ids)

    def test_missing_registry_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            self.assertEqual(lp._load_project_ids(root), set())


class ExistenceCheckTests(unittest.TestCase):
    def test_registered_project_without_hub_is_clean(self):
        # The bug: a real project in PROJECTS.md but no hub yet was flagged
        # as unknown-id every night. Must be silent now.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            _write_note(root, "n.md", ["alpha-app"])
            kinds = {e["kind"] for e in _run(root)}
            self.assertNotIn("projects-array-unknown-id", kinds)

    def test_hub_without_registry_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            _write_hub(root, "orphan-hub")
            _write_note(root, "n.md", ["orphan-hub"])
            kinds = {e["kind"] for e in _run(root)}
            self.assertNotIn("projects-array-unknown-id", kinds)

    def test_neither_registry_nor_hub_flags_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            _write_note(root, "n.md", ["ghost-typo"])
            events = [e for e in _run(root)
                      if e["kind"] == "projects-array-unknown-id"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["project_id"], "ghost-typo")

    def test_trajectory_with_hub_still_flagged_by_kind(self):
        # growth-arc is excluded from the registry set, but its hub is
        # hub_kind=trajectory → the kind check must still surface it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            _write_hub(root, "growth-arc", hub_kind="trajectory")
            _write_note(root, "n.md", ["growth-arc"])
            kinds = {e["kind"] for e in _run(root)}
            self.assertIn("projects-array-non-project-hub", kinds)
            self.assertNotIn("projects-array-unknown-id", kinds)

    def test_degrades_to_hub_only_without_registry(self):
        # No PROJECTS.md → empty id set → existence falls back to hub-only
        # (prior behaviour). A project with a hub is still clean; one
        # without is flagged.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_hub(root, "has-hub")
            _write_note(root, "a.md", ["has-hub"])
            _write_note(root, "b.md", ["no-hub"])
            kinds_by_note = {
                e["note_id"]: e["kind"] for e in _run(root)
                if e["kind"] == "projects-array-unknown-id"
            }
            self.assertNotIn("a.md", kinds_by_note)
            self.assertIn("b.md", kinds_by_note)


if __name__ == "__main__":
    unittest.main()
