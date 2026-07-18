"""End-to-end proof of a HETEROGENEOUS composite role — a `ledger` part and a
`narrative` part in one role — driven through the real `roles_persist.run` writer
against a tempdir ZTN base.

This is the definitive proof that the writer is archetype-agnostic: the same
cold-start / adopt / tick / churn / isolation machinery drives two DIFFERENT
part-kinds with no writer branch naming either. Claims proved:

  1. A first tick over a fresh composite stages BOTH parts (ledger items frozen +
     narrative draft frozen), emitting ONE aggregated role-cold-start clarification.
  2. `--approve-coldstart` adopts every pending part at once; both go live; state.md
     carries one AUTO sub-zone per part in config order, portrait preserved.
  3. A post-adopt tick advances the ledger AND revises the narrative in one pass;
     decisions.jsonl carries part-stamped rows from BOTH archetype vocabularies.
  4. A delta routed to the narrative part leaves the ledger part's file bytes and
     per-part hash untouched (isolation across archetypes).
  5. A narrative churn hold does not block the ledger part's independent progress
     in the same tick (per-part control paths).

Deterministic: no LLM, no network — the persist stage + record-grounding oracle
over real files on disk.
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

import role_state_hash  # noqa: E402
import roles_persist as x  # noqa: E402

ROLE_ID = "minder-pm"

COMPOSITE_CONFIG = """id: minder-pm
name: Minder PM
parts:
  - { id: workstreams, kind: ledger }
  - { id: purpose,     kind: narrative }
cadence: weekly
cadence_anchor: monday
status: active
schema_version: 2
remit:
  globs: ["1_projects/minder/**"]
