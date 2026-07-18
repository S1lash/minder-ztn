"""Tests for roles_archetype_stance.py — the DUAL-grounded Stance reference archetype
plugin, plus the engine seams it exercises (the generalized forward watermark + the
per-part freshness check + the values-oracle injection lane in roles_persist).

A stance grounds PER INSTANCE (chosen in config): `records` (the default — argue from the
owner's OWN NOTES, citations ⊆ the engine-injected `read_records`, exactly like a records
kind) OR `values` (argue from the owner's CONSTITUTION, citations ⊆ the engine-verified
oracle). One grounding-NEUTRAL `citations` field holds record stems or principle-ids per
mode.

Covers the minimal schema hook (fail-closed on a MISSING or invalid grounding — no silent
default; records and values both accepted explicitly), BOTH grounding gates (values: an
out-of-oracle / uncited / empty-oracle position rejected; records: an out-of-corpus /
uncited / empty-corpus position rejected — and a records stance needs NO values oracle),
the four ops (take-position / argue / note-counter / resolve) with their structural gates,
the append-only argument history (an `argue` keeps the prior; latest wins), the
deterministic counter-backoff (two `note-counter` → auto-held, never re-argued), the
no-act guarantee (a stance carries no act op and no outward effect), the per-mode
`consumed_records` (cited stems in records mode / empty in values mode), and the
composite-seam hooks.

The watermark-generalization block proves a records kind stays BYTE-IDENTICAL (the union
with a subset is a no-op) and a values kind advances without breaking, and that
`_part_is_fresh` routes on the PART's grounding. Two full-lifecycle integration blocks
drive real `roles_persist.run` ticks (cold-start → approve → argue): a VALUES stance (its
watermark stays None; freshness by live content) and a RECORDS stance (its watermark
advances off None over cited records; freshness by the watermark proxy — needs no values
oracle), each proving the adopted stance is NOT re-armed for cold-start and that a sibling
records part's watermark is unchanged.

The writer-existence-filter block proves the deterministic net BENEATH the prompt stage:
`roles_persist._inject_values_oracles` existence-filters the injected oracle against
`0_constitution/` so a fabricated principle-id smuggled in by a REGRESSED Stage 2.6 is
dropped at the WRITER (a body citing it is rejected), while a real id survives — the
existence half of the honesty guarantee is deterministic, the relevance half stays
Stage 2.6's. Unit-level tests cover `_common.constitution_principle_ids` (tolerant of
malformed / missing files) and the per-part prune in isolation.

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

import roles_archetype_stance as x  # noqa: E402
import roles_common as rc  # noqa: E402
import roles_persist as rp  # noqa: E402


_PID = "axiom-identity-001"
_PID2 = "axiom-work-001"


def _seed_constitution(base: Path, *pids: str) -> None:
    """Write minimal valid principle files so the writer's deterministic existence
    filter (`roles_persist._inject_values_oracles` → `constitution_principle_ids`)
    resolves the given ids under the test base's `0_constitution/`. The walker keys on
    the frontmatter `id:`, not the path, so a `---\\nid: {pid}\\n---` stub under the
    id's `{type}/` dir is enough."""
    for pid in pids:
        type_name = pid.split("-", 1)[0]   # axiom | principle | rule
        d = base / "0_constitution" / type_name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{pid}.md").write_text(f"---\nid: {pid}\n---\nseed\n", encoding="utf-8")


def _schema(grounding="values") -> dict:
    return {"grounding": grounding, "grounding_check": False}


def _rschema() -> dict:
    """A RECORDS-grounded stance schema (the default for a push-back role)."""
    return {"grounding": "records", "grounding_check": False}


def _state(positions=None, schema=None, **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "stance",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": schema if schema is not None else _schema(),
        "positions": list(positions or []),
    }
    state.update(top)
    return state


def _pos(key, position="hold the line", argument="you are drifting", cited=None,
         owner_counter=0, debate_status="open", at="2026-07-09", history=None,
         resolve_reason=None) -> dict:
    cited = list(cited if cited is not None else [_PID])
    p = {
        "key": key, "position": position, "argument": argument,
        "citations": cited, "owner_counter": owner_counter,
        "debate_status": debate_status, "provenance": list(cited),
        "at": at, "history": list(history or []),
    }
    if resolve_reason is not None:
        p["resolve_reason"] = resolve_reason
    return p


def _payload(oracle, *deltas) -> dict:
    """A VALUES-mode payload: `oracle` becomes the values_oracle (principle-ids)."""
    return {
        "role_id": "r", "hook": "tick", "read_records": [],
        "deltas": list(deltas),
        "values_oracle": None if oracle is None else list(oracle),
    }


def _rpayload(corpus, *deltas) -> dict:
    """A RECORDS-mode payload: `corpus` becomes the read_records oracle (record stems);
    no values_oracle is needed (Stage 2.6 is skipped for a records-grounded stance)."""
    return {
        "role_id": "r", "hook": "tick", "read_records": list(corpus or []),
        "deltas": list(deltas),
    }


def _take(key, cited=(_PID,), position="hold the line", argument="you are drifting") -> dict:
    return {"part": "p", "op": "take-position", "key": key, "position": position,
            "argument": argument, "citations": list(cited)}


def _argue(key, cited=(_PID,), argument="still drifting") -> dict:
    return {"part": "p", "op": "argue", "key": key, "argument": argument,
            "citations": list(cited)}


def _counter(key) -> dict:
    return {"part": "p", "op": "note-counter", "key": key}


def _resolve(key, to="resolved", reason="settled") -> dict:
    return {"part": "p", "op": "resolve", "key": key, "to": to, "reason": reason}


# =============================================================================
# validate_schema — minimal, DUAL-grounded, fail-closed on missing/invalid grounding
# =============================================================================

