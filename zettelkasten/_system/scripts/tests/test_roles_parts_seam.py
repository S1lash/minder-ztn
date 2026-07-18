"""Seam proof for the composite (parts[]) Roles model — BUILD-CONTRACT v2 §1-§7.

This module proves the six load-bearing claims of the parts[] seam end-to-end,
driving real `roles_persist.run` ticks against a tempdir ZTN base (config +
`roles_archetype_ledger` loaded for real, grounding checked against real in-remit
record files):

  1. Two parts keep independent, part-scoped `lk-NNNN` key namespaces — the same
     key string may appear in both parts (addressed by `part_id`), and each part's
     own sequence stays monotonic and never re-mints a RETIRED key, with a
     retirement in one part leaving the other's numbering untouched (collision-free
     ACROSS parts).
  2. A delta routed to one part does not touch its sibling — the sibling's state
     file bytes, its per-part `state_auto_hash`, and its `decisions.jsonl` rows are
     all unchanged.
  3. Per-part state lives in one file per part under `parts/`, with NO monolithic
     v1 `ledger.json` (no-cruft: the single-file path is removed, not layered over).
  4. `state.md` carries exactly one AUTO sub-zone per part, the owner portrait above
     the zones survives an auto-rewrite, and the per-part tamper flag scopes to the
     single edited part (proved symmetrically — tampering the FIRST part flags only
     it while a sibling tick still splices).
  5. A single-part role behaves byte-for-byte like the one populated part of a
     two-part composite (equivalence — the composite adds no per-part overhead to a
     part that receives the identical delta stream).
  6. A v1 scalar `archetype:` config is REJECTED fail-closed at the runner boundary
     (no silent back-compat), with a rebuild pointer naming `parts`.

Deterministic: no LLM, no network — only the persist stage + the record-grounding
oracle over files on disk.
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
import roles_common as rc  # noqa: E402
import roles_persist as x  # noqa: E402

ROLE_ID = "minder-pm"

SINGLE_CONFIG = """id: minder-pm
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

SCALAR_V1_CONFIG = """id: minder-pm
name: Minder PM
archetype: ledger
cadence: weekly
cadence_anchor: monday
status: active
remit:
  globs: ["1_projects/minder/**"]
"""


def _add(pk: str, title: str, rec: str, part: str,
         anchor: str = "project:minder") -> dict:
    return {
        "op": "add", "part": part, "provisional_key": pk, "title": title,
        "anchor": anchor, "status": "new", "provenance": [f"[[{rec}]]"],
    }


def _payload(*deltas: dict) -> dict:
    # `read_records` is engine-injected — any body value is overwritten.
    return {"role_id": ROLE_ID, "hook": "tick", "deltas": list(deltas)}


class _SeamBase(unittest.TestCase):
    """A tempdir ZTN base with one role dir; helpers to tick and inspect it."""

    CONFIG_TEXT = COMPOSITE_CONFIG

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.rdir.mkdir(parents=True, exist_ok=True)
        (self.rdir / "config.yml").write_text(self.CONFIG_TEXT, encoding="utf-8")

    @property
    def rdir(self) -> Path:
        return self.base / "_system" / "roles" / ROLE_ID

    def _mkrec(self, *stems: str) -> None:
        d = self.base / "1_projects" / "minder"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text(
                "---\ntype: meeting\n---\nbody\n", encoding="utf-8"
            )

    def _run(self, payload, approve: bool = False) -> dict:
        return x.run(ROLE_ID, payload, approve_coldstart=approve, base=self.base)

    def _part(self, part_id: str) -> dict:
        return json.loads(
            (self.rdir / "parts" / f"{part_id}.json").read_text(encoding="utf-8")
        )

    def _keys(self, part_id: str) -> dict:
        return {it["key"]: it for it in self._part(part_id)["items"]}

    def _decisions(self) -> list:
        p = self.rdir / "decisions.jsonl"
        if not p.exists():
            return []
        return [
            json.loads(l)
            for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]

    def _state_md(self) -> str:
        return (self.rdir / "state.md").read_text(encoding="utf-8")

    def _bootstrap_both(self) -> None:
        """Cold-start one item into each of workstreams + backlog, then approve."""
        self._mkrec("2026-07-01-standup")
        self._run(_payload(
            _add("w1", "WS one", "2026-07-01-standup", part="workstreams"),
            _add("b1", "BL one", "2026-07-01-standup", part="backlog"),
        ))
        self._run(None, approve=True)


