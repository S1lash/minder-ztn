"""Tests for lint_concept_audit.py — Scan A.7 + Step 1.D.

Coverage:
- concept format autofix (kebab → snake, case, type-prefix strip)
- concept drop (non-ASCII, type-only)
- audience-tag whitelist enforcement (canonical + extensions)
- audience-tag normalise + drop
- privacy-trio backfill (missing fields)
- type coercion (`is_sensitive`, `origin`)
- idempotence (re-run yields zero events)
- exclusion scope (registries / views / SOUL / templates not touched)
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests._fixture import clear_ztn_env  # type: ignore
import lint_concept_audit as la  # type: ignore


def _scaffold(root: Path) -> None:
    """Create the minimum directory structure needed."""
    for sub in (
        "_records/meetings", "_records/observations",
        "1_projects", "2_areas", "3_resources/people",
        "4_archive", "5_meta/mocs", "5_meta/templates",
        "_system/registries", "_system/views",
        "_system/state", "_sources/processed", "0_constitution",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _write_audiences(root: Path, extensions: list[str] | None = None) -> None:
    extensions = extensions or []
    rows = "\n".join(
        f"| {tag} | 2026-05-02 | active | test | — |" for tag in extensions
    )
    (root / "_system" / "registries" / "AUDIENCES.md").write_text(
        "# Audiences\n"
        "<!-- BEGIN extensions -->\n"
        "| Tag | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        + (rows + "\n" if rows else "")
        + "<!-- END extensions -->\n",
        encoding="utf-8",
    )


def _write_md(path: Path, frontmatter: str, body: str = "body\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


def _run(root: Path, mode: str = "scan") -> list[dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        la.main(["--mode", mode, "--root", str(root)])
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


class ConceptAutofixTests(unittest.TestCase):
    def test_kebab_normalised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            f = _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts:\n  - Team-Restructuring\n'
                'origin: personal\naudience_tags: []\nis_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("concept-format-autofix", ids)
            # File rewritten
            text = f.read_text(encoding="utf-8")
            self.assertIn("team_restructuring", text)
            self.assertNotIn("Team-Restructuring", text)
        clear_ztn_env()

    def test_non_ascii_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            f = _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts:\n  - тема\n  - delegation_pattern\n'
                'origin: personal\naudience_tags: []\nis_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("concept-drop-autofix", ids)
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("тема", text)
            self.assertIn("delegation_pattern", text)
        clear_ztn_env()


class AudienceAutofixTests(unittest.TestCase):
    def test_canonical_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts: []\norigin: work\n'
                'audience_tags:\n  - work\n  - professional-network\n'
                'is_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            self.assertEqual(events, [])  # nothing to fix
        clear_ztn_env()

    def test_unknown_tag_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)  # no extensions
            f = _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts: []\norigin: work\n'
                'audience_tags:\n  - work\n  - team-platform\n'
                'is_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            ids = [e["fix_id"] for e in events]
            self.assertIn("audience-tag-drop-autofix", ids)
            text = f.read_text(encoding="utf-8")
            self.assertNotIn("team-platform", text)
            self.assertIn("- work", text)
        clear_ztn_env()

    def test_extension_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root, extensions=["spouse"])
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts: []\norigin: personal\n'
                'audience_tags:\n  - spouse\nis_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            self.assertEqual(events, [])
        clear_ztn_env()

    def test_case_normalised_to_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            f = _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts: []\norigin: personal\n'
                'audience_tags:\n  - Family\nis_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("audience-tag-normalise-autofix", ids)
            text = f.read_text(encoding="utf-8")
            self.assertIn("- family", text)
            self.assertNotIn("Family", text)
        clear_ztn_env()


class PrivacyTrioBackfillTests(unittest.TestCase):
    def test_missing_trio_inserted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            f = _write_md(
                root / "1_projects" / "n.md",
                'id: foo\nlayer: knowledge\ntitle: "Foo"\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("privacy-trio-backfill-autofix", ids)
            text = f.read_text(encoding="utf-8")
            self.assertIn("origin: personal", text)
            self.assertIn("audience_tags: []", text)
            self.assertIn("is_sensitive: false", text)
        clear_ztn_env()

    def test_origin_coerced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\norigin: bogus\n'
                'audience_tags: []\nis_sensitive: false\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("origin-coerce-autofix", ids)
        clear_ztn_env()

    def test_is_sensitive_string_coerced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\norigin: personal\n'
                'audience_tags: []\nis_sensitive: "true"\n',
            )
            events = _run(root, mode="fix")
            ids = {e["fix_id"] for e in events}
            self.assertIn("is-sensitive-coerce-autofix", ids)
        clear_ztn_env()


class ScopeExclusionTests(unittest.TestCase):
    def test_soul_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            soul = _write_md(
                root / "_system" / "SOUL.md",
                'name: x\n', body="content\n",
            )
            original = soul.read_text(encoding="utf-8")
            events = _run(root, mode="fix")
            self.assertEqual(events, [])
            self.assertEqual(soul.read_text(encoding="utf-8"), original)
        clear_ztn_env()

    def test_template_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            tpl = _write_md(
                root / "5_meta" / "templates" / "note-template.md",
                'layer: knowledge\nconcepts:\n  - тема\n',
            )
            original = tpl.read_text(encoding="utf-8")
            events = _run(root, mode="fix")
            self.assertEqual(events, [])
            self.assertEqual(tpl.read_text(encoding="utf-8"), original)
        clear_ztn_env()

    def test_constitution_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            (root / "0_constitution" / "axiom").mkdir(parents=True, exist_ok=True)
            principle = _write_md(
                root / "0_constitution" / "axiom" / "p.md",
                'id: x\ntitle: x\n', body="text\n",
            )
            original = principle.read_text(encoding="utf-8")
            _run(root, mode="fix")
            self.assertEqual(principle.read_text(encoding="utf-8"), original)
        clear_ztn_env()


class IdempotenceTests(unittest.TestCase):
    def test_clean_state_zero_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts:\n  - team_restructuring\n'
                'origin: personal\naudience_tags: []\nis_sensitive: false\n',
            )
            self.assertEqual(_run(root, mode="scan"), [])
            self.assertEqual(_run(root, mode="fix"), [])
        clear_ztn_env()

    def test_fix_then_rerun_no_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts:\n  - Team-Restructuring\n'
                'origin: personal\naudience_tags:\n  - Family\n'
                'is_sensitive: "true"\n',
            )
            first = _run(root, mode="fix")
            self.assertGreater(len(first), 0)
            second = _run(root, mode="fix")
            self.assertEqual(second, [])
        clear_ztn_env()


class ScanModeNoWriteTests(unittest.TestCase):
    def test_scan_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            f = _write_md(
                root / "1_projects" / "n.md",
                'layer: knowledge\nconcepts:\n  - Team-Restructuring\n'
                'origin: personal\naudience_tags: []\nis_sensitive: false\n',
            )
            original = f.read_text(encoding="utf-8")
            events = _run(root, mode="scan")
            self.assertGreater(len(events), 0)
            self.assertEqual(f.read_text(encoding="utf-8"), original)
        clear_ztn_env()


def _write_domains(root: Path, extensions: list[str] | None = None) -> None:
    """Seed DOMAINS.md with optional extensions table rows."""
    extensions = extensions or []
    rows = "\n".join(
        f"| {dom} | 2026-05-02 | active | test | — |" for dom in extensions
    )
    (root / "_system" / "registries" / "DOMAINS.md").write_text(
        "# Domains\n"
        "<!-- BEGIN extensions -->\n"
        "| Domain | Added | Status | Purpose | Notes |\n"
        "|---|---|---|---|---|\n"
        + (rows + "\n" if rows else "")
        + "<!-- END extensions -->\n",
        encoding="utf-8",
    )


class DomainAutofixTests(unittest.TestCase):
    """`fix_domains` pass — Phase 1 deterministic substrate."""

    def test_canonical_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [work, career]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            domain_events = [e for e in events if "domain" in e.get("fix_id", "")]
            self.assertEqual(domain_events, [])
        clear_ztn_env()

    def test_unknown_value_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [work, payments, career]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            drops = [
                e for e in events
                if e.get("fix_id") == "domain-drop-autofix"
                and e.get("raw") == "payments"
            ]
            self.assertEqual(len(drops), 1)
            self.assertEqual(drops[0]["reason"], "not-in-whitelist")

    def test_slash_syntax_split_and_filtered(self):
        # `personal/psychology` → `personal` kept (canonical), `psychology`
        # dropped (not in whitelist). `work/process` analogous.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "2_areas" / "n.md",
                "layer: knowledge\ndomains: [personal/psychology, work/process]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            normalises = [
                e for e in events
                if e.get("fix_id") == "domain-normalise-autofix"
            ]
            results = sorted(
                e["result"] if isinstance(e["result"], str)
                else e["result"][0]
                for e in normalises
            )
            self.assertEqual(results, ["personal", "work"])
            drops = [
                e for e in events
                if e.get("fix_id") == "domain-drop-autofix"
            ]
            dropped_parts = sorted(e.get("part") for e in drops)
            self.assertEqual(dropped_parts, ["process", "psychology"])

    def test_slash_both_canonical_kept(self):
        # `work/learning` — both parts canonical → both kept.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [work/learning]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            _run(root, mode="fix")
            content = (root / "1_projects" / "n.md").read_text()
            self.assertIn("- work\n", content)
            self.assertIn("- learning\n", content)
        clear_ztn_env()

    def test_case_normalised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [Work, AI-Interaction]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            normalises = sorted(
                e["result"] for e in events
                if e.get("fix_id") == "domain-normalise-autofix"
            )
            self.assertEqual(normalises, ["ai-interaction", "work"])

    def test_extension_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_domains(root, extensions=["gardening"])
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [gardening, junk]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            domain_events = [e for e in events if "domain" in e.get("fix_id", "")]
            # Only "junk" should drop; gardening is in extensions.
            drops = [e for e in domain_events
                     if e.get("fix_id") == "domain-drop-autofix"]
            self.assertEqual(len(drops), 1)
            self.assertEqual(drops[0]["raw"], "junk")

    def test_format_unfixable_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [work, тема]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            events = _run(root, mode="scan")
            drops = [e for e in events
                     if e.get("fix_id") == "domain-drop-autofix"]
            self.assertEqual(len(drops), 1)
            self.assertEqual(drops[0]["reason"], "format-unfixable")

    def test_idempotent_after_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [Work, payments, personal/psychology]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            first = _run(root, mode="fix")
            self.assertGreater(
                len([e for e in first if "domain" in e.get("fix_id", "")]), 0
            )
            second = _run(root, mode="fix")
            self.assertEqual(
                [e for e in second if "domain" in e.get("fix_id", "")], []
            )
        clear_ztn_env()

    def test_dedupes_after_normalisation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_audiences(root)
            _write_md(
                root / "1_projects" / "n.md",
                "layer: knowledge\ndomains: [Work, work, WORK]\n"
                "origin: personal\naudience_tags: []\nis_sensitive: false\n",
            )
            _run(root, mode="fix")
            content = (root / "1_projects" / "n.md").read_text()
            # Final list should contain a single 'work'.
            self.assertEqual(content.count("- work\n"), 1)


if __name__ == "__main__":
    unittest.main()
