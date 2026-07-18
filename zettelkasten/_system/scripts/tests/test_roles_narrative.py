"""Tests for roles_archetype_narrative.py — the Narrative archetype plugin.

Covers the validator (grounding rejects uncited citations, engine-owned fields
refused, empty text refused, churn-guard trips on a revision flood over an
established narrative), the pure persist transform (append-only versioning, purpose
headline update, never blanks prior versions), the render (present-state: purpose +
latest narrative + unincorporated shift), and the composite-seam hooks.

No I/O, no LLM — validate/persist are pure in-memory transforms.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_archetype_narrative as x  # noqa: E402


def _state(*entries: dict, purpose: str = "", **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "narrative",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": 3,
        "purpose": purpose,
        "entries": list(entries),
    }
    state.update(top)
    return state


def _entry(version: int, kind: str, text: str, *, at: str = "2026-01-01",
           evidence=None) -> dict:
    return {"version": version, "at": at, "kind": kind, "text": text,
            "evidence": list(evidence if evidence is not None else ["[[rec-a]]"])}


def _payload(read_records, *deltas) -> dict:
    return {"role_id": "r", "hook": "tick",
            "read_records": list(read_records), "deltas": list(deltas)}


def _op(op: str, text: str, evidence=None) -> dict:
    return {"part": "p", "op": op, "text": text,
            "evidence": list(evidence if evidence is not None else ["[[rec-a]]"])}


class NarrativeValidatorTest(unittest.TestCase):
    def test_grounded_set_purpose_accepted(self) -> None:
        res = x.validate(x.fresh_state(), _payload(["rec-a"], _op("set-purpose", "P")))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_ungrounded_rejected(self) -> None:
        res = x.validate(x.fresh_state(),
                         _payload(["rec-a"], _op("revise-narrative", "N", ["[[nope]]"])))
        self.assertTrue(res.ok)  # non-blocking on fresh
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_unknown_op_rejected(self) -> None:
        res = x.validate(x.fresh_state(), _payload(["rec-a"], _op("add", "N")))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("unknown op", res.rejections[0]["reason"])

    def test_engine_owned_field_refused(self) -> None:
        bad = _op("note-shift", "N")
        bad["version"] = 99
        res = x.validate(x.fresh_state(), _payload(["rec-a"], bad))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("engine-owned", res.rejections[0]["reason"])

    def test_empty_text_rejected(self) -> None:
        res = x.validate(x.fresh_state(), _payload(["rec-a"], _op("set-purpose", "   ")))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("text", res.rejections[0]["reason"])

    def test_missing_evidence_rejected(self) -> None:
        res = x.validate(x.fresh_state(),
                         _payload(["rec-a"], {"part": "p", "op": "note-shift", "text": "N"}))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("evidence", res.rejections[0]["reason"])

    def test_fresh_never_churns(self) -> None:
        # 5 statements on a fresh narrative is cold-start territory, not churn.
        deltas = [_op("note-shift", f"s{i}") for i in range(5)]
        res = x.validate(x.fresh_state(), _payload(["rec-a"], *deltas))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 5)

    def test_established_churn_holds(self) -> None:
        prior = _state(_entry(1, "purpose", "P"), purpose="P")
        deltas = [_op("note-shift", f"s{i}") for i in range(4)]  # > threshold 3
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertFalse(res.ok)
        self.assertTrue(res.clarifications)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_established_at_threshold_ok(self) -> None:
        prior = _state(_entry(1, "purpose", "P"), purpose="P")
        deltas = [_op("note-shift", f"s{i}") for i in range(3)]  # == threshold
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 3)


class NarrativePersistTest(unittest.TestCase):
    def test_set_purpose_updates_headline_and_appends_entry(self) -> None:
        res = x.validate(x.fresh_state(), _payload(["rec-a"], _op("set-purpose", "Keep it coherent")))
        state = x.persist(x.fresh_state(), res.approved_deltas, None)
        self.assertEqual(state["purpose"], "Keep it coherent")
        self.assertEqual(state["entries"][0]["kind"], "purpose")
        self.assertEqual(state["entries"][0]["version"], 1)

    def test_versions_monotonic_across_ops(self) -> None:
        payload = _payload(["rec-a"],
                           _op("set-purpose", "P"),
                           _op("revise-narrative", "N"),
                           _op("note-shift", "S"))
        res = x.validate(x.fresh_state(), payload)
        state = x.persist(x.fresh_state(), res.approved_deltas, None)
        self.assertEqual([e["version"] for e in state["entries"]], [1, 2, 3])
        self.assertEqual([e["kind"] for e in state["entries"]],
                         ["purpose", "narrative", "shift"])

    def test_persist_is_append_only(self) -> None:
        prior = _state(_entry(1, "narrative", "old"), purpose="P")
        res = x.validate(prior, _payload(["rec-a"], _op("revise-narrative", "new")))
        state = x.persist(prior, res.approved_deltas, None)
        # Prior version preserved; new one appended at version 2.
        self.assertEqual(len(state["entries"]), 2)
        self.assertEqual(state["entries"][0]["text"], "old")
        self.assertEqual(state["entries"][1]["version"], 2)

    def test_persist_does_not_mutate_input(self) -> None:
        prior = _state(_entry(1, "purpose", "P"), purpose="P")
        before = len(prior["entries"])
        res = x.validate(prior, _payload(["rec-a"], _op("revise-narrative", "N")))
        x.persist(prior, res.approved_deltas, None)
        self.assertEqual(len(prior["entries"]), before)


class NarrativeRenderTest(unittest.TestCase):
    def test_empty_state(self) -> None:
        self.assertEqual(x.render(x.fresh_state()), "_No narrative yet._")

    def test_render_shows_purpose_and_latest_narrative(self) -> None:
        state = _state(
            _entry(1, "purpose", "Keep coherent"),
            _entry(2, "narrative", "Reading v1"),
            _entry(3, "narrative", "Reading v2"),
            purpose="Keep coherent", part_id="purpose",
        )
        out = x.render(state)
        self.assertIn("**Purpose:** Keep coherent", out)
        self.assertIn("Reading v2", out)
        self.assertNotIn("Reading v1", out)  # only the latest narrative shows

    def test_headline_label_derives_from_part_id(self) -> None:
        # A non-purpose narrative part (e.g. `alignment`) must NOT mislabel its
        # headline as "Purpose" — the label comes from the part id, so a composite
        # role's state.md never renders two "Purpose:" sections.
        align = _state(_entry(1, "purpose", "Do the tasks serve the idea"),
                       purpose="Do the tasks serve the idea", part_id="alignment")
        self.assertIn("**Alignment:** Do the tasks serve the idea", x.render(align))
        self.assertNotIn("**Purpose:**", x.render(align))
        # A `purpose` part still reads "Purpose:".
        purp = _state(_entry(1, "purpose", "The north"), purpose="The north",
                      part_id="purpose")
        self.assertIn("**Purpose:** The north", x.render(purp))
        # A multi-word part id humanises: `recovery-stance` -> "Recovery stance".
        rec = _state(_entry(1, "purpose", "Sleep debt easing"),
                     purpose="Sleep debt easing", part_id="recovery-stance")
        self.assertIn("**Recovery stance:** Sleep debt easing", x.render(rec))
        # No part id (fresh/legacy state) falls back to a neutral label.
        bare = _state(_entry(1, "purpose", "H"), purpose="H")
        self.assertIn("**Headline:** H", x.render(bare))

    def test_recent_shift_shown_only_when_newer_than_narrative(self) -> None:
        newer_shift = _state(
            _entry(1, "narrative", "N"), _entry(2, "shift", "things moved"),
            purpose="P")
        self.assertIn("things moved", x.render(newer_shift))
        older_shift = _state(
            _entry(1, "shift", "old shift"), _entry(2, "narrative", "N"),
            purpose="P")
        self.assertNotIn("old shift", x.render(older_shift))


class NarrativeSeamHooksTest(unittest.TestCase):
    def test_known_key_numbers_empty(self) -> None:
        self.assertEqual(list(x.known_key_numbers(_state(_entry(1, "purpose", "P")))), [])

    def test_identity_is_no_op_anchored(self) -> None:
        self.assertTrue(x.identity({"text": "x"}).anchored)

    def test_gate_identity_passthrough(self) -> None:
        deltas = [_op("set-purpose", "P")]
        kept, signals = x.gate_identity("r", "p", x.fresh_state(), deltas)
        self.assertEqual(kept, deltas)
        self.assertEqual(signals, [])

    def test_delta_counts_all_advanced(self) -> None:
        # A narrative creates no keyed items → every statement is an advance.
        self.assertEqual(x.delta_counts([_op("set-purpose", "P"), _op("note-shift", "S")]), (0, 2))

    def test_content_view_adopt_round_trip(self) -> None:
        state = _state(_entry(1, "purpose", "P"), _entry(2, "narrative", "N"), purpose="P")
        content = x.content_view(state)
        self.assertEqual(content["purpose"], "P")
        self.assertEqual(len(content["entries"]), 2)
        staging = {"drafted_at": "t", **content}
        adopted = x.adopt_staging(x.fresh_state(), staging)
        self.assertEqual(adopted["purpose"], "P")
        self.assertEqual(len(adopted["entries"]), 2)

    def test_content_summary_is_entries_only_no_purpose_double_count(self) -> None:
        # A set-purpose creates ONE purpose entry; content_summary lists that entry
        # once — it does NOT also emit a separate "purpose:" headline line (which
        # would double-count a single statement with duplicated text).
        state = _state(_entry(1, "purpose", "Keep it coherent", evidence=["[[rec-a]]"]),
                       purpose="Keep it coherent")
        summary = x.content_summary(state)
        self.assertEqual(summary, ["purpose v1: Keep it coherent"])
        # And a plain narrative entry → one label, its evidence stems.
        state2 = _state(_entry(1, "narrative", "the reading",
                               evidence=["[[rec-a]]", "[[rec-b]]"]))
        self.assertEqual(x.content_summary(state2), ["narrative v1: the reading"])
        self.assertEqual(sorted(x.consumed_records(state2)), ["rec-a", "rec-b"])

    def test_build_decisions_kinds(self) -> None:
        deltas = [_op("set-purpose", "P"), _op("note-shift", "S")]
        rows = x.build_decisions(deltas, [], x.fresh_state(), "r", "p", "tick", "2026-07-01T00:00:00Z")
        self.assertEqual([r["kind"] for r in rows], ["purpose-set", "shift-noted"])
        self.assertEqual([r["version"] for r in rows], [1, 2])
        self.assertTrue(all(r["key"] is None and r["part"] == "p" for r in rows))

    def test_cold_materialize_decisions(self) -> None:
        state = _state(_entry(1, "purpose", "P"), _entry(2, "narrative", "N"), purpose="P")
        rows = x.cold_materialize_decisions(state, "r", "p", "2026-07-01T00:00:00Z")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["kind"] == "cold-materialize" for r in rows))


if __name__ == "__main__":
    unittest.main()
