"""Tests for the act path (CONTRACT §6.2/§6.5, INV-16/28): mandate authorization
(`roles_mandate`), the rmw/idempotency/TOCTOU/atomicity engine (`roles_act`), and the
`http` adapter's direction-gated write verbs.

No real network: an in-memory `FakeBoard` simulates a GitHub-issues REST board so the
whole rmw spine (search-dedup → create, GET-baseline → TOCTOU → PATCH) is deterministic
and offline-testable. The direction gate is tested against the real `roles_tool_http`
verb check (no socket — a bad verb is refused before any request).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_act as ra  # noqa: E402
import roles_mandate as rm  # noqa: E402
import roles_tool_http as http_adapter  # noqa: E402
from roles_common import MandateSpec, MandateTarget  # noqa: E402
from roles_tools import ToolResult, ToolSpec  # noqa: E402


def _act_spec(tool_id: str = "board-write") -> ToolSpec:
    return ToolSpec(
        tool_id=tool_id, direction="act", adapter="http", cadence_slot="on-demand",
        grounding_landing="round-trip", max_calls_per_run=None, credential_ref="secret://board",
        plain_purpose="", usage_note="", status="active",
        act_config_items=tuple(sorted({
            "base_host": "https://api.example.com", "collection": "issues",
            "version_field": "updated_at", "match_field": "title", "id_field": "number",
            "state_field": "state", "open_value": "open", "closed_value": "closed",
            "create_fields": "title,body", "update_fields": "title,body,state",
        }.items())),
    )


def _read_spec() -> ToolSpec:
    return ToolSpec(
        tool_id="r", direction="read", adapter="http", cadence_slot="on-demand",
        grounding_landing="ephemeral", max_calls_per_run=3, credential_ref=None,
        plain_purpose="", usage_note="", status="active",
    )


SURFACE = "repos/acme/board"


class FakeBoard:
    """An in-memory GitHub-issues-shaped REST board. `exec_http` matches the transport
    signature `(spec, request, secret) -> ToolResult`, routing by method + url so the
    rmw engine drives it exactly as it would the real API. Every PATCH/POST bumps
    `updated_at` (a monotonic counter) so TOCTOU drift is reproducible."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.clock = 0
        self.calls: list[tuple[str, str]] = []
        self._next = 1

    def _stamp(self) -> str:
        self.clock += 1
        return f"v{self.clock}"

    def add(self, title: str, state: str = "open", body: str = "") -> dict:
        n = self._next
        self._next += 1
        self.issues[n] = {"number": n, "title": title, "state": state,
                          "body": body, "updated_at": self._stamp()}
        return self.issues[n]

    def _result(self, status_code: int, payload) -> ToolResult:
        return ToolResult(tool_id="board-write", status="ok",
                          data={"status_code": status_code,
                                "body": json.dumps(payload), "truncated": False},
                          summary=f"http {status_code}")

    def exec_http(self, spec, request, secret):  # noqa: ANN001
        method = request["method"].upper()
        url = request["url"]
        self.calls.append((method, url))
        base = "https://api.example.com/repos/acme/board/issues"
        if method == "GET" and url.startswith(base + "?"):
            return self._result(200, list(self.issues.values()))
        if method == "GET" and url.startswith(base + "/"):
            ref = int(url.rsplit("/", 1)[-1])
            if ref in self.issues:
                return self._result(200, self.issues[ref])
            return ToolResult.unknown("board-write", "http 404")
        if method == "POST" and url == base:
            issue = self.add(request["json"].get("title", ""),
                             body=request["json"].get("body", ""))
            return self._result(201, issue)
        if method == "PATCH" and url.startswith(base + "/"):
            ref = int(url.rsplit("/", 1)[-1])
            if ref not in self.issues:
                return ToolResult.unknown("board-write", "http 404")
            self.issues[ref].update(request["json"])
            self.issues[ref]["updated_at"] = self._stamp()
            return self._result(200, self.issues[ref])
        return ToolResult.unknown("board-write", "http 404 (unrouted)")


# -----------------------------------------------------------------------------
# roles_mandate
# -----------------------------------------------------------------------------