class CrossPartKeyNamespaceTest(_SeamBase):
    """Item 1 — part-scoped key namespaces, collision-free across parts at depth."""

    def test_namespaces_independent_and_retirement_does_not_reuse_or_bleed(self) -> None:
        self._bootstrap_both()  # ws lk-0001, bl lk-0001
        self.assertEqual(self._part("workstreams")["items"][0]["key"], "lk-0001")
        self.assertEqual(self._part("backlog")["items"][0]["key"], "lk-0001")

        # Deepen both namespaces on the same tick — each mints in its OWN space.
        self._mkrec("2026-07-08-sync")
        self._run(_payload(
            _add("w2", "WS two", "2026-07-08-sync", part="workstreams"),
            _add("b2", "BL two", "2026-07-08-sync", part="backlog"),
        ))
        self._mkrec("2026-07-15-sync")
        self._run(_payload(_add("w3", "WS three", "2026-07-15-sync", part="workstreams")))
        self.assertEqual(set(self._keys("workstreams")), {"lk-0001", "lk-0002", "lk-0003"})
        self.assertEqual(set(self._keys("backlog")), {"lk-0001", "lk-0002"})

        # The SAME key string lives in both parts but refers to DIFFERENT items —
        # proving the key is part-scoped (addressed by part_id), not global.
        self.assertNotEqual(
            self._keys("workstreams")["lk-0002"]["title"],
            self._keys("backlog")["lk-0002"]["title"],
        )

        # Retire workstreams lk-0001 (superseded by the live lk-0002).
        self._mkrec("2026-07-22-sup")
        s = self._run(_payload({
            "op": "supersede", "part": "workstreams", "key": "lk-0001",
            "by": "lk-0002", "evidence": ["[[2026-07-22-sup]]"],
        }))
        self.assertEqual(s["outcome"], "progress")
        self.assertEqual(self._keys("workstreams")["lk-0001"]["superseded_by"], "lk-0002")

        # A fresh add in workstreams must SEED PAST the retired lk-0001 → lk-0004,
        # never re-mint a retired number (known_key_numbers scans superseded_by).
        self._mkrec("2026-07-29-add")
        self._run(_payload(_add("w4", "WS four", "2026-07-29-add", part="workstreams")))
        self.assertEqual(
            set(self._keys("workstreams")), {"lk-0001", "lk-0002", "lk-0003", "lk-0004"}
        )
        # The workstreams retirement left backlog's numbering completely untouched.
        self.assertEqual(set(self._keys("backlog")), {"lk-0001", "lk-0002"})


class RoutingIsolationTest(_SeamBase):
    """Item 2 — a delta to one part leaves the sibling's file, hash + decisions alone."""

    def test_sibling_bytes_hash_and_decisions_untouched(self) -> None:
        self._bootstrap_both()
        backlog_path = self.rdir / "parts" / "backlog.json"
        bytes_before = backlog_path.read_bytes()
        hash_before = self._part("backlog")["state_auto_hash"]
        bl_decisions_before = [d for d in self._decisions() if d.get("part") == "backlog"]

        self._mkrec("2026-07-08-sync")
        summary = self._run(_payload(
            _add("w2", "WS two", "2026-07-08-sync", part="workstreams"),
        ))
        self.assertEqual(summary["outcome"], "progress")

        # Sibling untouched three ways: bytes, per-part hash, and audit rows.
        self.assertEqual(backlog_path.read_bytes(), bytes_before)
        self.assertEqual(self._part("backlog")["state_auto_hash"], hash_before)
        bl_decisions_after = [d for d in self._decisions() if d.get("part") == "backlog"]
        self.assertEqual(bl_decisions_after, bl_decisions_before)
        # ...while the addressed part did advance (a real routing, not a no-op).
        self.assertEqual(set(self._keys("workstreams")), {"lk-0001", "lk-0002"})
        self.assertTrue(
            any(d.get("part") == "workstreams" for d in self._decisions())
        )


