"""Tests for the people half of the identity audit.

The project side proved the surfaces; this side proves the generalisation.
Three things have to hold, and each one is a way the contract could be claimed
without being kept:

  * the people registry parses — live rows, the three prose retirement shapes,
    and a stale row read as a tier drop rather than as a retirement;
  * the surface set is DATA — the people registry declares four roles and, by
    omission, states that it has no node container and no hub, and the scan
    honours the omission. A synthetic third registry proves the same code
    serves a registry nobody wrote a branch for;
  * the owner is never drift — the identity every base carries and no registry
    table declares.

Every name here is synthetic (`ivan-petrov` and friends, the placeholders the
system contract itself uses). Engine code never names a real person.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import identity_audit as ia  # type: ignore
from _common import (  # type: ignore
    IDENTITY_KIND_UNKNOWN,
    RegistryEntry,
    owner_identity,
    parse_people_registry,
    people_registry_section_category,
    transliterate_identifier,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

def _scaffold(root: Path) -> None:
    for sub in (
        "_records/meetings", "1_projects", "2_areas", "3_resources/people",
        "4_archive", "5_meta/mocs", "_system/views", "_system/state",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)


# The registry as it is on disk today: `## Removed` carries a free-text reason
# with the kind and the successor embedded in prose. The reference tables at
# the tail are the trap — their first cells are perfectly good slugs.
_PEOPLE_MD = """# People Registry

## People

| ID | Name | Role | Org | Profile | Tier | Mentions | Last |
|---|---|---|---|---|---|---|---|
| ivan-petrov | Ivan Petrov | Dev | acme | [[ivan-petrov]] | 1 | 12 | 2026-01-02 |
| anna-orlova | Anna Orlova | QA | acme | [[anna-orlova]] | 1 | 4 | 2026-01-02 |
| petr-sinitsyn | Petr Sinitsyn | Analyst | acme | [[petr-sinitsyn]] | 2 | 2 | 2026-01-02 |

## Removed

| ID | Reason |
|----|--------|
| ivan | Merged with ivan-petrov (same person) |
| anna-orlofa | Renamed to anna-orlova — transcription artefact |
| ghost-name | Unknown — author couldn't identify (2026-01-02) |
| mystery-row | resolved offline |
| vague-merge | Merged with someone we could not place |

## ID Generation Rules

1. Format: `firstname-lastname`.

## Org Reference

| Org ID | Full Name |
|--------|-----------|
| acme | Acme Corp |

## Role Reference

| Role ID | Description |
|---------|-------------|
| dev | Developer |
| qa | QA Engineer |

## Stale People

| ID | Name | Role | Org | Profile | Tier | Mentions | Last | Reason |
|---|---|---|---|---|---|---|---|---|
| olga-brave | Olga Brave | PM | acme | [[olga-brave]] | stale | 1 | 2025-01-01 | no contact for a year |
"""

# The same registry after the schema migration: the kind and the successor are
# declared columns. The prose is still there and still disagrees on one row —
# the declared column must win.
_PEOPLE_MD_DECLARED = """# People Registry

## People

| ID | Name | Role | Org | Profile | Tier | Mentions | Last |
|---|---|---|---|---|---|---|---|
| ivan-petrov | Ivan Petrov | Dev | acme | [[ivan-petrov]] | 1 | 12 | 2026-01-02 |

## Removed