class MandateTest(unittest.TestCase):
    def _mandate(self, autonomy="advisory", until=None, blast="bounded"):
        return MandateSpec(
            autonomy=autonomy,
            scope=(MandateTarget(target="board-write", surface=SURFACE,
                                 mode="read-modify-write", blast=blast),),
            until=until)

    def test_no_mandate_refused(self) -> None:
        d = rm.authorize_act(None, "board-write", SURFACE, date(2026, 7, 19))
        self.assertFalse(d.allowed)

    def test_matched_target_allowed(self) -> None:
        d = rm.authorize_act(self._mandate(), "board-write", SURFACE, date(2026, 7, 19))
        self.assertTrue(d.allowed)
        self.assertEqual(d.target.surface, SURFACE)

    def test_expired_mandate_refused(self) -> None:
        d = rm.authorize_act(self._mandate(until="2026-01-01"), "board-write", SURFACE,
                             date(2026, 7, 19))
        self.assertFalse(d.allowed)
        self.assertIn("expired", d.reason)

    def test_wrong_surface_refused(self) -> None:
        d = rm.authorize_act(self._mandate(), "board-write", "repos/other/repo",
                             date(2026, 7, 19))
        self.assertFalse(d.allowed)

    def test_wrong_tool_refused(self) -> None:
        d = rm.authorize_act(self._mandate(), "other-tool", SURFACE, date(2026, 7, 19))
        self.assertFalse(d.allowed)

    def test_hitl_when_cage_unverified(self) -> None:
        d = rm.authorize_act(self._mandate(autonomy="autonomous"), "board-write", SURFACE,
                             date(2026, 7, 19))
        hitl, _ = rm.act_is_hitl(d, "autonomous", ingested_external=False, cage_verified=False)
        self.assertTrue(hitl)  # PLAN-2 §1: always HITL in the harness

    def test_hitl_when_advisory(self) -> None:
        d = rm.authorize_act(self._mandate(autonomy="advisory"), "board-write", SURFACE,
                             date(2026, 7, 19))
        hitl, reason = rm.act_is_hitl(d, "advisory", ingested_external=False, cage_verified=True)
        self.assertTrue(hitl)
        self.assertIn("advisory", reason)

    def test_autonomous_ok_when_cage_and_bounded(self) -> None:
        d = rm.authorize_act(self._mandate(autonomy="autonomous", blast="bounded"),
                             "board-write", SURFACE, date(2026, 7, 19))
        hitl, _ = rm.act_is_hitl(d, "autonomous", ingested_external=True, cage_verified=True)
        self.assertFalse(hitl)  # bounded-blast + firewall + cage → firewall-exempt

    def test_hitl_when_firewall_and_open_blast(self) -> None:
        d = rm.authorize_act(self._mandate(autonomy="autonomous", blast="open"),
                             "board-write", SURFACE, date(2026, 7, 19))
        hitl, reason = rm.act_is_hitl(d, "autonomous", ingested_external=True, cage_verified=True)
        self.assertTrue(hitl)
        self.assertIn("firewall", reason)

    # --- ZTN_ROLES_AUTONOMOUS_ACK launch path (no verified cage) ---
    def _auto(self, blast="bounded"):
        return rm.authorize_act(self._mandate(autonomy="autonomous", blast=blast),
                                "board-write", SURFACE, date(2026, 7, 19))

    def test_ack_bounded_act_runs_hands_free_even_when_ingesting_external(self) -> None:
        # The role's normal reversible work (status update / board reconcile) executes
        # hands-free under the ack marker even on a tick that read external content —
        # exactly the owner's intent ("update the status from the doc = do it").
        hitl, _ = rm.act_is_hitl(self._auto("bounded"), "autonomous",
                                 ingested_external=True, cage_verified=False,
                                 autonomous_ack=True)
        self.assertFalse(hitl)

    def test_ack_irreversible_act_stages_when_ingesting_external(self) -> None:
        # The one reserved exception: an irreversible (open-blast) act on a tick that read
        # external content stages for confirm — the confused-deputy guard even the
        # autonomy-consenting owner keeps.
        hitl, reason = rm.act_is_hitl(self._auto("open"), "autonomous",
                                      ingested_external=True, cage_verified=False,
                                      autonomous_ack=True)
        self.assertTrue(hitl)
        self.assertIn("firewall", reason)

    def test_ack_irreversible_act_runs_hands_free_without_external_ingestion(self) -> None:
        # An irreversible act on a tick that read NO external tool content has no injection
        # vector → runs hands-free under the ack (the owner's consent covers it).
        hitl, _ = rm.act_is_hitl(self._auto("open"), "autonomous",
                                 ingested_external=False, cage_verified=False,
                                 autonomous_ack=True)
        self.assertFalse(hitl)

    def test_ack_marker_does_not_unlock_advisory_dial(self) -> None:
        # The marker only unlocks a role DIALED autonomous; an advisory role stays HITL.
        hitl, reason = rm.act_is_hitl(self._auto("bounded"), "advisory",
                                      ingested_external=False, cage_verified=False,
                                      autonomous_ack=True)
        self.assertTrue(hitl)
        self.assertIn("advisory", reason)


