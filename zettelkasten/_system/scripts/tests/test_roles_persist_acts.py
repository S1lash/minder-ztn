"""Writer-level act integration (CONTRACT §6.2/§6.5, INV-16/26/28): the two-phase
HITL flow in `roles_persist` — stage in the tick (`_stage_acts`), execute on approval
(`_execute_pending_acts` / `_approve_acts`), watermark coupled to the confirmed act,
atomicity + TOCTOU drift. An in-memory `FakeBoard` (a GitHub-issues REST shape) is
injected as the transport so the whole flow is offline + deterministic.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_budget  # noqa: E402
import roles_inbox  # noqa: E402
import roles_persist  # noqa: E402
import roles_triggers  # noqa: E402
from roles_common import load_role_config  # noqa: E402
from roles_tools import ToolResult  # noqa: E402

_REGISTRY = """# Tools

## Active Tools

| Tool ID | Direction | Adapter | Cadence Slot | Grounding Landing | Budget | Credential | MCP Binding | Act Config | Plain Purpose | Usage Note | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| board-write | act | http | on-demand | round-trip | unlimited | — | — | base_host=https://api.example.com;collection=issues;version_field=updated_at;match_field=title;id_field=number;state_field=state;open_value=open;closed_value=closed;create_fields=title,body;update_fields=title,body,state | Writes a board. | Reconcile under mandate. | active |
"""

_CONFIG = """id: r
name: R
parts:
  - {id: w, kind: ledger, tools: [board-write]}
remit: {all: true}
cadence: daily
status: active
emit_inbox: true
mandate:
  autonomy: advisory
  scope:
    - {target: board-write, surface: repos/acme/board, mode: read-modify-write, blast: bounded}