class PerPartFileLayoutTest(_SeamBase):
    """Item 3 — per-part files under parts/; no monolithic v1 ledger.json."""

    def test_one_json_per_part_and_no_single_file_rudiment(self) -> None:
        self._bootstrap_both()
        parts_dir = self.rdir / "parts"
        self.assertTrue((parts_dir / "workstreams.json").is_file())
        self.assertTrue((parts_dir / "backlog.json").is_file())
        # No-cruft: the v1 single-file ledger.json path is REMOVED, not layered over.
        self.assertFalse((self.rdir / "ledger.json").exists())
        self.assertFalse((parts_dir / "ledger.json").exists())
        # parts/ holds exactly the two per-part state files (plus no stray .tmp).
        jsons = sorted(p.name for p in parts_dir.glob("*.json"))
        self.assertEqual(jsons, ["backlog.json", "workstreams.json"])
        self.assertEqual(list(parts_dir.glob("*.tmp")), [])


class StateMdZoningTest(_SeamBase):
    """Item 4 — one AUTO sub-zone per part, portrait preserved, per-part tamper scope."""

    def test_one_zone_per_part_and_owner_portrait_survives_rewrite(self) -> None:
        self._bootstrap_both()
        text = self._state_md()
        # Exactly one START marker per part (END markers read `<!-- END AUTO:`).
        self.assertEqual(text.count("<!-- AUTO: role-state/"), 2)
        self.assertIn("<!-- AUTO: role-state/workstreams", text)
        self.assertIn("<!-- AUTO: role-state/backlog", text)

        # Insert an owner portrait above the first zone, then progress a part.
        sentinel = "OWNER PORTRAIT PROSE 4242"
        idx = text.find("<!-- AUTO: role-state/")
        (self.rdir / "state.md").write_text(
            text[:idx] + sentinel + "\n\n" + text[idx:], encoding="utf-8"
        )
        self._mkrec("2026-07-08-sync")
        self._run(_payload(_add("w2", "WS two", "2026-07-08-sync", part="workstreams")))
        after = self._state_md()
        self.assertIn(sentinel, after)                       # portrait preserved
        self.assertIn("WS two", after)                        # auto zone updated
        self.assertEqual(after.count("<!-- AUTO: role-state/"), 2)  # still two zones

    def test_tamper_on_first_part_scopes_flag_and_sibling_still_splices(self) -> None:
        # Symmetric to the persist-suite case (which tampers the SECOND part): here
        # the FIRST part is edited and a SECOND-part tick runs, proving the guard is
        # keyed on part id, not on zone position.
        self._bootstrap_both()
        text = self._state_md()
        ws_marker = "<!-- AUTO: role-state/workstreams"
        wi = text.find(ws_marker)
        line_end = text.find("\n", wi)
        tampered = text[:line_end + 1] + "OWNER TAMPER FIRST 777\n" + text[line_end + 1:]
        (self.rdir / "state.md").write_text(tampered, encoding="utf-8")

        self._mkrec("2026-07-08-sync")
        summary = self._run(_payload(
            _add("b2", "BL two", "2026-07-08-sync", part="backlog"),
        ))
        self.assertEqual(summary["outcome"], "progress")
        self.assertEqual(
            summary["parts"]["workstreams"]["state_flag"], "auto-zone-edited"
        )
        self.assertNotEqual(
            summary["parts"]["backlog"].get("state_flag"), "auto-zone-edited"
        )
        after = self._state_md()
        self.assertIn("OWNER TAMPER FIRST 777", after)   # edited part preserved
        self.assertIn("BL two", after)                    # sibling zone spliced


