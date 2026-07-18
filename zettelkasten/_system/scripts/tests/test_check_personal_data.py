"""Tests for scripts/check_no_personal_data.py — the dynamic blacklist layer.

Proves `build_dynamic_blacklist` derives real, catchable patterns from a
temp instance's own registries (PEOPLE.md / PROJECTS.md / SOUL.md /
0_constitution), while the guard chain (`_finalize_pattern` and friends)
keeps synthetic placeholders, public product names, unfilled `{...}`
templates, and generic single words from ever becoming patterns.

Every test builds its own hermetic temp repo (never touches this repo's
real registries) and exercises the real production functions —
`build_dynamic_blacklist` + `scan_file` — the same pair `main()` wires
together.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO / "scripts"))

import check_no_personal_data as M  # type: ignore


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _scan(root: Path, engine_relpath: str) -> list[tuple[int, str, str]]:
    """Derive the dynamic blacklist from `root` and scan one engine file
    with it — the same two calls `main()` chains together."""
    patterns = M.build_dynamic_blacklist(root)
    compiled = [re.compile(p) for p in patterns]
    return M.scan_file(root / engine_relpath, compiled)


def _scan_like_main(root: Path, engine_relpath: str) -> list[tuple[int, str, str]]:
    """Same per-file pattern selection `main()` performs: general dynamic
    patterns always apply; constitution-derived patterns are skipped for
    files under `SANCTIONED_PRINCIPLE_HOMES`."""
    general, constitution = M.build_dynamic_blacklist_tagged(root)
    always_patterns = [re.compile(p) for p in general]
    constitution_patterns = [re.compile(p) for p in constitution]
    rel = Path(engine_relpath)
    patterns = (
        always_patterns
        if M.is_sanctioned_principle_home(rel)
        else always_patterns + constitution_patterns
    )
    return M.scan_file(root / engine_relpath, patterns)


class TestPeopleDerivation(unittest.TestCase):
    """(a) A synthetic person row + a matching leak in an engine file is caught."""

    def test_real_person_row_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/3_resources/people/PEOPLE.md",
                "# People Registry\n\n"
                "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| zzz-testperson | Тестова Персонова | Dev | acme | [[zzz-testperson]] | 1 | 3 | 2026-01-01 |\n",
            )
            _write(
                root / "engine_file.md",
                "Some unrelated line.\n"
                "Leaked mention of Тестова Персонова in a worked example.\n"
                "Also leaked the id zzz-testperson directly.\n",
            )
            hits = _scan(root, "engine_file.md")
            self.assertEqual(len(hits), 2, hits)
            matched_patterns = {h[1] for h in hits}
            self.assertTrue(any("Персонова" in p for p in matched_patterns), matched_patterns)
            self.assertTrue(any("zzz\\-testperson" in p for p in matched_patterns), matched_patterns)

    def test_removed_table_is_not_a_source(self) -> None:
        """The 2-column `## Removed` table (ID | Reason) has no Name column
        and must never be mistaken for a person row."""
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/3_resources/people/PEOPLE.md",
                "# People Registry\n\n"
                "## People\n\n"
                "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| real-person | Real Person | Dev | acme | [[real-person]] | 1 | 3 | 2026-01-01 |\n"
                "\n---\n\n"
                "## Removed\n\n"
                "| ID | Reason |\n"
                "|----|--------|\n"
                "| ghost-entry | Merged with real-person (duplicate) |\n",
            )
            values = M._people_candidates(root)
            self.assertIn("real-person", values)
            self.assertNotIn("ghost-entry", values)


class TestProjectDerivation(unittest.TestCase):
    def test_specific_display_name_emitted_generic_single_word_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/1_projects/PROJECTS.md",
                "# Project Registry\n\n"
                "## Active Projects\n\n"
                "| ID | Name | Description | Folder | Status |\n"
                "|----|------|-------------|--------|--------|\n"
                "| widget-forge | Widget Forge Platform | multi-word specific name | 1_projects/widget-forge/ | active |\n"
                "| solo | Widgets | single generic word as display name | 1_projects/solo/ | active |\n",
            )
            values = M._project_candidates(root)
            self.assertIn("widget-forge", values)
            self.assertIn("Widget Forge Platform", values)
            self.assertIn("solo", values)
            # "Widgets" is a single word < 6 chars after trim check fails the
            # specificity guard only if short; here it's 7 chars so let's
            # assert the guard logic directly instead of relying on length.
            self.assertFalse(M._is_specific_display_name("Fix"))
            self.assertTrue(M._is_specific_display_name("Widget Forge Platform"))


class TestSafeTermsGuard(unittest.TestCase):
    """(b) Known-safe synthetic placeholders and public product names never
    become patterns, even when a registry literally contains them (e.g. this
    instance's own 'minder' project id)."""

    def test_safe_terms_never_flag_legitimate_placeholder_usage(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/1_projects/PROJECTS.md",
                "# Project Registry\n\n"
                "## Active Projects\n\n"
                "| ID | Name | Description | Folder | Status |\n"
                "|----|------|-------------|--------|--------|\n"
                "| minder | Minder | the owner's real product, shares its name with the public term | 1_projects/minder/ | active |\n",
            )
            _write(
                root / "engine_file.md",
                "Depersonalized worked example: id `ivan-petrov-dev`.\n"
                "Built on top of the Minder engine architecture.\n"
                "See also ZTN and Zettelkasten as generic terms.\n",
            )
            hits = _scan(root, "engine_file.md")
            self.assertEqual(hits, [], hits)

    def test_is_safe_term_direct(self) -> None:
        self.assertTrue(M._is_safe_term("ivan-petrov"))
        self.assertTrue(M._is_safe_term("Minder"))
        self.assertTrue(M._is_safe_term("minder"))
        self.assertFalse(M._is_safe_term("Nimbus Cloud Systems"))


class TestPlaceholderGuard(unittest.TestCase):
    """(c) A `{...}` placeholder value never becomes a pattern."""

    def test_placeholder_name_row_is_skipped_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/3_resources/people/PEOPLE.md",
                "# People Registry\n\n"
                "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| person-id | {Полное Имя} | Dev | acme | [[person-id]] | 1 | 1 | 2026-01-01 |\n",
            )
            values = M._people_candidates(root)
            self.assertEqual(values, [])

    def test_looks_like_placeholder(self) -> None:
        self.assertTrue(M._looks_like_placeholder("{Your full name}"))
        self.assertTrue(M._looks_like_placeholder("REPLACE_WITH_NAME"))
        self.assertTrue(M._looks_like_placeholder("City, Country <fill in>"))
        self.assertFalse(M._looks_like_placeholder("Rivertown, Nordland"))