"""


class FakeBoard:
    def __init__(self):
        self.issues = {}
        self.clock = 0
        self._next = 1

    def _stamp(self):
        self.clock += 1
        return f"v{self.clock}"

    def add(self, title, state="open", body=""):
        n = self._next
        self._next += 1
        self.issues[n] = {"number": n, "title": title, "state": state,
                          "body": body, "updated_at": self._stamp()}
        return self.issues[n]

    def _res(self, code, payload):
        return ToolResult(tool_id="board-write", status="ok",
                          data={"status_code": code, "body": json.dumps(payload),
                                "truncated": False}, summary=f"http {code}")

    def exec_http(self, spec, request, secret):
        method, url = request["method"].upper(), request["url"]
        base = "https://api.example.com/repos/acme/board/issues"
        if method == "GET" and url.startswith(base + "?"):
            return self._res(200, list(self.issues.values()))
        if method == "GET" and url.startswith(base + "/"):
            ref = int(url.rsplit("/", 1)[-1])
            return self._res(200, self.issues[ref]) if ref in self.issues \
                else ToolResult.unknown("board-write", "http 404")
        if method == "POST" and url == base:
            i = self.add(request["json"].get("title", ""), body=request["json"].get("body", ""))
            return self._res(201, i)
        if method == "PATCH" and url.startswith(base + "/"):
            ref = int(url.rsplit("/", 1)[-1])
            self.issues[ref].update(request["json"])
            self.issues[ref]["updated_at"] = self._stamp()
            return self._res(200, self.issues[ref])
        return ToolResult.unknown("board-write", "404")


def _setup(tmp: Path):
    (tmp / "_system" / "registries").mkdir(parents=True, exist_ok=True)
    (tmp / "_system" / "registries" / "TOOLS.md").write_text(_REGISTRY, encoding="utf-8")
    d = tmp / "_system" / "roles" / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(_CONFIG, encoding="utf-8")
    return load_role_config("r", tmp)


def _clar(tmp: Path) -> str:
    p = tmp / "_system" / "state" / "CLARIFICATIONS.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _pending(tmp: Path) -> dict:
    p = tmp / "_system" / "roles" / "r" / "pending_acts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class ActStageTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        self.cfg = _setup(self.tmp)
        self.board = FakeBoard()
        self.board.add("Alpha: wire onboarding email")  # #1
        self.board.add("Beta: draft billing schema")    # #2

    def _payload(self, acts, emissions=None):
        return {"role_id": "r", "hook": "tick", "run_at": "2026-07-19T10:00:00Z",
                "acts": acts, "inbox_emissions": emissions or []}

    def test_stage_does_not_execute_or_advance(self):
        payload = self._payload(
            [{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
              "reason": "shipped", "evidence": ["[[rec-a]]"]}])
        stats = roles_persist._stage_acts(
            "r", self.cfg, payload, ["rec-a"], self.tmp, None,
            {"probe@dev": "v9"}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 1)
        self.assertTrue(stats["hitl"])                      # harness always HITL
        self.assertEqual(self.board.issues[1]["state"], "open")  # NOT executed
        self.assertIn("role-act-confirm", _clar(self.tmp))
        self.assertEqual(_pending(self.tmp)["acts"][0]["baseline"], self.board.issues[1]["updated_at"])
        # Watermark NOT advanced (still in pending, not committed).
        self.assertEqual(roles_triggers.load_trigger_state("r", self.tmp)["watermarks"], {})

    def test_act_evidence_is_informational_not_a_grounding_gate(self):
        # An act is EXTERNAL-driven (INV-10): its evidence documents WHY (from the tool
        # read) but is NOT checked against the in-remit corpus — the mandate + TOCTOU +
        # HITL are the gate. An act whose evidence is not an in-remit record still stages.
        payload = self._payload(
            [{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
              "reason": "the repo doc says shipped", "evidence": ["docs/project-alpha.md"]}])
        stats = roles_persist._stage_acts(
            "r", self.cfg, payload, ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 1)

    def test_act_on_unknown_part_refused(self):
        # CONTRACT §1.1 per-part grant: an act naming a part the role does not have is
        # refused before any mandate/network work (the body can't attribute an act to a
        # phantom part).
        stats = roles_persist._stage_acts(
            "r", self.cfg,
            self._payload([{"part": "ghost", "tool": "board-write", "op": "close",
                            "target_ref": "1", "evidence": ["x"]}]),
            ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 0)
        self.assertEqual(stats["refused"], 1)
        self.assertRegex("".join(stats["refusals"]), r"unknown part")

    def test_act_tool_not_granted_to_named_part_refused(self):
        # CONTRACT §1.1: with a real second part 'v' that has NO tools, acting as 'v' with
        # a tool granted only to 'w' is refused — a part cannot borrow another part's hand.
        two_part_cfg = _CONFIG.replace(
            "  - {id: w, kind: ledger, tools: [board-write]}\n",
            "  - {id: w, kind: ledger, tools: [board-write]}\n  - {id: v, kind: narrative}\n")
        (self.tmp / "_system" / "roles" / "r" / "config.yml").write_text(
            two_part_cfg, encoding="utf-8")
        cfg = load_role_config("r", self.tmp)
        stats = roles_persist._stage_acts(
            "r", cfg,
            self._payload([{"part": "v", "tool": "board-write", "op": "close",
                            "target_ref": "1", "evidence": ["x"]}]),
            ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 0)
        self.assertEqual(stats["refused"], 1)
        self.assertRegex("".join(stats["refusals"]), r"not granted to part")

    def test_all_refused_stage_surfaces_clarification(self):
        # FIX-SHIP-2 §7: when EVERY proposed act is refused at stage, the role would
        # silently not act — surface a CLARIFICATION, not just a log line.
        stats = roles_persist._stage_acts(
            "r", self.cfg,
            self._payload([{"part": "w", "tool": "nonexistent-tool", "op": "close",
                            "target_ref": "1", "evidence": ["x"]}]),
            ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 0)
        self.assertEqual(stats["refused"], 1)
        self.assertTrue(stats.get("refused_clar"))
        self.assertRegex(_clar(self.tmp), r"role-act-failed|role-tool-reauth")

    def test_out_of_scope_tool_refused(self):
        payload = self._payload(
            [{"part": "w", "tool": "some-other-tool", "op": "close", "target_ref": "1",
              "evidence": ["x"]}])
        stats = roles_persist._stage_acts(
            "r", self.cfg, payload, ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 0)
        self.assertEqual(stats["refused"], 1)

    def test_autonomous_tick_stages_only_defers_execute(self):
        # With a verified cage + autonomous mandate + no firewall, the act is NON-HITL —
        # but _stage_acts still only STAGES (does not execute inline): execution is
        # deferred to run() AFTER parts persist (§6.5 ordering). Board stays unchanged.
        d = self.tmp / "_system" / "roles" / "r"
        (d / "config.yml").write_text(
            _CONFIG.replace("autonomy: advisory", "autonomy: autonomous"), encoding="utf-8")
        cfg = load_role_config("r", self.tmp)
        with unittest.mock.patch.dict(os.environ, {"ZTN_ROLES_CAGE_VERIFIED": "1"}):
            stats = roles_persist._stage_acts(
                "r", cfg,
                self._payload([{"part": "w", "tool": "board-write", "op": "close",
                                "target_ref": "1", "reason": "done", "evidence": ["x"]}]),
                ["rec-a"], self.tmp, None, {"probe@dev": "v9"}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 1)
        self.assertFalse(stats["hitl"])                     # autonomous
        self.assertEqual(stats["executed"], 0)              # NOT executed inline
        self.assertEqual(self.board.issues[1]["state"], "open")  # board untouched
        self.assertTrue(_pending(self.tmp).get("acts"))     # staged, awaiting post-finalize execute

    def test_no_mandate_ignores_acts(self):
        # A config without a mandate → acts never staged (read-only role).
        d = self.tmp / "_system" / "roles" / "r"
        (d / "config.yml").write_text(_CONFIG.split("mandate:")[0], encoding="utf-8")
        cfg = load_role_config("r", self.tmp)
        stats = roles_persist._stage_acts(
            "r", cfg, self._payload([{"part": "w", "tool": "board-write", "op": "close",
                                      "target_ref": "1", "evidence": ["[[rec-a]]"]}]),
            ["rec-a"], self.tmp, None, {}, exec_http=self.board.exec_http)
        self.assertEqual(stats["staged"], 0)

    def _stage_autonomous(self, blast="bounded", env=None):
        d = self.tmp / "_system" / "roles" / "r"
        cfg_txt = _CONFIG.replace("autonomy: advisory", "autonomy: autonomous")
        if blast != "bounded":
            cfg_txt = cfg_txt.replace("blast: bounded", f"blast: {blast}")
        (d / "config.yml").write_text(cfg_txt, encoding="utf-8")
        cfg = load_role_config("r", self.tmp)
        with unittest.mock.patch.dict(os.environ, env or {}, clear=False):
            return roles_persist._stage_acts(
                "r", cfg,
                self._payload([{"part": "w", "tool": "board-write", "op": "close",
                                "target_ref": "1", "reason": "done", "evidence": ["x"]}]),
                ["rec-a"], self.tmp, None, {"probe@dev": "v9"}, exec_http=self.board.exec_http)

    def test_autonomous_ack_collapses_hitl_without_a_cage_claim(self):
        # The HONEST launch marker: autonomy=autonomous + ZTN_ROLES_AUTONOMOUS_ACK=1
        # makes the act NON-HITL WITHOUT asserting a verified no-FS cage (the harness has
        # none). The owner consented; the engine does not re-ask per act.
        stats = self._stage_autonomous(
            env={"ZTN_ROLES_AUTONOMOUS_ACK": "1", "ZTN_ROLES_CAGE_VERIFIED": ""})
        self.assertEqual(stats["staged"], 1)
        self.assertFalse(stats["hitl"])

    def test_autonomous_ack_irreversible_stages_when_ingestion_failclosed(self):
        # An irreversible (`blast: open`) autonomous act on a TOOL-BEARING role with no
        # clean tool-ctx: `_resolve_firewall_flag` FAIL-CLOSES the injection flag to True
        # (can't prove no external ingestion), so the reserved firewall exception fires and
        # the act STAGES for confirm even under the ack marker — the safe default. (A
        # bounded act stays hands-free — test_autonomous_ack_collapses_hitl_without_a_cage_claim;
        # the ingestion-controlled logic is pinned at the mandate level in test_roles_act.)
        stats = self._stage_autonomous(
            blast="open",
            env={"ZTN_ROLES_AUTONOMOUS_ACK": "1", "ZTN_ROLES_CAGE_VERIFIED": ""})
        self.assertEqual(stats["staged"], 1)
        self.assertTrue(stats["hitl"])

    def test_autonomous_ack_does_not_unlock_an_advisory_role(self):
        # Safety: the global ack marker only unlocks a role the owner DIALED autonomous.
        # An advisory role (the default _CONFIG) stays HITL even with the marker set.
        with unittest.mock.patch.dict(
                os.environ, {"ZTN_ROLES_AUTONOMOUS_ACK": "1", "ZTN_ROLES_CAGE_VERIFIED": ""},
                clear=False):
            stats = roles_persist._stage_acts(
                "r", self.cfg,
                self._payload([{"part": "w", "tool": "board-write", "op": "close",
                                "target_ref": "1", "reason": "done", "evidence": ["x"]}]),
                ["rec-a"], self.tmp, None, {"probe@dev": "v9"}, exec_http=self.board.exec_http)
        self.assertTrue(stats["hitl"])


class ActExecuteTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        self.cfg = _setup(self.tmp)
        self.board = FakeBoard()
        self.board.add("Alpha: wire onboarding email")  # #1
        self.board.add("Beta: draft billing schema")    # #2

    def _stage(self, acts, emissions=None, wm=None):
        payload = {"role_id": "r", "hook": "tick", "run_at": "2026-07-19T10:00:00Z",
                   "acts": acts, "inbox_emissions": emissions or []}
        return roles_persist._stage_acts(
            "r", self.cfg, payload, ["rec-a"], self.tmp, None, wm or {},
            exec_http=self.board.exec_http)

    def test_full_success_advances_wm_and_feeds_base(self):
        self._stage(
            [{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
              "reason": "shipped", "evidence": ["[[rec-a]]"]}],
            emissions=[{"text": "#1 onboarding shipped — closed on the board",
                        "evidence": ["[[rec-a]]"]}],
            wm={"probe@dev": "v9"})
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 1)
        self.assertTrue(stats["watermark_advanced"])
        self.assertEqual(self.board.issues[1]["state"], "closed")  # real write
        # inbox close-event fed to base
        self.assertEqual(stats["inbox_emitted"], 1)
        inbox = list(roles_inbox.roles_inbox_root(self.tmp).glob("r--*.md"))
        self.assertEqual(len(inbox), 1)
        # watermark advanced only now
        self.assertEqual(roles_triggers.load_trigger_state("r", self.tmp)["watermarks"],
                         {"probe@dev": "v9"})
        # pending cleared; budget recorded (1 act + 1 emission = 2 writes)
        self.assertEqual(_pending(self.tmp), {})
        self.assertEqual(roles_budget.load_budget("r", self.tmp)["writes_this_period"], 2)

    def test_writer_update_idempotent_skip_advances_no_board_change(self):
        # FIX-SHIP-2 §7 (writer-level): a staged update whose target already matches →
        # skipped, no PATCH; the reconcile is a full-success no-op (watermark advances).
        self.board.issues[2]["body"] = "already the target"
        self._stage([{"part": "w", "tool": "board-write", "op": "update", "target_ref": "2",
                      "fields": {"body": "already the target"}, "reason": "noop",
                      "evidence": ["x"]}], wm={"probe@dev": "v9"})
        before = self.board.issues[2]["updated_at"]
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["executed"], 0)
        self.assertEqual(self.board.issues[2]["updated_at"], before)  # no PATCH
        self.assertTrue(stats["watermark_advanced"])  # idempotent no-op is a full success

    def test_drift_aborts_no_write_no_wm(self):
        self._stage(
            [{"part": "w", "tool": "board-write", "op": "update", "target_ref": "2",
              "fields": {"body": "in review; Stripe blocker"}, "reason": "status",
              "evidence": ["[[rec-a]]"]}],
            wm={"probe@dev": "v9"})
        # concurrent change between stage and execute → version drifts
        self.board.issues[2]["body"] = "someone else"
        self.board.issues[2]["updated_at"] = self.board._stamp()
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["drift"], 1)
        self.assertFalse(stats["watermark_advanced"])
        self.assertEqual(self.board.issues[2]["body"], "someone else")  # not overwritten
        self.assertEqual(roles_triggers.load_trigger_state("r", self.tmp)["watermarks"], {})
        self.assertIn("role-act-drift", _clar(self.tmp))
        self.assertEqual(_pending(self.tmp), {})  # cleared to re-derive next tick

    def test_mixed_success_and_drift_discloses_dropped_close_events(self):
        # A mixed tick: act #1 (close) EXECUTES on the board, act #2 (update) DRIFTS.
        # acts_clean is False → #1's coupled close-event is held (never written). The
        # honest disclosure (mirroring the budget branch) must surface that the executed
        # act's close-event is dropped and NOT auto-recovered — never a silent loss.
        self._stage(
            [{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
              "reason": "shipped", "evidence": ["[[rec-a]]"]},
             {"part": "w", "tool": "board-write", "op": "update", "target_ref": "2",
              "fields": {"body": "in review"}, "reason": "status", "evidence": ["[[rec-a]]"]}],
            emissions=[{"text": "#1 shipped — closed on the board", "evidence": ["[[rec-a]]"]}],
            wm={"probe@dev": "v9"})
        # concurrent change to #2 between stage and execute → #2 drifts
        self.board.issues[2]["body"] = "someone else"
        self.board.issues[2]["updated_at"] = self.board._stamp()
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 1)          # #1 really closed
        self.assertEqual(stats["drift"], 1)             # #2 aborted
        self.assertEqual(self.board.issues[1]["state"], "closed")
        self.assertEqual(stats["inbox_emitted"], 0)     # close-event held (not full success)
        self.assertFalse(stats["watermark_advanced"])
        clar = _clar(self.tmp)
        self.assertIn("role-act-drift", clar)
        self.assertIn("NOT auto-recovered", clar)       # the honest disclosure fired

    def test_emission_already_on_disk_not_double_charged(self):
        # F4 crash-safety: if a prior --approve-acts run crashed after the close-event
        # landed but before pending cleared, the re-run re-uses the same run_at → same
        # content-hashed filename. The emission must NOT be re-charged to the budget.
        run_at = "2026-07-19T10:00:00Z"
        em_text = "#1 shipped — closed on the board"
        self._stage(
            [{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
              "reason": "shipped", "evidence": ["[[rec-a]]"]}],
            emissions=[{"text": em_text, "evidence": ["[[rec-a]]"]}],
            wm={"probe@dev": "v9"})
        # simulate the emission already landed on the crashed prior run
        roles_inbox.write_emission("r", em_text, ["[[rec-a]]"], False, run_at, self.tmp)
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 1)          # the act charged once
        self.assertEqual(stats["inbox_emitted"], 1)     # counted as emitted (full success)
        self.assertTrue(stats["watermark_advanced"])
        # budget = 1 (the act) NOT 2 — the pre-existing emission was not re-charged
        self.assertEqual(roles_budget.load_budget("r", self.tmp)["writes_this_period"], 1)

    def test_create_idempotent_skip_no_budget(self):
        self._stage([{"part": "w", "tool": "board-write", "op": "create",
                      "fields": {"title": "Alpha: wire onboarding email"},
                      "dedup_match": "Alpha: wire onboarding email",
                      "evidence": ["[[rec-a]]"]}])
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["executed"], 0)
        self.assertEqual(len(self.board.issues), 2)  # no double-create
        # a skip is a no-op → no budget consumed
        self.assertEqual(roles_budget.load_budget("r", self.tmp)["writes_this_period"], 0)

    def test_cumulative_budget_bounds_acts(self):
        # INV-20/28: the cumulative ceiling bounds ACTS (not just emissions). With a
        # ceiling of 2, staging 4 fresh creates executes only 2, holds the watermark,
        # surfaces role-budget-exhausted, and does NOT over-write past the ceiling.
        (self.tmp / "_system" / "roles" / "r" / "budget.json").write_text(json.dumps({
            "period_start": "2026-07-01", "period_days": 7,
            "max_writes_per_period": 2, "writes_this_period": 0, "max_tick_seconds": 120,
        }), encoding="utf-8")
        self._stage([{"part": "w", "tool": "board-write", "op": "create",
                      "fields": {"title": f"New task {i}"}, "dedup_match": f"New task {i}",
                      "evidence": ["x"]} for i in range(4)], wm={"probe@dev": "v9"})
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 2)          # only 2 writes, not 4
        self.assertTrue(stats["budget_hit"])
        self.assertFalse(stats["watermark_advanced"])   # not a full success
        self.assertEqual(len(self.board.issues), 4)     # 2 original + 2 created (NOT 6)
        self.assertEqual(roles_triggers.load_trigger_state("r", self.tmp)["watermarks"], {})
        self.assertIn("role-budget-exhausted", _clar(self.tmp))
        self.assertEqual(roles_budget.load_budget("r", self.tmp)["writes_this_period"], 2)

    def test_budget_truncated_emissions_hold_watermark(self):
        # Acts fit but the close-event would exceed the ceiling → NOT a full success:
        # the watermark must NOT advance and the base must not get a partial picture.
        (self.tmp / "_system" / "roles" / "r" / "budget.json").write_text(json.dumps({
            "period_start": "2026-07-01", "period_days": 7,
            "max_writes_per_period": 1, "writes_this_period": 0, "max_tick_seconds": 120,
        }), encoding="utf-8")
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "done", "evidence": ["x"]}],
                    emissions=[{"text": "closed #1", "evidence": ["x"]}],
                    wm={"probe@dev": "v9"})
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 1)          # the act fit (1 write)
        self.assertEqual(stats["inbox_emitted"], 0)     # the emission did NOT (budget)
        self.assertTrue(stats["budget_hit"])
        self.assertFalse(stats["watermark_advanced"])   # partial → watermark held
        self.assertEqual(roles_triggers.load_trigger_state("r", self.tmp)["watermarks"], {})

    def test_pending_not_overwritten_while_awaiting_approval(self):
        # A re-tick must NOT swap an un-approved pending (the owner approves what they saw).
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "first", "evidence": ["x"]}])
        first = _pending(self.tmp)["acts"][0]["target_ref"]
        stats2 = self._stage([{"part": "w", "tool": "board-write", "op": "close",
                               "target_ref": "2", "reason": "second", "evidence": ["x"]}])
        self.assertTrue(stats2["pending_exists"])
        self.assertEqual(stats2["staged"], 0)
        self.assertEqual(_pending(self.tmp)["acts"][0]["target_ref"], first)  # unchanged

    def test_phase2_refused_surfaces_role_act_failed(self):
        # A staged update whose fields filter to empty is refused at execute → surfaced,
        # not silently dropped.
        self._stage([{"part": "w", "tool": "board-write", "op": "update", "target_ref": "2",
                      "fields": {"not_a_field": "x"}, "reason": "r", "evidence": ["x"]}])
        stats = roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["failed"], 1)          # refused bucketed
        self.assertFalse(stats["watermark_advanced"])
        self.assertIn("role-act-failed", _clar(self.tmp))

    def test_act_outcomes_audited(self):
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "done", "evidence": ["x"]}])
        roles_persist._execute_pending_acts("r", self.cfg, self.tmp,
                                            exec_http=self.board.exec_http)
        audit = self.tmp / "_system" / "state" / "roles-tool-audit.jsonl"
        self.assertTrue(audit.exists())
        rows = [json.loads(l) for l in audit.read_text().splitlines() if l.strip()]
        act_rows = [r for r in rows if r.get("kind") == "act"]
        self.assertTrue(any(r["op"] == "close" and r["status"] == "executed" for r in act_rows))

    def test_mandate_expired_between_stage_and_execute_refuses(self):
        # Stage under a live mandate, then the mandate expires before approval → the
        # execute-time re-check refuses (INV-16 re-consent), holds the watermark, and
        # writes NOTHING to the board.
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "done", "evidence": ["x"]}], wm={"probe@dev": "v9"})
        # rewrite the config with an already-expired `until` and reload
        d = self.tmp / "_system" / "roles" / "r"
        (d / "config.yml").write_text(
            _CONFIG.replace("autonomy: advisory",
                            "autonomy: advisory\n  until: 2020-01-01"), encoding="utf-8")
        expired_cfg = load_role_config("r", self.tmp)
        stats = roles_persist._execute_pending_acts("r", expired_cfg, self.tmp,
                                                    exec_http=self.board.exec_http)
        self.assertEqual(stats["executed"], 0)
        self.assertEqual(self.board.issues[1]["state"], "open")  # NOT closed
        self.assertFalse(stats["watermark_advanced"])
        self.assertIn("mandate expired", _clar(self.tmp))
        self.assertEqual(_pending(self.tmp), {})  # cleared

    def test_empty_resolved_secret_refuses(self):
        import unittest.mock
        with unittest.mock.patch("roles_secrets.resolve_secret", return_value=""):
            secret, err = roles_persist._resolve_act_secret("secret://x", self.tmp)
        self.assertIsNone(secret)
        self.assertIn("empty", err)

    def test_approve_acts_mode_summary(self):
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "done", "evidence": ["[[rec-a]]"]}], wm={"probe@dev": "v9"})
        summary = roles_persist._approve_acts("r", self.cfg, "2026-07-19T11:00:00Z",
                                              self.tmp, exec_http=self.board.exec_http)
        self.assertEqual(summary["outcome"], "acts-executed")
        self.assertEqual(summary["run_status"], "ok")

    def test_approve_acts_resolves_the_role_act_confirm(self):
        # Regression: the emit subject and the three approve-acts resolve() calls MUST use
        # the same subject (bare role_id) — else the role-act-confirm block lingers under
        # ## Open Items after its acts already executed (the "Needs you: N acts waiting"
        # ghost). Stage → clarification is open → approve → it moves out of Open Items.
        self._stage([{"part": "w", "tool": "board-write", "op": "close", "target_ref": "1",
                      "reason": "done", "evidence": ["[[rec-a]]"]}], wm={"probe@dev": "v9"})
        clar_path = self.tmp / "_system" / "state" / "CLARIFICATIONS.md"
        open_start = _clar(self.tmp).index("## Open Items")
        open_end = _clar(self.tmp).index("## Resolved Items")
        self.assertIn("role-act-confirm", _clar(self.tmp)[open_start:open_end])  # open now
        roles_persist._approve_acts("r", self.cfg, "2026-07-19T11:00:00Z",
                                    self.tmp, exec_http=self.board.exec_http)
        after = _clar(self.tmp)
        o_start = after.index("## Open Items")
        o_end = after.index("## Resolved Items")
        self.assertNotIn("role-act-confirm", after[o_start:o_end])  # resolved out of Open


if __name__ == "__main__":
    unittest.main()