class SinglePartEquivalenceTest(unittest.TestCase):
    """Item 5 — a single-part role == the one populated part of a composite."""

    def _make_base(self, config_text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / ROLE_ID
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "config.yml").write_text(config_text, encoding="utf-8")
        return base

    @staticmethod
    def _mkrec(base: Path, *stems: str) -> None:
        d = base / "1_projects" / "minder"
        d.mkdir(parents=True, exist_ok=True)
        for s in stems:
            (d / f"{s}.md").write_text(
                "---\ntype: meeting\n---\nbody\n", encoding="utf-8"
            )

    def _drive_workstreams(self, base: Path) -> None:
        """Identical delta stream on the workstreams part: cold-start → approve → add.

        In the composite base, backlog receives NO delta on any tick, so it never
        stages — leaving workstreams as the sole populated part.
        """
        self._mkrec(base, "2026-07-01-standup")
        x.run(ROLE_ID, _payload(
            _add("w1", "WS one", "2026-07-01-standup", part="workstreams")
        ), base=base)
        x.run(ROLE_ID, None, approve_coldstart=True, base=base)
        self._mkrec(base, "2026-07-08-sync")
        x.run(ROLE_ID, _payload(
            _add("w2", "WS two", "2026-07-08-sync", part="workstreams")
        ), base=base)

    def test_single_part_matches_populated_part_of_composite(self) -> None:
        single_base = self._make_base(SINGLE_CONFIG)
        composite_base = self._make_base(COMPOSITE_CONFIG)
        self._drive_workstreams(single_base)
        self._drive_workstreams(composite_base)

        def ws_state(base: Path) -> dict:
            return json.loads(
                (base / "_system" / "roles" / ROLE_ID / "parts" / "workstreams.json")
                .read_text(encoding="utf-8")
            )

        single_ws = ws_state(single_base)
        composite_ws = ws_state(composite_base)

        # The part's whole persisted state is identical — same role_id, part_id,
        # archetype, items, keys, watermark, hash. The presence of a second part in
        # the composite adds ZERO overhead to a part fed the identical stream.
        self.assertEqual(single_ws, composite_ws)
        self.assertEqual(
            {it["key"] for it in single_ws["items"]}, {"lk-0001", "lk-0002"}
        )
        self.assertIsNotNone(single_ws["state_auto_hash"])

        # The rendered workstreams sub-zone is byte-identical between the two roles.
        def ws_zone(base: Path) -> str | None:
            sm = (base / "_system" / "roles" / ROLE_ID / "state.md").read_text(
                encoding="utf-8"
            )
            return role_state_hash.extract_part_zone(sm, "workstreams")

        self.assertIsNotNone(ws_zone(single_base))
        self.assertEqual(ws_zone(single_base), ws_zone(composite_base))
        # And the composite's state.md carries the single populated zone only —
        # backlog never staged, so no phantom sub-zone appears.
        composite_sm = (
            composite_base / "_system" / "roles" / ROLE_ID / "state.md"
        ).read_text(encoding="utf-8")
        self.assertIn("<!-- AUTO: role-state/workstreams", composite_sm)
        self.assertNotIn("<!-- AUTO: role-state/backlog", composite_sm)


class ScalarV1RejectionTest(unittest.TestCase):
    """Item 6 — a v1 scalar `archetype:` config is fail-closed at the runner."""

    def _write_scalar_role(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / ROLE_ID
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "config.yml").write_text(SCALAR_V1_CONFIG, encoding="utf-8")
        return base

    def test_runner_refuses_scalar_config_with_rebuild_pointer(self) -> None:
        base = self._write_scalar_role()
        # The runner loads config at the top of the tick and does NOT catch the
        # error — a v1 scalar config fails the WHOLE tick closed (no silent
        # coercion into a one-part composite).
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.run(ROLE_ID, _payload(), base=base)
        msg = str(ctx.exception)
        self.assertIn("scalar", msg)
        self.assertIn("parts", msg)   # the rebuild pointer names the replacement
        # No part state was ever written — the role never came alive.
        self.assertFalse((base / "_system" / "roles" / ROLE_ID / "parts").exists())

    def test_loader_and_runner_agree_fail_closed(self) -> None:
        base = self._write_scalar_role()
        # Both entry points refuse — the loader directly and the runner through it.
        with self.assertRaises(rc.RoleConfigError):
            rc.load_role_config(ROLE_ID, base=base)
        with self.assertRaises(rc.RoleConfigError):
            x.run(ROLE_ID, None, approve_coldstart=True, base=base)


if __name__ == "__main__":
    unittest.main()
