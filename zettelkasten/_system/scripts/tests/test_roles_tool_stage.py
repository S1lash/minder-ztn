"""Tests for the TOOL STAGE + read adapters (CONTRACT §2.2/§3, INV-10/19/20).

Proves the whole deterministic seam OFFLINE — grant → budget → secret-resolve →
adapter dispatch → ephemeral return → audit — plus the http adapter against a
LOCAL threaded HTTP server (no external network; the real-system live proof is a
one-time session run captured in IMPL-NOTES, kept out of CI per the no-network
convention).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_secrets  # noqa: E402
import roles_tool_http  # noqa: E402
import roles_tool_mcp  # noqa: E402
import roles_tool_stage as stage  # noqa: E402
import roles_tools as rt  # noqa: E402
from roles_common import load_role_config  # noqa: E402


_REGISTRY = """# Tools Registry

## Active Tools

| Tool ID | Direction | Adapter | Cadence Slot | Grounding Landing | Budget | Credential | MCP Binding | Act Config | Plain Purpose | Usage Note | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| http-get | read | http | on-demand | ephemeral | 2 | — | — | — | Fetch a URL. | Read a small endpoint. | active |
| notion-board | read | mcp | on-demand | ephemeral | unlimited | secret://notion | mcp__notion__query | — | Reads Notion. | Pull tasks. | active |
| authed-http | read | http | on-demand | ephemeral | 3 | secret://apikey | — | — | Fetch with auth. | Read behind a token. | active |
| board-write | act | http | on-demand | round-trip | unlimited | secret://apikey | — | base_host=https://api.example.com;collection=issues;version_field=updated_at;match_field=title;id_field=number;state_field=state;open_value=open;closed_value=closed;create_fields=title,body;update_fields=title,body,state | Writes a board. | Reconcile under mandate. | active |
"""

_CONFIG = """id: r
parts:
  - {id: p1, kind: ledger, tools: [http-get, notion-board, authed-http, board-write]}
