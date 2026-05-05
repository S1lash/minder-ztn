"""Tests for `_common.parse_action_hints` deterministic parser."""

from __future__ import annotations

import unittest

import _common as c  # type: ignore


GOOD_TRAILER = """\
Body of the lens output.

## Action Hints
- type: hub_stub_create
  params:
    suggested_slug: hub-inner-work
    cited_notes:
      - 2_areas/personal/a.md
      - 2_areas/personal/b.md
  confidence: medium
  brief_reasoning: |
    Tight cluster across four months on a single substrate.
- type: wikilink_add
  params:
    note_a: 2_areas/work/x.md
    note_b: 2_areas/personal/y.md
  confidence: high
  brief_reasoning: Same operating logic surfacing in two domains.
"""


class ExtractBlockTests(unittest.TestCase):
    def test_no_section_returns_none(self):
        self.assertIsNone(c.extract_action_hints_block("Body without trailer."))

    def test_extracts_until_next_top_level_heading(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md}\n"
            "  confidence: low\n"
            "  brief_reasoning: x\n"
            "## Footer\nignored\n"
        )
        block = c.extract_action_hints_block(body)
        self.assertIn("type: wikilink_add", block)
        self.assertNotIn("Footer", block)

    def test_subheadings_inside_block_are_kept(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md}\n"
            "  confidence: low\n"
            "  brief_reasoning: |\n"
            "    Has ### subheading inside reasoning.\n"
        )
        block = c.extract_action_hints_block(body)
        self.assertIn("### subheading", block)


class ParseGoodInputTests(unittest.TestCase):
    def test_parses_well_formed_trailer(self):
        hints, drops = c.parse_action_hints(GOOD_TRAILER)
        self.assertEqual(drops, [])
        self.assertEqual(len(hints), 2)
        self.assertEqual(hints[0].type, "hub_stub_create")
        self.assertEqual(hints[0].confidence, "medium")
        self.assertEqual(hints[0].params["suggested_slug"], "hub-inner-work")
        self.assertEqual(hints[1].type, "wikilink_add")
        self.assertEqual(hints[1].confidence, "high")
        self.assertEqual(hints[0].raw_index, 0)
        self.assertEqual(hints[1].raw_index, 1)

    def test_missing_section_returns_empty(self):
        hints, drops = c.parse_action_hints("just a body, no trailer.")
        self.assertEqual(hints, [])
        self.assertEqual(drops, [])

    def test_empty_section_returns_empty(self):
        hints, drops = c.parse_action_hints("## Action Hints\n\n")
        self.assertEqual(hints, [])
        self.assertEqual(drops, [])


class ParseDropTests(unittest.TestCase):
    def _drop_reason(self, body: str) -> str:
        _, drops = c.parse_action_hints(body)
        self.assertTrue(drops, "expected at least one drop")
        return drops[0]["reason"]

    def test_drops_unknown_type(self):
        body = (
            "## Action Hints\n"
            "- type: not_a_real_type\n"
            "  params: {a: 1}\n"
            "  confidence: low\n"
            "  brief_reasoning: x\n"
        )
        self.assertTrue(self._drop_reason(body).startswith("type-not-whitelisted"))

    def test_drops_missing_params(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md}\n"
            "  confidence: low\n"
            "  brief_reasoning: x\n"
        )
        self.assertTrue(self._drop_reason(body).startswith("missing-params"))

    def test_drops_bad_confidence(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md}\n"
            "  confidence: maybe\n"
            "  brief_reasoning: x\n"
        )
        self.assertTrue(self._drop_reason(body).startswith("bad-confidence"))

    def test_drops_missing_brief(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md}\n"
            "  confidence: low\n"
            "  brief_reasoning: ''\n"
        )
        self.assertEqual(self._drop_reason(body), "missing-brief-reasoning")

    def test_drops_non_mapping_entry(self):
        body = (
            "## Action Hints\n"
            "- just-a-string\n"
        )
        self.assertEqual(self._drop_reason(body), "entry-not-mapping")

    def test_yaml_error_returns_drop_with_raw_index_minus_one(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md\n"  # unterminated mapping
            "  confidence: low\n"
            "  brief_reasoning: x\n"
        )
        _, drops = c.parse_action_hints(body)
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["raw_index"], -1)
        self.assertTrue(drops[0]["reason"].startswith("yaml-parse-error"))

    def test_non_list_yaml_returns_drop(self):
        body = (
            "## Action Hints\n"
            "type: wikilink_add\n"  # mapping at top, not list
        )
        _, drops = c.parse_action_hints(body)
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["reason"], "expected-yaml-list")


class MixedGoodAndBadTests(unittest.TestCase):
    def test_good_kept_bad_dropped(self):
        body = (
            "## Action Hints\n"
            "- type: wikilink_add\n"
            "  params: {note_a: a.md, note_b: b.md}\n"
            "  confidence: high\n"
            "  brief_reasoning: ok\n"
            "- type: bogus\n"
            "  params: {}\n"
            "  confidence: low\n"
            "  brief_reasoning: x\n"
        )
        hints, drops = c.parse_action_hints(body)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0].type, "wikilink_add")
        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0]["raw_index"], 1)


if __name__ == "__main__":
    unittest.main()
