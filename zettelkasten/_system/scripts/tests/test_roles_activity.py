"""Tests for the plain-language role-activity digest (FIX-SHIP-2 §2)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_activity as ra  # noqa: E402


def _cfg(tmp: Path, rid: str = "minder-pm", name: str = "Minder PM"):
    d = tmp / "_system" / "roles" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(
        f"id: {rid}\nname: \"{name}\"\nparts: [{{id: p1, kind: ledger}}]\n"
        "remit: {all: true}\ncadence: daily\nstatus: active\n", encoding="utf-8")
    return d


def _write(tmp: Path, rel: str, lines: list[dict]):
    p = tmp / "_system" / "state" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


class ActivityTest(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        _cfg(self.tmp)
        self.today = date(2026, 7, 19)

    def test_empty_role_is_quiet(self):
        act = ra.collect_activity("minder-pm", self.tmp, today=self.today)
        self.assertEqual(act.runs_total, 0)
        self.assertIn("watching quietly", ra.render_plain(act))

    def test_reads_acts_and_needs_are_plain(self):
        _write(self.tmp, "roles-runs.jsonl", [
            {"role_id": "minder-pm", "run_at": "2026-07-18T10:00:00Z", "status": "ok"},
            {"role_id": "minder-pm", "run_at": "2026-07-17T10:00:00Z", "status": "empty"},
            {"role_id": "other", "run_at": "2026-07-18T10:00:00Z", "status": "ok"},  # not ours
        ])
        _write(self.tmp, "roles-tool-audit.jsonl", [
            {"at": "2026-07-18T10:00:00Z", "role_id": "minder-pm", "tool_id": "github-read"},
            {"at": "2026-07-18T10:00:00Z", "role_id": "minder-pm", "tool_id": "github-read"},
            {"at": "2026-07-18T10:01:00Z", "role_id": "minder-pm", "kind": "act",
             "op": "close", "status": "executed", "summary": "closed #1 (shipped)"},
            {"at": "2026-07-18T10:01:00Z", "role_id": "minder-pm", "kind": "act",
             "op": "create", "status": "skipped", "summary": "already there"},
        ])
        # a staged pending set + an open act-confirm clarification
        (self.tmp / "_system" / "roles" / "minder-pm" / "pending_acts.json").write_text(
            json.dumps({"acts": [{"op": "close"}, {"op": "create"}]}), encoding="utf-8")
        clar = self.tmp / "_system" / "state" / "CLARIFICATIONS.md"
        clar.write_text("# Clar\n\n<!-- role-clarif: role-act-confirm/minder-pm · 2 act(s) -->\n",
                        encoding="utf-8")

        act = ra.collect_activity("minder-pm", self.tmp, today=self.today)
        self.assertEqual(act.runs_total, 2)                 # our two, not «other»
        self.assertEqual(act.tool_reads.get("github-read"), 2)
        self.assertEqual(len(act.acts_executed), 1)
        self.assertEqual(act.acts_skipped, 1)
        self.assertEqual(act.staged_now, 2)
        text = ra.render_plain(act)
        self.assertIn("Minder PM", text)
        self.assertIn("read from github read (2)", text)  # tool-id de-jargoned (hyphen→space)
        self.assertIn("closed #1 (shipped)", text)         # plain, from the audit
        self.assertIn("--approve-acts minder-pm", text)    # actionable next step
        self.assertNotIn("role_id", text)                  # no engineer jargon

    def test_window_excludes_old_activity(self):
        _write(self.tmp, "roles-runs.jsonl", [
            {"role_id": "minder-pm", "run_at": "2026-06-01T10:00:00Z", "status": "ok"},  # >7d
        ])
        act = ra.collect_activity("minder-pm", self.tmp, days=7, today=self.today)
        self.assertEqual(act.runs_total, 0)

    def test_digest_across_roles(self):
        _cfg(self.tmp, "coach", "Coach")
        out = ra.render_digest(["minder-pm", "coach"], self.tmp, today=self.today)
        self.assertIn("What your roles did", out)
        self.assertIn("Minder PM", out)
        self.assertIn("Coach", out)

    def test_secret_never_in_audit_render(self):
        # audit rows never carry a secret; the render can't invent one.
        _write(self.tmp, "roles-tool-audit.jsonl", [
            {"at": "2026-07-18T10:00:00Z", "role_id": "minder-pm", "kind": "act",
             "op": "close", "status": "executed", "summary": "closed #1"}])
        text = ra.render_plain(ra.collect_activity("minder-pm", self.tmp, today=self.today))
        self.assertNotIn("Bearer", text)
        self.assertNotIn("secret", text.lower())


if __name__ == "__main__":
    unittest.main()
