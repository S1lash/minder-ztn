"""Tests for emit_batch_manifest.py — JSON manifest emitter.

Coverage:
- happy path round-trip
- concept-name normalisation in concept_hints / member_concepts /
  applies_in_concepts / concept_ids / related_concepts / previous_slugs
- concepts.upserts[]: name normalise + drop unnormalisables + subtype
  normalise + nested lists normalise
- audience_tags whitelist enforcement (canonical 5 + extensions)
- privacy trio coercion (origin enum, is_sensitive bool)
- top-level required keys missing → warning, write succeeds
- dry-run does not write
- idempotence
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tests._fixture import clear_ztn_env  # type: ignore
import emit_batch_manifest as e  # type: ignore


def _audiences_file(root: Path, extensions: list[str] | None = None) -> Path:
    extensions = extensions or []
    rows = "\n".join(
        f"| {tag} | 2026-05-02 | active | test | — |" for tag in extensions
    )
    p = root / "AUDIENCES.md"
    p.write_text(
        "# Audiences\n"
        "<!-- BEGIN extensions -->\n"
        "| Tag | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        + (rows + "\n" if rows else "")
        + "<!-- END extensions -->\n",
        encoding="utf-8",
    )
    return p


def _domains_file(root: Path, extensions: list[str] | None = None) -> Path:
    extensions = extensions or []
    rows = "\n".join(
        f"| {dom} | 2026-05-02 | active | test | — |" for dom in extensions
    )
    p = root / "DOMAINS.md"
    p.write_text(
        "# Domains\n"
        "<!-- BEGIN extensions -->\n"
        "| Domain | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        + (rows + "\n" if rows else "")
        + "<!-- END extensions -->\n",
        encoding="utf-8",
    )
    return p


def _run(input_data: dict, output: Path, audiences: Path,
         dry_run: bool = False, *, domains: Path | None = None,
         ) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    ) as fh:
        json.dump(input_data, fh)
        in_path = Path(fh.name)
    # Always isolate from live registry — when caller did not provide a
    # specific DOMAINS.md, write an empty one alongside AUDIENCES.md so
    # tests use the canonical 13 with no extensions.
    if domains is None:
        domains = _domains_file(audiences.parent)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    args = ["--input", str(in_path), "--output", str(output),
            "--audiences", str(audiences), "--domains", str(domains)]
    if dry_run:
        args.append("--dry-run")
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = e.main(args)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _minimal_manifest() -> dict:
    return {
        "batch_id": "20260502-120000",
        "timestamp": "2026-05-02T12:00:00Z",
        "format_version": "2.1",
        "processor": "ztn:process",
        "sources_processed": [],
        "records": {"created": [], "updated": []},
        "knowledge_notes": {"created": [], "updated": []},
        "hubs": {"created": [], "updated": []},
        "concepts": {"upserts": []},
        "stats": {},
    }


class HappyPathTests(unittest.TestCase):
    def test_clean_input_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": ["team_restructuring", "queue_prioritization"],
                "origin": "work",
                "audience_tags": ["work"],
                "is_sensitive": False,
            })
            output = tmp / "out.json"
            rc, _, err = _run(data, output, audiences)
            self.assertEqual(rc, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                written["records"]["created"][0]["concept_hints"],
                ["team_restructuring", "queue_prioritization"],
            )
            # No fix events expected on clean input
            self.assertEqual(err.strip(), "")
        clear_ztn_env()


class ConceptNormalisationTests(unittest.TestCase):
    def test_concept_hints_normalised(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": ["Team-Restructuring", "тема", "queue_prioritization"],
                "origin": "work",
                "audience_tags": [],
                "is_sensitive": False,
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 0)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            # Cyrillic dropped, kebab-snake normalised
            self.assertEqual(
                written["records"]["created"][0]["concept_hints"],
                ["team_restructuring", "queue_prioritization"],
            )
            # Events on stderr
            self.assertIn("concept-format-autofix", err)
        clear_ztn_env()

    def test_concepts_upserts_dropped_when_unnormalisable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["concepts"]["upserts"] = [
                {"name": "valid_concept", "type": "theme",
                 "related_concepts": []},
                {"name": "тема", "type": "theme"},
                {"name": "Team-Restructuring", "type": "theme"},
            ]
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 0)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            names = [u["name"] for u in written["concepts"]["upserts"]]
            self.assertEqual(names, ["valid_concept", "team_restructuring"])
            self.assertIn("concept-drop-autofix", err)
            self.assertIn("concept-format-autofix", err)
        clear_ztn_env()

    def test_concepts_upserts_subtype_and_related_normalised(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["concepts"]["upserts"] = [{
                "name": "qdrant",
                "type": "tool",
                "subtype": "Vector-Database",
                "related_concepts": ["Vector-Search", "embedding"],
                "previous_slugs": [],
            }]
            rc, _, _ = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            entry = written["concepts"]["upserts"][0]
            self.assertEqual(entry["subtype"], "vector_database")
            self.assertEqual(entry["related_concepts"],
                             ["vector_search", "embedding"])
        clear_ztn_env()


class AudienceWhitelistTests(unittest.TestCase):
    def test_unknown_tag_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)  # no extensions
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": [],
                "origin": "work",
                "audience_tags": ["work", "team-platform", "world"],
                "is_sensitive": False,
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(
                written["records"]["created"][0]["audience_tags"],
                ["work", "world"],
            )
            self.assertIn("audience-tag-drop-autofix", err)
        clear_ztn_env()

    def test_extension_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp, extensions=["spouse"])
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/observations/foo.md",
                "concept_hints": [],
                "origin": "personal",
                "audience_tags": ["spouse"],
                "is_sensitive": True,
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(
                written["records"]["created"][0]["audience_tags"],
                ["spouse"],
            )
        clear_ztn_env()

    def test_case_normalised_to_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/observations/foo.md",
                "concept_hints": [],
                "origin": "personal",
                "audience_tags": ["Family"],
                "is_sensitive": False,
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(
                written["records"]["created"][0]["audience_tags"],
                ["family"],
            )
            self.assertIn("audience-tag-normalise-autofix", err)
        clear_ztn_env()


class PrivacyCoercionTests(unittest.TestCase):
    def test_origin_coerced(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": [],
                "origin": "bogus",
                "audience_tags": [],
                "is_sensitive": False,
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(
                written["records"]["created"][0]["origin"], "personal"
            )
            self.assertIn("origin-coerce-autofix", err)
        clear_ztn_env()

    def test_is_sensitive_coerced_from_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": [],
                "origin": "work",
                "audience_tags": [],
                "is_sensitive": "true",
            })
            rc, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text(encoding="utf-8"))
            self.assertTrue(
                written["records"]["created"][0]["is_sensitive"]
            )
            self.assertIn("is-sensitive-coerce-autofix", err)
        clear_ztn_env()


class ManifestContractValidationTests(unittest.TestCase):
    def test_missing_required_top_level_key_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            del data["batch_id"]
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 3)
            self.assertIn("missing required top-level keys", err)
            self.assertFalse((tmp / "out.json").exists())
        clear_ztn_env()

    def test_unknown_processor_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["processor"] = "ztn:bogus"
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 3)
            self.assertIn("processor 'ztn:bogus' not in", err)
            self.assertFalse((tmp / "out.json").exists())
        clear_ztn_env()

    def test_incompatible_major_version_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["format_version"] = "3.0"
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 3)
            self.assertIn("format_version major", err)
            self.assertFalse((tmp / "out.json").exists())
        clear_ztn_env()

    def test_minor_version_drift_accepted(self):
        # 2.5 still major-2 → accepted (forward-compat per ARCHITECTURE
        # §8.12.2)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["format_version"] = "2.5"
            rc, _, _ = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 0)
            self.assertTrue((tmp / "out.json").exists())
        clear_ztn_env()

    def test_missing_required_section_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            del data["concepts"]
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 3)
            self.assertIn("requires sections", err)
            self.assertFalse((tmp / "out.json").exists())
        clear_ztn_env()

    def test_malformed_format_version_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["format_version"] = "two-point-zero"
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 3)
            self.assertIn("format_version", err)
        clear_ztn_env()

    def test_other_processors_have_relaxed_section_requirements(self):
        # ztn:lint / ztn:maintain / ztn:agent-lens require only `stats`
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            for proc in ("ztn:maintain", "ztn:lint", "ztn:agent-lens"):
                data = {
                    "batch_id": "20260502-120000",
                    "timestamp": "2026-05-02T12:00:00Z",
                    "format_version": "2.1",
                    "processor": proc,
                    "stats": {},
                }
                output = tmp / f"out-{proc.replace(':', '-')}.json"
                rc, _, err = _run(data, output, audiences)
                self.assertEqual(rc, 0, f"{proc}: {err}")
                self.assertTrue(output.exists())
        clear_ztn_env()


class DryRunTests(unittest.TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            output = tmp / "out.json"
            rc, out, _ = _run(_minimal_manifest(), output, audiences,
                              dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse(output.exists())
            # JSON was printed to stdout
            self.assertIn("batch_id", out)
        clear_ztn_env()


class IdempotenceTests(unittest.TestCase):
    def test_clean_input_zero_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"]["created"].append({
                "path": "_records/meetings/foo.md",
                "concept_hints": ["team_restructuring"],
                "origin": "work",
                "audience_tags": ["work"],
                "is_sensitive": False,
            })
            _, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(err.strip(), "")
            # Re-emit the written file: should still be clean
            written_data = json.loads(
                (tmp / "out.json").read_text(encoding="utf-8")
            )
            _, _, err2 = _run(written_data, tmp / "out2.json", audiences)
            self.assertEqual(err2.strip(), "")
        clear_ztn_env()


class DomainNormalisationTests(unittest.TestCase):
    """`walk_and_normalise` handling of `domains:` (plural) and `domain:`
    (singular). Deterministic substrate — silent autofix or silent drop."""

    def test_canonical_passthrough(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"] = [{"domains": ["work", "career", "health"]}]
            rc, _, err = _run(data, tmp / "out.json", audiences)
            self.assertEqual(rc, 0)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["records"][0]["domains"],
                ["work", "career", "health"],
            )
            domain_events = [
                ln for ln in err.splitlines()
                if ln.strip() and "domain" in ln
            ]
            self.assertEqual(domain_events, [])
        clear_ztn_env()

    def test_unknown_value_dropped_from_array(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"] = [{"domains": ["work", "payments", "career"]}]
            _, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["records"][0]["domains"], ["work", "career"],
            )
            self.assertIn("domain-drop-autofix", err)
            self.assertIn("payments", err)

    def test_slash_syntax_split_keeps_canonical(self):
        # `work/process` → keep `work`, drop `process`.
        # `personal/psychology` → keep `personal`, drop `psychology`.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"] = [{
                "domains": ["work/process", "personal/psychology"],
            }]
            _, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["records"][0]["domains"], ["work", "personal"],
            )
            self.assertIn("domain-normalise-autofix", err)

    def test_slash_both_canonical_both_kept(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"] = [{"domains": ["work/learning"]}]
            _, _, _ = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["records"][0]["domains"], ["work", "learning"],
            )

    def test_extension_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            domains = _domains_file(tmp, extensions=["gardening"])
            data = _minimal_manifest()
            data["records"] = [{"domains": ["gardening", "work"]}]
            _, _, err = _run(
                data, tmp / "out.json", audiences, domains=domains,
            )
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["records"][0]["domains"], ["gardening", "work"],
            )

    def test_singular_domain_normalised(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["constitution"] = {
                "principles": [{"id": "axiom-x-001", "domain": "ai_interaction"}],
            }
            _, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(
                written["constitution"]["principles"][0]["domain"],
                "ai-interaction",
            )

    def test_singular_domain_dropped_when_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["constitution"] = {
                "principles": [{"id": "axiom-x-001", "domain": "junk"}],
            }
            _, _, err = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertNotIn(
                "domain", written["constitution"]["principles"][0],
            )
            self.assertIn("domain-drop-autofix", err)

    def test_dedupes_after_normalisation(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            audiences = _audiences_file(tmp)
            data = _minimal_manifest()
            data["records"] = [{"domains": ["Work", "work", "WORK"]}]
            _, _, _ = _run(data, tmp / "out.json", audiences)
            written = json.loads((tmp / "out.json").read_text())
            self.assertEqual(written["records"][0]["domains"], ["work"])


if __name__ == "__main__":
    unittest.main()
