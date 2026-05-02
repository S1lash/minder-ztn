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


class NormalizeConceptNameTests(unittest.TestCase):
    """CONCEPT_NAMING.md autonomous heuristic — happy + edge cases."""

    def test_passthrough_canonical(self):
        self.assertEqual(c.normalize_concept_name("team_restructuring"),
                         "team_restructuring")

    def test_kebab_to_snake(self):
        self.assertEqual(c.normalize_concept_name("team-restructuring"),
                         "team_restructuring")

    def test_uppercase_to_lower(self):
        self.assertEqual(c.normalize_concept_name("Team-Restructuring"),
                         "team_restructuring")

    def test_em_dash_separator(self):
        self.assertEqual(c.normalize_concept_name("team — restructuring"),
                         "team_restructuring")

    def test_diacritic_fold(self):
        self.assertEqual(c.normalize_concept_name("naïve_bayes"),
                         "naive_bayes")

    def test_drops_non_ascii_residue(self):
        self.assertIsNone(c.normalize_concept_name("тема"))

    def test_strips_forbidden_type_prefix(self):
        self.assertEqual(c.normalize_concept_name("theme_queue_prioritization"),
                         "queue_prioritization")

    def test_drops_when_only_type_prefix(self):
        self.assertIsNone(c.normalize_concept_name("theme_"))

    def test_drops_when_empty_after_strip(self):
        self.assertIsNone(c.normalize_concept_name(""))
        self.assertIsNone(c.normalize_concept_name("   "))
        self.assertIsNone(c.normalize_concept_name("___"))

    def test_collapses_runs_of_underscores(self):
        self.assertEqual(c.normalize_concept_name("team___restructuring"),
                         "team_restructuring")

    def test_truncates_overlength(self):
        long_name = "a_" * 40 + "tail"
        result = c.normalize_concept_name(long_name)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 64)

    def test_punctuation_separators(self):
        self.assertEqual(c.normalize_concept_name("Node.js (v18)"),
                         "node_js_v18")

    def test_acronym_kept_lowercase(self):
        self.assertEqual(c.normalize_concept_name("OAuth"), "oauth")
        self.assertEqual(c.normalize_concept_name("p2p"), "p2p")

    def test_handles_none_input(self):
        self.assertIsNone(c.normalize_concept_name(None))

    def test_drops_transliteration_tsiya(self):
        # Q15 model slip: model transliterates "реструктуризация" instead
        # of translating to "restructuring". Mechanical safety net drops.
        self.assertIsNone(c.normalize_concept_name("restrukturizatsiya"))

    def test_drops_transliteration_ovanie(self):
        self.assertIsNone(c.normalize_concept_name("delegirovanie"))

    def test_drops_transliteration_with_shch(self):
        self.assertIsNone(c.normalize_concept_name("borshch_recipe"))

    def test_drops_atelnost(self):
        self.assertIsNone(c.normalize_concept_name("dejatelnost"))

    def test_keeps_short_words_not_transliterations(self):
        # `tsia` substring at end too short → not flagged
        self.assertEqual(c.normalize_concept_name("ratio"), "ratio")


class NormalizeConceptListTests(unittest.TestCase):
    def test_dedupes_after_normalisation(self):
        result = c.normalize_concept_list([
            "Team-Restructuring", "team_restructuring", "TEAM-restructuring"
        ])
        self.assertEqual(result, ["team_restructuring"])

    def test_preserves_first_seen_order(self):
        result = c.normalize_concept_list(["alpha", "beta", "gamma"])
        self.assertEqual(result, ["alpha", "beta", "gamma"])

    def test_drops_unresolvable_keeps_others(self):
        result = c.normalize_concept_list(["valid_one", "тема", "valid_two"])
        self.assertEqual(result, ["valid_one", "valid_two"])

    def test_empty_input_empty_output(self):
        self.assertEqual(c.normalize_concept_list([]), [])
        self.assertEqual(c.normalize_concept_list(None), [])


class NormalizeAudienceTagTests(unittest.TestCase):
    def test_canonical_passthrough(self):
        for tag in ("family", "friends", "work",
                    "professional-network", "world"):
            self.assertEqual(c.normalize_audience_tag(tag), tag)

    def test_uppercase_normalised(self):
        self.assertEqual(c.normalize_audience_tag("Family"), "family")

    def test_underscore_to_hyphen(self):
        self.assertEqual(c.normalize_audience_tag("professional_network"),
                         "professional-network")

    def test_drops_non_ascii(self):
        self.assertIsNone(c.normalize_audience_tag("семья"))

    def test_drops_too_short(self):
        self.assertIsNone(c.normalize_audience_tag("a"))

    def test_drops_too_long(self):
        self.assertIsNone(c.normalize_audience_tag("a" * 33))

    def test_passes_through_well_formed_extension(self):
        # caller decides accept/drop based on AUDIENCES.md Extensions
        self.assertEqual(c.normalize_audience_tag("team-platform"),
                         "team-platform")