remit: {all: true}
cadence: daily
status: active
"""


def _build_base(tmp: Path, config: str = _CONFIG) -> Path:
    (tmp / "_system" / "registries").mkdir(parents=True, exist_ok=True)
    (tmp / "_system" / "registries" / "TOOLS.md").write_text(_REGISTRY, encoding="utf-8")
    (tmp / "_system" / "roles" / "r").mkdir(parents=True, exist_ok=True)
    (tmp / "_system" / "roles" / "r" / "config.yml").write_text(config, encoding="utf-8")
    return tmp


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_GET(self):
        # Echo whether an Authorization header arrived (host-pin credential tests read it).
        auth = self.headers.get("Authorization", "")
        body = ('{"ok": true, "zen": "keep it simple", "auth": "%s"}' % auth).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


class HttpAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _StubHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _spec(self):
        return rt.ToolSpec(
            tool_id="http-get", direction="read", adapter="http",
            cadence_slot="on-demand", grounding_landing="ephemeral",
            max_calls_per_run=2, credential_ref=None, plain_purpose="", usage_note="",
            status="active")

    def test_real_local_get_succeeds(self):
        r = roles_tool_http.exec_tool(
            self._spec(), {"url": f"http://127.0.0.1:{self.port}/x"}, None)
        self.assertTrue(r.ok)
        self.assertIn("keep it simple", r.data["body"])
        self.assertEqual(r.data["status_code"], 200)
        self.assertTrue(r.raw_hash)
        self.assertTrue(r.is_external)

    def test_bad_scheme_declares_unknown(self):
        r = roles_tool_http.exec_tool(self._spec(), {"url": "ftp://x/y"}, None)
        self.assertEqual(r.status, "unknown")

    def test_write_method_refused(self):
        r = roles_tool_http.exec_tool(
            self._spec(), {"url": f"http://127.0.0.1:{self.port}/", "method": "POST"}, None)
        self.assertEqual(r.status, "unknown")

    def test_unreachable_declares_unknown(self):
        # An unroutable port → connection error → declare-unknown, never a guess.
        r = roles_tool_http.exec_tool(
            self._spec(), {"url": "http://127.0.0.1:1/", "timeout": 1}, None)
        self.assertEqual(r.status, "unknown")

    def _cred_spec(self, base_host):
        # A credential-bearing read http tool pinned to `base_host` (host declared in its
        # Act Config, exposed via ToolSpec.credential_host).
        return rt.ToolSpec(
            tool_id="authed", direction="read", adapter="http", cadence_slot="on-demand",
            grounding_landing="ephemeral", max_calls_per_run=None,
            credential_ref="secret://apikey", plain_purpose="", usage_note="",
            status="active", act_config_items=(("base_host", base_host),))

    def test_credential_attached_only_to_declared_host(self):
        # HOLE B guard: the Bearer token IS attached when the request host matches the
        # tool's declared base_host (the legit path still works).
        host = f"127.0.0.1:{self.port}"
        r = roles_tool_http.exec_tool(
            self._cred_spec(f"http://{host}"), {"url": f"http://{host}/x"}, "s3cr3t")
        self.assertTrue(r.ok)
        self.assertIn("Bearer s3cr3t", r.data["body"])  # server echoed the Authorization

    def test_credential_refused_on_foreign_host(self):
        # HOLE B: a body-chosen FOREIGN host never receives the token — refused pre-network.
        r = roles_tool_http.exec_tool(
            self._cred_spec(f"http://127.0.0.1:{self.port}"),
            {"url": "https://attacker.example/steal"}, "s3cr3t")
        self.assertEqual(r.status, "unknown")
        self.assertIn("not allowed", r.error)
        self.assertNotIn("s3cr3t", r.error)  # the token is never echoed in the refusal

    def test_credential_tool_without_declared_host_refused(self):
        # A credential-bearing tool that declares NO base_host is fail-closed (refused),
        # never leaked to whatever host the body named.
        spec = rt.ToolSpec(
            tool_id="authed", direction="read", adapter="http", cadence_slot="on-demand",
            grounding_landing="ephemeral", max_calls_per_run=None,
            credential_ref="secret://apikey", plain_purpose="", usage_note="",
            status="active")  # no act_config_items → credential_host None
        r = roles_tool_http.exec_tool(
            spec, {"url": f"http://127.0.0.1:{self.port}/x"}, "s3cr3t")
        self.assertEqual(r.status, "unknown")
        self.assertIn("declares no base_host", r.error)

    def test_redirect_strips_auth_on_host_change(self):
        # INV-12 second layer: even if the initial host-pin passes, a cross-host REDIRECT
        # must NOT re-send the Bearer/Cookie to the new host (CPython's default handler
        # would). Unit-test the handler directly.
        import urllib.request
        from email.message import Message
        h = roles_tool_http._NoAuthLeakRedirect()
        # exec_tool puts the Bearer in the request headers (redirected — the leak vector).
        hdrs = {"Authorization": "Bearer s3cr3t", "Cookie": "sess=1"}
        req = urllib.request.Request("https://api.github.com/x", headers=dict(hdrs))
        # cross-host redirect → Authorization + Cookie stripped
        new = h.redirect_request(req, None, 302, "Found", Message(),
                                 "https://attacker.example/y")
        self.assertIsNotNone(new)
        self.assertIsNone(new.get_header("Authorization"))
        self.assertIsNone(new.get_header("Cookie"))
        # same-host redirect → headers preserved (legit follow)
        req2 = urllib.request.Request("https://api.github.com/x", headers=dict(hdrs))
        new2 = h.redirect_request(req2, None, 302, "Found", Message(),
                                  "https://api.github.com/z")
        self.assertEqual(new2.get_header("Authorization"), "Bearer s3cr3t")


class McpAdapterTest(unittest.TestCase):
    def _spec(self):
        return rt.ToolSpec(
            tool_id="notion-board", direction="read", adapter="mcp",
            cadence_slot="on-demand", grounding_landing="ephemeral",
            max_calls_per_run=None, credential_ref="secret://notion",
            plain_purpose="", usage_note="", status="active",
            mcp_binding="mcp__notion__query")

    def test_prepare_uses_pinned_binding(self):
        # The body need not name a tool; the pinned registry binding is used.
        d = roles_tool_mcp.prepare(self._spec(), {"args": {"q": "tasks"}}, "tok")
        self.assertTrue(d["ok"])
        self.assertEqual(d["mcp_tool"], "mcp__notion__query")
        self.assertTrue(d["requires_secret"])

    def test_body_redirect_refused(self):
        # INV-23: a body attempt to redirect a read tool to an ACT mcp tool is refused.
        d = roles_tool_mcp.prepare(
            self._spec(), {"mcp_tool": "mcp__notion__update_page"}, "tok")
        self.assertFalse(d["ok"])
        self.assertIn("redirect refused", d["reason"])

    def test_unpinned_spec_refused(self):
        spec = rt.ToolSpec(
            tool_id="x", direction="read", adapter="mcp", cadence_slot="on-demand",
            grounding_landing="ephemeral", max_calls_per_run=1, credential_ref=None,
            plain_purpose="", usage_note="", status="active", mcp_binding=None)
        d = roles_tool_mcp.prepare(spec, {}, None)
        self.assertFalse(d["ok"])

    def test_normalize_ok(self):
        r = roles_tool_mcp.normalize(self._spec(), {"tasks": [1, 2, 3]})
        self.assertTrue(r.ok)
        self.assertTrue(r.raw_hash)
        self.assertTrue(r.is_external)

    def test_normalize_empty_is_unknown(self):
        self.assertEqual(roles_tool_mcp.normalize(self._spec(), {}).status, "unknown")
        self.assertEqual(roles_tool_mcp.normalize(self._spec(), None).status, "unknown")


class ToolStageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = _build_base(Path(self._tmp.name))
        self.cfg = load_role_config("r", self.base)

    def _ctx(self):
        return stage.ToolStageContext(role_id="r")

    def _req(self, tool, part="p1", **kw):
        return {"part": part, "tool": tool, **kw}

    def test_ungranted_tool_refused(self):
        ctx = self._ctx()
        # A real registry tool the role did NOT grant to this part.
        cfg = load_role_config("r", self.base)
        object.__setattr__(cfg.parts[0], "tools", ("http-get",))  # narrow grant
        r = stage.run_tool_request(cfg, self._req("notion-board"), ctx, self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("not granted to part", r.summary)

    def test_missing_part_refused(self):
        # A tool_request with no `part` cannot be per-part grant-checked → refused.
        r = stage.run_tool_request(self.cfg, {"tool": "http-get"}, self._ctx(), self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("no 'part'", r.summary)

    def test_tool_granted_to_part_a_refused_as_part_b(self):
        # FIX-2 / CONTRACT §1.1: grants are PER-PART, not a role-wide union. A two-part
        # role where each part grants a different tool — a tool granted to A is refused
        # when requested as B.
        d = self.base / "_system" / "roles" / "two"
        d.mkdir(parents=True)
        (d / "config.yml").write_text(
            "id: two\nparts:\n"
            "  - {id: a, kind: ledger, tools: [http-get]}\n"
            "  - {id: b, kind: ledger, tools: [notion-board]}\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n", encoding="utf-8")
        cfg = load_role_config("two", self.base)
        # http-get granted to part a → OK as a (reaches exec, degrades on bad url)
        ok = stage.run_tool_request(
            cfg, self._req("http-get", part="a", args={"url": "ftp://x"}), self._ctx(), self.base)
        self.assertNotIn("not granted to part", ok.summary)
        # http-get requested as part b (which grants only notion-board) → REFUSED
        bad = stage.run_tool_request(
            cfg, self._req("http-get", part="b", args={"url": "ftp://x"}), self._ctx(), self.base)
        self.assertEqual(bad.status, "unknown")
        self.assertIn("not granted to part 'b'", bad.summary)

    def test_registry_miss_refused(self):
        cfg = load_role_config("r", self.base)
        object.__setattr__(cfg.parts[0], "tools", ("ghost",))
        r = stage.run_tool_request(cfg, self._req("ghost"), ctx=self._ctx(), base=self.base)
        self.assertEqual(r.status, "unknown")

    def test_per_tool_budget_caps(self):
        ctx = self._ctx()
        # http-get cap = 2. Hit the local nothing — use a bad url (still consumes a slot).
        for _ in range(2):
            stage.run_tool_request(
                self.cfg, self._req("http-get", args={"url": "ftp://x"}), ctx, self.base)
        r = stage.run_tool_request(
            self.cfg, self._req("http-get", args={"url": "ftp://x"}), ctx, self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("budget", r.summary)

    def test_unlimited_never_caps(self):
        ctx = self._ctx()
        spec, refusal = stage.grant_and_budget(self.cfg, "notion-board", "p1", ctx, self.base)
        ctx.call_counts["notion-board"] = 999
        spec2, refusal2 = stage.grant_and_budget(self.cfg, "notion-board", "p1", ctx, self.base)
        self.assertIsNone(refusal2)  # unlimited → never a budget refusal

    def test_mcp_returns_harness_step_then_absorb(self):
        ctx = self._ctx()
        key = roles_secrets.generate_master_key()
        with unittest.mock.patch.dict(os.environ, {"ZTN_SECRET_MASTER_KEY": key}):
            roles_secrets.store_secret("notion", "notion-token", self.base)
            step = stage.run_tool_request(
                self.cfg, self._req("notion-board", mcp_tool="mcp__notion__query"),
                ctx, self.base)
            self.assertIsInstance(step, stage.HarnessStep)
            self.assertEqual(step.secret, "notion-token")  # runner resolved it, not the body
            self.assertEqual(step.part_id, "p1")
            # The SKILL makes the MCP call; feed the raw return back (with the part):
            r = stage.absorb_harness_return(
                self.cfg, "notion-board", {"tasks": [1]}, ctx, self.base, "p1")
        self.assertTrue(r.ok)
        self.assertTrue(ctx.ingested_external)  # firewall flag set on external ok

    def test_secret_resolved_and_passed_to_adapter(self):
        key = roles_secrets.generate_master_key()
        with unittest.mock.patch.dict(os.environ, {"ZTN_SECRET_MASTER_KEY": key}):
            roles_secrets.store_secret("apikey", "s3cr3t-token", self.base)
            captured = {}

            def fake_exec(spec, request, secret):
                captured["secret"] = secret
                return rt.ToolResult(tool_id=spec.tool_id, status="ok", data={}, summary="x")

            with unittest.mock.patch.object(roles_tool_http, "exec_tool", fake_exec):
                stage.run_tool_request(
                    self.cfg, self._req("authed-http", args={"url": "http://x"}),
                    self._ctx(), self.base)
        self.assertEqual(captured["secret"], "s3cr3t-token")

    def test_secret_failure_declares_unknown_with_reauth(self):
        # No master key set → resolve fails → honest-degrade + reauth signal.
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            r = stage.run_tool_request(
                self.cfg, self._req("authed-http", args={"url": "http://x"}),
                self._ctx(), self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("reauth", r.error)

    def test_audit_records_hash_not_raw_body(self):
        ctx = self._ctx()
        stage.absorb_harness_return(
            self.cfg, "notion-board", {"secret_task": "confidential-body"}, ctx, self.base, "p1")
        audit = stage.tool_audit_path(self.base).read_text(encoding="utf-8")
        self.assertIn("notion-board", audit)
        self.assertIn("raw_hash", audit)
        # INV-10: the raw return is NEVER in the audit — only its hash + a summary.
        self.assertNotIn("confidential-body", audit)

    def test_wall_clock_deadline_refuses(self):
        # A tick whose tool loop already exceeded max_tick_seconds refuses further
        # calls (code-enforced, INV-28) — an unlimited tool + looping body can't hold
        # the lock indefinitely. Simulate by stamping started_at far in the past.
        ctx = stage.ToolStageContext(role_id="r", started_at="2020-01-01T00:00:00Z")
        r = stage.run_tool_request(
            self.cfg, self._req("http-get", args={"url": "ftp://x"}), ctx, self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("wall-clock", r.summary)

    def test_first_call_stamps_started_at(self):
        ctx = stage.ToolStageContext(role_id="r")
        self.assertEqual(ctx.started_at, "")
        stage.run_tool_request(
            self.cfg, self._req("http-get", args={"url": "ftp://x"}), ctx, self.base)
        self.assertTrue(ctx.started_at)  # stamped on the first call

    def test_failures_recorded_in_ctx(self):
        ctx = stage.ToolStageContext(role_id="r")
        stage.run_tool_request(
            self.cfg, self._req("authed-http", args={"url": "http://x"}), ctx, self.base)
        # No secret → reauth failure recorded for observability.
        self.assertTrue(ctx.failures)
        self.assertTrue(ctx.failures[0]["reauth"])

    def test_act_tool_refused_via_tool_stage(self):
        # HOLE A (CRITICAL): an `act` tool granted to a part is NOT invocable via the read
        # TOOL STAGE — even though it is in `part.tools`. The body proposes acts[]; the
        # deterministic writer (roles_act) disposes under mandate + TOCTOU + HITL. Without
        # this guard the stage would be a side-door executing an arbitrary write with the
        # live secret, bypassing the entire act spine.
        spec, refusal = stage.grant_and_budget(
            self.cfg, "board-write", "p1", self._ctx(), self.base)
        self.assertIsNone(spec)
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status, "unknown")
        self.assertIn("ACT tool", refusal.error)
        # And end to end through run_tool_request (the body-facing path):
        r = stage.run_tool_request(
            self.cfg, self._req("board-write", args={"method": "POST", "url": "https://api.example.com/x"}),
            self._ctx(), self.base)
        self.assertEqual(r.status, "unknown")
        self.assertIn("ACT tool", r.error)

    def test_harness_counts_at_dispatch(self):
        # Budget self-enforcing across the round-trip: issuing a harness step consumes
        # the slot immediately (not only at absorb).
        key = roles_secrets.generate_master_key()
        with unittest.mock.patch.dict(os.environ, {"ZTN_SECRET_MASTER_KEY": key}):
            roles_secrets.store_secret("notion", "tok", self.base)
            ctx = self._ctx()
            step = stage.run_tool_request(
                self.cfg, self._req("notion-board", mcp_tool="mcp__notion__query"),
                ctx, self.base)
            self.assertIsInstance(step, stage.HarnessStep)
            self.assertEqual(ctx.call_counts["notion-board"], 1)  # counted at dispatch

    def test_harness_absorb_does_not_double_count(self):
        # One logical harness round-trip = ONE slot: dispatch counts, absorb does NOT
        # re-count (else a cap-N tool hits its cap after N/2 round-trips).
        key = roles_secrets.generate_master_key()
        with unittest.mock.patch.dict(os.environ, {"ZTN_SECRET_MASTER_KEY": key}):
            roles_secrets.store_secret("notion", "tok", self.base)
            ctx = self._ctx()
            stage.run_tool_request(
                self.cfg, self._req("notion-board", mcp_tool="mcp__notion__query"),
                ctx, self.base)
            self.assertEqual(ctx.call_counts["notion-board"], 1)
            stage.absorb_harness_return(
                self.cfg, "notion-board", {"tasks": [1]}, ctx, self.base, "p1")
            self.assertEqual(ctx.call_counts["notion-board"], 1)  # NOT 2

    def test_ctx_roundtrip(self):
        ctx = stage.ToolStageContext(role_id="r", call_counts={"http-get": 2},
                                     ingested_external=True)
        p = Path(self._tmp.name) / "ctx.json"
        stage.save_ctx(p, ctx)
        back = stage.load_ctx(p, "r")
        self.assertEqual(back.call_counts, {"http-get": 2})
        self.assertTrue(back.ingested_external)


if __name__ == "__main__":
    unittest.main()