# -----------------------------------------------------------------------------
# http adapter — direction-gated verbs
# -----------------------------------------------------------------------------

class HttpVerbGateTest(unittest.TestCase):
    def test_read_tool_refuses_post(self) -> None:
        r = http_adapter.exec_tool(_read_spec(), {"url": "https://x.test", "method": "POST"}, None)
        self.assertEqual(r.status, "unknown")
        self.assertIn("read adapter allows only", r.summary)

    def test_act_tool_allows_patch_verb_gate(self) -> None:
        # A bad url still fails, but NOT on the verb gate — proves PATCH passes the gate.
        r = http_adapter.exec_tool(_act_spec(), {"url": "ftp://x", "method": "PATCH"}, None)
        self.assertNotIn("adapter allows only", r.summary)


# -----------------------------------------------------------------------------
# roles_act — parse + endpoints
# -----------------------------------------------------------------------------

class ActParseTest(unittest.TestCase):
    def test_create_parses(self) -> None:
        op = ra.ActOperation.from_dict(
            {"part": "w", "tool": "board-write", "op": "create",
             "fields": {"title": "T", "body": "B"}, "dedup_match": "T", "evidence": ["[[r]]"]})
        self.assertIsNotNone(op)
        self.assertEqual(op.op, "create")

    def test_update_without_ref_dropped(self) -> None:
        self.assertIsNone(ra.ActOperation.from_dict(
            {"part": "w", "tool": "b", "op": "update", "fields": {"body": "x"}}))

    def test_unknown_op_dropped(self) -> None:
        self.assertIsNone(ra.ActOperation.from_dict(
            {"part": "w", "tool": "b", "op": "delete-everything"}))

    def test_target_ref_path_traversal_rejected(self) -> None:
        # A ref that would escape the mandated surface via the URL is refused (INV-16).
        for bad in ("1/../../other/repo/issues/7", "1/comments", "1?state=x", "../x", "a b"):
            self.assertIsNone(ra.ActOperation.from_dict(
                {"part": "w", "tool": "b", "op": "close", "target_ref": bad}), bad)

    def test_target_ref_plain_id_accepted(self) -> None:
        op = ra.ActOperation.from_dict(
            {"part": "w", "tool": "b", "op": "close", "target_ref": "42"})
        self.assertIsNotNone(op)
        self.assertEqual(op.target_ref, "42")

    def test_build_endpoints_missing_key_raises(self) -> None:
        spec = ToolSpec(tool_id="b", direction="act", adapter="http",
                        cadence_slot="on-demand", grounding_landing="round-trip",
                        max_calls_per_run=None, credential_ref=None, plain_purpose="",
                        usage_note="", status="active",
                        act_config_items=(("base_host", "https://x"),))
        with self.assertRaises(ra.ActError):
            ra.build_endpoints(spec, SURFACE)

    def test_build_endpoints_no_surface_raises(self) -> None:
        with self.assertRaises(ra.ActError):
            ra.build_endpoints(_act_spec(), "")

    def test_missing_status_vocab_refuses_no_github_default(self) -> None:
        # 3a refuse-don't-assume: an act tool that omits the status vocabulary must NOT
        # silently inherit GitHub's `state/open/closed` — build_endpoints refuses.
        cfg = {"base_host": "https://x", "collection": "c", "version_field": "v",
               "match_field": "m", "id_field": "i", "create_fields": "a", "update_fields": "a"}
        spec = ToolSpec(tool_id="b", direction="act", adapter="http",
                        cadence_slot="on-demand", grounding_landing="round-trip",
                        max_calls_per_run=None, credential_ref=None, plain_purpose="",
                        usage_note="", status="active",
                        act_config_items=tuple(sorted(cfg.items())))
        with self.assertRaises(ra.ActError):
            ra.build_endpoints(spec, "board")

    def test_search_query_derived_from_declared_vocab(self) -> None:
        # The optional search_query defaults to the tool's OWN status vocab, not GitHub's.
        cfg = {"base_host": "https://x", "collection": "c", "version_field": "v",
               "match_field": "m", "id_field": "i", "state_field": "status",
               "open_value": "todo", "closed_value": "done",
               "create_fields": "a", "update_fields": "a"}
        spec = ToolSpec(tool_id="b", direction="act", adapter="http",
                        cadence_slot="on-demand", grounding_landing="round-trip",
                        max_calls_per_run=None, credential_ref=None, plain_purpose="",
                        usage_note="", status="active",
                        act_config_items=tuple(sorted(cfg.items())))
        ep = ra.build_endpoints(spec, "board")
        self.assertIn("status=todo", ep["search_url"])  # derived from declared vocab