| ID | Kind | Successor | Date | Reason |
|----|------|-----------|------|--------|
| ivan | merge | `ivan-petrov` | 2026-01-02 | Merged with somebody-else |
| ghost-name | void | - | 2026-01-02 | never existed |
"""


def _write_people(root: Path, body: str = _PEOPLE_MD) -> None:
    (root / "3_resources" / "people" / "PEOPLE.md").write_text(body, encoding="utf-8")


def _write_soul(root: Path, name: str = "Пётр Синицын") -> None:
    (root / "_system").mkdir(parents=True, exist_ok=True)
    (root / "_system" / "SOUL.md").write_text(
        f"---\nid: soul\n---\n\n# SOUL\n\n## Identity\n\n- **Name:** {name}\n"
        "- **Role:** somewhere\n",
        encoding="utf-8",
    )


def _write_note(
    root: Path,
    rel: str,
    *,
    people: list[str] | None = None,
    tags: list[str] | None = None,
    body: str = "body\n",
) -> Path:
    fm = f"id: {Path(rel).stem}\n"
    if people is not None:
        fm += "people:\n" + "".join(f"  - {p}\n" for p in people)
    if tags is not None:
        fm += "tags:\n" + "".join(f"  - {t}\n" for t in tags)
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")
    return path


def _base(tmp: str, *, soul: bool = False, registry: str = _PEOPLE_MD) -> Path:
    root = Path(tmp)
    _scaffold(root)
    _write_people(root, registry)
    if soul:
        _write_soul(root)
    return root


def _residue_of(result: dict, identity: str) -> int:
    """Residue attributed to ONE identity.

    The shared fixture deliberately contains a malformed row (`vague-merge`
    declares a merge and names no resolvable successor), so a global
    `residue_count == 0` no longer says what these tests mean. Each one is
    about one identity; the assertion now says so.
    """
    for ident in result["identities"]:
        if ident["id"] == identity:
            return ident["residue_count"]
    return 0


def _people_findings(root: Path, identity: str | None = None) -> list[dict]:
    out: list[dict] = []
    result = ia.audit(root, specs=(ia.PEOPLE_SPEC,))
    for ident in result["identities"]:
        if identity is None or ident["id"] == identity:
            out.extend(ident["findings"])
    return out


# -----------------------------------------------------------------------------
# Registry parsing
# -----------------------------------------------------------------------------

class PeopleRegistryParsingTests(unittest.TestCase):
    def test_live_rows_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = parse_people_registry(_base(tmp))
            live = {k for k, v in reg.items() if v.category == "person"}
            self.assertEqual(
                live,
                {"ivan-petrov", "anna-orlova", "petr-sinitsyn", "olga-brave"},
            )

    def test_reference_tables_are_not_people(self):
        """Org and role tables sit in this file and have slug-shaped first
        cells. A default-to-person parser registers `dev` as a colleague."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = parse_people_registry(_base(tmp))
            for not_a_person in ("acme", "dev", "qa"):
                self.assertNotIn(not_a_person, reg)

    def test_stale_row_is_live_not_retired(self):
        """A tier drop is archival. It leaves the identifier valid, so a stale
        person is not a retirement and their references are not residue."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = parse_people_registry(_base(tmp))
            self.assertEqual(reg["olga-brave"].category, "person")
            self.assertIsNone(reg["olga-brave"].successor)
            self.assertIsNone(reg["olga-brave"].kind)

    def test_prose_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = parse_people_registry(_base(tmp))
            entry = reg["ivan"]
            self.assertEqual(entry.category, "consolidated")
            self.assertEqual(entry.kind, "merge")
            self.assertEqual(entry.successor, "ivan-petrov")

    def test_prose_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = parse_people_registry(_base(tmp))["anna-orlofa"]
            self.assertEqual(entry.kind, "rename")
            self.assertEqual(entry.successor, "anna-orlova")

    def test_prose_void_has_no_successor(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = parse_people_registry(_base(tmp))["ghost-name"]
            self.assertEqual(entry.kind, "void")
            self.assertIsNone(entry.successor)

    def test_unreadable_reason_is_unknown_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = parse_people_registry(_base(tmp))["mystery-row"]
            self.assertEqual(entry.kind, "unknown")
            self.assertIsNone(entry.successor)

    def test_merge_without_resolvable_successor_names_none(self):
        """The kind is readable, the successor is not. Reporting a merge with
        no successor is the honest answer; inventing one repoints live
        references at whatever word followed the marker."""
        with tempfile.TemporaryDirectory() as tmp:
            entry = parse_people_registry(_base(tmp))["vague-merge"]
            self.assertEqual(entry.kind, "merge")
            self.assertIsNone(entry.successor)

    def test_declared_columns_win_over_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = parse_people_registry(_base(tmp, registry=_PEOPLE_MD_DECLARED))
            self.assertEqual(reg["ivan"].kind, "merge")
            self.assertEqual(reg["ivan"].successor, "ivan-petrov")
            self.assertEqual(reg["ghost-name"].kind, "void")
            self.assertIsNone(reg["ghost-name"].successor)

    def test_retirement_heading_synonyms(self):
        """Which heading the retirement table carries is not settled across
        clones: the live registry says `Removed`, and the same rename that
        gave the project registry `Retired Identifiers` may reach this one.
        Every name resolves to the same category — a heading the parser cannot
        see is not skipped, it is read as a section of live people."""
        for heading in (
            "## Removed",
            "## Retired Identifiers",
            "## Retired identifiers (merge / rename / void)",
            "## Consolidated / superseded",
        ):
            self.assertEqual(
                people_registry_section_category(heading), "consolidated", heading
            )

    def test_live_heading_synonyms(self):
        for heading, expected in (
            ("# People Registry", "person"),
            ("## People", "person"),
            ("## Owner", "person"),
            ("## Stale People", "person"),
            ("## Org Reference", None),
            ("## Role Reference", None),
            ("## Profile Template", None),
            ("## ID Generation Rules", None),
        ):
            self.assertEqual(
                people_registry_section_category(heading), expected, heading
            )

    def test_missing_registry_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            self.assertEqual(parse_people_registry(root), {})


# -----------------------------------------------------------------------------
# Declared surfaces — and the undeclared ones
# -----------------------------------------------------------------------------

class PeopleSurfaceTests(unittest.TestCase):
    def test_field_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "_records/meetings/m1.md", people=["ivan"])
            f = _people_findings(root, "ivan")
            self.assertEqual([x["surface"] for x in f], ["field"])
            self.assertEqual(f[0]["target"], "ivan-petrov")
            self.assertEqual(f[0]["surface_class"], "live")
            self.assertIn("people:", f[0]["reason"])

    def test_tag_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", tags=["person/ivan"])
            f = _people_findings(root, "ivan")
            self.assertEqual([x["surface"] for x in f], ["tag"])
            self.assertEqual(f[0]["target"], "person/ivan-petrov")

    def test_correctly_namespaced_live_person_is_not_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", tags=["person/ivan-petrov"])
            self.assertEqual(_people_findings(root, "ivan-petrov"), [])

    def test_wikilink_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(
                root, "2_areas/a.md", body="see [[ivan]] and [[ivan|Ivan]]\n"
            )
            _write_note(root, "3_resources/people/ivan-petrov.md")
            f = _people_findings(root, "ivan")
            self.assertEqual([x["surface"] for x in f], ["wikilink", "wikilink"])
            # The suggestion names the successor's profile card, which is the
            # people registry's canonical node — it declares no hub and no
            # container, so the card is the only role that can answer.
            self.assertEqual(f[0]["target"], "[[ivan-petrov]]")
            self.assertEqual(f[0]["successor"], "ivan-petrov")

    def test_node_card_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            (root / "3_resources" / "people" / "ivan.md").write_text(
                "---\nid: ivan\n---\n\n# Ivan\n", encoding="utf-8"
            )
            f = _people_findings(root, "ivan")
            self.assertEqual([x["surface"] for x in f], ["node-card"])
            self.assertEqual(f[0]["path"], "3_resources/people/ivan.md")

    def test_undeclared_roles_are_never_reported(self):
        """The registry declares no node container and no hub. Both exist on
        disk here; neither is a surface of this identity, because the registry
        says the role does not exist for it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            (root / "3_resources" / "people" / "ivan").mkdir()
            (root / "3_resources" / "people" / "ivan" / "README.md").write_text(
                "---\nid: ivan\n---\n\n# Ivan\n", encoding="utf-8"
            )
            (root / "5_meta" / "mocs" / "hub-ivan.md").write_text(
                "---\nid: hub-ivan\n---\n\n# hub\n", encoding="utf-8"
            )
            surfaces = {f["surface"] for f in _people_findings(root, "ivan")}
            self.assertNotIn("node-container", surfaces)
            self.assertNotIn("hub", surfaces)

    def test_matching_is_exact_never_substring(self):
        """`ivan` is retired; `ivan-petrov` is the person it merged into. A
        substring match turns every reference to the live person into residue
        — and would rewrite them into `ivan-petrov-petrov`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(
                root, "2_areas/a.md",
                people=["ivan-petrov"], tags=["person/ivan-petrov"],
                body="[[ivan-petrov]] and [[ivan-petrov#section]]\n",
            )
            self.assertEqual(_people_findings(root, "ivan"), [])

    def test_stale_person_leaves_no_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(
                root, "2_areas/a.md",
                people=["olga-brave"], tags=["person/olga-brave"],
                body="[[olga-brave]]\n",
            )
            self.assertEqual(_people_findings(root, "olga-brave"), [])

    def test_void_identity_is_frozen_not_residue(self):
        """A void retirement has no successor, so its references have nowhere
        to go. The contract freezes them and excludes them from the check."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(
                root, "2_areas/a.md",
                people=["ghost-name"], tags=["person/ghost-name"],
                body="[[ghost-name]]\n",
            )
            result = ia.audit(root, specs=(ia.PEOPLE_SPEC,))
            self.assertEqual(_residue_of(result, "ghost-name"), 0)
            ghost = next(i for i in result["identities"] if i["id"] == "ghost-name")
            self.assertEqual(ghost["excluded"], "void")
            self.assertEqual(ghost["findings"], [])

    def test_unknown_kind_is_still_audited(self):
        """An unreadable retirement row is not a void one. Freezing it would
        turn "the scanner could not read this" into "the contract says leave
        it alone"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", tags=["person/mystery-row"])
            f = _people_findings(root, "mystery-row")
            self.assertEqual([x["surface"] for x in f], ["tag"])
            self.assertIsNone(f[0]["target"])


# -----------------------------------------------------------------------------
# The owner
# -----------------------------------------------------------------------------

class OwnerTests(unittest.TestCase):
    def test_identifier_derived_from_soul(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp, soul=True)
            self.assertEqual(owner_identity(root), "petr-sinitsyn")

    def test_declared_owner_row_wins_over_derivation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_soul(root)
            _write_people(root, _PEOPLE_MD + """
