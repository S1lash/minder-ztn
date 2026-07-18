"""Tests for roles_archetype_assessment.py — the Assessment reference archetype plugin.

Covers the schema hook (fail-closed on every malformed shape), the NEW cross-part
`over` existence check (exercised through the real `roles_common._parse_parts` with a
multi-part config, so the loader dispatch + error location are proven end-to-end), the
structural verdict gate (only a declared verdict is ever recorded), the records
grounding of every `assess` (uncited / out-of-zone rejected), the present-verdict-
per-key projection over an append-only history (a change keeps the prior; latest
wins), the ordered-vocabulary preservation (best→worst end to end), and the composite-
seam hooks (content_view/adopt round-trip, consumed_records, registry_summary,
build_decisions, identity).

A config-threading block proves the schema + cross-part check load end-to-end through
the REAL loader and writer overlay.

No I/O for the plugin tests — validate/persist are pure in-memory transforms.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_archetype_assessment as x  # noqa: E402
import roles_common as rc  # noqa: E402
import roles_persist as rp  # noqa: E402


_VERDICTS = ["on-track", "at-risk", "off"]


def _schema(over="records", verdicts=None) -> dict:
    return {
        "over": over,
        "verdicts": list(verdicts if verdicts is not None else _VERDICTS),
        "grounding": "records",
        "grounding_check": True,
    }


def _state(assessments=None, schema=None, **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "assessment",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": schema if schema is not None else _schema(),
        "assessments": list(assessments or []),
    }
    state.update(top)
    return state


def _entry(key, verdict, rationale="", provenance=None, at="2026-07-09", history=None) -> dict:
    return {
        "key": key,
        "verdict": verdict,
        "rationale": rationale,
        "provenance": list(provenance or []),
        "at": at,
        "history": list(history or []),
    }


def _payload(read_records, *deltas) -> dict:
    return {
        "role_id": "r",
        "hook": "tick",
        "read_records": list(read_records),
        "deltas": list(deltas),
    }


def _assess(key, verdict, evidence, rationale=None) -> dict:
    d = {"part": "p", "op": "assess", "key": key, "verdict": verdict, "evidence": list(evidence)}
    if rationale is not None:
        d["rationale"] = rationale
    return d


# =============================================================================
# validate_schema — fail-closed on every malformed shape
# =============================================================================

class ValidateSchemaTest(unittest.TestCase):
    def test_happy_path_returns_canonical(self) -> None:
        sch = x.validate_schema({"over": "nums", "verdicts": _VERDICTS, "grounding": "records"})
        self.assertEqual(sch["over"], "nums")
        self.assertEqual(sch["verdicts"], ["on-track", "at-risk", "off"])   # order preserved
        self.assertEqual(sch["grounding"], "records")
        self.assertTrue(sch["grounding_check"])          # Stage 2.5 ON for a claims part

    def test_over_records_is_valid(self) -> None:
        sch = x.validate_schema({"over": "records", "verdicts": ["a", "b"]})
        self.assertEqual(sch["over"], "records")

    def test_ordered_vocabulary_preserved_not_sorted(self) -> None:
        sch = x.validate_schema({"over": "records", "verdicts": ["z", "m", "a"]})
        self.assertEqual(sch["verdicts"], ["z", "m", "a"])   # NOT sorted — owner order

    def _fails(self, raw, needle) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.validate_schema(raw)
        self.assertIn(needle, str(ctx.exception))

    def test_not_a_mapping_fails(self) -> None:
        self._fails("nope", "schema")

    def test_missing_over_fails(self) -> None:
        self._fails({"verdicts": _VERDICTS}, "over")

    def test_empty_over_fails(self) -> None:
        self._fails({"over": "  ", "verdicts": _VERDICTS}, "over")

    def test_non_string_over_fails(self) -> None:
        self._fails({"over": 3, "verdicts": _VERDICTS}, "over")

    def test_missing_verdicts_fails(self) -> None:
        self._fails({"over": "records"}, "verdicts")

    def test_empty_verdicts_fails(self) -> None:
        self._fails({"over": "records", "verdicts": []}, "verdicts")

    def test_non_string_verdict_entry_fails(self) -> None:
        self._fails({"over": "records", "verdicts": ["ok", 7]}, "verdicts")

    def test_blank_verdict_entry_fails(self) -> None:
        self._fails({"over": "records", "verdicts": ["ok", "   "]}, "verdicts")

    def test_duplicate_verdict_fails(self) -> None:
        self._fails({"over": "records", "verdicts": ["ok", "bad", "ok"]}, "duplicate")

    def test_non_records_grounding_fails(self) -> None:
        self._fails({"over": "records", "verdicts": _VERDICTS, "grounding": "values"},
                    "grounding")


# =============================================================================
# validate_cross_part — the NEW cross-part `over` existence hook
# =============================================================================

class ValidateCrossPartUnitTest(unittest.TestCase):
    """Direct hook calls — the pure membership check."""

    def test_over_existing_sibling_ok(self) -> None:
        x.validate_cross_part(_schema(over="nums"), {"nums", "verdicts"})   # no raise

    def test_over_records_ok(self) -> None:
        x.validate_cross_part(_schema(over="records"), {"nums"})            # no raise

    def test_over_missing_sibling_raises(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.validate_cross_part(_schema(over="nope"), {"nums", "verdicts"})
        self.assertIn("over", str(ctx.exception))
        self.assertIn("nope", str(ctx.exception))

    def test_error_names_available_parts(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.validate_cross_part(_schema(over="typo"), {"nums"})
        self.assertIn("nums", str(ctx.exception))       # lists the real parts


_MULTI_CONFIG = """id: check
name: My Check
parts:
  - id: work
    kind: ledger
  - id: verdicts
    kind: assessment
    schema:
      over: {over}
      verdicts: ["on-track", "at-risk", "off"]   # quoted: bare `off`/`on` are YAML booleans
      grounding: records