# -----------------------------------------------------------------------------
# roles_act — the full rmw spine against the fake board
# -----------------------------------------------------------------------------

class ActExecuteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.board = FakeBoard()
        self.i1 = self.board.add("Alpha: wire onboarding email")   # #1
        self.i2 = self.board.add("Beta: draft billing schema")     # #2
        self.spec = _act_spec()

    def _op(self, **kw) -> ra.ActOperation:
        return ra.ActOperation.from_dict({"part": "w", "tool": "board-write", **kw})

    def test_create_idempotent_skips_existing(self) -> None:
        op = self._op(op="create", fields={"title": "Alpha: wire onboarding email"},
                      dedup_match="Alpha: wire onboarding email")
        out = ra.execute_act(self.spec, SURFACE, op, None, self.board.exec_http)
        self.assertEqual(out.status, "skipped")
        self.assertEqual(len(self.board.issues), 2)  # no double-create

    def test_create_dedup_keys_on_posted_title_not_free_dedup_match(self) -> None:
        # The idempotency key is derived from the POSTED title (fields[match_field]), not
        # a free-floating `dedup_match` — so a bogus dedup_match cannot cause a double-post
        # of an already-present item.
        op = self._op(op="create", fields={"title": "Alpha: wire onboarding email"},
                      dedup_match="totally-unrelated-needle")
        out = ra.execute_act(self.spec, SURFACE, op, None, self.board.exec_http)
        self.assertEqual(out.status, "skipped")  # matched #1 by its title, not dedup_match
        self.assertEqual(len(self.board.issues), 2)  # no double-post

    def test_create_without_title_refused(self) -> None:
        op = self._op(op="create", fields={"body": "no title"}, dedup_match="x")
        out = ra.execute_act(self.spec, SURFACE, op, None, self.board.exec_http)
        self.assertEqual(out.status, "refused")

    def test_create_new_posts(self) -> None:
        op = self._op(op="create", fields={"title": "Gamma: build ingestion", "body": "x"},
                      dedup_match="Gamma: build ingestion")
        out = ra.execute_act(self.spec, SURFACE, op, None, self.board.exec_http)
        self.assertEqual(out.status, "executed")
        self.assertEqual(len(self.board.issues), 3)

    def test_close_executes(self) -> None:
        staged, _ = ra.stage_act(self.spec, SURFACE,
                                 self._op(op="close", target_ref="1", reason="shipped"),
                                 None, self.board.exec_http)
        out = ra.execute_act(self.spec, SURFACE, staged, None, self.board.exec_http)
        self.assertEqual(out.status, "executed")
        self.assertEqual(self.board.issues[1]["state"], "closed")

    def test_close_already_closed_skips(self) -> None:
        self.board.issues[1]["state"] = "closed"
        staged, _ = ra.stage_act(self.spec, SURFACE,
                                 self._op(op="close", target_ref="1"),
                                 None, self.board.exec_http)
        out = ra.execute_act(self.spec, SURFACE, staged, None, self.board.exec_http)
        self.assertEqual(out.status, "skipped")

    def test_update_already_matching_is_idempotent_skip(self) -> None:
        # A re-run of an update whose fields already match the target → skip, no PATCH.
        self.board.issues[2]["body"] = "already the target body"
        staged, _ = ra.stage_act(
            self.spec, SURFACE,
            self._op(op="update", target_ref="2", fields={"body": "already the target body"}),
            None, self.board.exec_http)
        before = self.board.issues[2]["updated_at"]
        out = ra.execute_act(self.spec, SURFACE, staged, None, self.board.exec_http)
        self.assertEqual(out.status, "skipped")
        self.assertEqual(self.board.issues[2]["updated_at"], before)  # no PATCH bump

    def test_secret_never_appears_in_outcome_or_audit(self) -> None:
        # INV-12: a resolved token never lands in an ActOutcome or the audit — it only
        # rides the http Authorization header (which the FakeBoard never echoes back).
        import roles_persist
        SECRET = "SEKRET-TOKEN-must-never-surface"
        staged, _ = ra.stage_act(
            self.spec, SURFACE, self._op(op="close", target_ref="1", reason="done"),
            SECRET, self.board.exec_http)
        out = ra.execute_act(self.spec, SURFACE, staged, SECRET, self.board.exec_http)
        blob = json.dumps({"op": out.op, "ref": out.target_ref, "status": out.status,
                           "detail": out.detail, "effect": out.effect})
        self.assertNotIn(SECRET, blob)
        with tempfile.TemporaryDirectory() as t:
            base = Path(t)
            roles_persist._audit_act("r", "board-write", out, base)
            audit = (base / "_system" / "state" / "roles-tool-audit.jsonl").read_text()
        self.assertNotIn(SECRET, audit)

    def test_update_executes(self) -> None:
        staged, _ = ra.stage_act(
            self.spec, SURFACE,
            self._op(op="update", target_ref="2", fields={"body": "in review; Stripe blocker"},
                     reason="status change"),
            None, self.board.exec_http)
        out = ra.execute_act(self.spec, SURFACE, staged, None, self.board.exec_http)
        self.assertEqual(out.status, "executed")
        self.assertIn("Stripe", self.board.issues[2]["body"])

    def test_toctou_drift_aborts_write(self) -> None:
        # Stage captures baseline; a concurrent edit bumps updated_at → drift → no write.
        staged, stage_out = ra.stage_act(
            self.spec, SURFACE,
            self._op(op="update", target_ref="2", fields={"body": "mine"}),
            None, self.board.exec_http)
        self.assertEqual(stage_out.status, "executed")
        self.board.issues[2]["body"] = "someone else"        # concurrent change
        self.board.issues[2]["updated_at"] = self.board._stamp()
        out = ra.execute_act(self.spec, SURFACE, staged, None, self.board.exec_http)
        self.assertEqual(out.status, "drift")
        self.assertEqual(self.board.issues[2]["body"], "someone else")  # NOT overwritten

    def test_stage_missing_target_fails(self) -> None:
        _, out = ra.stage_act(self.spec, SURFACE,
                              self._op(op="close", target_ref="999"),
                              None, self.board.exec_http)
        self.assertEqual(out.status, "failed")

    def test_transport_failure_is_honest(self) -> None:
        def boom(spec, request, secret):  # noqa: ANN001
            raise RuntimeError("network down")
        out = ra.execute_act(self.spec, SURFACE,
                             self._op(op="create", fields={"title": "X"}, dedup_match="X"),
                             None, boom)
        self.assertEqual(out.status, "failed")

    def test_truncated_search_refuses_create_no_double_post(self) -> None:
        # A truncated dedup search MUST NOT read as "empty" (→ double-post). The item
        # exists but the search body is truncated → the create fails honestly.
        def truncated(spec, request, secret):  # noqa: ANN001
            if request["method"] == "GET" and "?" in request["url"]:
                return ToolResult(tool_id="board-write", status="ok",
                                  data={"status_code": 200, "body": '[{"number":1,"tit',
                                        "truncated": True}, summary="http 200")
            return self.board.exec_http(spec, request, secret)
        out = ra.execute_act(self.spec, SURFACE,
                             self._op(op="create", fields={"title": "Alpha: wire onboarding email"},
                                      dedup_match="Alpha: wire onboarding email"),
                             None, truncated)
        self.assertEqual(out.status, "failed")
        self.assertEqual(len(self.board.issues), 2)  # nothing created

    def test_full_page_search_refuses_create(self) -> None:
        big = [{"number": i, "title": f"t{i}", "state": "open"} for i in range(100)]
        def fullpage(spec, request, secret):  # noqa: ANN001
            if request["method"] == "GET" and "?" in request["url"]:
                return ToolResult(tool_id="board-write", status="ok",
                                  data={"status_code": 200, "body": json.dumps(big),
                                        "truncated": False}, summary="http 200")
            return self.board.exec_http(spec, request, secret)
        out = ra.execute_act(self.spec, SURFACE,
                             self._op(op="create", fields={"title": "New"}, dedup_match="New"),
                             None, fullpage)
        self.assertEqual(out.status, "failed")


