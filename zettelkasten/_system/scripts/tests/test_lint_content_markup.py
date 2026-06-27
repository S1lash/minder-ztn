"""Tests for lint_content_markup.py — Scan A.11 content markup canonicalization.

Coverage:
- synonym autofix (technical/technical-decision/practice → expert; personal → reflection)
  applied in fix mode with Evidence-Trail note; emitted-not-applied in scan mode
- judgment rows (idea/decision/principle/framework/product-insight) emitted with
  default + alternatives, NEVER auto-applied even in fix mode
- unknown drift value → content-type-unknown, never guessed
- canonical value (incl. story) → no event
- missing content_type / content_angle → flag events
- notes without content_potential → skipped entirely
- idempotence (re-run on healed synonym note yields no content-type event)
- Evidence Trail created when absent, prepended when present
- scope (out-of-PARA paths not touched)
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import lint_content_markup as lcm  # type: ignore


def _write_md(path: Path, frontmatter: str, body: str = "Body text.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


def _run(root: Path, mode: str = "scan") -> list[dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        lcm.main(["--mode", mode, "--root", str(root)])
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


def _fm(potential: str = "high", ctype: str | None = "expert",
        angle: str | None = "Why this matters") -> str:
    lines = ["layer: knowledge", "id: note", f"content_potential: {potential}"]
    if ctype is not None:
        lines.append(f"content_type: {ctype}")
    if angle is not None:
        lines.append(f"content_angle: {angle}")
    return "\n".join(lines) + "\n"


class SynonymAutofixTests(unittest.TestCase):
    def test_technical_to_expert_scan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md", _fm(ctype="technical"))
            events = _run(root, "scan")
            ct = [e for e in events if e["kind"] == "content-type"]
            self.assertEqual(len(ct), 1)
            self.assertEqual(ct[0]["raw"], "technical")
            self.assertEqual(ct[0]["target"], "expert")
            self.assertEqual(ct[0]["floor"], "strong")
            self.assertFalse(ct[0]["applied"])
            # scan mode must not write
            self.assertIn("content_type: technical", p.read_text(encoding="utf-8"))

    def test_technical_to_expert_fix_applies_and_trails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md", _fm(ctype="technical"))
            events = _run(root, "fix")
            ct = [e for e in events if e["kind"] == "content-type"]
            self.assertTrue(ct[0]["applied"])
            text = p.read_text(encoding="utf-8")
            self.assertIn("content_type: expert", text)
            self.assertNotIn("content_type: technical", text)
            self.assertIn("## Evidence Trail", text)
            self.assertIn("content_type canonicalized technical → expert", text)

    def test_personal_to_reflection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "2_areas" / "n.md", _fm(ctype="personal"))
            _run(root, "fix")
            self.assertIn("content_type: reflection",
                          p.read_text(encoding="utf-8"))

    def test_all_synonyms_map_to_expert(self):
        for raw in ("technical", "technical-decision", "practice"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                p = _write_md(root / "3_resources" / "n.md", _fm(ctype=raw))
                _run(root, "fix")
                self.assertIn("content_type: expert",
                              p.read_text(encoding="utf-8"), raw)

    def test_evidence_trail_prepended_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "Intro.\n\n## Evidence Trail\n\n- 2026-01-01: created\n"
            p = _write_md(root / "1_projects" / "n.md",
                          _fm(ctype="technical"), body)
            _run(root, "fix")
            text = p.read_text(encoding="utf-8")
            # new entry sits before the older one (most-recent-first)
            new_idx = text.index("content_type canonicalized")
            old_idx = text.index("2026-01-01: created")
            self.assertLess(new_idx, old_idx)
            self.assertEqual(text.count("## Evidence Trail"), 1)

    def test_targeted_edit_preserves_other_frontmatter_bytes(self):
        # frontmatter deliberately in NON-PyYAML-canonical style:
        # double quotes + 2-space-indented lists. A targeted edit must touch
        # ONLY the content_type line, leaving everything else byte-identical.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fm = (
                'id: n\n'
                'title: "Quoted title — with em dash"\n'
                'layer: knowledge\n'
                'tags:\n'
                '  - alpha\n'
                '  - beta\n'
                'content_potential: high\n'
                'content_type: technical\n'
                'content_angle: "Quoted angle"\n'
            )
            p = _write_md(root / "1_projects" / "n.md", fm, "Intro body.\n")
            before = p.read_text(encoding="utf-8")
            _run(root, "fix")
            after = p.read_text(encoding="utf-8")
            # only difference in frontmatter: content_type value
            self.assertIn("content_type: expert", after)
            self.assertNotIn("content_type: technical", after)
            # unrelated frontmatter lines preserved verbatim (quotes/indent)
            for line in ('title: "Quoted title — with em dash"', '  - alpha',
                         '  - beta'):
                self.assertIn(line, after, line)
            # the angle (a string) is separately normalized to a 1-element list
            self.assertIn('content_angle:\n  - "Quoted angle"', after)
            # exactly one content line changed + Evidence Trail added
            self.assertIn("## Evidence Trail", after)
            self.assertIn("Intro body.", after)

    def test_idempotent_after_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md", _fm(ctype="technical"))
            _run(root, "fix")
            second = _run(root, "fix")
            self.assertEqual(
                [e for e in second if e["kind"].startswith("content-type")], [])


class JudgmentRowTests(unittest.TestCase):
    def test_idea_emitted_not_applied_even_in_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md", _fm(ctype="idea"))
            events = _run(root, "fix")
            ct = [e for e in events if e["kind"] == "content-type"]
            self.assertEqual(len(ct), 1)
            self.assertEqual(ct[0]["target"], "insight")
            self.assertEqual(ct[0]["alternatives"], ["observation"])
            self.assertEqual(ct[0]["floor"], "weak")
            self.assertEqual(ct[0]["reason"], "judgment")
            self.assertFalse(ct[0]["applied"])
            # NOT written — judgment is owner's call
            self.assertIn("content_type: idea", p.read_text(encoding="utf-8"))

    def test_decision_principle_framework_default_insight_alt_expert(self):
        for raw in ("decision", "principle", "framework", "product-insight"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_md(root / "2_areas" / "n.md", _fm(ctype=raw))
                events = _run(root, "fix")
                ct = [e for e in events if e["kind"] == "content-type"][0]
                self.assertEqual(ct["target"], "insight", raw)
                self.assertEqual(ct["alternatives"], ["expert"], raw)
                self.assertFalse(ct["applied"], raw)


class UnknownAndCanonicalTests(unittest.TestCase):
    def test_unknown_value_surfaced_never_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md", _fm(ctype="wibble"))
            events = _run(root, "fix")
            unk = [e for e in events if e["kind"] == "content-type-unknown"]
            self.assertEqual(len(unk), 1)
            self.assertEqual(unk[0]["raw"], "wibble")
            self.assertIn("content_type: wibble", p.read_text(encoding="utf-8"))

    def test_canonical_types_no_event(self):
        # import the set rather than hardcode it — so the test tracks the SoT
        for raw in sorted(lcm.CANONICAL_FIVE):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _write_md(root / "1_projects" / "n.md", _fm(ctype=raw))
                events = _run(root, "scan")
                self.assertEqual(
                    [e for e in events if e["kind"].startswith("content-type")],
                    [], raw)

    def test_story_is_canonical_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md", _fm(ctype="story"))
            _run(root, "fix")
            self.assertIn("content_type: story", p.read_text(encoding="utf-8"))


class MissingFieldTests(unittest.TestCase):
    def test_missing_content_angle_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md", _fm(ctype="expert", angle=None))
            events = _run(root, "scan")
            ang = [e for e in events if e["kind"] == "content-angle"]
            self.assertEqual(len(ang), 1)

    def test_empty_content_angle_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md",
                      "layer: knowledge\ncontent_potential: high\n"
                      "content_type: expert\ncontent_angle: ''\n")
            events = _run(root, "scan")
            self.assertEqual(
                len([e for e in events if e["kind"] == "content-angle"]), 1)

    def test_missing_content_type_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md", _fm(ctype=None))
            events = _run(root, "scan")
            self.assertEqual(
                len([e for e in events if e["kind"] == "content-type-missing"]), 1)

    def test_drift_type_and_missing_angle_both_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md",
                      _fm(ctype="technical", angle=None))
            events = _run(root, "scan")
            kinds = sorted(e["kind"] for e in events)
            self.assertEqual(kinds, ["content-angle", "content-type"])


class ContentAngleFormatTests(unittest.TestCase):
    def test_string_angle_normalized_to_list_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md",
                          'layer: knowledge\ncontent_potential: high\n'
                          'content_type: insight\n'
                          'content_angle: "Why this matters"\n')
            events = _run(root, "fix")
            fmt = [e for e in events if e["kind"] == "content-angle-format"]
            self.assertEqual(len(fmt), 1)
            self.assertTrue(fmt[0]["applied"])
            text = p.read_text(encoding="utf-8")
            # converted to a 1-element list, scalar (with quotes) preserved
            self.assertIn('content_angle:\n  - "Why this matters"', text)

    def test_string_angle_scan_only_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md",
                          'layer: knowledge\ncontent_potential: high\n'
                          'content_type: insight\ncontent_angle: A plain angle\n')
            events = _run(root, "scan")
            self.assertEqual(
                len([e for e in events if e["kind"] == "content-angle-format"]), 1)
            self.assertIn("content_angle: A plain angle",
                          p.read_text(encoding="utf-8"))  # scan never writes

    def test_list_angle_unchanged_no_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md",
                      'layer: knowledge\ncontent_potential: high\n'
                      'content_type: insight\ncontent_angle:\n  - One\n  - Two\n')
            events = _run(root, "fix")
            self.assertEqual(
                [e for e in events if e["kind"].startswith("content-angle")], [])

    def test_angle_normalize_matches_note_indent(self):
        # note uses 4-space list indent elsewhere → angle list uses 4-space too
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = _write_md(root / "1_projects" / "n.md",
                          'layer: knowledge\ntags:\n    - alpha\n'
                          'content_potential: high\ncontent_type: insight\n'
                          'content_angle: Solo\n')
            _run(root, "fix")
            self.assertIn("content_angle:\n    - Solo", p.read_text(encoding="utf-8"))

    def test_idempotent_after_angle_normalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md",
                      'layer: knowledge\ncontent_potential: high\n'
                      'content_type: insight\ncontent_angle: Solo\n')
            _run(root, "fix")
            second = _run(root, "fix")
            self.assertEqual(
                [e for e in second if e["kind"].startswith("content-angle")], [])


class ScopeTests(unittest.TestCase):
    def test_no_content_potential_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "1_projects" / "n.md",
                      "layer: knowledge\ncontent_type: technical\n")
            self.assertEqual(_run(root, "scan"), [])

    def test_out_of_para_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root / "_system" / "views" / "n.md", _fm(ctype="technical"))
            _write_md(root / "_records" / "meetings" / "n.md", _fm(ctype="idea"))
            self.assertEqual(_run(root, "scan"), [])


if __name__ == "__main__":
    unittest.main()
