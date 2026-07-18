"""Tests for minder_query.py — the lens-style thin remit resolver.

Isolated to a tempdir ZTN base passed via the `base` param — no env
mutation, no LLM, no network. Exercises remit resolution across every axis
(globs / tags / project_ids / person_ids / hubs / decision_notes / all), the
fail-closed empty remit, honor-system privacy (in-remit sensitive notes kept,
out-of-remit sensitive foreign entities dropped with no stub), and the full
`_common.CONCEPT_TYPES_ALL` type vocabulary with raw-type preservation.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import minder_query as x  # noqa: E402
import roles_common as rc  # noqa: E402
from _common import CONCEPT_TYPES_ALL  # noqa: E402


class MinderQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _note(self, rel: str, body: str = "Body text.\n", **fm) -> None:
        p = self.base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) if fm else ""
        p.write_text(f"---\n{fm_text}---\n{body}", encoding="utf-8")

    def _paths(self, result: dict) -> list[str]:
        return [u["path"] for u in result["units"]]

    def _write_config(self, role_id: str, remit: dict) -> None:
        """Seed a minimal valid `_system/roles/<id>/config.yml` with `remit`."""
        cfg = {
            "id": role_id,
            "parts": [{"id": "board", "kind": "ledger"}],
            "remit": remit,
            "cadence": "weekly",
            "cadence_anchor": "monday",
            "status": "active",
            "schema_version": 2,
        }
        p = self.base / "_system" / "roles" / role_id / "config.yml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    def _run_cli(self, argv: list) -> dict:
        """Invoke the CLI end-to-end, asserting rc==0, and parse its JSON stdout."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_code = x.main(argv)
        self.assertEqual(rc_code, 0)
        return json.loads(buf.getvalue())

    # -- fail-closed empty remit ------------------------------------------

    def test_empty_remit_fail_closed(self) -> None:
        # A note exists, but an empty remit matches nothing and never scans.
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self.assertTrue(rc.RemitSpec().is_empty)
        res = x.resolve_corpus(rc.RemitSpec(), base=self.base)
        self.assertEqual(res["units"], [])
        self.assertEqual(res["entity_stubs"], [])
        self.assertEqual(res["counts"]["scanned"], 0)  # short-circuit, no scan
        self.assertEqual(res["counts"]["units"], 0)

    def test_malformed_remit_degrades_to_empty(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea")
        remit = rc.parse_remit("not a mapping")
        self.assertTrue(remit.is_empty)
        res = x.resolve_corpus(remit, base=self.base)
        self.assertEqual(res["units"], [])

    # -- axes -------------------------------------------------------------

    def test_globs_axis(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note("1_projects/minder/sub/deep.md", id="d", type="idea")
        self._note("1_projects/other/b.md", id="b", type="idea")
        res = x.resolve_corpus(
            rc.RemitSpec(globs=("1_projects/minder/**",)), base=self.base
        )
        self.assertEqual(
            self._paths(res),
            ["1_projects/minder/a.md", "1_projects/minder/sub/deep.md"],
        )

    def test_tags_axis(self) -> None:
        self._note("2_areas/a.md", id="a", type="idea", tags=["minder"])
        self._note("2_areas/b.md", id="b", type="idea", tags=["other"])
        res = x.resolve_corpus(rc.RemitSpec(tags=("minder",)), base=self.base)
        self.assertEqual(self._paths(res), ["2_areas/a.md"])

    def test_project_ids_axis_entity_note_and_crossref(self) -> None:
        self._note("1_projects/proj1.md", id="proj1", type="project")
        self._note("1_projects/other.md", id="other", type="project")
        self._note("1_projects/work/c.md", id="c", type="idea", projects=["proj1"])
        res = x.resolve_corpus(rc.RemitSpec(project_ids=("proj1",)), base=self.base)
        self.assertEqual(
            set(self._paths(res)),
            {"1_projects/proj1.md", "1_projects/work/c.md"},
        )

    def test_person_ids_axis_entity_note_by_layer(self) -> None:
        self._note("3_resources/people/alice.md", id="alice", layer="person")
        self._note("3_resources/people/bob.md", id="bob", layer="person")
        self._note("2_areas/note.md", id="n", type="idea", people=["alice"])
        res = x.resolve_corpus(rc.RemitSpec(person_ids=("alice",)), base=self.base)
        self.assertEqual(
            set(self._paths(res)),
            {"3_resources/people/alice.md", "2_areas/note.md"},
        )

    def test_hubs_axis(self) -> None:
        self._note("5_meta/mocs/hub-x.md", id="hub-x", title="Hub X")
        self._note("5_meta/mocs/hub-y.md", id="hub-y", title="Hub Y")
        self._note("2_areas/n.md", id="n", type="idea", hubs=["hub-x"])
        res = x.resolve_corpus(rc.RemitSpec(hubs=("hub-x",)), base=self.base)
        self.assertEqual(
            set(self._paths(res)),
            {"5_meta/mocs/hub-x.md", "2_areas/n.md"},
        )

    def test_decision_notes_axis(self) -> None:
        self._note("1_projects/d.md", id="d", type="decision")
        self._note("1_projects/e.md", id="e", type="idea")
        res = x.resolve_corpus(rc.RemitSpec(decision_notes=True), base=self.base)
        self.assertEqual(self._paths(res), ["1_projects/d.md"])

    def test_all_axis_includes_sensitive_no_stubs(self) -> None:
        self._note("1_projects/a.md", id="a", type="idea")
        self._note("2_areas/s.md", id="s", type="idea", is_sensitive=True)
        res = x.resolve_corpus(rc.RemitSpec(all=True), base=self.base)
        self.assertEqual(set(self._paths(res)), {"1_projects/a.md", "2_areas/s.md"})
        self.assertEqual(res["counts"]["sensitive_in_remit"], 1)
        # `all` short-circuits stub emission (whole corpus already returned).
        self.assertEqual(res["entity_stubs"], [])

    # -- honor-system privacy ---------------------------------------------

    def test_in_remit_sensitive_note_returned(self) -> None:
        # Honor-system: the resolver NEVER drops an in-remit note, even sensitive.
        self._note("1_projects/minder/s.md", id="s", type="idea", is_sensitive=True)
        res = x.resolve_corpus(
            rc.RemitSpec(globs=("1_projects/minder/**",)), base=self.base
        )
        self.assertEqual(len(res["units"]), 1)
        self.assertEqual(res["counts"]["sensitive_in_remit"], 1)
        self.assertTrue(res["units"][0]["trio"]["is_sensitive"])

    def test_foreign_sensitive_entity_stub_dropped(self) -> None:
        self._note(
            "1_projects/minder/a.md", id="a", type="idea",
            projects=["secret", "public"],
        )
        # Out-of-remit foreign entities referenced by the in-remit note.
        self._note(
            "1_projects/vault/secret.md", id="secret", type="project",
            is_sensitive=True,
        )
        self._note("1_projects/pub/public.md", id="public", type="project")
        res = x.resolve_corpus(
            rc.RemitSpec(globs=("1_projects/minder/**",)), base=self.base
        )
        stub_ids = {s["id"] for s in res["entity_stubs"]}
        self.assertIn("public", stub_ids)
        self.assertNotIn("secret", stub_ids)  # sensitive → no stub
        self.assertEqual(res["counts"]["dropped_sensitive_stubs"], 1)
        public_stub = next(s for s in res["entity_stubs"] if s["id"] == "public")
        self.assertEqual(public_stub["type"], "project")

    # -- full type vocabulary ---------------------------------------------

    def test_resolve_type_full_vocabulary(self) -> None:
        for t in CONCEPT_TYPES_ALL:
            self.assertEqual(x.resolve_type({"type": t}), t)
        # Out-of-vocabulary declared kind falls back to the vocab's `other`.
        self.assertEqual(x.resolve_type({"type": "meeting"}), "other")
        # First valid member of `types` wins.
        self.assertEqual(x.resolve_type({"types": ["decision", "fact"]}), "decision")
        # Layer discriminator for first-class entity notes without a `type`.
        self.assertEqual(x.resolve_type({"layer": "person"}), "person")
        self.assertEqual(x.resolve_type({"layer": "project"}), "project")
        self.assertEqual(x.resolve_type({}), "other")

    def test_raw_type_preserved_in_subset(self) -> None:
        self._note("_records/meetings/m.md", id="m", type="meeting", title="Standup")
        res = x.resolve_corpus(
            rc.RemitSpec(globs=("_records/**",)), base=self.base
        )
        unit = res["units"][0]
        self.assertEqual(unit["type"], "other")  # canonical resolved type
        self.assertEqual(unit["frontmatter_subset"]["type"], "meeting")  # raw kept

    # -- mode: --list (zone index, no bodies) -----------------------------

    def test_list_mode_index_without_bodies_same_set(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note("1_projects/minder/sub/b.md", id="b", type="idea")
        self._note("1_projects/other/c.md", id="c", type="idea")
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        idx = x.list_index(remit, base=self.base)
        full = x.resolve_corpus(remit, base=self.base)
        # Same in-remit set as the full resolve …
        self.assertEqual(self._paths(idx), self._paths(full))
        self.assertEqual(
            self._paths(idx),
            ["1_projects/minder/a.md", "1_projects/minder/sub/b.md"],
        )
        # … but NO bodies, while carrying the navigation metadata + counts.
        for unit in idx["units"]:
            self.assertNotIn("body", unit)
            self.assertIn("trio", unit)
            self.assertIn("frontmatter_subset", unit)
        self.assertEqual(idx["counts"]["units"], 2)
        # The full resolve still carries bodies (the tool trims only in --list).
        self.assertTrue(all("body" in u for u in full["units"]))

    # -- mode: --search (grep restricted to remit) ------------------------

    def test_search_matches_in_remit_not_out_of_remit(self) -> None:
        # Same keyword ("kafka") in an in-remit and an out-of-remit note.
        self._note(
            "1_projects/minder/in.md", id="in", type="idea",
            body="We should adopt kafka for the event bus.\n",
        )
        self._note(
            "1_projects/other/out.md", id="out", type="idea",
            body="The other project also uses kafka heavily.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.search_corpus(remit, "kafka", base=self.base)
        hit_paths = {m["path"] for m in res["matches"]}
        self.assertIn("1_projects/minder/in.md", hit_paths)
        self.assertNotIn("1_projects/other/out.md", hit_paths)  # fail-closed
        self.assertEqual(res["counts"]["matched"], 1)
        # Snippet carries the match context.
        snippet = res["matches"][0]["snippet"]
        self.assertIn("kafka", snippet.lower())

    def test_search_matches_frontmatter(self) -> None:
        self._note(
            "1_projects/minder/t.md", id="t", type="idea",
            tags=["payments-gateway"], body="No keyword in the body.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.search_corpus(remit, "payments-gateway", base=self.base)
        self.assertEqual([m["path"] for m in res["matches"]], ["1_projects/minder/t.md"])

    def test_search_empty_query_matches_nothing(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea", body="text\n")
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.search_corpus(remit, "", base=self.base)
        self.assertEqual(res["matches"], [])

    # -- mode: --read (full note, scoped-read boundary) -------------------

    def test_read_in_remit_returns_body(self) -> None:
        self._note(
            "1_projects/minder/a.md", id="a", type="idea",
            body="The full body of note A.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.read_notes(remit, ["1_projects/minder/a.md"], base=self.base)
        self.assertEqual(res["counts"]["returned"], 1)
        self.assertEqual(res["counts"]["refused"], 0)
        note = res["notes"][0]
        self.assertEqual(note["path"], "1_projects/minder/a.md")
        self.assertIn("The full body of note A.", note["body"])
        self.assertIn("trio", note)
        self.assertIn("frontmatter_subset", note)
        self.assertEqual(res["refused"], [])

    def test_read_out_of_remit_rejected(self) -> None:
        # The note exists but is outside the remit → fail-closed refusal.
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note(
            "1_projects/other/secret.md", id="secret", type="idea",
            body="Confidential body that must never leak.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.read_notes(remit, ["1_projects/other/secret.md"], base=self.base)
        self.assertEqual(res["notes"], [])  # body NOT returned
        self.assertEqual(res["counts"]["returned"], 0)
        self.assertEqual(res["counts"]["refused"], 1)
        refusal = res["refused"][0]
        self.assertTrue(refusal["refused"])
        self.assertEqual(refusal["path"], "1_projects/other/secret.md")
        self.assertEqual(refusal["reason"], "out-of-remit")

    def test_read_out_of_remit_sensitive_rejected(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note(
            "1_projects/vault/s.md", id="s", type="idea", is_sensitive=True,
            body="Sensitive out-of-remit body.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.read_notes(remit, ["1_projects/vault/s.md"], base=self.base)
        self.assertEqual(res["notes"], [])  # sensitive body NOT returned
        self.assertEqual(res["counts"]["refused"], 1)
        self.assertEqual(res["refused"][0]["reason"], "out-of-remit")

    def test_read_mixed_comma_separated_in_and_out(self) -> None:
        self._note(
            "1_projects/minder/a.md", id="a", type="idea", body="Body A.\n",
        )
        self._note("1_projects/other/b.md", id="b", type="idea", body="Body B.\n")
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.read_notes(
            remit,
            ["1_projects/minder/a.md,1_projects/other/b.md"],  # comma-separated
            base=self.base,
        )
        self.assertEqual([n["path"] for n in res["notes"]], ["1_projects/minder/a.md"])
        self.assertEqual([r["path"] for r in res["refused"]], ["1_projects/other/b.md"])

    def test_read_nonexistent_path_reason_not_found(self) -> None:
        self._note("1_projects/minder/a.md", id="a", type="idea")
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.read_notes(remit, ["1_projects/minder/ghost.md"], base=self.base)
        self.assertEqual(res["refused"][0]["reason"], "not-found")

    # -- read-around defence: wikilinks are never dereferenced (C8) --------

    def test_wikilink_in_body_does_not_return_out_of_remit_target(self) -> None:
        # An in-remit note whose BODY references an out-of-remit note via a
        # `[[wikilink]]`. The tool must return the in-remit body verbatim (link
        # text intact) but must NEVER dereference the link and surface the
        # out-of-remit target's body — read-around defence rests on the tool
        # following no link (every fetch re-enters `_matches_remit`).
        self._note(
            "1_projects/minder/a.md", id="a", type="idea",
            body="See [[secret]] for the confidential plan.\n",
        )
        self._note(
            "1_projects/vault/secret.md", id="secret", type="idea",
            body="TOP-SECRET out-of-remit body that must never leak.\n",
        )
        remit = rc.RemitSpec(globs=("1_projects/minder/**",))
        res = x.resolve_corpus(remit, base=self.base)
        # Only the in-remit note is returned …
        self.assertEqual(self._paths(res), ["1_projects/minder/a.md"])
        # … with its wikilink text preserved verbatim (not expanded) …
        self.assertIn("[[secret]]", res["units"][0]["body"])
        # … and the linked out-of-remit target's body/path never appear.
        blob = json.dumps(res, default=x._json_default)
        self.assertNotIn("TOP-SECRET out-of-remit body", blob)
        self.assertNotIn("1_projects/vault/secret.md", blob)

    # -- end-to-end --role → config.yml remit loading (C9b) ---------------

    def test_role_config_remit_matches_equivalent_remit_json(self) -> None:
        # The same in-remit set must resolve whether scope comes from the
        # engine-owned `--role → config.yml` path or an equivalent inline remit.
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note("1_projects/minder/sub/b.md", id="b", type="idea")
        self._note("1_projects/other/c.md", id="c", type="idea")
        remit = {"globs": ["1_projects/minder/**"]}
        self._write_config("minder-pm", remit)

        via_role = self._run_cli(
            ["--role", "minder-pm", "--base", str(self.base), "--list", "--compact"]
        )
        via_json = self._run_cli(
            ["--remit-json", json.dumps(remit), "--base", str(self.base),
             "--list", "--compact"]
        )
        self.assertEqual(via_role["role_id"], "minder-pm")
        self.assertEqual(via_role["parts"], [{"id": "board", "kind": "ledger"}])
        self.assertEqual(
            self._paths(via_role),
            ["1_projects/minder/a.md", "1_projects/minder/sub/b.md"],
        )
        self.assertEqual(self._paths(via_role), self._paths(via_json))

    # -- widen attempt blocked: --read out-of-remit refused (C9c / B2) -----

    def test_cli_read_out_of_remit_rejected_via_role(self) -> None:
        # Even through the engine-owned `--role` scope, `--read` of a path
        # outside the remit is refused — a body cannot widen its own scope.
        self._note("1_projects/minder/a.md", id="a", type="idea")
        self._note(
            "1_projects/other/secret.md", id="secret", type="idea",
            body="Confidential body that must never leak.\n",
        )
        self._write_config("minder-pm", {"globs": ["1_projects/minder/**"]})
        res = self._run_cli(
            ["--role", "minder-pm", "--base", str(self.base),
             "--read", "1_projects/other/secret.md", "--compact"]
        )
        self.assertEqual(res["mode"], "read")
        self.assertEqual(res["notes"], [])
        self.assertEqual(res["counts"]["refused"], 1)
        self.assertEqual(res["refused"][0]["reason"], "out-of-remit")
        self.assertNotIn("Confidential body", json.dumps(res, default=x._json_default))

    # -- CLI wiring for the three modes -----------------------------------

    def test_cli_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            x.main([
                "--remit-json", "{}", "--base", str(self.base),
                "--list", "--search", "q",
            ])


if __name__ == "__main__":
    unittest.main()