class GenericBoardTest(unittest.TestCase):
    """A non-GitHub REST board driven purely by act_config vocabulary (INV-19)."""

    def _spec(self):
        return ToolSpec(
            tool_id="jira-like", direction="act", adapter="http", cadence_slot="on-demand",
            grounding_landing="round-trip", max_calls_per_run=None, credential_ref=None,
            plain_purpose="", usage_note="", status="active",
            act_config_items=tuple(sorted({
                "base_host": "https://jira.example.com", "collection": "tickets",
                "version_field": "rev", "match_field": "summary", "id_field": "key",
                "state_field": "status", "open_value": "todo", "closed_value": "done",
                "create_fields": "summary,description",
                "update_fields": "summary,description,status",
            }.items())),
        )

    def test_close_uses_configured_state_vocab(self) -> None:
        tickets = {1: {"key": 1, "summary": "T", "status": "todo", "rev": "r1"}}
        def exec_http(spec, request, secret):  # noqa: ANN001
            method, url = request["method"].upper(), request["url"]
            base = "https://jira.example.com/repos/acme/board/tickets"
            def res(code, payload):
                return ToolResult(tool_id="jira-like", status="ok",
                                  data={"status_code": code, "body": json.dumps(payload),
                                        "truncated": False}, summary="")
            if method == "GET" and url.startswith(base + "/"):
                return res(200, tickets[int(url.rsplit("/", 1)[-1])])
            if method == "PATCH" and url.startswith(base + "/"):
                ref = int(url.rsplit("/", 1)[-1])
                tickets[ref].update(request["json"]); tickets[ref]["rev"] = "r2"
                return res(200, tickets[ref])
            return ToolResult.unknown("jira-like", "404")
        spec = self._spec()
        staged, _ = ra.stage_act(spec, SURFACE, ra.ActOperation.from_dict(
            {"part": "w", "tool": "jira-like", "op": "close", "target_ref": "1", "reason": "done"}),
            None, exec_http)
        out = ra.execute_act(spec, SURFACE, staged, None, exec_http)
        self.assertEqual(out.status, "executed")
        self.assertEqual(tickets[1]["status"], "done")  # the configured closed_value