class ValidateSchemaTest(unittest.TestCase):
    def test_values_grounding_returns_canonical(self) -> None:
        sch = x.validate_schema({"grounding": "values"})
        self.assertEqual(sch["grounding"], "values")
        self.assertFalse(sch["grounding_check"])          # Stage 2.5 OFF for a stance

    def test_records_grounding_returns_canonical(self) -> None:
        # The DEFAULT for a push-back role — argue from the owner's own notes.
        sch = x.validate_schema({"grounding": "records"})
        self.assertEqual(sch["grounding"], "records")
        self.assertFalse(sch["grounding_check"])          # Stage 2.5 OFF in both modes

    def test_none_schema_fails_closed(self) -> None:
        # No silent default: grounding is REQUIRED (the concierge always emits it).
        self._fails(None, "grounding")

    def test_empty_dict_fails_closed(self) -> None:
        # An empty schema block omits grounding → fail-closed, no default.
        self._fails({}, "grounding")

    def _fails(self, raw, needle) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.validate_schema(raw)
        self.assertIn(needle, str(ctx.exception))

    def test_non_mapping_fails(self) -> None:
        self._fails("nope", "grounding")

    def test_owner_confirm_grounding_fails_closed(self) -> None:
        # owner-confirm is not a stance grounding mode (only records / values).
        self._fails({"grounding": "owner-confirm"}, "values")

    def test_bogus_grounding_fails_closed(self) -> None:
        self._fails({"grounding": "nonsense"}, "values")

    def test_non_string_grounding_fails(self) -> None:
        self._fails({"grounding": 7}, "values")


# =============================================================================
# Values grounding — citations (principle-ids) ⊆ the engine-verified oracle
# =============================================================================

class ValuesGroundingTest(unittest.TestCase):
    def test_take_position_cited_in_oracle_accepted(self) -> None:
        res = x.validate(_state(), _payload([_PID], _take("scope")))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_take_position_cited_outside_oracle_rejected(self) -> None:
        res = x.validate(_state(), _payload([_PID], _take("scope", cited=["fake-principle-999"])))
        self.assertTrue(res.ok)                            # tick not blocked
        self.assertEqual(res.approved_deltas, ())          # delta dropped
        self.assertIn("not in the engine-verified oracle", res.rejections[0]["reason"])

    def test_partial_forge_rejected(self) -> None:
        # One real principle + one forged → the whole delta is rejected (no half-grounding).
        res = x.validate(_state(), _payload([_PID], _take("scope", cited=[_PID, "made-up-000"])))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("made-up-000", res.rejections[0]["reason"])

    def test_empty_oracle_rejects_all_values_ops(self) -> None:
        res = x.validate(_state(), _payload([], _take("scope")))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not in the engine-verified oracle", res.rejections[0]["reason"])

    def test_absent_oracle_fails_closed(self) -> None:
        # values_oracle=None (no oracle injected) → treated as empty → every position rejected.
        res = x.validate(_state(), _payload(None, _take("scope")))
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.rejections), 1)

    def test_uncited_take_position_rejected(self) -> None:
        d = _take("scope")
        del d["citations"]
        res = x.validate(_state(), _payload([_PID], d))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("must cite at least one constitution principle", res.rejections[0]["reason"])

    def test_argue_cited_outside_oracle_rejected(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload([_PID], _argue("scope", cited=["nope-001"])))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not in the engine-verified oracle", res.rejections[0]["reason"])

    def test_note_counter_needs_no_oracle(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload([], _counter("scope")))   # empty oracle
        self.assertEqual(len(res.approved_deltas), 1)              # counter is not a values-op

    def test_resolve_needs_no_oracle(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload(None, _resolve("scope")))  # absent oracle
        self.assertEqual(len(res.approved_deltas), 1)

    def test_oracle_accepts_dict_shape(self) -> None:
        # The runner may inject the oracle as a {id: relation} verdict map — tolerated.
        payload = {"role_id": "r", "hook": "tick", "read_records": [],
                   "deltas": [_take("scope")], "values_oracle": {_PID: "aligned"}}
        res = x.validate(_state(), payload)
        self.assertEqual(len(res.approved_deltas), 1)


# =============================================================================
# Records grounding — citations (record stems) ⊆ the engine-injected read_records
# (the DEFAULT push-back mode; grounds in the owner's OWN notes, needs NO values oracle)
# =============================================================================

_REC = "2026-07-01-note"
_REC2 = "2026-07-05-note"


def _rstate(positions=None, **top) -> dict:
    return _state(positions=positions, schema=_rschema(), **top)


class RecordsGroundingTest(unittest.TestCase):
    def test_take_position_cited_in_corpus_accepted(self) -> None:
        res = x.validate(_rstate(), _rpayload([_REC], _take("scope", cited=[_REC])))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_take_position_out_of_corpus_rejected(self) -> None:
        # A record stem NOT in read_records is ungrounded — a body cannot cite a note
        # outside the role's remit.
        res = x.validate(_rstate(), _rpayload([_REC], _take("scope", cited=["ghost-note"])))
        self.assertTrue(res.ok)                            # tick not blocked
        self.assertEqual(res.approved_deltas, ())          # delta dropped
        self.assertIn("not in read_records", res.rejections[0]["reason"])

    def test_uncited_take_position_rejected(self) -> None:
        d = _take("scope")
        del d["citations"]
        res = x.validate(_rstate(), _rpayload([_REC], d))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("must cite at least one in-remit record", res.rejections[0]["reason"])

    def test_empty_corpus_rejects_all_grounded_ops(self) -> None:
        # No records in remit → every take-position/argue is ungrounded (fail-closed).
        res = x.validate(_rstate(), _rpayload([], _take("scope", cited=[_REC])))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not in read_records", res.rejections[0]["reason"])

    def test_needs_no_values_oracle(self) -> None:
        # A records-grounded stance is Stage-2.6-SKIPPED: no values_oracle in the payload,
        # yet a valid record citation is ACCEPTED (it grounds in read_records, not values).
        payload = {"role_id": "r", "hook": "tick", "read_records": [_REC],
                   "deltas": [_take("scope", cited=[_REC])]}          # no values_oracle key
        res = x.validate(_rstate(), payload)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_wikilink_and_md_forms_normalise(self) -> None:
        # A [[wikilink]] / name.md citation for a real in-remit stem grounds (shared
        # normalisation with every records kind).
        res = x.validate(_rstate(), _rpayload([_REC], _take("scope", cited=[f"[[{_REC}]]"])))
        self.assertEqual(len(res.approved_deltas), 1)

    def test_argue_cited_out_of_corpus_rejected(self) -> None:
        prior = _rstate(positions=[_pos("scope", cited=[_REC])])
        res = x.validate(prior, _rpayload([_REC], _argue("scope", cited=["ghost-note"])))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not in read_records", res.rejections[0]["reason"])

    def test_note_counter_needs_no_corpus(self) -> None:
        prior = _rstate(positions=[_pos("scope", cited=[_REC])])
        res = x.validate(prior, _rpayload([], _counter("scope")))     # empty corpus
        self.assertEqual(len(res.approved_deltas), 1)                 # not a grounded op

    def test_persist_and_consumed_records_yields_cited_stems(self) -> None:
        res = x.validate(_rstate(), _rpayload([_REC], _take("scope", cited=[_REC])))
        self.assertTrue(res.ok, res.rejections)
        ns = x.persist(_rstate(), res.approved_deltas, None)
        p = ns["positions"][0]
        self.assertEqual(p["citations"], [_REC])
        # A records stance CONSUMES its cited records → rides the shared watermark.
        self.assertEqual(list(x.consumed_records(ns)), [_REC])

    def test_argue_history_and_provenance_grow(self) -> None:
        s1 = x.persist(_rstate(), x.validate(
            _rstate(), _rpayload([_REC], _take("scope", cited=[_REC], argument="v1"))
        ).approved_deltas, None)
        s2 = x.persist(s1, x.validate(
            s1, _rpayload([_REC, _REC2], _argue("scope", cited=[_REC2], argument="v2"))
        ).approved_deltas, None)
        p = s2["positions"][0]
        self.assertEqual(p["argument"], "v2")              # latest wins
        self.assertEqual(p["citations"], [_REC2])
        self.assertEqual(p["history"][0]["argument"], "v1")
        self.assertEqual(p["history"][0]["citations"], [_REC])
        self.assertEqual(sorted(x.consumed_records(s2)), [_REC, _REC2])   # grow-only