class RecomputeHubTrioTests(unittest.TestCase):
    """Hub privacy derivation: dominant origin / audience intersection /
    sensitivity contagion. Owner-set fields ALWAYS preserved."""

    def test_empty_members_uses_conservative_defaults(self):
        fm, events = c.recompute_hub_trio({}, [])
        self.assertEqual(fm["origin"], "personal")
        self.assertEqual(fm["audience_tags"], [])
        self.assertFalse(fm["is_sensitive"])
        self.assertEqual(len(events), 3)

    def test_dominant_origin_wins(self):
        members = [
            {"origin": "work"},
            {"origin": "work"},
            {"origin": "personal"},
        ]
        fm, _ = c.recompute_hub_trio({}, members)
        self.assertEqual(fm["origin"], "work")

    def test_origin_tie_breaks_to_personal(self):
        members = [
            {"origin": "work"},
            {"origin": "personal"},
        ]
        fm, _ = c.recompute_hub_trio({}, members)
        self.assertEqual(fm["origin"], "personal")

    def test_audience_intersection_fail_closed(self):
        members = [
            {"audience_tags": ["work", "friends"]},
            {"audience_tags": ["work"]},
            {"audience_tags": []},  # one member at owner-only collapses set
        ]
        fm, _ = c.recompute_hub_trio({}, members)
        self.assertEqual(fm["audience_tags"], [])

    def test_audience_intersection_when_all_agree(self):
        members = [
            {"audience_tags": ["work", "friends"]},
            {"audience_tags": ["work", "friends"]},
        ]
        fm, _ = c.recompute_hub_trio({}, members)
        self.assertEqual(fm["audience_tags"], ["friends", "work"])

    def test_sensitivity_contagion(self):
        members = [
            {"is_sensitive": False},
            {"is_sensitive": True},
            {"is_sensitive": False},
        ]
        fm, _ = c.recompute_hub_trio({}, members)
        self.assertTrue(fm["is_sensitive"])

    def test_owner_set_origin_preserved(self):
        """If hub.origin already set, derivation does not overwrite."""
        members = [{"origin": "work"}, {"origin": "work"}]
        fm, events = c.recompute_hub_trio({"origin": "personal"}, members)
        self.assertEqual(fm["origin"], "personal")
        self.assertNotIn("hub-origin-derive-autofix",
                         {e["fix_id"] for e in events})

    def test_owner_set_audience_preserved(self):
        members = [{"audience_tags": []}]
        fm, events = c.recompute_hub_trio(
            {"audience_tags": ["work"]}, members
        )
        self.assertEqual(fm["audience_tags"], ["work"])
        self.assertNotIn("hub-audience-derive-autofix",
                         {e["fix_id"] for e in events})

    def test_owner_set_is_sensitive_preserved(self):
        members = [{"is_sensitive": True}]
        fm, events = c.recompute_hub_trio(
            {"is_sensitive": False}, members
        )
        self.assertFalse(fm["is_sensitive"])
        self.assertNotIn("hub-sensitivity-derive-autofix",
                         {e["fix_id"] for e in events})

    def test_partial_owner_set_only_missing_filled(self):
        """Owner set origin only; audience and is_sensitive derived."""
        members = [
            {"origin": "work", "audience_tags": ["work"], "is_sensitive": True},
        ]
        fm, events = c.recompute_hub_trio({"origin": "personal"}, members)
        self.assertEqual(fm["origin"], "personal")  # preserved
        self.assertEqual(fm["audience_tags"], ["work"])  # derived
        self.assertTrue(fm["is_sensitive"])  # derived
        ids = {e["fix_id"] for e in events}
        self.assertIn("hub-audience-derive-autofix", ids)
        self.assertIn("hub-sensitivity-derive-autofix", ids)
        self.assertNotIn("hub-origin-derive-autofix", ids)

    def test_idempotent_after_full_set(self):
        """Running twice on a fully-set hub produces zero events."""
        fm, _ = c.recompute_hub_trio({}, [{"origin": "work"}])
        _, events_again = c.recompute_hub_trio(fm, [{"origin": "work"}])
        self.assertEqual(events_again, [])


if __name__ == "__main__":
    unittest.main()
