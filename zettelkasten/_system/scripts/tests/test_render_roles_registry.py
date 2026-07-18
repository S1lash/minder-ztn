"""Tests for render_roles_registry.py (composite parts[] model).

Isolated to a tempdir ZTN base passed via `--root` / the `base` param — no
env mutation, no LLM, no network. Exercises glob discovery, per-part
item-count projection (breakdown + cold-start staging), multi-part roles,
last-successful-run selection, drop-and-surface of a malformed config, the
no-cruft rejection of a v1 scalar-`archetype` config and of an unresolvable
part kind, DASH degradation (missing / corrupt state; a kind without a
summarizer), the four CLI modes (diff / --apply / --check / --dry-run),
atomic idempotency, and the never-raise contract.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_roles_registry as x  # noqa: E402
import unittest  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _role(
    base: Path,
    role_id: str,
    *,
    parts: list[tuple[str, str]] | None = None,
    cadence: str = "weekly",
    anchor: str = "monday",
    name: str | None = None,
    part_states: dict[str, dict] | None = None,
    config_text: str | None = None,
) -> None:
    """Create a role instance dir with a composite config + optional part states.

    `parts` is an ordered list of `(part_id, kind)`; `part_states` maps a
    part_id to the dict written to `parts/{part_id}.json`. Defaults to a single
    `workstreams`/`ledger` part.
    """
    rdir = base / "_system" / "roles" / role_id
    if config_text is not None:
        _write(rdir / "config.yml", config_text)
    else:
        if parts is None:
            parts = [("workstreams", "ledger")]
        lines = [f"id: {role_id}"]
        if name is not None:
            lines.append(f'name: "{name}"')
        lines.append("parts:")
        for pid, kind in parts:
            lines.append(f"  - {{ id: {pid}, kind: {kind} }}")
        lines.append(f"cadence: {cadence}")
        lines.append(f"cadence_anchor: {anchor}")
        _write(rdir / "config.yml", "\n".join(lines) + "\n")
    for pid, state in (part_states or {}).items():
        _write(rdir / "parts" / f"{pid}.json", json.dumps(state))


def _run_entry(role_id: str, run_at: str, status: str) -> str:
    return json.dumps(
        {"role_id": role_id, "run_at": run_at, "status": status,
         "hook": "tick", "counts": {}}
    )


class RenderRolesRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        (self.base / "_system" / "views").mkdir(parents=True, exist_ok=True)
        (self.base / "_system" / "state").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @property
    def view_path(self) -> Path:
        return self.base / "_system" / "views" / "ROLES.md"

    # -- build_rows / render_document -------------------------------------

    def test_empty_base_renders_placeholder(self) -> None:
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(rows, [])
        self.assertEqual(skipped, [])
        doc = x.render_document(rows, skipped)
        self.assertIn("No roles defined yet", doc)
        self.assertTrue(doc.endswith("\n"))
        self.assertTrue(doc.startswith("# Roles Registry"))

    def test_basic_row_counts_and_last_run(self) -> None:
        _role(
            self.base, "alpha", name="Alpha PM",
            part_states={
                "workstreams": {
                    "items": [
                        {"status": "new"},
                        {"status": "active"},
                        {"status": "active"},
                        {"status": "done"},
                    ],
                    "staging": {"items": [{}, {}]},
                },
            },
        )
        _write(
            self.base / "_system" / "state" / "roles-runs.jsonl",
            "\n".join([
                _run_entry("alpha", "2026-07-01T09:00:00Z", "ok"),
                _run_entry("alpha", "2026-07-05T09:00:00Z", "error"),
            ]) + "\n",
        )
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.id, "alpha")
        self.assertEqual(row.name, "Alpha PM")
        self.assertEqual(row.cadence, "weekly (monday)")
        self.assertEqual(row.status, "active")
        # last_run = last successful (ok/empty), not the later error entry
        self.assertEqual(row.last_run, "2026-07-01")
        self.assertEqual(len(row.parts), 1)
        self.assertEqual(row.parts[0].part_id, "workstreams")
        self.assertEqual(row.parts[0].kind, "ledger")
        cell = x._format_parts_cell(row.parts)
        self.assertEqual(
            cell,
            "workstreams (ledger): "
            "4 (new 1 · active 2 · done 1) · cold-start 2 staged",
        )

    def test_multi_part_row_lists_parts_in_order(self) -> None:
        _role(
            self.base, "pm",
            parts=[("purpose", "ledger"), ("workstreams", "ledger")],
            part_states={
                "purpose": {"items": []},
                "workstreams": {"items": [{"status": "active"}, {"status": "blocked"}]},
            },
        )
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(skipped, [])
        row = rows[0]
        self.assertEqual([p.part_id for p in row.parts], ["purpose", "workstreams"])
        cell = x._format_parts_cell(row.parts)
        self.assertEqual(
            cell,
            "purpose (ledger): 0; workstreams (ledger): 2 (active 1 · blocked 1)",
        )

    def test_name_falls_back_to_id(self) -> None:
        _role(self.base, "beta", part_states={"workstreams": {"items": []}})
        rows, _ = x.build_rows(self.base)
        self.assertEqual(rows[0].name, "beta")

    def test_missing_part_state_shows_dash(self) -> None:
        _role(self.base, "gamma")  # no part state json (defined, never ticked)
        rows, _ = x.build_rows(self.base)
        self.assertIsNone(rows[0].parts[0].summary)
        self.assertEqual(
            x._format_parts_cell(rows[0].parts), "workstreams (ledger): —"
        )
        self.assertEqual(rows[0].last_run, None)

    def test_unresolvable_kind_is_skipped(self) -> None:
        # A part kind with no installed plugin fail-closes the config load, so
        # the WHOLE role is dropped-and-surfaced (not shown with a DASH count).
        _role(self.base, "delta", parts=[("metrics", "metrics")])
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["dir"], "delta")
        self.assertIn("metrics", skipped[0]["reason"])

    def test_v1_scalar_archetype_config_is_skipped(self) -> None:
        # No-cruft: a residual v1 `archetype:` scalar config must not load.
        _role(
            self.base, "legacy",
            config_text="id: legacy\narchetype: ledger\ncadence: daily\n",
        )
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(rows, [])
        self.assertEqual(skipped[0]["dir"], "legacy")
        self.assertIn("archetype", skipped[0]["reason"])

    def test_kind_without_summarizer_degrades_to_dash(self) -> None:
        # A kind whose plugin loads (config passes) but has no `registry_summary`
        # hook shows DASH — honest, never a guessed count. Simulated by making the
        # seam dispatch return None (as it does for a plugin lacking the hook).
        _role(self.base, "eps",
              part_states={"workstreams": {"items": [{"status": "active"}]}})
        orig = x._summary_from_plugin
        x._summary_from_plugin = lambda kind, state: None
        try:
            rows, skipped = x.build_rows(self.base)
        finally:
            x._summary_from_plugin = orig
        self.assertEqual(skipped, [])
        self.assertIsNone(rows[0].parts[0].summary)
        self.assertEqual(
            x._format_parts_cell(rows[0].parts), "workstreams (ledger): —"
        )

    def test_narrative_part_summarized_via_seam(self) -> None:
        # A narrative part now gets a real count via its own registry_summary hook.
        _role(self.base, "nar",
              parts=[("purpose", "narrative")],
              part_states={"purpose": {"purpose": "P", "entries": [
                  {"version": 1, "kind": "purpose", "text": "P"},
                  {"version": 2, "kind": "narrative", "text": "N"}]}})
        rows, _ = x.build_rows(self.base)
        cell = x._format_parts_cell(rows[0].parts)
        self.assertEqual(cell, "purpose (narrative): 2 (purpose 1 · narrative 1)")

    def test_unknown_status_surfaced_not_dropped(self) -> None:
        _role(self.base, "zeta",
              part_states={"workstreams": {
                  "items": [{"status": "active"}, {"status": "weird"}]}})
        rows, _ = x.build_rows(self.base)
        cell = x._format_parts_cell(rows[0].parts)
        self.assertEqual(cell, "workstreams (ledger): 2 (active 1 · weird 1)")

    def test_malformed_config_dropped_and_surfaced(self) -> None:
        _role(self.base, "good", part_states={"workstreams": {"items": []}})
        _role(self.base, "bad",
              config_text="id: bad\nparts:\n  - {id: w, kind: ledger}\ncadence: hourly\n")
        rows, skipped = x.build_rows(self.base)
        self.assertEqual([r.id for r in rows], ["good"])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["dir"], "bad")
        self.assertIn("cadence", skipped[0]["reason"])
        doc = x.render_document(rows, skipped)
        self.assertIn("## Skipped", doc)
        self.assertIn("bad", doc)

    def test_id_mismatch_surfaced(self) -> None:
        _role(self.base, "dirname",
              config_text="id: otherid\nparts:\n  - {id: w, kind: ledger}\ncadence: daily\n")
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(rows, [])
        self.assertEqual(skipped[0]["dir"], "dirname")

    def test_rows_sorted_by_id(self) -> None:
        _role(self.base, "zulu", part_states={"workstreams": {"items": []}})
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        rows, _ = x.build_rows(self.base)
        self.assertEqual([r.id for r in rows], ["alpha", "zulu"])

    def test_frame_marker_not_a_role(self) -> None:
        # `_frame.md` (engine file) lives under roles/ but must never be a role.
        _write(self.base / "_system" / "roles" / "_frame.md", "engine frame\n")
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        rows, skipped = x.build_rows(self.base)
        self.assertEqual([r.id for r in rows], ["alpha"])
        self.assertEqual(skipped, [])

    def test_corrupt_part_json_tolerated(self) -> None:
        _role(self.base, "alpha")
        _write(
            self.base / "_system" / "roles" / "alpha" / "parts" / "workstreams.json",
            "{not json",
        )
        rows, skipped = x.build_rows(self.base)
        self.assertEqual(skipped, [])
        self.assertIsNone(rows[0].parts[0].summary)

    def test_cadence_formats(self) -> None:
        _role(self.base, "d", cadence="daily", anchor="monday")
        _role(self.base, "m",
              config_text="id: m\nparts:\n  - {id: w, kind: ledger}\ncadence: monthly\ncadence_anchor: 15\n")
        rows, _ = x.build_rows(self.base)
        by_id = {r.id: r.cadence for r in rows}
        self.assertEqual(by_id["d"], "daily")
        self.assertEqual(by_id["m"], "monthly (day 15)")

    # -- CLI modes --------------------------------------------------------

    def _main(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = x.main(["--root", str(self.base), *argv])
        return rc, buf.getvalue()

    def test_apply_writes_and_is_idempotent(self) -> None:
        _role(self.base, "alpha",
              part_states={"workstreams": {"items": [{"status": "active"}]}})
        rc, out = self._main("--apply")
        self.assertEqual(rc, 0)
        self.assertTrue(self.view_path.is_file())
        first = self.view_path.read_text(encoding="utf-8")
        self.assertIn("alpha", first)
        self.assertIn("workstreams (ledger)", first)
        self.assertEqual(json.loads(out)["changed"], True)
        # second apply → no change, byte-identical
        rc2, out2 = self._main("--apply")
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(out2)["changed"], False)
        self.assertEqual(self.view_path.read_text(encoding="utf-8"), first)

    def test_written_file_is_lf(self) -> None:
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        self._main("--apply")
        raw = self.view_path.read_bytes()
        self.assertNotIn(b"\r\n", raw)

    def test_check_exit_codes(self) -> None:
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        # file absent → would change → exit 3
        rc, out = self._main("--check")
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out)["changed"], True)
        self.assertFalse(self.view_path.is_file())  # --check never writes
        # write it, then --check is clean
        self._main("--apply")
        rc2, out2 = self._main("--check")
        self.assertEqual(rc2, 0)
        self.assertEqual(json.loads(out2)["changed"], False)
        # mutate a role → --check exit 3 again
        _role(self.base, "beta", part_states={"workstreams": {"items": []}})
        rc3, _ = self._main("--check")
        self.assertEqual(rc3, 3)

    def test_dry_run_prints_content_no_write(self) -> None:
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        rc, out = self._main("--dry-run")
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("# Roles Registry"))
        self.assertIn("alpha", out)
        self.assertFalse(self.view_path.is_file())

    def test_default_prints_diff_no_write(self) -> None:
        _role(self.base, "alpha", part_states={"workstreams": {"items": []}})
        rc, out = self._main()
        self.assertEqual(rc, 0)
        self.assertIn("+# Roles Registry", out)  # unified diff of a new file
        self.assertFalse(self.view_path.is_file())

    def test_never_raises_on_internal_error(self) -> None:
        original = x.build_rows
        x.build_rows = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc, out = self._main("--check")
        finally:
            x.build_rows = original
        self.assertEqual(rc, 0)  # never-raise: even --check degrades to 0
        payload = json.loads(out)
        self.assertEqual(payload["ok"], False)
        self.assertIn("boom", payload["reason"])


if __name__ == "__main__":
    unittest.main()