# =============================================================================
# Structural gate — ops / key / lifecycle / one-touch / forbidden fields
# =============================================================================

class StructuralTest(unittest.TestCase):
    def test_unknown_op_rejected(self) -> None:
        res = x.validate(_state(), _payload([_PID], {"part": "p", "op": "act", "key": "s"}))
        self.assertIn("unknown op", res.rejections[0]["reason"])

    def test_missing_key_rejected(self) -> None:
        d = _take("scope")
        del d["key"]
        res = x.validate(_state(), _payload([_PID], d))
        self.assertIn("key", res.rejections[0]["reason"])

    def test_take_position_on_existing_key_rejected(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload([_PID], _take("scope")))
        self.assertIn("already holds a position", res.rejections[0]["reason"])

    def test_take_position_missing_position_rejected(self) -> None:
        d = _take("scope")
        d["position"] = "  "
        res = x.validate(_state(), _payload([_PID], d))
        self.assertIn("position", res.rejections[0]["reason"])

    def test_take_position_missing_argument_rejected(self) -> None:
        d = _take("scope")
        d["argument"] = ""
        res = x.validate(_state(), _payload([_PID], d))
        self.assertIn("argument", res.rejections[0]["reason"])

    def test_argue_nonexistent_key_rejected(self) -> None:
        res = x.validate(_state(), _payload([_PID], _argue("ghost")))
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_argue_held_position_rejected_backoff(self) -> None:
        prior = _state(positions=[_pos("scope", debate_status="held")])
        res = x.validate(prior, _payload([_PID], _argue("scope")))
        self.assertIn("not re-argued", res.rejections[0]["reason"])

    def test_argue_resolved_position_rejected(self) -> None:
        prior = _state(positions=[_pos("scope", debate_status="resolved")])
        res = x.validate(prior, _payload([_PID], _argue("scope")))
        self.assertIn("not re-argued", res.rejections[0]["reason"])

    def test_note_counter_nonexistent_rejected(self) -> None:
        res = x.validate(_state(), _payload([], _counter("ghost")))
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_note_counter_on_resolved_rejected(self) -> None:
        prior = _state(positions=[_pos("scope", debate_status="resolved")])
        res = x.validate(prior, _payload([], _counter("scope")))
        self.assertIn("resolved", res.rejections[0]["reason"])

    def test_resolve_nonexistent_rejected(self) -> None:
        res = x.validate(_state(), _payload(None, _resolve("ghost")))
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_resolve_bad_target_rejected(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload(None, _resolve("scope", to="archived")))
        self.assertIn("resolve 'to'", res.rejections[0]["reason"])

    def test_resolve_missing_reason_rejected(self) -> None:
        prior = _state(positions=[_pos("scope")])
        res = x.validate(prior, _payload(None, {"part": "p", "op": "resolve",
                                                "key": "scope", "to": "held"}))
        self.assertIn("reason", res.rejections[0]["reason"])

    def test_resolve_already_resolved_rejected(self) -> None:
        prior = _state(positions=[_pos("scope", debate_status="resolved")])
        res = x.validate(prior, _payload(None, _resolve("scope")))
        self.assertIn("already resolved", res.rejections[0]["reason"])

    def test_key_touched_twice_rejected(self) -> None:
        res = x.validate(_state(), _payload([_PID], _take("scope"),
                                            _take("scope", position="again")))
        self.assertEqual(len(res.approved_deltas), 1)      # first wins this tick
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("already touched", res.rejections[0]["reason"])

    def test_unknown_grounding_holds_tick(self) -> None:
        # A corrupt state with a grounding that is NEITHER records NOR values cannot be
        # validated → the whole tick is held (surface, don't guess a mode).
        state = _state(schema={"grounding": "nonsense"})
        res = x.validate(state, _payload([_PID], _take("scope")))
        self.assertFalse(res.ok)


class BodyForbiddenTest(unittest.TestCase):
    def _rejected(self, field, value) -> None:
        d = _take("scope")
        d[field] = value
        res = x.validate(_state(), _payload([_PID], d))
        self.assertTrue(res.ok)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn(field, res.rejections[0]["reason"])

    def test_body_cannot_set_owner_counter(self) -> None:
        self._rejected("owner_counter", 5)

    def test_body_cannot_set_debate_status(self) -> None:
        self._rejected("debate_status", "resolved")

    def test_body_cannot_set_history(self) -> None:
        self._rejected("history", [{"argument": "x"}])

    def test_body_cannot_set_provenance(self) -> None:
        self._rejected("provenance", ["[[forged]]"])

    def test_body_cannot_set_at(self) -> None:
        self._rejected("at", "1999-01-01")

    def test_body_cannot_set_resolve_reason(self) -> None:
        self._rejected("resolve_reason", "sneaky")


# =============================================================================
# persist — the ops + the append-only argument history
# =============================================================================