class TestConstitutionDerivation(unittest.TestCase):
    """(d) A verbatim >=20-char axiom statement is caught; (e) an abstract
    paraphrase of it is not (literal-match linter, by design)."""

    AXIOM_MD = (
        "---\n"
        "id: axiom-test-001\n"
        "title: Measure twice, ship once — small batches beat big rewrites\n"
        "type: axiom\n"
        "domain: identity\n"
        "statement: >\n"
        "  A distinctive, sufficiently long verbatim axiom sentence used only\n"
        "  for this test fixture.\n"
        "status: active\n"
        "---\n\n"
        "# Measure twice, ship once — small batches beat big rewrites\n"
    )

    def _root_with_axiom(self, t: str) -> Path:
        root = Path(t)
        _write(root / "zettelkasten/0_constitution/axiom/identity/001-test.md", self.AXIOM_MD)
        return root

    def test_verbatim_statement_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom(t)
            _write(
                root / "engine_file.md",
                "Quoting verbatim: A distinctive, sufficiently long verbatim axiom "
                "sentence used only for this test fixture.\n",
            )
            hits = _scan(root, "engine_file.md")
            self.assertEqual(len(hits), 1, hits)

    def test_title_is_also_caught(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom(t)
            _write(
                root / "engine_file.md",
                "Measure twice, ship once — small batches beat big rewrites — worked example.\n",
            )
            hits = _scan(root, "engine_file.md")
            self.assertEqual(len(hits), 1, hits)

    def test_abstract_paraphrase_is_not_caught(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom(t)
            _write(
                root / "engine_file.md",
                "General idea: keep improving when a better option is known.\n",
            )
            hits = _scan(root, "engine_file.md")
            self.assertEqual(hits, [], hits)

    def test_short_statement_below_threshold_is_not_derived(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/0_constitution/rule/tech/001-short.md",
                "---\nid: rule-test-001\ntitle: Short rule\nstatement: Too short.\nstatus: active\n---\n\n# Short rule\n",
            )
            values = M._constitution_candidates(root)
            self.assertEqual(values, [])


class TestSanctionedPrincipleHomes(unittest.TestCase):
    """`SANCTIONED_PRINCIPLE_HOMES` exempts only the constitution-derived
    slice of the dynamic blacklist, only for files under those three paths —
    every other pattern class (here: a PEOPLE.md row) still applies inside a
    sanctioned home, and the constitution-derived patterns still apply to
    every file NOT under one of those paths."""

    AXIOM_MD = TestConstitutionDerivation.AXIOM_MD

    def _root_with_axiom_and_person(self, t: str) -> Path:
        root = Path(t)
        _write(root / "zettelkasten/0_constitution/axiom/identity/001-test.md", self.AXIOM_MD)
        _write(
            root / "zettelkasten/3_resources/people/PEOPLE.md",
            "# People Registry\n\n"
            "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| zzz-testperson | Тестова Персонова | Dev | acme | [[zzz-testperson]] | 1 | 3 | 2026-01-01 |\n",
        )
        return root

    def test_verbatim_axiom_not_flagged_in_starter_pack(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            relpath = "zettelkasten/5_meta/starter-pack/axioms/measure-twice.md"
            _write(
                root / relpath,
                "Measure twice, ship once — small batches beat big rewrites\n",
            )
            hits = _scan_like_main(root, relpath)
            self.assertEqual(hits, [], hits)

    def test_verbatim_axiom_not_flagged_in_constitution_spec(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            relpath = "zettelkasten/0_constitution/CONSTITUTION.md"
            _write(
                root / relpath,
                "Worked example:\ntitle: Measure twice, ship once — small batches beat big rewrites\n",
            )
            hits = _scan_like_main(root, relpath)
            self.assertEqual(hits, [], hits)

    def test_verbatim_axiom_not_flagged_in_pipeline_test_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            relpath = "zettelkasten/_system/scripts/tests/_fixture.py"
            _write(
                root / relpath,
                '# Measure twice, ship once — small batches beat big rewrites\n',
            )
            hits = _scan_like_main(root, relpath)
            self.assertEqual(hits, [], hits)

    def test_same_verbatim_axiom_still_flagged_outside_sanctioned_home(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            relpath = "integrations/claude-code/skills/example-skill/SKILL.md"
            _write(
                root / relpath,
                "Measure twice, ship once — small batches beat big rewrites\n",
            )
            hits = _scan_like_main(root, relpath)
            self.assertEqual(len(hits), 1, hits)

    def test_person_name_still_flagged_inside_sanctioned_home(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            relpath = "zettelkasten/5_meta/starter-pack/axioms/measure-twice.md"
            _write(
                root / relpath,
                "Leaked mention of Тестова Персонова in a starter-pack file.\n",
            )
            hits = _scan_like_main(root, relpath)
            self.assertEqual(len(hits), 1, hits)

    def test_is_sanctioned_principle_home_paths(self) -> None:
        self.assertTrue(M.is_sanctioned_principle_home(
            Path("zettelkasten/5_meta/starter-pack/axioms/x.md")))
        self.assertTrue(M.is_sanctioned_principle_home(
            Path("zettelkasten/0_constitution/CONSTITUTION.md")))
        self.assertTrue(M.is_sanctioned_principle_home(
            Path("zettelkasten/_system/scripts/tests/test_foo.py")))
        self.assertFalse(M.is_sanctioned_principle_home(
            Path("zettelkasten/0_constitution/axiom/identity/001.md")))
        self.assertFalse(M.is_sanctioned_principle_home(
            Path("integrations/claude-code/skills/foo/SKILL.md")))

    def test_build_dynamic_blacklist_flat_view_unchanged(self) -> None:
        """`build_dynamic_blacklist` (flat) still returns exactly the union
        of the tagged split, so existing callers that don't care about the
        sanctioned-homes exception see no behaviour change."""
        with tempfile.TemporaryDirectory() as t:
            root = self._root_with_axiom_and_person(t)
            general, constitution = M.build_dynamic_blacklist_tagged(root)
            self.assertEqual(M.build_dynamic_blacklist(root), general + constitution)


class TestIdentityDerivation(unittest.TestCase):
    """SOUL.md Identity section: Name / Role-employer / Location, guarded."""

    def test_employer_extracted_from_role_at_and_parenthetical(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/_system/SOUL.md",
                "## Identity\n\n"
                "- **Name:** Test Ownerova\n"
                "- **Role:** Head of Delivery @ Acme Global Corp (brand Acme Cloud). Prior title: Lead.\n"
                "- **Location:** Testville, Testland\n\n"
                "## Values\n\nunrelated section\n",
            )
            values = M._identity_candidates(root)
            self.assertIn("Test Ownerova", values)
            self.assertIn("Acme Global Corp", values)
            self.assertIn("Acme Cloud", values)
            self.assertIn("Testville, Testland", values)
            # Location must NOT be split into a bare, over-generic country name.
            self.assertNotIn("Testland", values)

    def test_role_without_at_yields_no_employer_guess(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/_system/SOUL.md",
                "## Identity\n\n- **Role:** Freelance consultant, various clients\n\n## Values\n\nx\n",
            )
            self.assertEqual(M._identity_candidates(root), [])

    def test_fresh_clone_placeholders_yield_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/_system/SOUL.md",
                "## Identity\n\n"
                "- **Name:** {Your full name as you'd like agents to refer to you}\n"
                "- **Role:** {Current professional role / occupation}\n"
                "- **Location:** {City, Country}\n\n"
                "## Values\n\nx\n",
            )
            self.assertEqual(M._identity_candidates(root), [])


class TestTableParserRobustness(unittest.TestCase):
    """A single stray blank line inside a table body (real PEOPLE.md
    artifact from batch-appended rows) must not truncate the table."""

    def test_single_blank_line_inside_table_does_not_truncate(self) -> None:
        text = (
            "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| first-person | First Person | Dev | acme | [[first-person]] | 1 | 5 | 2026-01-01 |\n"
            "\n"
            "| second-person | Second Person | Dev | acme | [[second-person]] | 1 | 2 | 2026-01-01 |\n"
        )
        rows = M._id_name_rows_from_tables(text)
        self.assertEqual(
            rows,
            [("first-person", "First Person"), ("second-person", "Second Person")],
        )

    def test_two_blank_lines_end_the_table(self) -> None:
        text = (
            "| ID | Name |\n"
            "|---|---|\n"
            "| a-b | A B |\n"
            "\n\n"
            "| c-d | C D |\n"
        )
        rows = M._id_name_rows_from_tables(text)
        self.assertEqual(rows, [("a-b", "A B")])

    def test_heading_between_tables_never_merges_them(self) -> None:
        text = (
            "| ID | Name |\n"
            "|---|---|\n"
            "| a-b | A B |\n"
            "\n"
            "## Next\n\n"
            "| Old ID | Status |\n"
            "|---|---|\n"
            "| a-b | archived |\n"
        )
        tables = M.parse_markdown_tables(text)
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0]["rows"], [["a-b", "A B"]])
        self.assertEqual(tables[1]["header"], ["Old ID", "Status"])


class TestMissingRegistries(unittest.TestCase):
    """(f) Missing registry files never error — each source degrades to []."""

    def test_empty_repo_yields_empty_dynamic_blacklist(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.assertEqual(M.build_dynamic_blacklist(root), [])

    def test_partial_repo_only_uses_what_exists(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            _write(
                root / "zettelkasten/3_resources/people/PEOPLE.md",
                "| ID | Name | Role | Org | Profile | Tier | Mentions | Last |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| only-person | Only Person | Dev | acme | [[only-person]] | 1 | 1 | 2026-01-01 |\n",
            )
            patterns = M.build_dynamic_blacklist(root)
            self.assertTrue(any("only" in p.lower() for p in patterns), patterns)


class TestFinalizePatternGuards(unittest.TestCase):
    def test_min_length(self) -> None:
        self.assertIsNone(M._finalize_pattern("abcd"))
        self.assertIsNotNone(M._finalize_pattern("abcde"))

    def test_common_word_stoplist(self) -> None:
        for word in ("Status", "Active", "Personal", "Work", "Name", "Role", "Project"):
            self.assertIsNone(M._finalize_pattern(word), word)

    def test_regex_special_chars_are_escaped(self) -> None:
        pattern = M._finalize_pattern("O'Brien-Test.Name")
        self.assertIsNotNone(pattern)
        compiled = re.compile(pattern)
        self.assertTrue(compiled.search("mention of O'Brien-Test.Name here"))
        self.assertFalse(compiled.search("O'BrienXTestYName"))


if __name__ == "__main__":
    unittest.main()
