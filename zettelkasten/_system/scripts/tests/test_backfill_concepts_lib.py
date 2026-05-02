"""Tests for backfill_concepts_lib — batching, verdict application, resume."""

from __future__ import annotations

import unittest
from pathlib import Path

import backfill_concepts_lib as bcl  # type: ignore


class BatchingTests(unittest.TestCase):
    def test_origin_source_is_primary(self):
        fm = {
            Path("a.md"): {"origin_source": "src1"},
            Path("b.md"): {"origin_source": "src1"},
            Path("c.md"): {"origin_source": "src2"},
            Path("d.md"): {},
        }
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=1)
        kinds = [b.primary_kind for b in batches]
        self.assertIn("origin_source", kinds)
        # src1 → 2 files, src2 → 1, residual d.md falls through
        src1 = [b for b in batches if b.primary_key == "origin_source=src1"]
        self.assertEqual(len(src1), 1)
        self.assertEqual(len(src1[0].files), 2)

    def test_size_cap_splits_oversize_clusters(self):
        fm = {
            Path(f"f{i}.md"): {"origin_source": "src1"} for i in range(35)
        }
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=1)
        sizes = [len(b.files) for b in batches]
        self.assertEqual(sizes, [15, 15, 5])
        # All same primary key
        self.assertTrue(all(b.primary_key == "origin_source=src1" for b in batches))

    def test_secondary_uses_hub(self):
        fm = {
            Path("a.md"): {},  # no origin_source
            Path("b.md"): {},
        }
        hub_membership = {Path("a.md"): "hub-x", Path("b.md"): "hub-x"}
        batches = bcl.compute_batches(
            fm, batch_size=15, min_pack=1, hub_membership=hub_membership,
        )
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].primary_kind, "hub")
        self.assertEqual(batches[0].primary_key, "hub=hub-x")

    def test_tertiary_domain_temporal(self):
        fm = {
            Path("a.md"): {"domains": ["work"], "created": "2026-04-01"},
            Path("b.md"): {"domains": ["work"], "created": "2026-04-15"},
            Path("c.md"): {"domains": ["work"], "created": "2026-05-01"},
        }
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=1)
        # April cluster vs May cluster
        keys = sorted(b.primary_key for b in batches)
        self.assertEqual(keys, ["domain-cluster=work@2026-04", "domain-cluster=work@2026-05"])

    def test_alphabetical_fallback(self):
        fm = {Path("z.md"): {}, Path("a.md"): {}, Path("m.md"): {}}
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=1)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].primary_kind, "alphabetical")
        names = [p.name for p in batches[0].files]
        self.assertEqual(names, ["a.md", "m.md", "z.md"])

    def test_mixed_routing_assigns_each_only_once(self):
        fm = {
            Path("a.md"): {"origin_source": "src1"},
            Path("b.md"): {},
            Path("c.md"): {"domains": ["work"], "created": "2026-04-01"},
            Path("d.md"): {},
        }
        hub_membership = {Path("b.md"): "hub-x"}
        batches = bcl.compute_batches(
            fm, batch_size=15, min_pack=1, hub_membership=hub_membership,
        )
        all_files = [p for b in batches for p in b.files]
        self.assertEqual(set(all_files), set(fm.keys()))
        self.assertEqual(len(all_files), 4)


class PackingTests(unittest.TestCase):
    def test_default_packs_small_clusters(self):
        # 30 files, each from its own origin_source — without packing
        # would yield 30 batches of size 1; with default min_pack=8
        # they pack into ≤ ceil(30/15) = 2 batches.
        fm = {
            Path(f"f{i}.md"): {"origin_source": f"src{i}", "created": "2026-04-01"}
            for i in range(30)
        }
        batches = bcl.compute_batches(fm, batch_size=15)
        self.assertLessEqual(len(batches), 2)
        # All packed
        self.assertTrue(all(b.primary_kind == "packed" for b in batches))
        # All files retained
        all_files = [p for b in batches for p in b.files]
        self.assertEqual(set(all_files), set(fm.keys()))

    def test_large_clusters_pass_through(self):
        # 20 files from one source — split into 15+5 by batch_size cap.
        # The 15-chunk passes through (≥ min_pack); the 5-chunk would
        # pack on its own but there's nothing to pack with → packed@YM.
        fm = {
            Path(f"f{i}.md"): {"origin_source": "src1", "created": "2026-04-01"}
            for i in range(20)
        }
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=8)
        kinds = sorted(b.primary_kind for b in batches)
        # First chunk preserved as origin_source; tail-of-15 (size 5)
        # falls below min_pack and gets packed.
        self.assertEqual(kinds, ["origin_source", "packed"])

    def test_packed_grouped_by_year_month(self):
        # Mix of two months, each with small clusters. Packing should
        # keep the months in separate batches when both fit cleanly.
        fm = {}
        for i in range(5):
            fm[Path(f"april-{i}.md")] = {"origin_source": f"src{i}", "created": "2026-04-01"}
            fm[Path(f"may-{i}.md")] = {"origin_source": f"src-may-{i}", "created": "2026-05-01"}
        batches = bcl.compute_batches(fm, batch_size=15, min_pack=8)
        keys = sorted({b.primary_key for b in batches})
        self.assertIn("packed@2026-04", keys)
        self.assertIn("packed@2026-05", keys)


