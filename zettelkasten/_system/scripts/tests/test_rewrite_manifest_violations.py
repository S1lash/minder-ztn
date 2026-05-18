"""Tests for rewrite_manifest_violations.py — one-shot retrofit utility.

Coverage:
- broken manifest (bare-string sources, non-empty bare-string tier1.people,
  missing privacy trio) → post-retrofit passes schema validation
- dry-run does NOT mutate the file on disk
- --apply writes back atomically
- clean manifest → no-op (idempotent)
- single-file mode
- directory mode batches multiple files
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import rewrite_manifest_violations as r  # type: ignore
from tests._fixture import clear_ztn_env  # type: ignore


def _audiences_file(root: Path) -> Path:
    p = root / "AUDIENCES.md"
    p.write_text(
        "# Audiences\n"
        "<!-- BEGIN extensions -->\n"
        "| Tag | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        "<!-- END extensions -->\n",
        encoding="utf-8",
    )
    return p


def _domains_file(root: Path) -> Path:
    p = root / "DOMAINS.md"
    p.write_text(
        "# Domains\n"
        "<!-- BEGIN extensions -->\n"
        "| Domain | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        "<!-- END extensions -->\n",
        encoding="utf-8",
    )
    return p


def _broken_manifest() -> dict:
    """Manifest exhibiting every broken pattern Phase 3 fixes."""
    return {
        "batch_id": "20260514-103200",
        "timestamp": "2026-05-14T10:32:00Z",
        "format_version": "2.1",
        "processor": "ztn:process",
        # Bare strings + structured (mixed list).
        "sources_processed": [
            "_sources/processed/plaud/2026-05-14T10:00:00Z/transcript.md",
            "_sources/processed/garmin/2026-05-14/metrics.md",
        ],
        # Missing privacy trio.
        "records": {
            "created": [
                {"path": "_records/meetings/foo.md"},
            ],
            "updated": [],
        },
        "knowledge_notes": {"created": [], "updated": []},
        # Non-empty bare-string array.
        "hubs": [],
        "concepts": {
            "upserts": [{"name": "manifest_schema_evolution",
                         "type": "technical"}],
        },
        "tier1_objects": {
            "people": ["alice-smith", "bob-jones"],
            "projects": [{"id": "minder"}],
        },
        "stats": {},
    }


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = r.main(args)
    return rc, out_buf.getvalue(), err_buf.getvalue()


class RetrofitTests(unittest.TestCase):
    def test_broken_manifest_retrofitted_to_schema_valid(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            audience_accept = {"work", "family", "world", "team", "client"}
            domain_accept = {"work", "career", "health", "identity"}
            data = _broken_manifest()
            retro, events = r.retrofit_manifest(
                data, audience_accept, domain_accept,
            )
            # sources_processed: bare strings wrapped
            for entry in retro["sources_processed"]:
                self.assertIsInstance(entry, dict)
                self.assertIn("path", entry)
            self.assertEqual(
                retro["sources_processed"][0]["source_type"],
                "plaud-transcript",
            )
            self.assertEqual(
                retro["sources_processed"][1]["source_type"],
                "garmin-daily",
            )
            # hubs: empty list became canonical envelope
            self.assertEqual(retro["hubs"], {"created": [], "updated": []})
            # tier1.people: bare strings wrapped into upserts
            self.assertEqual(
                [u["id"] for u in retro["tier1_objects"]["people"]["upserts"]],
                ["alice-smith", "bob-jones"],
            )
            # tier1.projects: dict list bucketed into upserts; trio defaults
            # injected because tier1.projects.upserts is an entity-list path.
            self.assertEqual(
                retro["tier1_objects"]["projects"]["upserts"][0]["id"],
                "minder",
            )
            self.assertEqual(
                retro["tier1_objects"]["projects"]["upserts"][0]["origin"],
                "personal",
            )
            # records[0]: privacy trio injected
            rec = retro["records"]["created"][0]
            self.assertEqual(rec["origin"], "personal")
            self.assertEqual(rec["audience_tags"], [])
            self.assertEqual(rec["is_sensitive"], False)
            # Events should have multiple fix categories
            event_ids = {ev["fix_id"] for ev in events}
            self.assertIn("sources-processed-coerce-autofix", event_ids)
            self.assertIn("hubs-empty-shape-autofix", event_ids)
            self.assertIn("tier1-bare-string-wrap-autofix", event_ids)
            self.assertIn("privacy-trio-inject-autofix", event_ids)
        clear_ztn_env()

    def test_idempotent_on_clean_input(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            audience_accept, domain_accept = r._load_accept_sets(
                audiences, domains,
            )
            data = {
                "batch_id": "20260514-103200",
                "timestamp": "2026-05-14T10:32:00Z",
                "format_version": "2.1",
                "processor": "ztn:process",
                "sources_processed": [],
                "records": {"created": [], "updated": []},
                "knowledge_notes": {"created": [], "updated": []},
                "hubs": {"created": [], "updated": []},
                "concepts": {"upserts": []},
                "stats": {},
            }
            before = json.dumps(data, sort_keys=True)
            _, events = r.retrofit_manifest(
                data, audience_accept, domain_accept,
            )
            after = json.dumps(data, sort_keys=True)
            self.assertEqual(before, after)
            self.assertEqual(events, [])
        clear_ztn_env()


class CliDryRunTests(unittest.TestCase):
    def test_dry_run_does_not_mutate_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            batches = tmp / "batches"
            batches.mkdir()
            broken = batches / "20260514-103200-process.json"
            original = json.dumps(_broken_manifest(), indent=2)
            broken.write_text(original, encoding="utf-8")

            rc, out, _ = _run_cli([
                "--batches-dir", str(batches),
                "--audiences", str(audiences),
                "--domains", str(domains),
            ])
            self.assertEqual(rc, 0)
            self.assertIn("would change", out)
            # File on disk is unchanged.
            self.assertEqual(broken.read_text(encoding="utf-8"), original)
        clear_ztn_env()

    def test_apply_rewrites_file(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            batches = tmp / "batches"
            batches.mkdir()
            broken = batches / "20260514-103200-process.json"
            broken.write_text(
                json.dumps(_broken_manifest(), indent=2), encoding="utf-8",
            )

            rc, out, _ = _run_cli([
                "--batches-dir", str(batches),
                "--audiences", str(audiences),
                "--domains", str(domains),
                "--apply",
            ])
            self.assertEqual(rc, 0)
            self.assertIn("rewrote", out)
            written = json.loads(broken.read_text(encoding="utf-8"))
            self.assertIsInstance(written["sources_processed"][0], dict)
            upserts = written["tier1_objects"]["people"]["upserts"]
            self.assertEqual(
                [u["id"] for u in upserts],
                ["alice-smith", "bob-jones"],
            )
            self.assertEqual(
                written["records"]["created"][0]["origin"], "personal",
            )
        clear_ztn_env()

    def test_clean_file_reports_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            batches = tmp / "batches"
            batches.mkdir()
            clean = batches / "20260514-103200-process.json"
            clean.write_text(json.dumps({
                "batch_id": "20260514-103200",
                "timestamp": "2026-05-14T10:32:00Z",
                "format_version": "2.1",
                "processor": "ztn:process",
                "sources_processed": [],
                "records": {"created": [], "updated": []},
                "knowledge_notes": {"created": [], "updated": []},
                "hubs": {"created": [], "updated": []},
                "concepts": {"upserts": []},
                "stats": {},
            }, indent=2), encoding="utf-8")
            rc, out, _ = _run_cli([
                "--batches-dir", str(batches),
                "--audiences", str(audiences),
                "--domains", str(domains),
            ])
            self.assertEqual(rc, 0)
            self.assertIn("clean", out)
        clear_ztn_env()

    def test_single_file_mode(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp)
            broken = tmp / "broken.json"
            broken.write_text(
                json.dumps(_broken_manifest(), indent=2), encoding="utf-8",
            )
            rc, out, _ = _run_cli([
                "--file", str(broken),
                "--audiences", str(audiences),
                "--domains", str(domains),
                "--apply",
            ])
            self.assertEqual(rc, 0)
            written = json.loads(broken.read_text(encoding="utf-8"))
            self.assertEqual(
                written["tier1_objects"]["projects"]["upserts"][0]["id"],
                "minder",
            )
        clear_ztn_env()


class RetrofitFullPipelineTests(unittest.TestCase):
    def test_retrofit_handles_legacy_sensitive_entities_shape(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _audiences_file(tmp)
            _domains_file(tmp)
            audience_accept = {"work", "family", "world", "team", "client"}
            domain_accept = {"work", "career", "health", "identity"}
            data = {
                "batch_id": "20260514-103200",
                "timestamp": "2026-05-14T10:32:00Z",
                "format_version": "2.1",
                "processor": "ztn:process",
                "sources_processed": [],
                "records": {"created": [], "updated": []},
                "knowledge_notes": {"created": [], "updated": []},
                "hubs": {"created": [], "updated": []},
                "concepts": {"upserts": []},
                "sensitive_entities": [
                    {"note_id": "20260506-therapy", "reason": "privacy"},
                ],
                "stats": {},
            }
            retro, events = r.retrofit_manifest(
                data, audience_accept, domain_accept,
            )
            entry = retro["sensitive_entities"][0]
            self.assertEqual(entry["id"], "20260506-therapy")
            self.assertEqual(entry["kind"], "note")
            self.assertEqual(entry["reason"], "privacy")
            self.assertNotIn("note_id", entry)
            self.assertIn(
                "sensitive-entities-note-id-coerce-autofix",
                {ev["fix_id"] for ev in events},
            )
        clear_ztn_env()

    def test_retrofit_relocates_misplaced_tier2_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _audiences_file(tmp)
            _domains_file(tmp)
            audience_accept = {"work", "family", "world", "team", "client"}
            domain_accept = {"work", "career", "health", "identity"}
            data = {
                "batch_id": "20260514-103200",
                "timestamp": "2026-05-14T10:32:00Z",
                "format_version": "2.1",
                "processor": "ztn:process",
                "sources_processed": [],
                "records": {"created": [], "updated": []},
                "knowledge_notes": {"created": [], "updated": []},
                "hubs": {"created": [], "updated": []},
                "concepts": {"upserts": []},
                "tier2_objects": {
                    "tasks": {
                        "upserts": [
                            {
                                "id": "task-pay-the-bill",
                                "type": "action",
                                "due": "2026-05-20",
                            },
                        ],
                    },
                },
                "stats": {},
            }
            retro, events = r.retrofit_manifest(
                data, audience_accept, domain_accept,
            )
            self.assertNotIn(
                "tasks", retro.get("tier2_objects", {}) or {},
            )
            created = retro["tier1_objects"]["tasks"]["created"]
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0]["id"], "task-pay-the-bill")
            self.assertEqual(created[0]["title"], "Pay the bill")
            self.assertEqual(created[0]["ownership"], "MINE")
            self.assertEqual(created[0]["deadline"], "2026-05-20")
            self.assertIn(
                "tier2-tasks-relocated-to-tier1",
                {ev["fix_id"] for ev in events},
            )
        clear_ztn_env()


if __name__ == "__main__":
    unittest.main()
