"""Tests for build_concept_registry — corpus aggregator + alias preservation."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests._fixture import clear_ztn_env, make_fixture  # type: ignore

import build_concept_registry as bcr  # type: ignore


def _write_md(path: Path, frontmatter: str, body: str = "Body.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")


class HarvestCorpusTests(unittest.TestCase):
    def test_aggregates_concepts_across_records_and_para(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            _write_md(
                fx.base / "_records/meetings/20260401-meeting-foo.md",
                'id: rec1\ncreated: 2026-04-01\nconcepts:\n  - api_v2_design\n  - rate_limit',
            )
            _write_md(
                fx.base / "_records/meetings/20260403-meeting-bar.md",
                'id: rec2\ncreated: 2026-04-03\nconcepts: [api_v2_design, latency_budget]',
            )
            _write_md(
                fx.base / "1_projects/some-project.md",
                'id: proj1\ncreated: 2026-03-15\nconcepts:\n  - api_v2_design',
            )
            _write_md(
                fx.base / "_records/meetings/README.md",
                "should_be_skipped: true",
            )
            agg, stats = bcr.build(fx.base, top_threshold=2)
            self.assertEqual(stats["mentions_seen"], 5)
            self.assertEqual(set(agg.keys()), {"api_v2_design", "rate_limit", "latency_budget"})
            api = agg["api_v2_design"]
            self.assertEqual(api.mentions, 3)
            self.assertEqual(api.first_seen, date(2026, 3, 15))
            self.assertEqual(api.last_seen, date(2026, 4, 3))
        clear_ztn_env()

    def test_normalises_dirty_concept_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            _write_md(
                fx.base / "_records/observations/20260405-obs-foo.md",
                'id: obs1\ncreated: 2026-04-05\nconcepts:\n  - "API V2 Design"\n  - "rate-limit"',
            )
            agg, _ = bcr.build(fx.base, top_threshold=10)
            self.assertIn("api_v2_design", agg)
            self.assertIn("rate_limit", agg)
        clear_ztn_env()

    def test_empty_corpus_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            agg, stats = bcr.build(fx.base, top_threshold=10)
            self.assertEqual(agg, {})
            self.assertEqual(stats["mentions_seen"], 0)
            self.assertEqual(stats["batches_read"], 0)
        clear_ztn_env()

    def test_skips_template_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            _write_md(
                fx.base / "5_meta/templates/note-template.md",
                'concepts:\n  - placeholder_concept',
            )
            agg, _ = bcr.build(fx.base, top_threshold=1)
            self.assertNotIn("placeholder_concept", agg)
        clear_ztn_env()


class HarvestBatchesTests(unittest.TestCase):
    def test_pulls_type_subtype_chronologically(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            batches = fx.base / "_system/state/batches"
            batches.mkdir(parents=True)
            (batches / "20260101-aaa.json").write_text(json.dumps({
                "batch_id": "20260101-aaa",
                "timestamp": "2026-01-01T10:00:00Z",
                "concepts": {"upserts": [
                    {"name": "api_v2_design", "type": "idea", "subtype": "rest"},
                ]},
            }))
            (batches / "20260301-bbb.json").write_text(json.dumps({
                "batch_id": "20260301-bbb",
                "timestamp": "2026-03-01T10:00:00Z",
                "concepts": {"upserts": [
                    {"name": "api_v2_design", "type": "decision", "subtype": "later"},
                ]},
            }))
            _write_md(
                fx.base / "_records/meetings/20260101-meeting.md",
                'created: 2026-01-01\nconcepts: [api_v2_design]',
            )
            agg, _ = bcr.build(fx.base, top_threshold=10)
            self.assertEqual(agg["api_v2_design"].type, "idea")
            self.assertEqual(agg["api_v2_design"].subtype, "rest")
        clear_ztn_env()

    def test_drops_type_outside_emit_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            batches = fx.base / "_system/state/batches"
            batches.mkdir(parents=True)
            (batches / "b.json").write_text(json.dumps({
                "batch_id": "b",
                "timestamp": "2026-01-01T10:00:00Z",
                "concepts": {"upserts": [
                    {"name": "ivan_petrov", "type": "person"},
                    {"name": "acme_payments", "type": "bogus_value"},
                ]},
            }))
            agg, _ = bcr.build(fx.base, top_threshold=10)
            self.assertIsNone(agg.get("ivan_petrov").type if agg.get("ivan_petrov") else None)
            self.assertIsNone(agg.get("acme_payments").type if agg.get("acme_payments") else None)
        clear_ztn_env()

    def test_unparseable_batch_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            batches = fx.base / "_system/state/batches"
            batches.mkdir(parents=True)
            (batches / "bad.json").write_text("not json{")
            agg, stats = bcr.build(fx.base, top_threshold=10)
            self.assertEqual(stats["batches_read"], 0)
        clear_ztn_env()


class AliasPreservationTests(unittest.TestCase):
    def test_aliases_carry_over_from_existing_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            registry = fx.base / "_system/registries/CONCEPTS.md"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                "---\nschema_version: 1.0\n---\n\n"
                "## Top by mentions\n\n"
                "| name | type | subtype | first_seen | last_seen | mentions | aliases |\n"
                "|---|---|---|---|---|---|---|\n"
                "| api_v2_design | idea | — | 2026-01-01 | 2026-04-01 | 5 | api_v2, api2 |\n"
            )
            _write_md(
                fx.base / "_records/meetings/20260401-meeting.md",
                'created: 2026-04-01\nconcepts: [api_v2_design]',
            )
            agg, _ = bcr.build(fx.base, top_threshold=1)
            self.assertEqual(agg["api_v2_design"].aliases, ["api_v2", "api2"])
        clear_ztn_env()

    def test_orphan_aliases_kept_with_zero_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            registry = fx.base / "_system/registries/CONCEPTS.md"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                "## Top\n\n"
                "| name | type | subtype | first_seen | last_seen | mentions | aliases |\n"
                "|---|---|---|---|---|---|---|\n"
                "| renamed_concept | idea | — | 2026-01-01 | 2026-01-01 | 0 | old_name |\n"
            )
            agg, _ = bcr.build(fx.base, top_threshold=1)
            self.assertIn("renamed_concept", agg)
            self.assertEqual(agg["renamed_concept"].mentions, 0)
            self.assertEqual(agg["renamed_concept"].aliases, ["old_name"])
        clear_ztn_env()


class RenderTests(unittest.TestCase):
    def test_top_tail_split_by_threshold(self):
        agg = {
            "popular": bcr.ConceptAgg(name="popular", mentions=150),
            "rare": bcr.ConceptAgg(name="rare", mentions=2),
        }
        out = bcr.render_registry(agg, top_threshold=100, today=date(2026, 5, 1))
        self.assertIn("total_concepts: 2", out)
        self.assertIn("total_mentions: 152", out)
        # popular row appears before tail header
        top_idx = out.index("| popular |")
        tail_header_idx = out.index("## Tail")
        rare_idx = out.index("| rare |")
        self.assertLess(top_idx, tail_header_idx)
        self.assertLess(tail_header_idx, rare_idx)

    def test_empty_corpus_renders_placeholders(self):
        out = bcr.render_registry({}, top_threshold=10, today=date(2026, 5, 1))
        self.assertIn("total_concepts: 0", out)
        self.assertIn("(none — corpus has no concept above threshold yet)", out)
        self.assertIn("(none)", out)


class IdempotenceTests(unittest.TestCase):
    def test_main_writes_then_re_runs_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            _write_md(
                fx.base / "_records/meetings/20260401-meeting.md",
                'created: 2026-04-01\nconcepts: [test_concept]',
            )
            self.assertEqual(bcr.main(["--root", str(fx.base)]), 0)
            registry = fx.base / "_system/registries/CONCEPTS.md"
            first = registry.read_text()
            self.assertEqual(bcr.main(["--root", str(fx.base)]), 0)
            second = registry.read_text()
            # Same date semantics — idempotent on identical inputs
            self.assertEqual(first, second)
        clear_ztn_env()


if __name__ == "__main__":
    unittest.main()
