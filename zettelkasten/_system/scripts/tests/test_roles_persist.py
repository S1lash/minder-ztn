"""Tests for roles_persist.py — the composite (parts[]) sole writer.

Drives full role ticks against a tempdir ZTN base (config + archetype plugins
loaded for real): per-part cold-start staging freeze, re-surface-only, approval
adoption, key mint + stable carry across ticks, atomic per-part writes, the
3-consecutive-reject auto-pause (per part), churn / identity holds, schema-version
tolerance, per-part state.md sub-zone splicing with owner-portrait preservation,
and delta routing across a two-part composite role.

`read_records` is ENGINE-INJECTED: the writer overwrites any body value with the
deterministic `minder_query --list` stems of the role's remit. So grounding is
exercised against REAL in-remit record files created on disk (integration-style),
not a hand-passed corpus. No LLM, no network — only the deterministic persist stage.
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

import roles_archetype_ledger as ledger_plugin  # noqa: E402
import roles_persist as x  # noqa: E402

ROLE_ID = "minder-pm"
PART = "workstreams"

CONFIG = """id: minder-pm
name: Minder PM
parts:
  - { id: workstreams, kind: ledger }
cadence: weekly
cadence_anchor: monday
status: active
schema_version: 2
remit:
  globs: ["1_projects/minder/**"]
"""

# A config whose `status` is quoted — parses to active, but `_auto_pause_config`
# cannot flip it (it only rewrites a bare column-0 `status: active`). Proves the
# auto-pause is authoritative from the PART stop even when the config text flip
# is a silent no-op.
QUOTED_CONFIG = CONFIG.replace("status: active", 'status: "active"')

# Two-part composite role (both ledger, independent key namespaces + sub-zones).
COMPOSITE_CONFIG = """id: minder-pm
name: Minder PM
parts:
  - { id: workstreams, kind: ledger }
  - { id: backlog,     kind: ledger }
cadence: weekly
cadence_anchor: monday
status: active
schema_version: 2
remit:
  globs: ["1_projects/minder/**"]