class PersistTest(unittest.TestCase):
    def _do(self, state, oracle, *deltas) -> dict:
        res = x.validate(state, _payload(oracle, *deltas))
        self.assertTrue(res.ok, res.rejections)
        return x.persist(state, res.approved_deltas, None)

    def test_take_position_creates_open_entry(self) -> None:
        ns = self._do(_state(), [_PID], _take("scope", position="hold", argument="drifting"))
        p = ns["positions"][0]
        self.assertEqual(p["position"], "hold")
        self.assertEqual(p["argument"], "drifting")
        self.assertEqual(p["citations"], [_PID])
        self.assertEqual(p["debate_status"], "open")
        self.assertEqual(p["owner_counter"], 0)
        self.assertEqual(p["history"], [])
        self.assertEqual(p["provenance"], [_PID])

    def test_argue_pushes_prior_onto_history_latest_wins(self) -> None:
        s1 = self._do(_state(), [_PID], _take("scope", argument="v1"))
        s2 = self._do(s1, [_PID, _PID2], _argue("scope", cited=[_PID2], argument="v2"))
        p = s2["positions"][0]
        self.assertEqual(p["argument"], "v2")              # latest wins
        self.assertEqual(p["citations"], [_PID2])
        self.assertEqual(len(p["history"]), 1)             # the prior kept
        self.assertEqual(p["history"][0]["argument"], "v1")
        self.assertEqual(p["history"][0]["citations"], [_PID])
        self.assertEqual(p["provenance"], [_PID, _PID2])   # grow-only across arguments

    def test_argue_keeps_position_headline(self) -> None:
        s1 = self._do(_state(), [_PID], _take("scope", position="hold the line"))
        s2 = self._do(s1, [_PID], _argue("scope"))
        self.assertEqual(s2["positions"][0]["position"], "hold the line")

    def test_full_trajectory_accumulates_history(self) -> None:
        s = self._do(_state(), [_PID], _take("scope", argument="a1"))
        for arg in ("a2", "a3", "a4"):
            s = self._do(s, [_PID], _argue("scope", argument=arg))
        p = s["positions"][0]
        self.assertEqual(p["argument"], "a4")
        self.assertEqual([h["argument"] for h in p["history"]], ["a1", "a2", "a3"])

    def test_resolve_closes_and_keeps_trail(self) -> None:
        s1 = self._do(_state(), [_PID], _take("scope", argument="v1"))
        s2 = self._do(s1, None, _resolve("scope", to="resolved", reason="owner agreed"))
        p = s2["positions"][0]
        self.assertEqual(p["debate_status"], "resolved")
        self.assertEqual(p["resolve_reason"], "owner agreed")
        self.assertEqual(p["argument"], "v1")              # argument preserved (never deleted)


# =============================================================================
# Counter-backoff — two note-counter → auto-held; then never re-argued
# =============================================================================

class CounterBackoffTest(unittest.TestCase):
    def _do(self, state, oracle, *deltas) -> dict:
        res = x.validate(state, _payload(oracle, *deltas))
        self.assertTrue(res.ok, res.rejections)
        return x.persist(state, res.approved_deltas, None)

    def test_one_counter_stays_open(self) -> None:
        s1 = self._do(_state(), [_PID], _take("scope"))
        s2 = self._do(s1, [], _counter("scope"))
        p = s2["positions"][0]
        self.assertEqual(p["owner_counter"], 1)
        self.assertEqual(p["debate_status"], "open")

    def test_two_counters_auto_hold(self) -> None:
        s = self._do(_state(), [_PID], _take("scope"))
        s = self._do(s, [], _counter("scope"))
        s = self._do(s, [], _counter("scope"))
        p = s["positions"][0]
        self.assertEqual(p["owner_counter"], 2)
        self.assertEqual(p["debate_status"], "held")       # auto-backoff
        self.assertIn("backing off", p["resolve_reason"])

    def test_backoff_blocks_further_argue(self) -> None:
        # End-to-end: two counters auto-hold, and a subsequent argue is refused (the
        # backoff is enforced by validate reading the held status).
        s = self._do(_state(), [_PID], _take("scope"))
        s = self._do(s, [], _counter("scope"))
        s = self._do(s, [], _counter("scope"))
        res = x.validate(s, _payload([_PID], _argue("scope")))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not re-argued", res.rejections[0]["reason"])

    def test_counter_on_held_position_stays_held(self) -> None:
        s = self._do(_state(), [_PID], _take("scope"))
        s = self._do(s, [], _counter("scope"))
        s = self._do(s, [], _counter("scope"))             # → held
        s = self._do(s, [], _counter("scope"))             # a third counter on a held pos
        p = s["positions"][0]
        self.assertEqual(p["owner_counter"], 3)
        self.assertEqual(p["debate_status"], "held")       # stays held, no crash


# =============================================================================
# No-act guarantee — a stance carries no act op and no outward effect
# =============================================================================

class NoActGuaranteeTest(unittest.TestCase):
    def test_op_vocabulary_has_no_act(self) -> None:
        self.assertEqual(set(x.DELTAS),
                         {"take-position", "argue", "note-counter", "resolve"})
        for op in x.DELTAS:
            for banned in ("act", "emit", "send", "apply", "write"):
                self.assertNotIn(banned, op)

    def test_grounding_modes_is_dual_and_no_scalar(self) -> None:
        # Grounding is per-instance now: the plugin declares the SUPPORTED SET, and does
        # NOT expose a scalar GROUNDING_MODEL (a scalar would lie about a dual kind).
        self.assertEqual(x.GROUNDING_MODES, ("records", "values"))
        self.assertFalse(hasattr(x, "GROUNDING_MODEL"))

    def test_persist_only_changes_state_no_side_channel(self) -> None:
        # A stance persist returns new state and nothing else — the outward surfacing is
        # the role's role-nudge channel (owned by roles_persist), never the plugin.
        res = x.validate(_state(), _payload([_PID], _take("scope")))
        ns = x.persist(_state(), res.approved_deltas, None)
        self.assertIn("positions", ns)
        self.assertFalse(hasattr(x, "act"))
        self.assertFalse(hasattr(x, "emit"))


# =============================================================================
# consumed_records — EMPTY (a stance consumes no records)
# =============================================================================

class ConsumedRecordsTest(unittest.TestCase):
    def test_consumed_is_empty_even_with_provenance(self) -> None:
        state = _state(positions=[_pos("scope", cited=[_PID, _PID2])])
        self.assertEqual(list(x.consumed_records(state)), [])   # principles are not records


# =============================================================================
# render
# =============================================================================