class VerdictParseTests(unittest.TestCase):
    def test_concept_validation_drops_unknown_type(self):
        fm_by_path = {Path("a.md"): {}}
        payload = {
            "batch_results": [{
                "note_path": "a.md",
                "concepts": ["api_v2_design"],
                "new_concepts": [
                    {"name": "ivan_petrov", "type": "person"},
                    {"name": "acme_payments", "type": "bogus"},
                    {"name": "rate_limit", "type": "idea"},
                ],
            }]
        }
        verdicts = bcl.parse_subagent_verdict(payload, fm_by_path)
        self.assertEqual(len(verdicts), 1)
        v = verdicts[0]
        self.assertIn("api_v2_design", v.concepts)
        self.assertIn("rate_limit", v.concepts)
        self.assertNotIn("ivan_petrov", v.concepts)
        self.assertNotIn("acme_payments", v.concepts)
        self.assertEqual(len(v.new_concepts), 1)
        self.assertEqual(v.new_concepts[0]["name"], "rate_limit")
        # 2 events for dropped new-concepts
        self.assertEqual(
            sum(1 for e in v.events if e["fix_id"] == "backfill-new-concept-drop"),
            2,
        )

    def test_normalises_concept_names(self):
        fm_by_path = {Path("a.md"): {}}
        payload = {
            "batch_results": [{
                "note_path": "a.md",
                "concepts": ["API V2 Design", "rate-limit", "rate-limit"],
            }]
        }
        verdicts = bcl.parse_subagent_verdict(payload, fm_by_path)
        self.assertEqual(verdicts[0].concepts, ["api_v2_design", "rate_limit"])

    def test_unknown_path_dropped_silently(self):
        fm_by_path = {Path("a.md"): {}}
        payload = {
            "batch_results": [
                {"note_path": "phantom.md", "concepts": ["x"]},
                {"note_path": "a.md", "concepts": ["api_v2_design"]},
            ]
        }
        verdicts = bcl.parse_subagent_verdict(payload, fm_by_path)
        self.assertEqual([v.path for v in verdicts], [Path("a.md")])

    def test_domain_corrections_validated(self):
        fm_by_path = {Path("a.md"): {"domains": ["wrk", "personal"]}}
        payload = {
            "batch_results": [{
                "note_path": "a.md",
                "concepts": [],
                "domain_corrections": [
                    {"raw": "wrk", "action": "remap", "target": "work"},
                    {"raw": "old", "action": "drop"},
                    {"raw": "weird", "action": "rename", "target": "x"},
                    {"raw": "bad", "action": "remap", "target": "INVALID/!@#"},
                ],
            }]
        }
        verdicts = bcl.parse_subagent_verdict(payload, fm_by_path)
        v = verdicts[0]
        actions = [(c["action"], c.get("target")) for c in v.domain_corrections]
        self.assertEqual(actions, [("remap", "work"), ("drop", None)])
        # `rename` is unknown action, `bad` has invalid target — both as events
        self.assertGreaterEqual(len(v.events), 2)


class ApplyVerdictTests(unittest.TestCase):
    def test_concepts_replaces_existing(self):
        fm = {"id": "x", "concepts": ["old"], "domains": ["work"]}
        v = bcl.NoteVerdict(
            path=Path("a.md"),
            concepts=["new_a", "new_b"],
            new_concepts=[],
            domain_corrections=[],
        )
        new_fm = bcl.apply_verdict_to_frontmatter(fm, v)
        self.assertEqual(new_fm["concepts"], ["new_a", "new_b"])
        # original fm not mutated
        self.assertEqual(fm["concepts"], ["old"])

    def test_domain_drop_removes_value(self):
        fm = {"domains": ["work", "stale"]}
        v = bcl.NoteVerdict(
            path=Path("a.md"),
            concepts=[],
            new_concepts=[],
            domain_corrections=[{"raw": "stale", "action": "drop"}],
        )
        new_fm = bcl.apply_verdict_to_frontmatter(fm, v)
        self.assertEqual(new_fm["domains"], ["work"])

    def test_domain_remap_dedupes(self):
        fm = {"domains": ["wrk", "work"]}
        v = bcl.NoteVerdict(
            path=Path("a.md"),
            concepts=[],
            new_concepts=[],
            domain_corrections=[
                {"raw": "wrk", "action": "remap", "target": "work"},
            ],
        )
        new_fm = bcl.apply_verdict_to_frontmatter(fm, v)
        self.assertEqual(new_fm["domains"], ["work"])


class ResumeTests(unittest.TestCase):
    def test_parse_processed_batches(self):
        log = (
            "## Batch 1/41 — 2026-05-02 10:00\n\n"
            "- Files: 5\n\n"
            "## Batch 2/41 — 2026-05-02 10:05\n\n"
            "- Files: 7\n"
        )
        self.assertEqual(bcl.parse_processed_batches(log), {1, 2})

    def test_empty_log(self):
        self.assertEqual(bcl.parse_processed_batches(""), set())


if __name__ == "__main__":
    unittest.main()