## Owner

| ID | Name | Profile |
|---|---|---|
| ivan-petrov | Ivan Petrov | [[ivan-petrov]] |
""")
            self.assertEqual(owner_identity(root), "ivan-petrov")

    def test_owner_row_is_a_live_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_people(root, _PEOPLE_MD + """
## Owner

| ID | Name | Profile |
|---|---|---|
| owner-person | Owner | [[owner-person]] |
""")
            reg = parse_people_registry(root)
            self.assertEqual(reg["owner-person"].category, "person")

    def test_owner_is_never_reported(self):
        """The owner's identifier is on hundreds of live surfaces and in no
        registry table. Here the registry even retires it by mistake — the
        audit still refuses to call the owner of the base drift."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_soul(root)  # owner = petr-sinitsyn
            _write_people(root, _PEOPLE_MD.replace(
                "| mystery-row | resolved offline |",
                "| petr-sinitsyn | Merged with ivan-petrov |",
            ))
            _write_note(
                root, "2_areas/a.md",
                people=["petr-sinitsyn"], tags=["person/petr-sinitsyn"],
                body="[[petr-sinitsyn]]\n",
            )
            result = ia.audit(root, specs=(ia.PEOPLE_SPEC,))
            self.assertEqual(result["owner"], "petr-sinitsyn")
            owner_row = next(
                i for i in result["identities"] if i["id"] == "petr-sinitsyn"
            )
            self.assertEqual(owner_row["excluded"], "owner")
            self.assertEqual(owner_row["findings"], [])
            self.assertEqual(_residue_of(result, "petr-sinitsyn"), 0)

    def test_transliteration(self):
        self.assertEqual(transliterate_identifier("Пётр Синицын"), "petr-sinitsyn")
        self.assertEqual(transliterate_identifier("John Doe"), "john-doe")
        self.assertIsNone(transliterate_identifier(""))
        self.assertIsNone(transliterate_identifier("   "))

    def test_absent_soul_leaves_owner_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            self.assertIsNone(owner_identity(root))