class RenderTest(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(x.render(_state()), "_No positions yet._")

    def test_grouped_open_then_held_then_resolved(self) -> None:
        state = _state(positions=[
            _pos("a", position="A", debate_status="resolved", resolve_reason="done"),
            _pos("b", position="B", debate_status="open", owner_counter=1),
            _pos("c", position="C", debate_status="held", resolve_reason="backed off")])
        out = x.render(state)
        self.assertLess(out.index("### open"), out.index("### held"))
        self.assertLess(out.index("### held"), out.index("### resolved"))
        self.assertIn("owner pushed back 1×", out)
        self.assertIn("grounded in: " + _PID, out)


# =============================================================================
# Composite-seam hooks
# =============================================================================

class SeamHooksTest(unittest.TestCase):
    def test_known_key_numbers_empty(self) -> None:
        self.assertEqual(list(x.known_key_numbers(_state())), [])

    def test_identity_anchored_never_fabricates(self) -> None:
        idr = x.identity({"key": "scope"}, None)
        self.assertTrue(idr.anchored)
        self.assertIsNone(idr.anchor)

    def test_gate_identity_passthrough(self) -> None:
        kept, sigs = x.gate_identity("r", "p", _state(), [{"op": "take-position", "key": "s"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(sigs, [])

    def test_content_view_and_adopt_round_trip(self) -> None:
        stored = [_pos("scope")]
        cv = x.content_view(_state(positions=stored))
        self.assertEqual(cv["positions"], stored)
        adopted = x.adopt_staging(_state(positions=[]), cv)     # schema NOT frozen
        self.assertEqual(adopted["positions"], stored)

    def test_content_summary(self) -> None:
        state = _state(positions=[_pos("a", position="hold"),
                                  _pos("b", position="press", debate_status="held")])
        labels = x.content_summary(state)
        self.assertIn("a: hold", labels[0])
        self.assertIn("b: press (held)", labels[1])

    def test_registry_summary_breakdown_render_order(self) -> None:
        state = _state(positions=[_pos("a", debate_status="open"),
                                  _pos("b", debate_status="open"),
                                  _pos("c", debate_status="resolved")])
        summ = x.registry_summary(state)
        self.assertEqual(summ["total"], 3)
        self.assertEqual(summ["breakdown"], [["open", 2], ["resolved", 1]])

    def test_registry_summary_counts_staged(self) -> None:
        state = _state(positions=[], staging={"positions": [_pos("a")]})
        self.assertEqual(x.registry_summary(state)["staged"], 1)

    def test_delta_counts(self) -> None:
        added, advanced = x.delta_counts([
            {"op": "take-position"}, {"op": "argue"}, {"op": "note-counter"},
            {"op": "resolve"}])
        self.assertEqual((added, advanced), (1, 3))

    def test_build_decisions_kinds(self) -> None:
        prior = _state(positions=[_pos("a"), _pos("b")])
        approved = [_take("c"), _argue("a"), _counter("b"), _resolve("a")]
        rows = x.build_decisions(approved, [], prior, "r", "p", "tick", "ts")
        self.assertEqual([r["kind"] for r in rows],
                         ["position-take", "position-argue", "position-counter",
                          "position-resolve"])
        self.assertEqual(rows[0]["cited"], [_PID])

    def test_cold_materialize_decisions(self) -> None:
        state = _state(positions=[_pos("scope", cited=[_PID])])
        rows = x.cold_materialize_decisions(state, "r", "p", "ts")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "cold-materialize")
        self.assertEqual(rows[0]["debate_status"], "open")


# =============================================================================
# PART_GROUNDING_MODES grew to include `values`
# =============================================================================

class GroundingModesGrewTest(unittest.TestCase):
    def test_values_is_a_grounding_mode(self) -> None:
        self.assertIn("values", rc.PART_GROUNDING_MODES)
        self.assertEqual(rc.PART_GROUNDING_MODES,
                         frozenset({"records", "owner-confirm", "values"}))


# =============================================================================
# Watermark generalization — byte-identical for records kinds; safe for values
# =============================================================================

class WatermarkGeneralizationTest(unittest.TestCase):
    """The `_progress` forward watermark now advances over `read_records ∪
    consumed_records`. These prove the union is a no-op for a records kind (consumed ⊆
    read, never above the prior watermark) and never breaks for a values kind."""

    def test_union_with_subset_is_noop(self) -> None:
        read = ["2026-07-01", "2026-07-05", "2026-07-03"]
        consumed_subset = ["2026-07-03"]                   # ⊆ read, ≤ max
        self.assertEqual(rp._advance_watermark(None, read),
                         rp._advance_watermark(None, read + consumed_subset))

    def test_older_consumed_never_raises_watermark(self) -> None:
        # A records kind's historical consumed stems are all ≤ the prior watermark, so
        # including them never moves it.
        self.assertEqual(rp._advance_watermark("2026-07-20", ["2026-07-25"]),
                         rp._advance_watermark("2026-07-20", ["2026-07-25", "2026-07-10"]))

    def test_values_kind_empty_consumed_does_not_break(self) -> None:
        # A stance reads no records this tick: read_records=[] + consumed=[] → stays put.
        self.assertIsNone(rp._advance_watermark(None, [] + []))
        # With a records-bearing remit it still rides the shared watermark.
        self.assertEqual(rp._advance_watermark(None, ["2026-07-05"] + []), "2026-07-05")

    def test_part_is_fresh_records_grounding_unchanged(self) -> None:
        # A records grounding: seen_watermark None + no staging → fresh, exactly as before
        # (the content branch is never entered for grounding == "records"). This is the
        # branch a records-grounded stance ALSO rides — it consumes its cited records on
        # adopt, so its watermark leaves None like any records kind.
        self.assertTrue(rp._part_is_fresh({"seen_watermark": None, "staging": None},
                                          "records"))
        self.assertFalse(rp._part_is_fresh({"seen_watermark": "2026-07-01",
                                            "staging": None}, "records"))
        self.assertFalse(rp._part_is_fresh({"seen_watermark": None,
                                            "staging": {"items": []}}, "records"))

    def test_part_is_fresh_values_stance_uses_content_not_watermark(self) -> None:
        # A values stance with a live position but a None watermark is NOT fresh (would
        # re-arm cold-start otherwise); one with no content IS fresh. The content branch
        # is gated on grounding != "records", threaded from PartSpec.grounding.
        adopted = _state(positions=[_pos("scope")], seen_watermark=None, staging=None)
        self.assertFalse(rp._part_is_fresh(adopted, "values", x))
        empty = _state(positions=[], seen_watermark=None, staging=None)
        self.assertTrue(rp._part_is_fresh(empty, "values", x))


# =============================================================================
# Config threading — real _parse_parts + writer overlay
# =============================================================================

_STANCE_CONFIG = """id: opponent
name: Opponent
parts:
  - id: positions
    kind: stance
    schema:
      grounding: values
cadence: daily
status: active
schema_version: 2
remit:
  all: true
"""


class ConfigThreadingTest(unittest.TestCase):
    def test_loads_and_overlays_schema(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / "opponent"
        rdir.mkdir(parents=True)
        (rdir / "config.yml").write_text(_STANCE_CONFIG, encoding="utf-8")

        cfg = rc.load_role_config("opponent", base)
        part = next(p for p in cfg.parts if p.kind == "stance")
        self.assertEqual(part.grounding, "values")
        self.assertFalse(part.grounding_check)

        fresh = rp._load_part_state("opponent", part, base)
        self.assertEqual(fresh["schema"]["grounding"], "values")
        self.assertEqual(fresh["positions"], [])

    def test_records_grounding_in_config_loads(self) -> None:
        # `grounding: records` is now a valid stance config (the default push-back mode);
        # PartSpec.grounding threads through so the writer's seams route to records.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text(
            "id: r\nparts:\n  - id: p\n    kind: stance\n    schema:\n"
            "      grounding: records\nremit: {all: true}\ncadence: daily\nstatus: active\n",
            encoding="utf-8")
        cfg = rc.load_role_config_file(path)
        part = next(p for p in cfg.parts if p.kind == "stance")
        self.assertEqual(part.grounding, "records")

    def test_missing_grounding_in_config_fails_closed(self) -> None:
        # No grounding declared → fail-closed (no silent default; the concierge emits it).
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text(
            "id: r\nparts:\n  - id: p\n    kind: stance\n    schema: {}\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n",
            encoding="utf-8")
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(path)
        self.assertIn("grounding", str(ctx.exception))


# =============================================================================
# Full lifecycle through the real roles_persist writer — the two seams end-to-end
# =============================================================================

_ORACLE = {"positions": [_PID, _PID2]}

_ROLE_CONFIG = """id: opponent
name: Opponent
parts:
  - { id: positions, kind: stance, schema: { grounding: values } }
cadence: daily
status: active
schema_version: 2
remit:
  globs: ["1_projects/x/**"]
"""

_COMPOSITE_CONFIG = """id: opponent
name: Opponent
parts:
  - { id: work,      kind: ledger }
  - { id: positions, kind: stance, schema: { grounding: values } }
cadence: daily
status: active
schema_version: 2
remit:
  globs: ["1_projects/x/**"]
"""


class StanceLifecycleTest(unittest.TestCase):
    """Drives real `roles_persist.run` ticks: cold-start → approve → argue, proving the
    adopted stance is not re-armed for cold-start (generalized freshness) and the
    values-oracle reaches the plugin through the payload lane."""

    ROLE = "opponent"
    CONFIG = _ROLE_CONFIG

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / "config.yml").write_text(self.CONFIG, encoding="utf-8")
        # The writer existence-filters the injected oracle against 0_constitution/, so a
        # real tick needs the cited principle-ids to resolve to real files under the base.
        _seed_constitution(self.base, _PID, _PID2)

    @property
    def rdir(self) -> Path:
        return self.base / "_system" / "roles" / self.ROLE

    def _mkrec(self, *stems: str) -> None:
        d = self.base / "1_projects" / "x"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text("---\ntype: meeting\n---\nbody\n", encoding="utf-8")

    def _part(self, part_id="positions") -> dict:
        return json.loads((self.rdir / "parts" / f"{part_id}.json").read_text(encoding="utf-8"))

    def _run(self, deltas=None, approve=False) -> dict:
        payload = None if approve else {
            "role_id": self.ROLE, "hook": "tick", "deltas": deltas or [],
            "values_oracles": _ORACLE,
        }
        return rp.run(self.ROLE, payload, approve_coldstart=approve, base=self.base)

    def test_cold_start_then_adopt_not_re_armed_and_argue_progresses(self) -> None:
        self._mkrec("2026-07-01-note")
        # Tick 1: take-position on a fresh part → cold-start staged.
        s1 = self._run([_take("scope", position="hold", argument="v1") | {"part": "positions"}])
        self.assertEqual(s1["outcome"], "cold-start-staged")
        self.assertIsNone(self._part()["seen_watermark"])          # not advanced pre-approval
        self.assertIsInstance(self._part()["staging"], dict)

        # Approve → the position goes live; watermark stays None (a stance consumes no
        # records), and state.md renders the stance zone (proving the adopted part is
        # not skipped as "fresh").
        self._run(approve=True)
        part = self._part()
        self.assertIsNone(part["staging"])
        self.assertIsNone(part["seen_watermark"])                  # values kind → stays None
        self.assertEqual(len(part["positions"]), 1)
        state_md = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("<!-- AUTO: role-state/positions", state_md)
        self.assertIn("hold", state_md)

        # Tick 2 after adopt: an argue must PROGRESS (not re-stage). This is the
        # generalized-freshness proof — a None watermark no longer means "cold-start".
        self._mkrec("2026-07-05-note")
        s3 = self._run([_argue("scope", argument="v2") | {"part": "positions"}])
        self.assertEqual(s3["outcome"], "progress")
        p = self._part()["positions"][0]
        self.assertEqual(p["argument"], "v2")
        self.assertEqual(len(p["history"]), 1)                     # v1 preserved
        # On a progress tick the stance rides the shared records watermark.
        self.assertEqual(self._part()["seen_watermark"], "2026-07-05-note")

    def test_forged_principle_rejected_end_to_end(self) -> None:
        # A body citing a principle NOT in the injected oracle is rejected by the writer.
        self._mkrec("2026-07-01-note")
        summary = self._run([
            _take("scope", cited=["fabricated-999"]) | {"part": "positions"}])
        self.assertEqual(summary["run_status"], "rejected")
        ppath = self.rdir / "parts" / "positions.json"
        if ppath.exists():
            self.assertEqual(self._part()["positions"], [])   # nothing persisted

    def test_no_oracle_injected_fails_closed(self) -> None:
        # A payload with NO values_oracles → the stance's oracle is empty → fail-closed.
        self._mkrec("2026-07-01-note")
        payload = {"role_id": self.ROLE, "hook": "tick",
                   "deltas": [_take("scope") | {"part": "positions"}]}   # no values_oracles
        summary = rp.run(self.ROLE, payload, base=self.base)
        self.assertEqual(summary["run_status"], "rejected")

    def test_writer_drops_fabricated_id_from_regressed_oracle(self) -> None:
        # Simulate a REGRESSED Stage 2.6 that let a FABRICATED principle-id INTO the
        # oracle (the fake is NOT in 0_constitution/). The writer's deterministic
        # existence filter drops it BEFORE the plugin's ⊆-check, so a body citing that
        # fake id is REJECTED even though the (regressed) oracle "held" it — proving the
        # existence half is enforced at the WRITER, independent of Stage 2.6.
        self._mkrec("2026-07-01-note")
        fake = "principle-fabricated-999"                    # not seeded → does not resolve
        payload = {
            "role_id": self.ROLE, "hook": "tick",
            "deltas": [_take("scope", cited=[fake]) | {"part": "positions"}],
            "values_oracles": {"positions": [_PID, fake]},   # regressed: real + fabricated
        }
        summary = rp.run(self.ROLE, payload, base=self.base)
        self.assertEqual(summary["run_status"], "rejected")
        ppath = self.rdir / "parts" / "positions.json"
        if ppath.exists():
            self.assertEqual(self._part()["positions"], [])  # nothing persisted

    def test_writer_keeps_real_id_from_regressed_oracle(self) -> None:
        # The SAME regressed oracle (real + fabricated), but the body cites the REAL id.
        # The real id survives the existence filter (the fabricated one's presence does
        # not poison it), so the take-position is ACCEPTED — cold-start staged. Proves the
        # filter drops on EXISTENCE only, never over-filtering a genuine principle.
        self._mkrec("2026-07-01-note")
        fake = "principle-fabricated-999"
        payload = {
            "role_id": self.ROLE, "hook": "tick",
            "deltas": [_take("scope", cited=[_PID]) | {"part": "positions"}],
            "values_oracles": {"positions": [_PID, fake]},
        }
        summary = rp.run(self.ROLE, payload, base=self.base)
        self.assertEqual(summary["outcome"], "cold-start-staged")
        self.assertEqual(len(self._part()["staging"]["positions"]), 1)


class RecordsKindByteIdenticalInCompositeTest(StanceLifecycleTest):
    """A sibling ledger part in the SAME role advances its records watermark exactly as
    a records kind always has — the union with (empty) stance consumption changes
    nothing for it. Proves the seam generalization did not perturb records kinds."""

    CONFIG = _COMPOSITE_CONFIG

    def _add(self, pk, title, rec) -> dict:
        return {"op": "add", "part": "work", "provisional_key": pk, "title": title,
                "anchor": "project:minder", "status": "new", "provenance": [f"[[{rec}]]"]}

    def test_ledger_watermark_is_max_read_records_not_just_cited(self) -> None:
        self._mkrec("2026-07-01-a")
        # Cold-start the ledger part alone, then approve.
        self._run([self._add("w1", "WS one", "2026-07-01-a")])
        self._run(approve=True)
        self.assertEqual(self._part("work")["seen_watermark"], "2026-07-01-a")

        # Two records now in remit; the ledger add cites only the OLDER one, yet the
        # watermark advances to the NEWER (max of read_records), exactly as before the
        # union change — the consumed subset never lowers it.
        self._mkrec("2026-07-09-c")
        summary = self._run([self._add("w2", "WS two", "2026-07-01-a")])   # cites older
        self.assertEqual(summary["run_status"], "ok")
        self.assertEqual(self._part("work")["seen_watermark"], "2026-07-09-c")

    # The stance lifecycle tests inherited from the base also run against the composite
    # config, exercising the two parts side by side.


# =============================================================================
# Records-grounded stance — full lifecycle through the real writer
# =============================================================================

_RECORDS_ROLE_CONFIG = """id: notewatch
name: Notewatch
parts:
  - { id: positions, kind: stance, schema: { grounding: records } }
cadence: daily
status: active
schema_version: 2
remit:
  globs: ["1_projects/x/**"]
"""


class RecordsStanceLifecycleTest(unittest.TestCase):
    """Drives real `roles_persist.run` ticks for a RECORDS-grounded stance: cold-start →
    approve → argue. Proves it rides the shared RECORDS watermark (unlike a values
    stance, whose watermark stays None), needs NO values oracle (Stage 2.6 skipped — the
    payload carries none), does not auto-pause on valid notes, and is NOT re-armed for
    cold-start after adopt (freshness via the watermark proxy — the records branch)."""

    ROLE = "notewatch"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / "config.yml").write_text(_RECORDS_ROLE_CONFIG, encoding="utf-8")
        # NOTE: no constitution is seeded — a records-grounded stance never consults it.

    @property
    def rdir(self) -> Path:
        return self.base / "_system" / "roles" / self.ROLE

    def _mkrec(self, *stems: str) -> None:
        d = self.base / "1_projects" / "x"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text("---\ntype: meeting\n---\nbody\n", encoding="utf-8")

    def _part(self, part_id="positions") -> dict:
        return json.loads((self.rdir / "parts" / f"{part_id}.json").read_text(encoding="utf-8"))

    def _run(self, deltas=None, approve=False) -> dict:
        # No `values_oracles` in the payload — a records-grounded stance is Stage-2.6-skipped.
        payload = None if approve else {
            "role_id": self.ROLE, "hook": "tick", "deltas": deltas or [],
        }
        return rp.run(self.ROLE, payload, approve_coldstart=approve, base=self.base)

    def test_rides_records_watermark_and_not_re_armed(self) -> None:
        self._mkrec("2026-07-01-note")
        # Tick 1: take-position citing an in-remit record → cold-start staged.
        s1 = self._run([_take("scope", cited=["2026-07-01-note"], argument="v1")
                        | {"part": "positions"}])
        self.assertEqual(s1["outcome"], "cold-start-staged")
        self.assertIsNone(self._part()["seen_watermark"])          # not advanced pre-approval

        # Approve → live; the records stance CONSUMES its cited record, so the watermark
        # advances OFF None (the KEY difference from a values stance, which stays None).
        self._run(approve=True)
        part = self._part()
        self.assertIsNone(part["staging"])
        self.assertEqual(part["seen_watermark"], "2026-07-01-note")   # records watermark!
        self.assertEqual(len(part["positions"]), 1)
        state_md = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("<!-- AUTO: role-state/positions", state_md)

        # Tick 2 after adopt: an argue citing a NEWER in-remit record PROGRESSES (not
        # re-stage) — the generalized-freshness proof via the watermark proxy — and needs
        # no values oracle. Does NOT auto-pause (valid notes).
        self._mkrec("2026-07-09-note")
        s3 = self._run([_argue("scope", cited=["2026-07-09-note"], argument="v2")
                        | {"part": "positions"}])
        self.assertEqual(s3["outcome"], "progress")
        p = self._part()["positions"][0]
        self.assertEqual(p["argument"], "v2")
        self.assertEqual(len(p["history"]), 1)                     # v1 preserved
        self.assertEqual(p["citations"], ["2026-07-09-note"])
        self.assertEqual(self._part()["seen_watermark"], "2026-07-09-note")
        self.assertNotEqual(self._part().get("status"), "paused")  # never auto-paused

    def test_out_of_remit_citation_rejected(self) -> None:
        # A body citing a record NOT in the role's remit is rejected end-to-end (the
        # records oracle is the engine-authored read_records, which the body cannot forge).
        self._mkrec("2026-07-01-note")
        summary = self._run([_take("scope", cited=["ghost-note"]) | {"part": "positions"}])
        self.assertEqual(summary["run_status"], "rejected")
        ppath = self.rdir / "parts" / "positions.json"
        if ppath.exists():
            self.assertEqual(self._part()["positions"], [])        # nothing persisted


# =============================================================================
# Writer existence filter — the deterministic net BENEATH Stage 2.6 (unit level)
# =============================================================================

import types  # noqa: E402

import _common  # noqa: E402


class ConstitutionExistenceFilterUnitTest(unittest.TestCase):
    """Directly exercises the two pure pieces of the writer-level net:
    `_common.constitution_principle_ids` (the existence set) and
    `roles_persist._inject_values_oracles` (the per-part prune). Proves the mechanism
    without a full tick and independent of any prompt stage."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_id_set_collects_real_excludes_missing_and_malformed(self) -> None:
        _seed_constitution(self.base, _PID, _PID2)
        # A malformed principle file (broken YAML) must NOT contribute an id — the
        # tolerant walker fails closed on it, never raising.
        (self.base / "0_constitution" / "rule").mkdir(parents=True, exist_ok=True)
        (self.base / "0_constitution" / "rule" / "broken.md").write_text(
            "---\nid: [unterminated\n---\nbody\n", encoding="utf-8")
        ids = _common.constitution_principle_ids(self.base)
        self.assertIn(_PID, ids)
        self.assertIn(_PID2, ids)
        self.assertNotIn("principle-fabricated-999", ids)   # never written
        self.assertNotIn("rule-broken-000", ids)            # malformed → dropped

    def test_id_set_empty_when_no_constitution(self) -> None:
        # No 0_constitution/ under the base → empty set, no crash (fail-closed).
        self.assertEqual(_common.constitution_principle_ids(self.base), set())

    def _cfg_plugins(self):
        # The seam is gated on the PART's grounding (PartSpec.grounding), so the values
        # instance is selected by `grounding="values"` on the part — not a plugin constant.
        cfg = types.SimpleNamespace(
            parts=[types.SimpleNamespace(id="positions", grounding="values")])
        plugins = {"positions": x}   # the real stance plugin (dual-grounded)
        return cfg, plugins

    def test_inject_drops_nonexistent_keeps_existing(self) -> None:
        _seed_constitution(self.base, _PID, _PID2)
        cfg, plugins = self._cfg_plugins()
        payload = {"values_oracles": {"positions": [_PID, "principle-fabricated-999", _PID2]}}
        out = rp._inject_values_oracles(cfg, plugins, payload, self.base)
        self.assertEqual(out["values_oracles"]["positions"], [_PID, _PID2])   # fake pruned
        self.assertIsNot(out, payload)                                         # copy, atomic

    def test_inject_preserves_dict_verdict_shape(self) -> None:
        _seed_constitution(self.base, _PID)
        cfg, plugins = self._cfg_plugins()
        payload = {"values_oracles":
                   {"positions": {_PID: "aligned", "principle-fabricated-999": "aligned"}}}
        out = rp._inject_values_oracles(cfg, plugins, payload, self.base)
        self.assertEqual(out["values_oracles"]["positions"], {_PID: "aligned"})

    def test_inject_noop_when_no_values_part(self) -> None:
        # A records-only role never walks the constitution and passes the payload through.
        cfg = types.SimpleNamespace(parts=[types.SimpleNamespace(id="log", grounding="records")])
        plugins = {"log": types.SimpleNamespace()}
        payload = {"values_oracles": {"positions": ["principle-fabricated-999"]}}
        out = rp._inject_values_oracles(cfg, plugins, payload, self.base)
        self.assertIs(out, payload)   # untouched — no values-grounded part

    def test_inject_noop_for_records_grounded_stance(self) -> None:
        # A stance instance with grounding=records is NOT a values part — the SAME plugin,
        # but the per-part gate reads PartSpec.grounding, so its oracle is left untouched
        # (it grounds in read_records, never the constitution). Proves the per-part seam.
        cfg = types.SimpleNamespace(
            parts=[types.SimpleNamespace(id="positions", grounding="records")])
        plugins = {"positions": x}   # dual-grounded stance plugin, records instance
        payload = {"values_oracles": {"positions": ["principle-fabricated-999"]}}
        out = rp._inject_values_oracles(cfg, plugins, payload, self.base)
        self.assertIs(out, payload)   # untouched — this stance instance is records-grounded

    def test_inject_selects_only_values_stance_in_composite(self) -> None:
        # A composite with BOTH a records-stance and a values-stance: only the values
        # instance's oracle is existence-filtered; the records instance's is left alone.
        _seed_constitution(self.base, _PID)
        cfg = types.SimpleNamespace(parts=[
            types.SimpleNamespace(id="notes", grounding="records"),
            types.SimpleNamespace(id="values", grounding="values"),
        ])
        plugins = {"notes": x, "values": x}
        payload = {"values_oracles": {
            "notes": ["principle-fabricated-999"],           # records instance → untouched
            "values": [_PID, "principle-fabricated-999"],    # values instance → pruned
        }}
        out = rp._inject_values_oracles(cfg, plugins, payload, self.base)
        self.assertEqual(out["values_oracles"]["notes"], ["principle-fabricated-999"])
        self.assertEqual(out["values_oracles"]["values"], [_PID])   # fake pruned


if __name__ == "__main__":
    unittest.main()
