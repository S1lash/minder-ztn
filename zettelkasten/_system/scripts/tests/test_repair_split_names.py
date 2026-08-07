"""Tests for repair_split_names — recovering a slash-split inbox item name.

A producer names an export after the recording's title, and a title can contain
`/`. No filesystem accepts that in a name, so one segment becomes two nested
directories and the item arrives a level deeper than its layout says.
`normalize_portable_name` cannot reach it — it works on a NAME, and both
resulting segments are perfectly legal names.

The join is autonomous ONLY for the unambiguous shape. These tests hold both
halves: that the unambiguous case is recovered, and that every ambiguous one is
left exactly where it is.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import repair_split_names as r  # type: ignore


# A minimal registry in the shape `SOURCES.md` really has. Scope comes from
# here, never from the code: `Layout` decides whether an autonomous join is even
# possible, and `Skip Subdirs` marks folders the repair must not enter.
_SOURCES_MD = """# Sources Registry

## Active Sources

| ID | Inbox Path | Family | Layout | Default Domain | Skip Subdirs | Description | Status |
|---|---|---|---|---|---|---|---|
| plaud | `_sources/inbox/plaud/` | transcript | dir-with-summary | auto | — | x | active |
| notes | `_sources/inbox/notes/` | transcript | flat-md | auto | — | x | active |
| garmin | `_sources/inbox/garmin/` | metric-day | flat-md | health | raw | x | active |
"""


def _base(tmp: str) -> Path:
    """A base laid out as the engine expects: `<base>/_sources/inbox`, `<base>/_system`."""
    base = Path(tmp) / "zettelkasten"
    (base / "_system" / "registries").mkdir(parents=True)
    (base / "_system" / "registries" / "SOURCES.md").write_text(_SOURCES_MD, encoding="utf-8")
    (base / "_sources" / "inbox" / "plaud").mkdir(parents=True)
    return base


def _inbox(tmp: str) -> Path:
    return _base(tmp) / "_sources" / "inbox"


def _item(path: Path, marker: str = "transcript_with_summary.md") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / marker).write_text("body\n", encoding="utf-8")
    return path


class DetectionTests(unittest.TestCase):
    def test_split_name_is_detected_and_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "plaud" / "07-09 Встреча - A" / "B-тест вкладок")

            found = r.find_candidates(inbox)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["verdict"], "join")
            self.assertEqual(found[0]["target"], "plaud/07-09 Встреча - A-B-тест вкладок")

            r.apply_joins(inbox, found)
            self.assertTrue(
                (inbox / "plaud" / "07-09 Встреча - A-B-тест вкладок"
                 / "transcript_with_summary.md").is_file()
            )
            self.assertFalse((inbox / "plaud" / "07-09 Встреча - A").exists())

    def test_ordinary_item_folder_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "plaud" / "2026-07-09T10-00-00Z")
            self.assertEqual(r.find_candidates(inbox), [])

    def test_flat_md_source_produces_no_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            (inbox / "notes").mkdir()
            (inbox / "notes" / "a.md").write_text("x\n", encoding="utf-8")
            self.assertEqual(r.find_candidates(inbox), [])


class RegistryScopeTests(unittest.TestCase):
    """Scope is the registry's to declare — the repair never decides it itself."""

    def test_skip_subdirs_is_never_entered(self):
        """`garmin/raw/` holds payloads declared out of the queue. Moving anything
        out of it would be a repair reaching past a boundary the owner declared."""
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "garmin" / "raw" / "2026-05", "day.md")
            self.assertEqual(r.find_candidates(inbox), [])

    def test_flat_md_folder_is_surfaced_never_joined(self):
        """A folder under a file-item layout may be the owner's own organisation."""
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "notes" / "some folder", "a.md")
            found = r.find_candidates(inbox)
            self.assertEqual([c["verdict"] for c in found], ["surface"])
            r.apply_joins(inbox, found)
            self.assertTrue((inbox / "notes" / "some folder").is_dir())

    def test_unknown_source_is_surfaced_never_joined(self):
        """An absent registry row means unknown scope — fail towards asking."""
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "brand-new-source" / "A" / "B")
            found = r.find_candidates(inbox)
            self.assertEqual([c["verdict"] for c in found], ["surface"])

    def test_unreadable_registry_joins_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "plaud" / "A" / "B")
            found = r.find_candidates(inbox, registry={})
            self.assertEqual([c["verdict"] for c in found], ["surface"])


class AmbiguityTests(unittest.TestCase):
    """Inside a folder layout, every shape but the unambiguous one is surfaced."""

    def test_two_children_is_surfaced_not_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            parent = inbox / "plaud" / "ambiguous"
            _item(parent / "x", "transcript.md")
            _item(parent / "y", "transcript.md")

            found = r.find_candidates(inbox)
            self.assertEqual(found[0]["verdict"], "surface")
            r.apply_joins(inbox, found)
            self.assertTrue((parent / "x").is_dir(), "nothing moves on an ambiguous shape")

    def test_single_child_that_is_not_an_item_is_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            (inbox / "plaud" / "parent" / "child" / "deeper").mkdir(parents=True)
            found = r.find_candidates(inbox)
            self.assertEqual(found[0]["verdict"], "surface")
            self.assertIn("not a complete item", found[0]["reason"])

    def test_existing_target_is_surfaced_never_suffixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "plaud" / "A" / "B")
            _item(inbox / "plaud" / "A-B")
            found = [c for c in r.find_candidates(inbox) if c["parent"] == "plaud/A"]
            self.assertEqual(found[0]["verdict"], "surface")
            self.assertIn("already exists", found[0]["reason"])

    def test_empty_folder_is_not_a_split_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            (inbox / "plaud" / "empty").mkdir()
            self.assertEqual(r.find_candidates(inbox), [])

    def test_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = _inbox(tmp)
            _item(inbox / "plaud" / "A" / "B")
            r.apply_joins(inbox, r.find_candidates(inbox))
            second = r.find_candidates(inbox)
            self.assertEqual(second, [])
            self.assertEqual(r.apply_joins(inbox, second), [])

    def test_join_uses_the_same_character_as_portable_normalisation(self):
        """A recovered name equals what the normaliser would have made of the original."""
        from _common import normalize_portable_name  # type: ignore

        self.assertEqual(normalize_portable_name("A/B"), f"A{r.JOIN}B")

    def test_missing_inbox_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(r.find_candidates(Path(tmp) / "nope"), [])


if __name__ == "__main__":
    unittest.main()