# -----------------------------------------------------------------------------
# The surface set is data — a third registry proves it
# -----------------------------------------------------------------------------

_LENS_REGISTRY = {
    "old-lens": RegistryEntry(
        entity_id="old-lens", category="consolidated",
        successor="new-lens", status="merged", kind="merge",
    ),
    "new-lens": RegistryEntry(entity_id="new-lens", category="lens"),
}


class ThirdRegistryTests(unittest.TestCase):
    """A registry the scan has never heard of, added as data only.

    No new branch, no new function, no edit to the scan: a `RegistrySpec` with
    two declared roles. If this needed code, the contract's own sanity test
    would have failed — a new kind of identity must be a row in a declaration,
    not a rule inside the procedure.
    """

    SPEC = ia.RegistrySpec(
        name="lens",
        registry_path="_system/registries/AGENT_LENSES.md",
        parse=lambda root: dict(_LENS_REGISTRY),
        surfaces=(ia.SURFACE_TAG, ia.SURFACE_WIKILINK),
        membership_field=None,
        node_dir=None,
        expected_namespace={"lens": "lens", "consolidated": None},
        audited_categories=("consolidated",),
    )

    def test_declared_roles_are_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            _write_note(
                root, "2_areas/a.md",
                tags=["lens/old-lens"], body="[[old-lens]]\n",
            )
            result = ia.audit(root, specs=(self.SPEC,))
            surfaces = sorted(
                f["surface"] for i in result["identities"] for f in i["findings"]
            )
            self.assertEqual(surfaces, ["tag", "wikilink"])
            self.assertEqual(result["residue_count"], 2)
            self.assertEqual(
                result["registries"][0]["registry_path"],
                "_system/registries/AGENT_LENSES.md",
            )

    def test_undeclared_roles_are_absent(self):
        """This registry declares no membership field and no node. A note
        carrying `projects: [old-lens]` and a card at `1_projects/old-lens.md`
        are not its surfaces, and reporting either would be the scan inventing
        a role the registry never claimed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scaffold(root)
            (root / "1_projects" / "old-lens.md").write_text(
                "---\nid: old-lens\n---\n\n# old\n", encoding="utf-8"
            )
            path = root / "2_areas" / "a.md"
            path.write_text(
                "---\nid: a\nprojects:\n  - old-lens\n---\nbody\n",
                encoding="utf-8",
            )
            result = ia.audit(root, specs=(self.SPEC,))
            self.assertEqual(result["residue_count"], 0)


# -----------------------------------------------------------------------------
# Report and exit
# -----------------------------------------------------------------------------

class ReportTests(unittest.TestCase):
    def _run(self, root: Path, argv: list[str]) -> int:
        buf = io.StringIO()
        with redirect_stdout(buf):
            return ia.main(["--root", str(root), *argv])

    def test_people_residue_fails_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", tags=["person/ivan"])
            self.assertEqual(self._run(root, ["--report", "--fail-on-residue"]), 2)

    def test_clean_people_side_passes_the_gate(self):
        # The declared-column fixture, whose retirement rows are all
        # well-formed. The shared prose fixture deliberately holds a malformed
        # one, and a base with a malformed row is not clean.
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp, registry=_PEOPLE_MD_DECLARED)
            _write_note(root, "2_areas/a.md", tags=["person/ivan-petrov"])
            self.assertEqual(self._run(root, ["--report", "--fail-on-residue"]), 0)

    def test_json_report_carries_both_registries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp, soul=True)
            _write_note(root, "2_areas/a.md", tags=["person/ivan"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                ia.main(["--root", str(root), "--report", "--json"])
            data = json.loads(buf.getvalue())
            self.assertEqual(
                [r["registry_path"] for r in data["registries"]],
                ["1_projects/PROJECTS.md", "3_resources/people/PEOPLE.md"],
            )
            ident = next(i for i in data["identities"] if i["id"] == "ivan")
            self.assertEqual(ident["registry"], "people")
            self.assertEqual(ident["registry_path"], "3_resources/people/PEOPLE.md")
            self.assertEqual(ident["kind"], "merge")
            self.assertEqual(data["owner"], "petr-sinitsyn")


if __name__ == "__main__":
    unittest.main()
