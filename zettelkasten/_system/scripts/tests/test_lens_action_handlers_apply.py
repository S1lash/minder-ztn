"""Tests for lens_action_handlers apply_* implementations."""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

import lens_action_handlers as h  # type: ignore


def _make_base(tmp: Path) -> Path:
    base = tmp / "zettelkasten"
    for sub in (
        "_records/meetings",
        "1_projects",
        "2_areas/personal",
        "2_areas/work",
        "5_meta/mocs",
        "_system/state",
    ):
        (base / sub).mkdir(parents=True)
    (base / "_system/state/OPEN_THREADS.md").write_text(
        "---\nid: open-threads\nlayer: system\n---\n\n# Open Threads\n\n## Active\n\n_(empty)_\n\n---\n\n## Resolved\n\n_(empty)_\n",
        encoding="utf-8",
    )
    return base


class WikilinkApplyTests(unittest.TestCase):
    def test_creates_section_when_absent_and_links_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "2_areas/personal/a.md").write_text("# A\n\nbody\n", encoding="utf-8")
            (base / "2_areas/work/b.md").write_text("# B\n\nbody\n", encoding="utf-8")
            out = h.apply_wikilink_add(
                {"note_a": "2_areas/personal/a.md", "note_b": "2_areas/work/b.md"},
                source_lens="cross-domain-bridge/2026-05-04",
                base=base,
            )
            self.assertTrue(out["success"])
            self.assertTrue(out["applied"])
            a_text = (base / "2_areas/personal/a.md").read_text(encoding="utf-8")
            b_text = (base / "2_areas/work/b.md").read_text(encoding="utf-8")
            self.assertIn("## Связи (auto)", a_text)
            self.assertIn("[[b]]", a_text)
            self.assertIn("from_lens: cross-domain-bridge/2026-05-04", a_text)
            self.assertIn("[[a]]", b_text)

    def test_appends_inside_existing_auto_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "2_areas/personal/a.md").write_text(
                "# A\n\nbody\n\n## Связи (auto)\n\n- [[old]] <!-- from_lens: x/2026-01-01 -->\n",
                encoding="utf-8",
            )
            (base / "2_areas/work/b.md").write_text("# B\n", encoding="utf-8")
            h.apply_wikilink_add(
                {"note_a": "2_areas/personal/a.md", "note_b": "2_areas/work/b.md"},
                source_lens="cross-domain-bridge/2026-05-04",
                base=base,
            )
            a_text = (base / "2_areas/personal/a.md").read_text(encoding="utf-8")
            self.assertEqual(a_text.count("## Связи (auto)"), 1)
            self.assertIn("[[old]]", a_text)
            self.assertIn("[[b]]", a_text)


class HubStubApplyTests(unittest.TestCase):
    def test_creates_hub_with_frontmatter_and_back_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "2_areas/personal/n1.md").write_text("# N1\n", encoding="utf-8")
            (base / "2_areas/personal/n2.md").write_text("# N2\n", encoding="utf-8")
            (base / "2_areas/personal/n3.md").write_text("# N3\n", encoding="utf-8")
            out = h.apply_hub_stub_create(
                {"suggested_slug": "hub-test-cluster",
                 "cited_notes": [
                     "2_areas/personal/n1.md",
                     "2_areas/personal/n2.md",
                     "2_areas/personal/n3.md",
                 ]},
                source_lens="knowledge-emergence/2026-05-04",
                base=base,
            )
            self.assertTrue(out["success"])
            hub_path = base / "5_meta/mocs/hub-test-cluster.md"
            self.assertTrue(hub_path.is_file())
            hub_text = hub_path.read_text(encoding="utf-8")
            self.assertTrue(hub_text.startswith("---\n"))
            self.assertIn("id: hub-test-cluster", hub_text)
            self.assertIn("layer: hub", hub_text)
            self.assertIn("hub_kind: domain", hub_text)
            self.assertIn("from_lens: knowledge-emergence/2026-05-04", hub_text)
            self.assertIn("origin: personal", hub_text)
            self.assertIn("audience_tags: []", hub_text)
            self.assertIn("is_sensitive: false", hub_text)
            self.assertIn("## Что объединяет", hub_text)
            self.assertIn("## Заметки", hub_text)
            self.assertIn("[[n1]]", hub_text)
            self.assertIn("[[n2]]", hub_text)
            self.assertIn("[[n3]]", hub_text)
            for n in ("n1", "n2", "n3"):
                back = (base / f"2_areas/personal/{n}.md").read_text(encoding="utf-8")
                self.assertIn("[[hub-test-cluster]]", back)

    def test_strips_optional_hub_prefix_from_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "2_areas/personal/n1.md").write_text("# N1\n", encoding="utf-8")
            h.apply_hub_stub_create(
                {"suggested_slug": "hub-noprefix-test", "cited_notes": ["2_areas/personal/n1.md"]},
                source_lens="x/2026-05-04",
                base=base,
            )
            self.assertTrue((base / "5_meta/mocs/hub-noprefix-test.md").is_file())
            self.assertFalse((base / "5_meta/mocs/hub-hub-noprefix-test.md").exists())


class OpenThreadApplyTests(unittest.TestCase):
    def test_replaces_empty_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "_records/meetings/m.md").write_text("# m\n", encoding="utf-8")
            h.apply_open_thread_add(
                {"thread_title": "X stalls",
                 "cited_records": ["_records/meetings/m.md"],
                 "priority": "high"},
                source_lens="stalled-thread/2026-05-04",
                base=base,
            )
            text = (base / "_system/state/OPEN_THREADS.md").read_text(encoding="utf-8")
            self.assertNotIn("_(empty)_", text.split("## Resolved")[0])
            self.assertIn("X stalls", text)
            self.assertIn("priority high", text)
            self.assertIn("from_lens: stalled-thread/2026-05-04", text)

    def test_appends_when_active_section_already_has_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "_records/meetings/m.md").write_text("# m\n", encoding="utf-8")
            (base / "_system/state/OPEN_THREADS.md").write_text(
                "# Open Threads\n\n## Active\n\n- existing thread\n\n---\n\n## Resolved\n\n_(empty)_\n",
                encoding="utf-8",
            )
            h.apply_open_thread_add(
                {"thread_title": "Another", "cited_records": ["_records/meetings/m.md"]},
                source_lens="stalled-thread/2026-05-04",
                base=base,
            )
            text = (base / "_system/state/OPEN_THREADS.md").read_text(encoding="utf-8")
            self.assertIn("- existing thread", text)
            self.assertIn("Another", text)


class DecisionUpdateApplyTests(unittest.TestCase):
    def test_appends_today_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = _make_base(Path(tmp))
            (base / "1_projects/decision-x.md").write_text(
                "# Decision X\n\nbody\n",
                encoding="utf-8",
            )
            h.apply_decision_update_section(
                {"decision_note_path": "1_projects/decision-x.md",
                 "update_reason": "two records disconfirm assumption A"},
                source_lens="decision-review/2026-05-04",
                base=base,
            )
            text = (base / "1_projects/decision-x.md").read_text(encoding="utf-8")
            today = date.today().isoformat()
            self.assertIn(f"## Update {today}", text)
            self.assertIn("**Reason:** two records disconfirm assumption A", text)
            self.assertIn("from_lens: decision-review/2026-05-04", text)


if __name__ == "__main__":
    unittest.main()
