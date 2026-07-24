"""Tests for the inbox door + no-self-feed (CONTRACT §4.2, INV-4/11/17/20/27)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path


def _cage_verified_env():
    """Context manager: the out-of-band cage-verified marker (so a `body_caged: true`
    payload actually relaxes the emission gate). PLAN 1 real runs never set it."""
    return unittest.mock.patch.dict(os.environ, {"ZTN_ROLES_CAGE_VERIFIED": "1"})

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_budget  # noqa: E402
import roles_inbox  # noqa: E402
import roles_persist  # noqa: E402
from roles_common import load_role_config  # noqa: E402


def _cfg(tmp: Path, extra: str = "emit_inbox: true\n"):
    d = tmp / "_system" / "roles" / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(
        "id: r\nparts: [{id: p1, kind: ledger}]\n"
        "remit: {all: true}\ncadence: daily\nstatus: active\n" + extra,
        encoding="utf-8")
    return load_role_config("r", tmp)


def _clar_text(tmp: Path) -> str:
    p = tmp / "_system" / "state" / "CLARIFICATIONS.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


class RenderTest(unittest.TestCase):
    def test_render_has_source_and_grounding(self):
        md = roles_inbox.render_emission(
            "r", "Task X is done per the call.", ["rec-a"], False, "2026-07-19T10:00:00Z")
        self.assertIn("source: role:r", md)
        self.assertIn("is_sensitive: false", md)
        self.assertIn("Task X is done", md)
        self.assertIn("Grounded in: rec-a", md)

    def test_filename_flat_with_role_prefix_and_portable(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            p = roles_inbox.write_emission("r", "hello", ["rec-a"], False,
                                           "2026-07-19T10:00:00Z", tmp)
            self.assertEqual(p.parent, roles_inbox.roles_inbox_root(tmp))
            self.assertTrue(p.name.startswith("r--2026-07-19-"))
            self.assertNotIn(":", p.name)  # Windows-portable
            # Idempotent: same text → same filename.
            p2 = roles_inbox.write_emission("r", "hello", ["rec-a"], False,
                                            "2026-07-19T10:00:00Z", tmp)
            self.assertEqual(p, p2)


class ProcessEmissionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _emit(self, payload, cfg=None):
        cfg = cfg or _cfg(self.tmp)
        return roles_persist._process_inbox_emissions(
            "r", cfg, payload, ["rec-a", "rec-b"], self.tmp)

    def test_opt_in_required(self):
        cfg = _cfg(self.tmp, "")  # no emit_inbox
        n = self._emit({"inbox_emissions": [{"text": "x", "evidence": ["rec-a"]}]}, cfg)
        self.assertEqual(n, (0, 0, 0))

    # A CAGED body (body_caged: True) with no external ingestion writes autonomously;
    # everything else is HITL-gated. PLAN 1 ships no verified cage, so real ticks are
    # always un-caged → owner-confirmed; these `caged` payloads simulate the future
    # verified-cage runtime to exercise the write path.
    _CAGED = {"body_caged": True, "ingested_external_tool": False}

    def test_caged_grounded_emission_written_and_budgeted(self):
        with _cage_verified_env():
            n = self._emit({**self._CAGED, "run_at": "2026-07-19T10:00:00Z",
                            "inbox_emissions": [{"text": "Task closed per Notion.",
                                                 "evidence": ["rec-a"]}]})
        self.assertEqual(n, (1, 0, 0))
        files = list(roles_inbox.roles_inbox_root(self.tmp).glob("r--*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(roles_budget.load_budget("r", self.tmp)["writes_this_period"], 1)

    def test_uncaged_emission_hitl_gated(self):
        # FIX-1 leak close: an UN-CAGED body could have raw-read out-of-remit and
        # paraphrased it into `text` (not corpus-checkable) — so even a no-external,
        # in-budget, grounded emission is owner-confirmed, never silently written.
        n = self._emit({"body_caged": False, "ingested_external_tool": False,
                        "inbox_emissions": [{"text": "from my zone", "evidence": ["rec-a"]}]})
        self.assertEqual(n, (0, 0, 1))  # gated, not written
        self.assertEqual(len(list(roles_inbox.roles_inbox_root(self.tmp).glob("*.md"))), 0)
        self.assertIn("role-emission-confirm", _clar_text(self.tmp))

    def test_body_caged_true_unforgeable_without_env(self):
        # UNFORGEABLE: a payload `body_caged: true` does NOT relax the gate unless the
        # out-of-band env marker is set (the body / a regressed heredoc can't forge it).
        n = self._emit({"body_caged": True, "ingested_external_tool": False,
                        "inbox_emissions": [{"text": "forged", "evidence": ["rec-a"]}]})
        self.assertEqual(n, (0, 0, 1))  # STILL gated — env not set
        self.assertEqual(len(list(roles_inbox.roles_inbox_root(self.tmp).glob("*.md"))), 0)

    def test_ungrounded_dropped(self):
        with _cage_verified_env():
            n = self._emit({**self._CAGED, "inbox_emissions": [{"text": "x", "evidence": []}]})
            self.assertEqual(n, (0, 0, 0))
            n2 = self._emit({**self._CAGED,
                             "inbox_emissions": [{"text": "x", "evidence": ["not-in-corpus"]}]})
        self.assertEqual(n2, (0, 0, 0))

    def test_firewall_gates_external_derived_emission_even_when_caged(self):
        # External ingestion → HITL regardless of the cage (INV-17 firewall). The flag
        # comes ONLY from the engine-owned tool ctx (a payload flag is ignored).
        import json
        ctx = self.tmp / "ctx.json"
        ctx.write_text(json.dumps({"ingested_external": True}), encoding="utf-8")
        with _cage_verified_env():
            n = roles_persist._process_inbox_emissions(
                "r", _cfg(self.tmp),
                {**self._CAGED,
                 "inbox_emissions": [{"text": "From Notion.", "evidence": ["rec-a"]}]},
                ["rec-a"], self.tmp, tool_ctx=ctx)
        self.assertEqual(n, (0, 0, 1))  # gated
        self.assertEqual(len(list(roles_inbox.roles_inbox_root(self.tmp).glob("*.md"))), 0)
        self.assertIn("role-emission-confirm", _clar_text(self.tmp))

    def test_tool_ctx_external_overrides_body_supplied_false(self):
        # The belt: a body-supplied `ingested_external_tool: false` is IGNORED when the
        # runner passes the tool ctx — the engine-authored ctx flag wins (INV-17).
        import json
        ctx = self.tmp / "ctx.json"
        ctx.write_text(json.dumps({"ingested_external": True}), encoding="utf-8")
        with _cage_verified_env():
            n = roles_persist._process_inbox_emissions(
                "r", _cfg(self.tmp),
                {**self._CAGED, "ingested_external_tool": False,  # body lies
                 "inbox_emissions": [{"text": "from notion", "evidence": ["rec-a"]}]},
                ["rec-a"], self.tmp, tool_ctx=ctx)
        self.assertEqual(n, (0, 0, 1))  # gated despite the body's false + the cage
        self.assertIn("role-emission-confirm", _clar_text(self.tmp))

    def test_caged_tool_ctx_false_writes(self):
        import json
        ctx = self.tmp / "ctx.json"
        ctx.write_text(json.dumps({"ingested_external": False}), encoding="utf-8")
        with _cage_verified_env():
            n = roles_persist._process_inbox_emissions(
                "r", _cfg(self.tmp),
                {**self._CAGED, "inbox_emissions": [{"text": "own zone", "evidence": ["rec-a"]}]},
                ["rec-a"], self.tmp, tool_ctx=ctx)
        self.assertEqual(n, (1, 0, 0))

    def test_budget_exhaustion_defers_on_write_path(self):
        # Budget-defer only on the write path (caged + no external); the HITL gate is
        # checked BEFORE budget, so an un-caged emission gates rather than defers.
        state = roles_budget.load_budget("r", self.tmp)
        roles_budget.record_writes("r", state["max_writes_per_period"], self.tmp)
        with _cage_verified_env():
            n = self._emit({**self._CAGED,
                            "inbox_emissions": [{"text": "late", "evidence": ["rec-a"]}]})
        self.assertEqual(n, (0, 1, 0))
        self.assertIn("role-budget-exhausted", _clar_text(self.tmp))


class ToolRequestTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        _cfg(self.tmp)  # writes a role config for r

    def test_grounded_tool_request_surfaces_clarification(self):
        n = roles_persist._process_tool_request(
            "r", {"tool_request_proposal": {"text": "I'd reconcile the board directly with "
                  "write access to the project tracker.", "evidence": ["rec-a"]}},
            ["rec-a"], self.tmp)
        self.assertEqual(n, 1)
        self.assertIn("role-tool-request", _clar_text(self.tmp))
        self.assertIn("never granting itself", _clar_text(self.tmp))  # INV-3 wording

    def test_ungrounded_tool_request_dropped(self):
        n = roles_persist._process_tool_request(
            "r", {"tool_request_proposal": {"text": "give me a tool", "evidence": []}},
            ["rec-a"], self.tmp)
        self.assertEqual(n, 0)
        self.assertNotIn("role-tool-request", _clar_text(self.tmp))


class ToolObservabilityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_tool_activity_and_failures_logged(self):
        ctx_data = {
            "call_counts": {"notion-board": 2, "gdrive": 1},
            "ingested_external": True,
            "failures": [{"tool_id": "notion-board", "status": "unknown",
                          "reason": "creds", "reauth": True}],
        }
        lines = roles_persist._tool_activity_lines(ctx_data)
        joined = "\n".join(lines)
        self.assertIn("3 call(s)", joined)      # 2 + 1
        self.assertIn("1 degraded", joined)
        self.assertIn("notion-board", joined)
        self.assertIn("injection firewall active", joined)  # external ingestion trace

    def test_reauth_ids_and_signal(self):
        ctx_data = {"failures": [
            {"tool_id": "notion-board", "reauth": True, "reason": "creds"},
            {"tool_id": "notion-board", "reauth": True, "reason": "creds"},  # dup
            {"tool_id": "gdrive", "reauth": False, "reason": "timeout"},
        ]}
        self.assertEqual(roles_persist._reauth_tool_ids(ctx_data), ["notion-board"])
        sig = roles_persist._reauth_signal("r", "notion-board", ctx_data)
        self.assertEqual(sig.ctype, "role-tool-reauth")
        self.assertIn("notion-board", sig.subject)

    def test_run_emits_reauth_and_logs_tools(self):
        # End-to-end via run(): a ctx with a reauth failure → role-tool-reauth surfaced
        # + a tool line in log_roles.md (a silent honest-degrade would show clean).
        import json
        d = self.tmp / "_system" / "roles" / "r"
        d.mkdir(parents=True)
        (d / "config.yml").write_text(
            "id: r\nparts: [{id: p1, kind: ledger}]\nremit: {all: true}\n"
            "cadence: daily\nstatus: active\n", encoding="utf-8")
        ctx = self.tmp / "ctx.json"
        ctx.write_text(json.dumps({
            "role_id": "r", "call_counts": {"notion-board": 1}, "ingested_external": False,
            "failures": [{"tool_id": "notion-board", "status": "unknown",
                          "reason": "creds", "reauth": True}],
        }), encoding="utf-8")
        summary = roles_persist.run(
            "r", {"role_id": "r", "hook": "tick", "run_at": "2026-07-19T10:00:00Z",
                  "deltas": []}, base=self.tmp, tool_ctx=ctx)
        self.assertIn("role-tool-reauth", summary.get("clarifications", []))
        log = (self.tmp / "_system" / "state" / "log_roles.md").read_text(encoding="utf-8")
        self.assertIn("notion-board", log)  # tool failure visible in the tick's log


class NoSelfFeedGroundingTest(unittest.TestCase):
    def test_self_authored_record_detected(self):
        unit = {"path": "x.md", "frontmatter_subset": {"source": "role:r"}}
        self.assertTrue(roles_persist._is_self_authored_record(unit, "r"))
        other = {"path": "y.md", "frontmatter_subset": {"source": "role:other"}}
        self.assertFalse(roles_persist._is_self_authored_record(other, "r"))
        plain = {"path": "z.md", "frontmatter_subset": {"source": "plaud"}}
        self.assertFalse(roles_persist._is_self_authored_record(plain, "r"))


if __name__ == "__main__":
    unittest.main()