cadence: daily
status: active
schema_version: 2
remit:
  all: true
"""


class ValidateCrossPartLoaderTest(unittest.TestCase):
    """Through the REAL `_parse_parts` with a multi-part config — proves the loader
    dispatch, sibling-id discovery, and error location work end-to-end."""

    def _write(self, over: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text(_MULTI_CONFIG.format(over=over), encoding="utf-8")
        return path

    def test_over_existing_sibling_loads(self) -> None:
        cfg = rc.load_role_config_file(self._write("work"))
        self.assertEqual(cfg.part_ids, ("work", "verdicts"))
        assess = next(p for p in cfg.parts if p.kind == "assessment")
        self.assertEqual(assess.schema["over"], "work")
        self.assertTrue(assess.grounding_check)          # Stage 2.5 ON

    def test_over_records_loads(self) -> None:
        cfg = rc.load_role_config_file(self._write("records"))
        assess = next(p for p in cfg.parts if p.kind == "assessment")
        self.assertEqual(assess.schema["over"], "records")

    def test_over_typo_fails_closed_with_part_location(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write("wrok"))   # typo of 'work'
        msg = str(ctx.exception)
        self.assertIn("part 'verdicts'", msg)            # loader located the error
        self.assertIn("wrok", msg)

    def test_over_retired_sibling_fails_closed(self) -> None:
        # 'archived' is not a declared part id — a sibling that no longer exists reads
        # exactly like a typo: fail-closed, not silently ignored.
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write("archived"))
        self.assertIn("part 'verdicts'", str(ctx.exception))

    def test_over_self_fails_closed(self) -> None:
        # A part cannot reference itself — the loader passes SIBLING ids (self excluded),
        # so `over: <own id>` reads like any non-existent sibling: fail-closed.
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write("verdicts"))   # the assessment's own id
        self.assertIn("part 'verdicts'", str(ctx.exception))

    def test_single_part_config_has_no_validate_cross_part(self) -> None:
        # A role whose parts do NOT export validate_cross_part (ledger) loads with no
        # cross-part pass firing — the loader default-skips it (archetype-agnostic).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text("id: r\nparts: [{id: p, kind: ledger}]\n"
                        "remit: {all: true}\ncadence: daily\nstatus: active\n",
                        encoding="utf-8")
        cfg = rc.load_role_config_file(path)             # no raise
        self.assertEqual(cfg.part_ids, ("p",))


# =============================================================================
# Verdict gate — only a declared verdict is ever recorded
# =============================================================================

class VerdictGateTest(unittest.TestCase):
    def test_declared_verdict_accepted(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"],
                                         _assess("g1", "at-risk", ["[[2026-07-09]]"])))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)
        ns = x.persist(state, res.approved_deltas, None)
        self.assertEqual(ns["assessments"][0]["verdict"], "at-risk")

    def test_out_of_set_verdict_rejected_tick_not_blocked(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"],
                                         _assess("g1", "sideways", ["[[2026-07-09]]"])))
        self.assertTrue(res.ok)                           # tick not blocked
        self.assertEqual(res.approved_deltas, ())         # but the delta is dropped
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("not in the declared verdict set", res.rejections[0]["reason"])

    def test_missing_verdict_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"],
                                         {"part": "p", "op": "assess", "key": "g1",
                                          "evidence": ["[[2026-07-09]]"]}))
        self.assertIn("verdict", res.rejections[0]["reason"])


# =============================================================================
# Grounding — every assess cites a real in-remit record (records oracle)
# =============================================================================

class GroundingTest(unittest.TestCase):
    def test_uncited_assess_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload([], {"part": "p", "op": "assess",
                                              "key": "g1", "verdict": "on-track"}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("evidence", res.rejections[0]["reason"])

    def test_out_of_zone_citation_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"],
                                         _assess("g1", "on-track", ["[[not-in-zone]]"])))
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_cited_assess_grows_provenance(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"],
                                         _assess("g1", "on-track", ["[[2026-07-09]]"])))
        ns = x.persist(state, res.approved_deltas, None)
        self.assertEqual(ns["assessments"][0]["provenance"], ["[[2026-07-09]]"])


# =============================================================================
# Body may never set an engine-owned field
# =============================================================================

class BodyForbiddenTest(unittest.TestCase):
    def _rejected(self, delta) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"], delta))
        self.assertTrue(res.ok)
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.rejections), 1)

    def test_body_cannot_set_history(self) -> None:
        d = _assess("g1", "on-track", ["[[2026-07-09]]"])
        d["history"] = [{"verdict": "off"}]
        self._rejected(d)

    def test_body_cannot_set_provenance(self) -> None:
        d = _assess("g1", "on-track", ["[[2026-07-09]]"])
        d["provenance"] = ["[[forged]]"]
        self._rejected(d)

    def test_body_cannot_set_at(self) -> None:
        d = _assess("g1", "on-track", ["[[2026-07-09]]"])
        d["at"] = "1999-01-01"
        self._rejected(d)


# =============================================================================
# Structural gate — op / key / one-touch / empty schema
# =============================================================================

class StructuralTest(unittest.TestCase):
    def test_unknown_op_rejected(self) -> None:
        res = x.validate(_state(), _payload([], {"part": "p", "op": "verdict", "key": "g1"}))
        self.assertIn("unknown op", res.rejections[0]["reason"])

    def test_missing_key_rejected(self) -> None:
        res = x.validate(_state(), _payload(["2026-07-09"],
                                            {"part": "p", "op": "assess",
                                             "verdict": "on-track", "evidence": ["[[2026-07-09]]"]}))
        self.assertIn("key", res.rejections[0]["reason"])

    def test_key_assessed_twice_rejected(self) -> None:
        res = x.validate(_state(), _payload(["2026-07-09"],
                                            _assess("g1", "on-track", ["[[2026-07-09]]"]),
                                            _assess("g1", "off", ["[[2026-07-09]]"])))
        self.assertEqual(len(res.approved_deltas), 1)     # first wins this tick
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("already assessed", res.rejections[0]["reason"])

    def test_bad_rationale_type_rejected(self) -> None:
        d = _assess("g1", "on-track", ["[[2026-07-09]]"])
        d["rationale"] = 12
        res = x.validate(_state(), _payload(["2026-07-09"], d))
        self.assertIn("rationale", res.rejections[0]["reason"])

    def test_empty_schema_holds(self) -> None:
        state = _state(schema={"over": "records", "verdicts": [], "grounding": "records"})
        res = x.validate(state, _payload(["2026-07-09"],
                                         _assess("g1", "on-track", ["[[2026-07-09]]"])))
        self.assertFalse(res.ok)                          # no vocabulary to gate against


# =============================================================================
# Present-verdict-per-key projection over an append-only history
# =============================================================================

class PresentStateProjectionTest(unittest.TestCase):
    def _do(self, state, key, verdict, evidence, rationale=None) -> dict:
        res = x.validate(state, _payload([evidence[0][2:-2]],
                                         _assess(key, verdict, evidence, rationale)))
        self.assertTrue(res.ok, res.rejections)
        return x.persist(state, res.approved_deltas, None)

    def test_first_assess_creates_entry_empty_history(self) -> None:
        ns = self._do(_state(), "g1", "on-track", ["[[2026-07-01]]"], "kickoff clean")
        e = ns["assessments"][0]
        self.assertEqual(e["verdict"], "on-track")
        self.assertEqual(e["rationale"], "kickoff clean")
        self.assertEqual(e["history"], [])
        self.assertEqual(e["provenance"], ["[[2026-07-01]]"])

    def test_verdict_change_keeps_prior_latest_wins(self) -> None:
        s1 = self._do(_state(), "g1", "on-track", ["[[2026-07-01]]"], "clean")
        s2 = self._do(s1, "g1", "at-risk", ["[[2026-07-05]]"], "slipping")
        e = s2["assessments"][0]
        self.assertEqual(e["verdict"], "at-risk")         # latest wins
        self.assertEqual(e["rationale"], "slipping")
        self.assertEqual(len(e["history"]), 1)            # the prior kept
        self.assertEqual(e["history"][0]["verdict"], "on-track")
        self.assertEqual(e["history"][0]["rationale"], "clean")
        self.assertEqual(e["provenance"], ["[[2026-07-01]]", "[[2026-07-05]]"])  # grow-only

    def test_reaffirm_same_verdict_adds_no_history(self) -> None:
        s1 = self._do(_state(), "g1", "at-risk", ["[[2026-07-01]]"], "watch")
        s2 = self._do(s1, "g1", "at-risk", ["[[2026-07-05]]"])   # same verdict, no rationale
        e = s2["assessments"][0]
        self.assertEqual(e["verdict"], "at-risk")
        self.assertEqual(e["history"], [])                # no push on a reaffirmation
        self.assertEqual(e["rationale"], "watch")         # standing reason preserved
        self.assertEqual(e["provenance"], ["[[2026-07-01]]", "[[2026-07-05]]"])
        self.assertEqual(e["at"], x.today_iso())          # reaffirmation refreshes the date

    def test_full_trajectory_accumulates_history(self) -> None:
        s = _state()
        for verdict, rec in [("on-track", "2026-07-01"), ("at-risk", "2026-07-05"),
                             ("at-risk", "2026-07-06"), ("off", "2026-07-09")]:
            s = self._do(s, "g1", verdict, [f"[[{rec}]]"])
        e = s["assessments"][0]
        self.assertEqual(e["verdict"], "off")                          # latest
        self.assertEqual([h["verdict"] for h in e["history"]],
                         ["on-track", "at-risk"])                      # every CHANGE, in order


# =============================================================================
# consumed_records — the shared records watermark seam
# =============================================================================

class ConsumedRecordsTest(unittest.TestCase):
    def test_yields_cited_stems(self) -> None:
        state = _state(assessments=[
            _entry("g1", "on-track", provenance=["[[2026-07-09]]"]),
            _entry("g2", "off", provenance=["[[2026-07-08]]", "[[]]"])])  # degenerate dropped
        self.assertEqual(sorted(x.consumed_records(state)), ["2026-07-08", "2026-07-09"])


# =============================================================================
# Render — grouped by verdict in DECLARED order (best→worst)
# =============================================================================

class RenderTest(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(x.render(_state()), "_No assessments yet._")

    def test_grouped_in_declared_order(self) -> None:
        state = _state(assessments=[
            _entry("g3", "off", rationale="blocked", at="2026-07-09"),
            _entry("g1", "on-track", at="2026-07-09"),
            _entry("g2", "on-track", at="2026-07-08",
                   history=[{"verdict": "at-risk", "rationale": "", "at": "2026-07-01"}])])
        out = x.render(state)
        # Declared order best→worst: on-track section BEFORE off section.
        self.assertLess(out.index("### on-track"), out.index("### off"))
        self.assertIn("- g3 — blocked (as of 2026-07-09)", out)
        self.assertIn("- g2", out)
        self.assertIn("· was at-risk", out)              # last verdict change surfaced


# =============================================================================
# Composite-seam hooks
# =============================================================================

class SeamHooksTest(unittest.TestCase):
    def test_known_key_numbers_empty(self) -> None:
        self.assertEqual(list(x.known_key_numbers(_state())), [])

    def test_identity_anchored_never_fabricates(self) -> None:
        idr = x.identity({"key": "g1"}, None)
        self.assertTrue(idr.anchored)
        self.assertIsNone(idr.anchor)

    def test_gate_identity_passthrough(self) -> None:
        kept, sigs = x.gate_identity("r", "p", _state(), [{"op": "assess", "key": "g1"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(sigs, [])

    def test_content_view_and_adopt_round_trip(self) -> None:
        stored = [_entry("g1", "on-track", provenance=["[[2026-07-09]]"])]
        cv = x.content_view(_state(assessments=stored))
        self.assertEqual(cv["assessments"], stored)
        adopted = x.adopt_staging(_state(assessments=[]), cv)   # schema NOT frozen
        self.assertEqual(adopted["assessments"], stored)

    def test_content_summary(self) -> None:
        state = _state(assessments=[_entry("g1", "on-track", rationale="clean"),
                                    _entry("g2", "off")])
        labels = x.content_summary(state)
        self.assertIn("g1: on-track — clean", labels[0])
        self.assertIn("g2: off", labels[1])

    def test_registry_summary_breakdown_declared_order(self) -> None:
        state = _state(assessments=[_entry("g1", "on-track"), _entry("g2", "on-track"),
                                    _entry("g3", "off")])
        summ = x.registry_summary(state)
        self.assertEqual(summ["total"], 3)
        self.assertEqual(summ["breakdown"], [["on-track", 2], ["off", 1]])  # declared order

    def test_registry_summary_counts_staged(self) -> None:
        state = _state(assessments=[], staging={"assessments": [_entry("g1", "on-track")]})
        self.assertEqual(x.registry_summary(state)["staged"], 1)

    def test_delta_counts(self) -> None:
        added, advanced = x.delta_counts([{"op": "assess"}, {"op": "assess"}])
        self.assertEqual((added, advanced), (2, 0))

    def test_build_decisions_kinds(self) -> None:
        prior = _state(assessments=[_entry("g1", "on-track"), _entry("g2", "at-risk")])
        approved = [
            _assess("g1", "at-risk", ["[[2026-07-09]]"]),    # existing, changed
            _assess("g2", "at-risk", ["[[2026-07-09]]"]),    # existing, same
            _assess("g3", "off", ["[[2026-07-09]]"]),        # new key
        ]
        rows = x.build_decisions(approved, [], prior, "r", "p", "tick", "ts")
        self.assertEqual([r["kind"] for r in rows],
                         ["verdict-change", "verdict-reaffirm", "verdict-set"])
        self.assertEqual(rows[0]["verdict"], "at-risk")

    def test_cold_materialize_decisions(self) -> None:
        state = _state(assessments=[_entry("g1", "off", provenance=["[[2026-07-09]]"])])
        rows = x.cold_materialize_decisions(state, "r", "p", "ts")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "cold-materialize")
        self.assertEqual(rows[0]["verdict"], "off")


# =============================================================================
# Config threading — real _parse_parts + writer overlay
# =============================================================================

class AssessmentConfigThreadingTest(unittest.TestCase):
    def _write_dir(self, over="work") -> tuple[Path, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / "check"
        rdir.mkdir(parents=True)
        (rdir / "config.yml").write_text(_MULTI_CONFIG.format(over=over), encoding="utf-8")
        return base, "check"

    def test_missing_schema_fails_closed(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text("id: r\nparts: [{id: p, kind: assessment}]\n"
                        "remit: {all: true}\ncadence: daily\nstatus: active\n",
                        encoding="utf-8")
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(path)
        self.assertIn("schema", str(ctx.exception))

    def test_writer_overlays_schema_on_fresh_and_loaded_state(self) -> None:
        base, role = self._write_dir("work")
        cfg = rc.load_role_config(role, base)
        part = next(p for p in cfg.parts if p.kind == "assessment")

        fresh = rp._load_part_state(role, part, base)
        self.assertEqual(fresh["schema"]["verdicts"], ["on-track", "at-risk", "off"])
        self.assertEqual(fresh["schema"]["over"], "work")
        self.assertEqual(fresh["assessments"], [])

        # A stored state with a STALE verdict vocabulary is re-overlaid from config.
        stale = dict(fresh)
        stale["schema"] = {"over": "work", "verdicts": ["old"], "grounding": "records"}
        (base / "_system" / "roles" / role / "parts").mkdir(exist_ok=True)
        (base / "_system" / "roles" / role / "parts" / "verdicts.json").write_text(
            json.dumps(stale), encoding="utf-8")
        loaded = rp._load_part_state(role, part, base)
        self.assertEqual(loaded["schema"]["verdicts"], ["on-track", "at-risk", "off"])  # config wins


if __name__ == "__main__":
    unittest.main()