"""


def _add(pk: str, title: str, rec: str) -> dict:
    return {"op": "add", "part": "workstreams", "provisional_key": pk,
            "title": title, "anchor": "project:minder", "status": "new",
            "provenance": [f"[[{rec}]]"]}


def _narr(op: str, text: str, rec: str) -> dict:
    return {"op": op, "part": "purpose", "text": text, "evidence": [f"[[{rec}]]"]}


def _payload(*deltas: dict) -> dict:
    return {"role_id": ROLE_ID, "hook": "tick", "deltas": list(deltas)}


class CompositeBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / "config.yml").write_text(COMPOSITE_CONFIG, encoding="utf-8")
        self._mkrec("2026-07-01-standup", "2026-07-08-standup")

    @property
    def rdir(self) -> Path:
        return self.base / "_system" / "roles" / ROLE_ID

    def _mkrec(self, *stems: str) -> None:
        d = self.base / "1_projects" / "minder"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text("---\ntype: meeting\n---\nbody\n", encoding="utf-8")

    def _run(self, payload, approve: bool = False) -> dict:
        return x.run(ROLE_ID, payload, approve_coldstart=approve, base=self.base)

    def _part(self, part_id: str) -> dict:
        return json.loads((self.rdir / "parts" / f"{part_id}.json").read_text(encoding="utf-8"))

    def _state_md(self) -> str:
        return (self.rdir / "state.md").read_text(encoding="utf-8")

    def _decisions(self) -> list:
        p = self.rdir / "decisions.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def _cold_start_and_adopt(self) -> None:
        """Stage both parts, then adopt them live."""
        self._run(_payload(
            _add("w1", "Ship auth", "2026-07-01-standup"),
            _narr("set-purpose", "Keep Minder coherent with the vision", "2026-07-01-standup"),
        ))
        self._run(None, approve=True)


class CompositeColdStartTest(CompositeBase):
    def test_first_tick_stages_both_parts(self) -> None:
        summary = self._run(_payload(
            _add("w1", "Ship auth", "2026-07-01-standup"),
            _narr("set-purpose", "Keep Minder coherent", "2026-07-01-standup"),
        ))
        self.assertEqual(summary["outcome"], "cold-start-staged")
        # Both parts frozen; nothing live yet.
        self.assertIsInstance(self._part("workstreams")["staging"], dict)
        self.assertIsInstance(self._part("purpose")["staging"], dict)
        self.assertEqual(self._part("workstreams")["items"], [])
        self.assertEqual(self._part("purpose")["entries"], [])
        # ONE aggregated role-cold-start clarification covering both parts.
        clar = (self.base / "_system" / "state" / "CLARIFICATIONS.md").read_text(encoding="utf-8")
        self.assertIn("role-cold-start: minder-pm", clar)
        self.assertIn("workstreams", clar)
        self.assertIn("purpose", clar)

    def test_approve_adopts_both_live(self) -> None:
        self._cold_start_and_adopt()
        ws = self._part("workstreams")
        pu = self._part("purpose")
        self.assertIsNone(ws["staging"])
        self.assertIsNone(pu["staging"])
        self.assertEqual(ws["items"][0]["key"], "lk-0001")
        self.assertEqual(pu["purpose"], "Keep Minder coherent with the vision")
        self.assertEqual(pu["entries"][0]["kind"], "purpose")

    def test_state_md_has_both_zones_in_order_portrait_preserved(self) -> None:
        self._cold_start_and_adopt()
        md = self._state_md()
        i_ws = md.find("<!-- AUTO: role-state/workstreams")
        i_pu = md.find("<!-- AUTO: role-state/purpose")
        self.assertGreater(i_ws, 0)
        self.assertGreater(i_pu, i_ws, "zones must appear in config parts[] order")
        self.assertIn("Ship auth", md)
        self.assertIn("**Purpose:** Keep Minder coherent", md)
        # Owner portrait hint above the zones survives.
        self.assertLess(md.find("Portrait:"), i_ws)


class StagedPartRenderTest(CompositeBase):
    def test_staged_part_leaks_no_zone_when_sibling_progresses(self) -> None:
        # Partial cold-start: only the ledger part gets a first draft; the narrative
        # part stays fresh (no delta). Adopt → ledger live, narrative still fresh.
        self._run(_payload(_add("w1", "Ship auth", "2026-07-01-standup")))
        self._run(None, approve=True)
        self.assertIsNone(self._part("workstreams")["staging"])
        # Now a tick that PROGRESSES the live ledger AND first-drafts (stages) the
        # narrative in the SAME tick. The staged narrative must NOT leak a sub-zone.
        self._run(_payload(
            {"op": "advance", "part": "workstreams", "key": "lk-0001",
             "to_status": "active", "evidence": ["[[2026-07-08-standup]]"]},
            _narr("set-purpose", "Coherent with the vision", "2026-07-08-standup"),
        ))
        md = self._state_md()
        self.assertIn("<!-- AUTO: role-state/workstreams", md)      # live part rendered
        self.assertNotIn("<!-- AUTO: role-state/purpose", md)       # staged part: NO zone
        # The narrative is genuinely staged, not live.
        self.assertIsInstance(self._part("purpose")["staging"], dict)
        self.assertEqual(self._part("purpose")["entries"], [])


class CompositeTickTest(CompositeBase):
    def test_post_adopt_tick_progresses_both_archetypes(self) -> None:
        self._cold_start_and_adopt()
        summary = self._run(_payload(
            {"op": "advance", "part": "workstreams", "key": "lk-0001",
             "to_status": "active", "evidence": ["[[2026-07-08-standup]]"]},
            _narr("revise-narrative", "Auth work is the spine now", "2026-07-08-standup"),
        ))
        self.assertEqual(summary["outcome"], "progress")
        # Ledger advanced.
        self.assertEqual(self._part("workstreams")["items"][0]["status"], "active")
        # Narrative gained a version-2 narrative entry (append-only).
        entries = self._part("purpose")["entries"]
        self.assertEqual(entries[-1]["kind"], "narrative")
        self.assertEqual(entries[-1]["version"], 2)
        # decisions.jsonl carries rows from BOTH vocabularies, part-stamped.
        kinds = {(d["part"], d["kind"]) for d in self._decisions()}
        self.assertIn(("workstreams", "status-advance"), kinds)
        self.assertIn(("purpose", "narrative-revised"), kinds)

    def test_set_field_on_ledger_within_composite(self) -> None:
        self._cold_start_and_adopt()
        self._run(_payload({
            "op": "set-field", "part": "workstreams", "key": "lk-0001",
            "field": "priority", "value": "high", "evidence": ["[[2026-07-08-standup]]"],
        }))
        self.assertEqual(self._part("workstreams")["items"][0]["priority"], "high")
        self.assertIn("prio:high", self._state_md())


class CompositeIsolationTest(CompositeBase):
    def test_narrative_delta_leaves_ledger_untouched(self) -> None:
        self._cold_start_and_adopt()
        ws_before = (self.rdir / "parts" / "workstreams.json").read_bytes()
        ws_hash_before = self._part("workstreams")["state_auto_hash"]
        self._run(_payload(_narr("note-shift", "Momentum picked up", "2026-07-08-standup")))
        ws_after = (self.rdir / "parts" / "workstreams.json").read_bytes()
        self.assertEqual(ws_before, ws_after, "ledger file must be byte-identical")
        self.assertEqual(self._part("workstreams")["state_auto_hash"], ws_hash_before)
        # The narrative gained the shift.
        self.assertEqual(self._part("purpose")["entries"][-1]["kind"], "shift")

    def test_unroutable_only_tick_rejects_and_surfaces(self) -> None:
        # A tick whose only delta names a part the role does not have must NOT read
        # as a clean `empty` success (which would advance cadence and hide the drop).
        # It degrades to `rejected` AND emits a role-unroutable clarification.
        self._cold_start_and_adopt()
        summary = self._run(_payload(
            {"op": "note-shift", "part": "ghostpart", "text": "x",
             "evidence": ["[[2026-07-08-standup]]"]}))
        self.assertEqual(summary["run_status"], "rejected")
        self.assertEqual(summary["outcome"], "rejected")
        self.assertIn("role-unroutable", summary["clarifications"])
        clar = (self.base / "_system" / "state" / "CLARIFICATIONS.md").read_text(encoding="utf-8")
        self.assertIn("role-unroutable: minder-pm", clar)
        self.assertIn("ghostpart", clar)
        self.assertIn("workstreams, purpose", clar)  # the role's real parts named
        # Nothing was persisted to either part.
        self.assertEqual(self._part("purpose")["entries"][-1]["kind"], "purpose")  # unchanged

    def test_narrative_churn_hold_does_not_block_ledger_progress(self) -> None:
        self._cold_start_and_adopt()
        # 4 narrative statements (> threshold 3) → narrative HELD; ledger advance
        # in the same tick still lands (per-part control paths).
        deltas = [_narr("note-shift", f"shift {i}", "2026-07-08-standup") for i in range(4)]
        deltas.append({"op": "advance", "part": "workstreams", "key": "lk-0001",
                       "to_status": "active", "evidence": ["[[2026-07-08-standup]]"]})
        self._run(_payload(*deltas))
        # Ledger progressed.
        self.assertEqual(self._part("workstreams")["items"][0]["status"], "active")
        # Narrative unchanged (still just the adopted purpose entry) + held clarification.
        self.assertEqual(len(self._part("purpose")["entries"]), 1)
        clar = (self.base / "_system" / "state" / "CLARIFICATIONS.md").read_text(encoding="utf-8")
        self.assertIn("role-churn-guard", clar)


class OrphanedPartTest(CompositeBase):
    """A part dropped from config while its state sits on disk is surfaced, not
    silently skipped (role-orphaned-part; surface, don't decide)."""

    def _clar(self) -> str:
        return (self.base / "_system" / "state" / "CLARIFICATIONS.md").read_text(encoding="utf-8")

    def test_orphaned_part_state_surfaces_clarification(self) -> None:
        self._cold_start_and_adopt()  # workstreams + purpose live
        # Simulate a part dropped from config: a state file with no matching config part.
        (self.rdir / "parts" / "ghost.json").write_text("{}", encoding="utf-8")
        self._run(_payload())  # empty tick
        clar = self._clar()
        self.assertIn("role-orphaned-part", clar)
        self.assertIn("`ghost`", clar)
        # Surface, don't decide: the orphan file is NEVER deleted.
        self.assertTrue((self.rdir / "parts" / "ghost.json").exists())

    def test_all_parts_declared_no_orphan_clarification(self) -> None:
        self._cold_start_and_adopt()
        self._run(_payload())  # empty tick, every on-disk part is declared
        self.assertNotIn("role-orphaned-part", self._clar())


class EmissionTest(CompositeBase):
    """The proactive voice — bounded, grounded, always-HITL role-nudges."""

    def _clar(self) -> str:
        p = self.base / "_system" / "state" / "CLARIFICATIONS.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _nudge(self, text: str, rec: str = "2026-07-08-standup") -> dict:
        return {"text": text, "evidence": [f"[[{rec}]]"]}

    def test_grounded_nudge_surfaces_as_role_nudge_clarification(self) -> None:
        self._cold_start_and_adopt()
        summary = self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                             "nudges": [self._nudge("Auth is blocking three workstreams — decide this week")]})
        self.assertIn("role-nudge", summary["clarifications"])
        clar = self._clar()
        self.assertIn("role-nudge: minder-pm ·", clar)
        self.assertIn("Auth is blocking three workstreams", clar)
        self.assertIn(f"origin role:{ROLE_ID}", clar)

    def test_ungrounded_nudge_dropped(self) -> None:
        self._cold_start_and_adopt()
        summary = self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                             "nudges": [
                                 {"text": "no evidence here", "evidence": []},
                                 {"text": "cites a phantom", "evidence": ["[[nope-not-in-remit]]"]},
                             ]})
        self.assertNotIn("role-nudge", summary["clarifications"])
        self.assertNotIn("no evidence here", self._clar())
        self.assertNotIn("cites a phantom", self._clar())

    def test_cumulative_anti_salami_budget_defers(self) -> None:
        self._cold_start_and_adopt()
        # Emit more than the open-budget of DISTINCT nudges in one tick.
        from roles_common import ROLE_NUDGE_OPEN_BUDGET
        nudges = [self._nudge(f"distinct nudge number {i}") for i in range(ROLE_NUDGE_OPEN_BUDGET + 2)]
        self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [], "nudges": nudges})
        clar = self._clar()
        surfaced = clar.count("<!-- role-clarif: role-nudge/minder-pm ·")
        self.assertEqual(surfaced, ROLE_NUDGE_OPEN_BUDGET)  # capped at the budget
        # A further tick's new nudge still defers while the budget is full.
        s2 = self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                        "nudges": [self._nudge("one more while full")]})
        self.assertNotIn("one more while full", self._clar())

    def test_free_form_text_sanitized_no_block_corruption(self) -> None:
        self._cold_start_and_adopt()
        # A newline + a `-->` in the text must NOT split the header / marker or
        # close the hidden HTML comment early.
        self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                   "nudges": [self._nudge("first line\nsecond --> line urgent")]})
        clar = self._clar()
        # Exactly one conformant open marker; no stray `-->` leaking into the header.
        self.assertEqual(clar.count("<!-- role-clarif: role-nudge/minder-pm ·"), 1)
        header = [ln for ln in clar.splitlines() if ln.startswith("### ") and "role-nudge" in ln]
        self.assertEqual(len(header), 1)
        self.assertNotIn("\n\n-->", clar)

    def test_distinct_nudges_sharing_60char_prefix_both_surface(self) -> None:
        self._cold_start_and_adopt()
        prefix = "The auth workstream is the single most important thing to decide"
        self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [], "nudges": [
            self._nudge(prefix + " — before the SPRINT ends"),
            self._nudge(prefix + " — before the QUARTER ends"),
        ]})
        # Full-text hash keys the subject → two distinct open items, not one.
        self.assertEqual(self._clar().count("<!-- role-clarif: role-nudge/minder-pm ·"), 2)

    def _open_nudge_markers(self) -> int:
        clar = self._clar()
        cut = clar.find("## Resolved Items")
        open_region = clar[:cut] if cut >= 0 else clar
        return open_region.count("<!-- role-clarif: role-nudge/minder-pm ·")

    def test_dismissed_nudge_does_not_renag(self) -> None:
        self._cold_start_and_adopt()
        from roles_common import resolve_clarification
        n = {"role_id": ROLE_ID, "hook": "tick", "deltas": [],
             "nudges": [self._nudge("close the vendor contract this week")]}
        self._run(n)
        self.assertEqual(self._open_nudge_markers(), 1)
        # Owner sees + dismisses it (moves to Resolved Items). The subject carries a
        # hash suffix — resolve by the marker the tick wrote.
        subj = self._clar().split("role-nudge/minder-pm · ", 1)[1].split(" -->", 1)[0]
        resolve_clarification("role-nudge", f"minder-pm · {subj}", "dismissed", base=self.base)
        # Next tick re-proposes the identical nudge → suppressed (anti-flip-flop):
        # no NEW open nudge (the only marker left is the resolved one).
        self._run(n)
        self.assertEqual(self._open_nudge_markers(), 0)

    def test_identity_suggestion_surfaces_routed_to_edit(self) -> None:
        self._cold_start_and_adopt()
        summary = self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                             "identity_suggestion": {
                                 "text": "widen my remit to the minder calls — relevant work keeps landing there",
                                 "evidence": ["[[2026-07-08-standup]]"]}})
        self.assertIn("role-identity-suggest", summary["clarifications"])
        clar = self._clar()
        self.assertIn("role-identity-suggest: minder-pm ·", clar)
        self.assertIn("widen my remit", clar)
        self.assertIn("/ztn:role:edit minder-pm", clar)  # routed to edit, not action

    def test_ungrounded_identity_suggestion_dropped(self) -> None:
        self._cold_start_and_adopt()
        summary = self._run({"role_id": ROLE_ID, "hook": "tick", "deltas": [],
                             "identity_suggestion": {"text": "change me", "evidence": []}})
        self.assertNotIn("role-identity-suggest", summary["clarifications"])

    def test_no_nudge_during_cold_start(self) -> None:
        # A role that is still cold-starting must NOT emit a proactive nudge (it is
        # not yet adopted). First-ever tick stages the draft AND carries a nudge.
        self._run(_payload(
            _add("w1", "Ship auth", "2026-07-01-standup"),
            _narr("set-purpose", "Coherent vision", "2026-07-01-standup"),
        ) | {"nudges": [self._nudge("premature nudge before adoption", "2026-07-01-standup")]})
        self.assertNotIn("premature nudge", self._clar())

    def test_same_nudge_dedups_across_ticks(self) -> None:
        self._cold_start_and_adopt()
        n = {"role_id": ROLE_ID, "hook": "tick", "deltas": [],
             "nudges": [self._nudge("the exact same concern")]}
        self._run(n)
        self._run(n)  # same nudge again next tick
        # One open item, not two — dedup by (ctype, subject) across ticks.
        self.assertEqual(
            self._clar().count("<!-- role-clarif: role-nudge/minder-pm · the exact same concern"), 1)


if __name__ == "__main__":
    unittest.main()
