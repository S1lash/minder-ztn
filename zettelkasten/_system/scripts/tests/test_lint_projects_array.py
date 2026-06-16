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
    # Real hubs always carry frontmatter (id, title, …); an `id` keeps the
    # block non-empty so an absent hub_kind reads as "field absent → default
    # project" rather than "malformed frontmatter".
    fm = f"id: hub-{slug}\n"
    if hub_kind:
        fm += f"hub_kind: {hub_kind}\n"
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


class LoadProjectRegistryTests(unittest.TestCase):
    def test_categorises_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            reg = lp._load_project_registry(root)
            self.assertEqual(reg["project"], {"alpha-app", "beta-service"})
            self.assertEqual(reg["trajectory"], {"growth-arc"})
            self.assertEqual(reg["consolidated"], {"legacy-thing"})
            # template + placeholder rows leak into no category
            for cat in reg.values():
                self.assertNotIn("project-id", cat)

    def test_missing_registry_returns_empty_cats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            reg = lp._load_project_registry(root)
            self.assertEqual(reg, {c: set() for c in lp.REGISTRY_CATEGORIES})


class ResolutionTests(unittest.TestCase):
    """A.8 resolves every projects: entry against PROJECTS.md (single SoT)."""

    def _kinds_for(self, projects, *, hubs=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_projects_md(root, _REGISTRY)
            for slug, kind in (hubs or {}).items():
                _write_hub(root, slug, hub_kind=kind)
            _write_note(root, "n.md", projects)
            return [e for e in _run(root) if "project_id" in e]

    def test_registered_project_clean_with_or_without_hub(self):
        # Registered project needs no hub — the friend's fresh-install case.
        self.assertEqual(self._kinds_for(["alpha-app"]), [])
        self.assertEqual(
            self._kinds_for(["beta-service"], hubs={"beta-service": None}), []
        )

    def test_registered_trajectory_flagged_non_project(self):
        ev = self._kinds_for(["growth-arc"])
        self.assertEqual([e["kind"] for e in ev], ["projects-array-non-project"])

    def test_consolidated_id_flagged(self):
        ev = self._kinds_for(["legacy-thing"])
        self.assertEqual(
            [e["kind"] for e in ev], ["projects-array-consolidated"]
        )

    def test_orphan_project_hub_flagged(self):
        # THE GAP this change closes: a hub_kind=project hub whose slug is
        # not registered is drift — a hub vouches for nothing.
        ev = self._kinds_for(["ghost-proj"], hubs={"ghost-proj": "project"})
        self.assertEqual(
            [e["kind"] for e in ev], ["projects-array-orphan-hub"]
        )

    def test_orphan_default_kind_hub_is_project(self):
        # hub_kind absent defaults to project → still orphan when unregistered.
        ev = self._kinds_for(["ghost-default"], hubs={"ghost-default": None})
        self.assertEqual(
            [e["kind"] for e in ev], ["projects-array-orphan-hub"]
        )

    def test_unregistered_non_project_hub(self):
        ev = self._kinds_for(["some-domain"], hubs={"some-domain": "domain"})
        self.assertEqual(
            [e["kind"] for e in ev], ["projects-array-non-project-hub"]
        )

    def test_unknown_id_no_hub(self):
        ev = self._kinds_for(["ghost-typo"])
        self.assertEqual([e["kind"] for e in ev], ["projects-array-unknown-id"])


class DegradationTests(unittest.TestCase):
    def test_empty_registry_skips_resolution(self):
        # No PROJECTS.md → SoT absent → resolution skipped entirely (a friend
        # mid-setup must not be flooded). Length check is unaffected.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_hub(root, "has-hub", hub_kind="project")
            _write_note(root, "a.md", ["has-hub"])
            _write_note(root, "b.md", ["no-hub"])
            ev = [e for e in _run(root) if "project_id" in e]
            self.assertEqual(ev, [])

    def test_length_check_runs_without_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_note(root, "c.md", ["a", "b", "c"])  # 3 → overcount
            kinds = {e["kind"] for e in _run(root)}
            self.assertIn("projects-array-overcount", kinds)


if __name__ == "__main__":
    unittest.main()