class BaselineRoundTripTest(unittest.TestCase):
    def test_empty_baseline_preserved_not_collapsed(self) -> None:
        op = ra.ActOperation.from_dict(
            {"part": "w", "tool": "b", "op": "close", "target_ref": "1", "baseline": ""})
        self.assertEqual(op.baseline, "")  # NOT None — TOCTOU still compares
        self.assertEqual(ra.ActOperation.from_dict(op.to_dict()).baseline, "")

    def test_absent_baseline_is_none(self) -> None:
        op = ra.ActOperation.from_dict(
            {"part": "w", "tool": "b", "op": "create", "fields": {"title": "x"}})
        self.assertIsNone(op.baseline)


class DedupPaginationTest(unittest.TestCase):
    def _ep(self):
        return ra.build_endpoints(_act_spec(), SURFACE)

    def _paged_exec(self, pages):
        # pages: list of item-lists, one per page (1-indexed via &page=N).
        def exec_http(spec, request, secret):  # noqa: ANN001
            page = 1
            for frag in request["url"].split("&"):
                if frag.startswith("page="):
                    page = int(frag.split("=")[1])
            items = pages[page - 1] if 1 <= page <= len(pages) else []
            return ToolResult(tool_id="board-write", status="ok",
                              data={"status_code": 200, "body": json.dumps(items),
                                    "truncated": False}, summary="")
        return exec_http

    def test_match_found_on_second_page(self):
        p1 = [{"number": i, "title": f"t{i}", "state": "open"} for i in range(100)]
        p2 = [{"number": 200, "title": "Wanted", "state": "open"}]  # short page → the end
        match, status, _ = ra._dedup_find(self._paged_exec([p1, p2]), _act_spec(), None,
                                          self._ep(), "Wanted")
        self.assertEqual(status, "ok")
        self.assertIsNotNone(match)
        self.assertEqual(match["number"], 200)

    def test_short_first_page_is_the_end_no_match(self):
        p1 = [{"number": 1, "title": "a", "state": "open"}]  # < per_page → end
        match, status, _ = ra._dedup_find(self._paged_exec([p1]), _act_spec(), None,
                                          self._ep(), "Wanted")
        self.assertEqual(status, "ok")
        self.assertIsNone(match)

    def test_unbounded_board_is_inconclusive_not_double_post(self):
        full = [{"number": i, "title": f"t{i}", "state": "open"} for i in range(100)]
        # every page full → never reaches the end → inconclusive past the cap
        match, status, _ = ra._dedup_find(self._paged_exec([full] * 20), _act_spec(), None,
                                          self._ep(), "Wanted")
        self.assertEqual(status, "inconclusive")
        self.assertIsNone(match)


