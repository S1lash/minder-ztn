"""Tests for _common parsing & validation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests._fixture import (  # type: ignore
    BAD_ENUM,
    BAD_ID_SHAPE,
    MALFORMED_YAML,
    VALID_NOTE,
    VALID_PERSONAL_NOTE,
    VALID_SENSITIVE_NOTE,
    clear_ztn_env,
    make_fixture,
)
import _common as c  # type: ignore


class ParseFileTests(unittest.TestCase):
    def test_valid_note_parses_all_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            p = c.parse_file(md)
            self.assertEqual(p.id, "axiom-identity-001")
            self.assertEqual(p.type, "axiom")
            self.assertTrue(p.is_core)
            self.assertEqual(p.scope, "shared")
            self.assertIn("claude-code", p.applies_to)
        clear_ztn_env()

    def test_missing_required_raises_schema_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/002.md", MALFORMED_YAML)
            with self.assertRaises(c.SchemaError):
                c.parse_file(md)
        clear_ztn_env()

    def test_bad_enum_value_raises_schema_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/003.md", BAD_ENUM)
            with self.assertRaises(c.SchemaError):
                c.parse_file(md)
        clear_ztn_env()

    def test_bad_id_shape_raises_schema_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/004.md", BAD_ID_SHAPE)
            with self.assertRaises(c.SchemaError):
                c.parse_file(md)
        clear_ztn_env()

    def test_no_frontmatter_raises_parse_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/005.md", "# no frontmatter\njust markdown\n")
            with self.assertRaises(c.ParseError):
                c.parse_file(md)
        clear_ztn_env()


class IterPrinciplesTests(unittest.TestCase):
    def test_ignores_constitution_md_and_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            # Top-level protocol doc — must be skipped
            (fx.constitution / "CONSTITUTION.md").write_text("# proto")
            fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            principles = c.iter_principles(fx.constitution)
            self.assertEqual(len(principles), 1)
            self.assertEqual(principles[0].id, "axiom-identity-001")
        clear_ztn_env()

    def test_deterministic_ordering_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            fx.write_principle("principle/tech/001.md", VALID_PERSONAL_NOTE)
            fx.write_principle("rule/health/001.md", VALID_SENSITIVE_NOTE)
            principles = c.iter_principles(fx.constitution)
            self.assertEqual(
                [p.id for p in principles],
                sorted([p.id for p in principles]),
            )
        clear_ztn_env()

    def test_duplicate_id_across_files_fails(self):
        """Two files with the same `id` is a real bug (copy-paste mistake)."""
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            # Second file with same id but different path
            fx.write_principle("axiom/identity/002.md", VALID_NOTE)
            with self.assertRaises(c.SchemaError) as ctx:
                c.iter_principles(fx.constitution)
            self.assertIn("duplicate id", str(ctx.exception))
        clear_ztn_env()

    def test_unicode_title_and_statement_preserved(self):
        """Russian text in title / statement must round-trip cleanly."""
        ru_note = (
            "---\n"
            "id: axiom-identity-001\n"
            "title: Качество — форма уважения к себе и к миру\n"
            "type: axiom\n"
            "domain: identity\n"
            "statement: Выбирай путь качества, когда система переживёт решение.\n"
            "priority_tier: 1\n"
            "scope: shared\n"
            "applies_to: [claude-code]\n"
            "status: active\n"
            "created: 2026-01-01\n"
            "---\n\n"
            "# Title\n\n"
            "## Evidence Trail\n"
            "- **2026-01-01** | landing | — seeded\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/001.md", ru_note)
            p = c.parse_file(md)
            self.assertIn("Качество", p.title)
            self.assertIn("Выбирай", p.statement)
        clear_ztn_env()

    def test_symlinks_are_skipped(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            real = fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            link = fx.constitution / "axiom" / "identity" / "002-symlink.md"
            os.symlink(real, link)
            principles = c.iter_principles(fx.constitution)
            # Only the real file, symlink skipped
            self.assertEqual(len(principles), 1)
        clear_ztn_env()


class VisibilityTests(unittest.TestCase):
    def test_all_scopes_visible_constant(self):
        """Single-context model: three scopes, all visible."""
        self.assertEqual(
            c.ALL_SCOPES_VISIBLE,
            frozenset({"shared", "personal", "sensitive"}),
        )

    def test_is_visible_excludes_archived_and_placeholder(self):
        """Default exclusion: archived + placeholder never visible."""
        import tempfile
        from tests._fixture import VALID_NOTE  # type: ignore
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            p = c.parse_file(md)
            self.assertTrue(c.is_visible(p, consumer="claude-code"))
            # Simulate a placeholder by using allow_statuses
            placeholder = VALID_NOTE.replace("status: active", "status: placeholder")
            md2 = fx.write_principle("axiom/ethics/001.md",
                                     placeholder.replace("axiom-identity-001", "axiom-ethics-001")
                                                .replace("domain: identity", "domain: ethics"))
            p2 = c.parse_file(md2)
            self.assertFalse(c.is_visible(p2, consumer="claude-code"))
            self.assertTrue(c.is_visible(p2, consumer="claude-code",
                                          allow_statuses={"placeholder"}))
        clear_ztn_env()

    def test_is_visible_respects_applies_to(self):
        """Consumer filter uses applies_to inclusion."""
        import tempfile
        from tests._fixture import VALID_NOTE  # type: ignore
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            md = fx.write_principle("axiom/identity/001.md", VALID_NOTE)
            p = c.parse_file(md)
            self.assertTrue(c.is_visible(p, consumer="claude-code"))
            self.assertFalse(c.is_visible(p, consumer="minder"))
        clear_ztn_env()


class SoulMarkersTests(unittest.TestCase):
    def test_finds_bounds_when_markers_present(self):
        text = (
            "before\n"
            f"{c.SOUL_MARKER_START}\n"
            "auto-content\n"
            f"{c.SOUL_MARKER_END}\n"
            "after\n"
        )
        bounds = c.find_soul_auto_zone(text)
        self.assertIsNotNone(bounds)
        start, end = bounds
        self.assertEqual(text[start:end], "auto-content\n")

    def test_none_when_markers_missing(self):
        self.assertIsNone(c.find_soul_auto_zone("no markers here"))


if __name__ == "__main__":
    unittest.main()