"""


def _add(pk: str, title: str, rec: str, part: str = PART,
         anchor: str = "project:minder") -> dict:
    return {
        "op": "add", "part": part, "provisional_key": pk, "title": title,
        "anchor": anchor, "status": "new", "provenance": [f"[[{rec}]]"],
    }


def _payload(*deltas: dict) -> dict:
    # `read_records` is engine-injected — the body value (if any) is ignored.
    return {"role_id": ROLE_ID, "hook": "tick", "deltas": list(deltas)}


class _Base(unittest.TestCase):
    CONFIG_TEXT = CONFIG

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / "config.yml").write_text(self.CONFIG_TEXT, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @property
    def rdir(self) -> Path:
        return self.base / "_system" / "roles" / ROLE_ID

    def _mkrec(self, *stems: str) -> None:
        """Create real in-remit record files so `minder_query --list` returns them."""
        d = self.base / "1_projects" / "minder"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text("---\ntype: meeting\n---\nbody\n", encoding="utf-8")

    def _part(self, part_id: str = PART) -> dict:
        return json.loads(
            (self.rdir / "parts" / f"{part_id}.json").read_text(encoding="utf-8")
        )

    def _clarifications(self) -> str:
        p = self.base / "_system" / "state" / "CLARIFICATIONS.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def _decisions(self) -> list:
        p = self.rdir / "decisions.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def _run(self, payload, approve=False) -> dict:
        return x.run(ROLE_ID, payload, approve_coldstart=approve, base=self.base)

    def _runs_count(self) -> int:
        p = self.base / "_system" / "state" / "roles-runs.jsonl"
        if not p.exists():
            return 0
        return len([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()])

    def _bootstrap_live(self) -> None:
        """Cold-start one item, then approve → part has lk-0001 live."""
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        self._run(None, approve=True)


class RolesPersistTest(_Base):
    # -- ask is read-only, even the CLI misuse path leaves no run ----------

    def test_ask_payload_via_cli_writes_no_run(self) -> None:
        self._bootstrap_live()
        before = self._runs_count()
        ask_pf = self.base / "ask.json"
        ask_pf.write_text(
            json.dumps({"role_id": ROLE_ID, "hook": "ask", "deltas": []}),
            encoding="utf-8",
        )
        rc = x.main(["--role", ROLE_ID, "--payload", str(ask_pf), "--base", str(self.base)])
        self.assertEqual(rc, 1)
        self.assertEqual(self._runs_count(), before, "ask must not append a run")

    # -- cold-start -------------------------------------------------------

    def test_cold_start_freezes_into_staging(self) -> None:
        self._mkrec("2026-07-01-standup")
        summary = self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        self.assertEqual(summary["outcome"], "cold-start-staged")
        self.assertEqual(summary["run_status"], "ok")
        part = self._part()
        self.assertEqual(part["items"], [])                 # nothing live yet
        self.assertIsInstance(part["staging"], dict)
        self.assertEqual(len(part["staging"]["items"]), 1)
        self.assertEqual(part["staging"]["items"][0]["key"], "lk-0001")
        self.assertIsNone(part["seen_watermark"])            # not advanced pre-approval
        self.assertIn("role-cold-start", self._clarifications())

    def test_cold_start_retick_resurfaces_only(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        part_before = (self.rdir / "parts" / f"{PART}.json").read_bytes()
        self._mkrec("2026-07-02-sync")
        summary = self._run(_payload(_add("p2", "B (new)", "2026-07-02-sync")))
        self.assertEqual(summary["outcome"], "cold-start-resurfaced")
        self.assertEqual(summary["run_status"], "rejected")   # non-progress
        # The part file is byte-for-byte untouched: no addendum, no watermark move.
        self.assertEqual((self.rdir / "parts" / f"{PART}.json").read_bytes(), part_before)
        part = self._part()
        self.assertEqual(part["items"], [])
        self.assertIsNone(part["seen_watermark"])
        self.assertEqual(summary["clarifications"], ["role-cold-start"])
        self.assertEqual(summary["counts"]["clarifications"], 1)

    def test_cold_start_approval_adopts_live(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        summary = self._run(None, approve=True)
        self.assertEqual(summary["outcome"], "cold-start-approved")
        part = self._part()
        self.assertIsNone(part["staging"])
        self.assertEqual(len(part["items"]), 1)
        self.assertEqual(part["items"][0]["key"], "lk-0001")
        self.assertIsNotNone(part["seen_watermark"])          # advanced on approval
        self.assertIsNotNone(part["state_auto_hash"])         # state.md rendered
        state = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("AUTO: role-state/workstreams", state)
        self.assertIn("A", state)

    def test_approve_coldstart_resolves_cold_start_clarification(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        open_part, _, resolved_part = self._clarifications().partition("## Resolved Items")
        self.assertIn("role-cold-start: minder-pm", open_part)
        self.assertNotIn("role-cold-start: minder-pm", resolved_part)

        self._run(None, approve=True)
        open_after, _, resolved_after = self._clarifications().partition("## Resolved Items")
        self.assertNotIn("role-cold-start: minder-pm", open_after)
        self.assertIn("role-cold-start: minder-pm", resolved_after)
        self.assertIn("role-clarif: role-cold-start/minder-pm", resolved_after)
        self.assertIn("**Resolved:** adopted via approve-coldstart", resolved_after)

    def test_resolve_clarification_returns_false_for_missing_item(self) -> None:
        from roles_common import resolve_clarification
        self.assertFalse(
            resolve_clarification("role-cold-start", "minder-pm", "x", base=self.base)
        )
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        self.assertFalse(
            resolve_clarification("role-cold-start", "other-role", "x", base=self.base)
        )
        self.assertTrue(
            resolve_clarification("role-cold-start", "minder-pm", "done", base=self.base)
        )
        self.assertFalse(
            resolve_clarification("role-cold-start", "minder-pm", "done", base=self.base)
        )

    # -- key mint + carry across ticks ------------------------------------

    def test_keys_mint_and_carry_across_ticks(self) -> None:
        self._bootstrap_live()  # lk-0001 live
        self._mkrec("2026-07-02-standup")
        s1 = self._run(_payload(
            {"op": "advance", "part": PART, "key": "lk-0001", "to_status": "active",
             "evidence": ["[[2026-07-02-standup]]"]},
            _add("p2", "B", "2026-07-02-standup"),
        ))
        self.assertEqual(s1["outcome"], "progress")
        keys = {it["key"]: it for it in self._part()["items"]}
        self.assertEqual(set(keys), {"lk-0001", "lk-0002"})
        self.assertEqual(keys["lk-0001"]["status"], "active")

        self._mkrec("2026-07-03-standup")
        self._run(_payload(_add("p3", "C", "2026-07-03-standup")))
        keys2 = {it["key"] for it in self._part()["items"]}
        self.assertEqual(keys2, {"lk-0001", "lk-0002", "lk-0003"})

    def test_part_written_atomically(self) -> None:
        self._bootstrap_live()
        self.assertFalse((self.rdir / "parts" / f"{PART}.json.tmp").exists())
        self.assertIsInstance(self._part(), dict)

    # -- 3-reject auto-pause (per part) -----------------------------------

    def test_three_rejects_auto_pause(self) -> None:
        self._bootstrap_live()
        # An ungrounded add (its cited record never created) is a no-progress reject.
        reject = _payload({
            "op": "add", "part": PART, "provisional_key": "pz", "title": "Z",
            "anchor": "project:minder", "status": "new",
            "provenance": ["[[nonexistent-record]]"],
        })
        s1 = self._run(reject)
        self.assertEqual(s1["run_status"], "rejected")
        self.assertEqual(s1["consecutive_rejects"], 1)
        self.assertEqual(s1["parts"][PART]["consecutive_rejects"], 1)
        s2 = self._run(reject)
        self.assertEqual(s2["consecutive_rejects"], 2)
        s3 = self._run(reject)
        self.assertEqual(s3["outcome"], "paused")
        self.assertEqual(s3["run_status"], "paused")
        self.assertEqual(s3["consecutive_rejects"], 3)
        config = (self.rdir / "config.yml").read_text(encoding="utf-8")
        self.assertIn("status: paused", config)
        self.assertIn("role-auto-paused", self._clarifications())

    def test_reject_counter_resets_on_progress(self) -> None:
        self._bootstrap_live()
        reject = _payload({
            "op": "add", "part": PART, "provisional_key": "pz", "title": "Z",
            "anchor": "project:minder", "provenance": ["[[missing]]"],
        })
        self._run(reject)
        self.assertEqual(self._part()["consecutive_rejects"], 1)
        self._mkrec("2026-07-05-ok")
        self._run(_payload(_add("pg", "Good", "2026-07-05-ok")))
        self.assertEqual(self._part()["consecutive_rejects"], 0)

    def test_auto_pause_authoritative_when_config_flip_noops(self) -> None:
        (self.rdir / "config.yml").write_text(QUOTED_CONFIG, encoding="utf-8")
        self._bootstrap_live()  # lk-0001 live
        reject = _payload({
            "op": "add", "part": PART, "provisional_key": "pz", "title": "Z",
            "anchor": "project:minder", "status": "new",
            "provenance": ["[[nonexistent-record]]"],
        })
        self._run(reject)
        self._run(reject)
        s3 = self._run(reject)
        self.assertEqual(s3["outcome"], "paused")

        config = (self.rdir / "config.yml").read_text(encoding="utf-8")
        self.assertIn('status: "active"', config)          # quoted flip was a no-op
        self.assertNotIn("status: paused", config)
        # ...but the authoritative PART stop WAS written — the pause is real.
        part = self._part()
        self.assertEqual(part["status"], "paused")
        self.assertIn("paused_reason", part)
        self.assertIn("role-auto-paused", self._clarifications())

        # Next progress tick must NOT re-run validate: the part stop short-circuits
        # to paused-role, nothing persisted.
        self._mkrec("2026-07-05-ok")
        items_before = self._part()["items"]
        s4 = self._run(_payload(_add("pg", "Good", "2026-07-05-ok")))
        self.assertEqual(s4["outcome"], "paused-role")
        self.assertEqual(s4["run_status"], "paused")
        self.assertEqual(self._part()["items"], items_before)

    def test_split_records_all_child_keys_in_decisions(self) -> None:
        self._bootstrap_live()  # lk-0001 live
        self._mkrec("2026-07-07-add")
        self._run(_payload(_add("p2", "B", "2026-07-07-add")))  # lk-0002
        self._mkrec("2026-07-08-split")
        summary = self._run(_payload({
            "op": "split", "part": PART, "key": "lk-0001",
            "into": [{"title": "X1"}, {"title": "X2"}],
            "evidence": ["[[2026-07-08-split]]"],
        }))
        self.assertEqual(summary["outcome"], "progress")

        keys = {it["key"]: it for it in self._part()["items"]}
        self.assertEqual(keys["lk-0001"]["status"], "merged")
        self.assertIn("lk-0003", keys)
        self.assertIn("lk-0004", keys)

        split_rows = [d for d in self._decisions() if d.get("kind") == "split"]
        self.assertEqual(len(split_rows), 1)
        row = split_rows[0]
        self.assertEqual(row["key"], "lk-0001")
        self.assertEqual(row["part"], PART)                 # decision rows carry part
        self.assertEqual(row["into_keys"], ["lk-0003", "lk-0004"])
        self.assertEqual(keys["lk-0001"]["superseded_by"], "lk-0003")

    # -- state.md owner-zone preservation ---------------------------------

    def test_owner_portrait_preserved_across_auto_rewrite(self) -> None:
        self._bootstrap_live()
        state_path = self.rdir / "state.md"
        sentinel = "OWNER SENTINEL PROSE 12345"
        text = state_path.read_text(encoding="utf-8")
        marker = "<!-- AUTO: role-state/workstreams"
        idx = text.find(marker)
        self.assertGreater(idx, 0)
        state_path.write_text(text[:idx] + sentinel + "\n\n" + text[idx:], encoding="utf-8")

        self._mkrec("2026-07-06-standup")
        self._run(_payload(_add("p2", "B", "2026-07-06-standup")))
        after = state_path.read_text(encoding="utf-8")
        self.assertIn(sentinel, after)   # owner zone preserved
        self.assertIn("B", after)        # auto zone updated with the new item

    # -- cold-start gate ordering + watermark semantics (§11.7) -----------

    def test_paused_role_with_pending_staging_writes_nothing(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        part_before = (self.rdir / "parts" / f"{PART}.json").read_bytes()
        (self.rdir / "config.yml").write_text(
            self.CONFIG_TEXT.replace("status: active", "status: paused"), encoding="utf-8"
        )
        self._mkrec("2026-07-02-sync")
        summary = self._run(_payload(_add("p2", "B", "2026-07-02-sync")))
        self.assertEqual(summary["outcome"], "paused-role")
        self.assertEqual(summary["run_status"], "paused")
        self.assertEqual((self.rdir / "parts" / f"{PART}.json").read_bytes(), part_before)

    def test_approval_watermark_is_adopted_provenance_only(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("p1", "A", "2026-07-01-standup")))
        self._mkrec("2026-07-05-sync")
        self._run(_payload(_add("p2", "B", "2026-07-05-sync")))   # re-surface only
        self._run(None, approve=True)
        part = self._part()
        self.assertEqual(part["seen_watermark"], "2026-07-01-standup")
        self.assertEqual({it["key"] for it in part["items"]}, {"lk-0001"})

        # The un-adopted 2026-07-05 record is still un-seen, so the first post-
        # approval tick proposes it as a normal grounded add → lk-0002.
        s = self._run(_payload(_add("p2", "B", "2026-07-05-sync")))
        self.assertEqual(s["outcome"], "progress")
        part2 = self._part()
        self.assertEqual({it["key"] for it in part2["items"]}, {"lk-0001", "lk-0002"})
        self.assertEqual(part2["seen_watermark"], "2026-07-05-sync")

    def test_fresh_part_state_sources_churn_threshold_from_plugin(self) -> None:
        fresh = x._fresh_part_state(ROLE_ID, PART, "ledger")
        self.assertEqual(fresh["churn_threshold"], ledger_plugin.DEFAULT_CHURN_THRESHOLD)
        self.assertEqual(fresh["identity_strictness"], ledger_plugin.DEFAULT_IDENTITY_STRICTNESS)
        self.assertEqual(fresh["churn_threshold"], ledger_plugin.fresh_state()["churn_threshold"])
        self.assertEqual(fresh["role_id"], ROLE_ID)
        self.assertEqual(fresh["part_id"], PART)
        self.assertEqual(fresh["archetype"], "ledger")
        self.assertEqual(fresh["description"], x._PART_DESCRIPTION)

    def test_repeat_churn_hold_counts_pending_clarification(self) -> None:
        self._bootstrap_live()  # lk-0001 live
        self._mkrec("2026-07-09-sweep")
        churn = _payload({
            "op": "advance", "part": PART, "key": "lk-0001", "to_status": "archived",
            "archive_reason": "done", "evidence": ["[[2026-07-09-sweep]]"],
        })
        s1 = self._run(churn)
        self.assertEqual(s1["run_status"], "rejected")
        self.assertEqual(s1["clarifications"], ["role-churn-guard"])
        self.assertEqual(s1["counts"]["clarifications"], 1)
        s2 = self._run(churn)
        self.assertEqual(s2["run_status"], "rejected")
        self.assertEqual(s2["counts"]["clarifications"], 1)   # deduped but still pending
        self.assertEqual(self._part()["consecutive_rejects"], 0)   # hold is not a failure

    # -- schema-version tolerance (migrate-before-validate; §6 / B1) --------

    def _set_part_version(self, v, part_id: str = PART) -> None:
        p = self.rdir / "parts" / f"{part_id}.json"
        state = json.loads(p.read_text(encoding="utf-8"))
        state["version"] = v
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_future_version_part_is_refused(self) -> None:
        self._bootstrap_live()  # lk-0001 live, version 1
        self._set_part_version(ledger_plugin.LEDGER_VERSION + 1)
        before = (self.rdir / "parts" / f"{PART}.json").read_bytes()
        self._mkrec("2026-07-10-x")
        summary = self._run(_payload(_add("p2", "B", "2026-07-10-x")))
        self.assertEqual(summary["outcome"], "schema-version-future")
        self.assertEqual(summary["run_status"], "error")
        self.assertEqual(summary["clarifications"], ["role-schema-version"])
        self.assertIn("role-schema-version", self._clarifications())
        self.assertEqual((self.rdir / "parts" / f"{PART}.json").read_bytes(), before)

    def test_past_version_part_degrades_with_empty_migration_table(self) -> None:
        self.assertEqual(x.MIGRATIONS, {})
        self._bootstrap_live()
        self._set_part_version(ledger_plugin.LEDGER_VERSION - 1)
        self._mkrec("2026-07-10-ok")
        summary = self._run(_payload(_add("p2", "B", "2026-07-10-ok")))
        self.assertEqual(summary["outcome"], "progress")
        self.assertIn("role-schema-version", self._clarifications())
        self.assertEqual(
            {it["key"] for it in self._part()["items"]}, {"lk-0001", "lk-0002"}
        )

    def test_past_version_part_migrates_when_path_registered(self) -> None:
        self._bootstrap_live()
        self._set_part_version(ledger_plugin.LEDGER_VERSION - 1)
        orig = x.MIGRATIONS
        x.MIGRATIONS = {
            (ledger_plugin.LEDGER_VERSION - 1, ledger_plugin.LEDGER_VERSION): lambda s: s
        }
        self.addCleanup(setattr, x, "MIGRATIONS", orig)
        self._mkrec("2026-07-10-ok")
        summary = self._run(_payload(_add("p2", "B", "2026-07-10-ok")))
        self.assertEqual(summary["outcome"], "progress")
        self.assertNotIn("role-schema-version", self._clarifications())
        self.assertEqual(self._part()["version"], ledger_plugin.LEDGER_VERSION)

    def test_migrate_part_is_pure_and_returns_none_without_path(self) -> None:
        state = {"version": 0, "items": [{"key": "lk-0001"}]}
        self.assertIsNone(x.migrate_part(state, 0, 1))
        self.assertEqual(state["version"], 0)
        self.assertIs(x.migrate_part(state, 1, 1), state)

    def test_supersede_logged_under_its_own_kind(self) -> None:
        self._bootstrap_live()  # lk-0001 live
        self._mkrec("2026-07-07-add")
        self._run(_payload(_add("p2", "B", "2026-07-07-add")))  # lk-0002
        self._mkrec("2026-07-08-sup")
        summary = self._run(_payload({
            "op": "supersede", "part": PART, "key": "lk-0001", "by": "lk-0002",
            "evidence": ["[[2026-07-08-sup]]"],
        }))
        self.assertEqual(summary["outcome"], "progress")
        sup_rows = [d for d in self._decisions() if d.get("kind") == "supersede"]
        self.assertEqual(len(sup_rows), 1)
        self.assertEqual(sup_rows[0]["key"], "lk-0001")
        self.assertEqual(sup_rows[0]["by"], "lk-0002")
        self.assertEqual([d for d in self._decisions() if d.get("kind") == "merge"], [])
        keys = {it["key"]: it for it in self._part()["items"]}
        self.assertEqual(keys["lk-0001"]["superseded_by"], "lk-0002")

    # -- unroutable deltas -------------------------------------------------

    def test_unroutable_delta_rejected_not_guessed(self) -> None:
        self._bootstrap_live()
        self._mkrec("2026-07-11-x")
        # A delta addressing a part not in the config is unroutable → rejected,
        # never guessed into an existing part.
        summary = self._run(_payload(_add("pz", "Z", "2026-07-11-x", part="ghost")))
        self.assertGreaterEqual(summary["counts"]["rejected"], 1)
        # The workstreams part stays untouched (no phantom add).
        self.assertEqual({it["key"] for it in self._part()["items"]}, {"lk-0001"})


class RolesCompositeTest(_Base):
    """Two ledger parts in one role — routing, per-part files, per-part sub-zones,
    independent key namespaces."""
    CONFIG_TEXT = COMPOSITE_CONFIG

    def _bootstrap_both(self) -> None:
        self._mkrec("2026-07-01-standup")
        self._run(_payload(
            _add("w1", "WS one", "2026-07-01-standup", part="workstreams"),
            _add("b1", "BL one", "2026-07-01-standup", part="backlog"),
        ))
        self._run(None, approve=True)

    def test_cold_start_stages_every_part_and_one_clarification(self) -> None:
        self._mkrec("2026-07-01-standup")
        summary = self._run(_payload(
            _add("w1", "WS one", "2026-07-01-standup", part="workstreams"),
            _add("b1", "BL one", "2026-07-01-standup", part="backlog"),
        ))
        self.assertEqual(summary["outcome"], "cold-start-staged")
        # Both parts frozen into their OWN staging file.
        self.assertEqual(len(self._part("workstreams")["staging"]["items"]), 1)
        self.assertEqual(len(self._part("backlog")["staging"]["items"]), 1)
        # A single aggregated role-cold-start clarification.
        self.assertEqual(self._clarifications().count("role-cold-start: minder-pm"), 1)

    def test_approval_adopts_both_parts_with_own_zones(self) -> None:
        self._bootstrap_both()
        self.assertEqual(len(self._part("workstreams")["items"]), 1)
        self.assertEqual(len(self._part("backlog")["items"]), 1)
        # Independent key namespaces: each part's first item is lk-0001.
        self.assertEqual(self._part("workstreams")["items"][0]["key"], "lk-0001")
        self.assertEqual(self._part("backlog")["items"][0]["key"], "lk-0001")
        state = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("AUTO: role-state/workstreams", state)
        self.assertIn("AUTO: role-state/backlog", state)
        # Sub-zone order matches config.parts[] order.
        self.assertLess(
            state.index("role-state/workstreams"), state.index("role-state/backlog")
        )

    def test_routing_keeps_parts_independent(self) -> None:
        self._bootstrap_both()
        self._mkrec("2026-07-02-sync")
        # Add to workstreams only; backlog receives no delta this tick.
        summary = self._run(_payload(
            _add("w2", "WS two", "2026-07-02-sync", part="workstreams"),
        ))
        self.assertEqual(summary["outcome"], "progress")
        ws_keys = {it["key"] for it in self._part("workstreams")["items"]}
        bl_keys = {it["key"] for it in self._part("backlog")["items"]}
        self.assertEqual(ws_keys, {"lk-0001", "lk-0002"})   # new item minted here
        self.assertEqual(bl_keys, {"lk-0001"})              # backlog untouched

    def test_staggered_cold_start_inserts_second_zone_in_order(self) -> None:
        # workstreams cold-starts + approves first (state.md gets its zone only);
        # backlog acquires content LATER and its zone must be inserted in config
        # order (after workstreams), exercising the insert path.
        self._mkrec("2026-07-01-standup")
        self._run(_payload(_add("w1", "WS one", "2026-07-01-standup", part="workstreams")))
        self._run(None, approve=True)
        state1 = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("AUTO: role-state/workstreams", state1)
        self.assertNotIn("AUTO: role-state/backlog", state1)   # backlog still fresh

        self._mkrec("2026-07-08-bl")
        self._run(_payload(_add("b1", "BL one", "2026-07-08-bl", part="backlog")))
        self._run(None, approve=True)
        state2 = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("AUTO: role-state/backlog", state2)       # inserted
        self.assertLess(
            state2.index("role-state/workstreams"), state2.index("role-state/backlog")
        )
        self.assertEqual(self._part("backlog")["items"][0]["key"], "lk-0001")
        # workstreams zone survived the backlog insertion.
        self.assertIn("WS one", state2)

    def test_per_part_zone_edit_does_not_block_sibling(self) -> None:
        self._bootstrap_both()
        state_path = self.rdir / "state.md"
        text = state_path.read_text(encoding="utf-8")
        # Owner hand-edits the BACKLOG sub-zone inner content.
        bl_marker = "<!-- AUTO: role-state/backlog"
        bi = text.find(bl_marker)
        line_end = text.find("\n", bi)
        edited = text[:line_end + 1] + "OWNER TAMPER 999\n" + text[line_end + 1:]
        state_path.write_text(edited, encoding="utf-8")

        # A tick that progresses workstreams must splice its zone but preserve the
        # hand-edited backlog zone (its per-part hash guard fires independently).
        self._mkrec("2026-07-02-sync")
        summary = self._run(_payload(
            _add("w2", "WS two", "2026-07-02-sync", part="workstreams"),
        ))
        self.assertEqual(summary["parts"]["backlog"]["state_flag"], "auto-zone-edited")
        after = state_path.read_text(encoding="utf-8")
        self.assertIn("OWNER TAMPER 999", after)   # sibling edit preserved
        self.assertIn("WS two", after)             # workstreams still updated


if __name__ == "__main__":
    unittest.main()