class HttpBackoffTest(unittest.TestCase):
    def _resp(self, body):
        class R:
            status = 200
            def read(self, n): return body.encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return R()

    def test_429_retried_then_succeeds(self):
        import urllib.error
        calls = {"n": 0}
        def fake_open(req, timeout=None):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] <= 2:
                raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)
            return self._resp("[]")
        with unittest.mock.patch.object(http_adapter._OPENER, "open", side_effect=fake_open), \
             unittest.mock.patch.object(http_adapter, "_sleep", lambda *_: None):
            r = http_adapter.exec_tool(_read_spec(), {"url": "https://x.test"}, None)
        self.assertEqual(r.status, "ok")
        self.assertEqual(calls["n"], 3)  # 2 × 429 + 1 × 200

    def test_persistent_429_honest_degrades(self):
        import urllib.error
        def fake_open(req, timeout=None):  # noqa: ANN001
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)
        with unittest.mock.patch.object(http_adapter._OPENER, "open", side_effect=fake_open), \
             unittest.mock.patch.object(http_adapter, "_sleep", lambda *_: None):
            r = http_adapter.exec_tool(_read_spec(), {"url": "https://x.test"}, None)
        self.assertEqual(r.status, "unknown")
        self.assertIn("429", r.summary)

    def test_retry_after_header_honoured(self):
        import urllib.error
        class H:
            def get(self, k, d=None): return "2" if k == "Retry-After" else d
        exc = urllib.error.HTTPError("https://x", 429, "rate", H(), None)
        self.assertEqual(http_adapter._retry_after_seconds(exc, 0), 2.0)


class RedirectSecretStripTest(unittest.TestCase):
    def test_authorization_stripped_on_cross_host_redirect(self) -> None:
        import urllib.request, email.message
        h = http_adapter._NoAuthLeakRedirect()
        req = urllib.request.Request("https://a.test/x",
                                     headers={"Authorization": "Bearer SECRET"})
        new = h.redirect_request(req, None, 302, "Found", email.message.Message(),
                                 "https://evil.test/y")
        self.assertIsNotNone(new)
        self.assertNotIn("Authorization", new.headers)
        self.assertNotIn("Authorization", getattr(new, "unredirected_hdrs", {}))

    def test_authorization_kept_on_same_host_redirect(self) -> None:
        import urllib.request, email.message
        h = http_adapter._NoAuthLeakRedirect()
        req = urllib.request.Request("https://a.test/x",
                                     headers={"Authorization": "Bearer S"})
        new = h.redirect_request(req, None, 302, "Found", email.message.Message(),
                                 "https://a.test/y")
        self.assertEqual(new.headers.get("Authorization"), "Bearer S")


if __name__ == "__main__":
    unittest.main()
