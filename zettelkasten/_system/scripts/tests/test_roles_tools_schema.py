"""Tests for the tools-forward config schema additions (CONTRACT §1).

Covers the additive schema seam PLAN 1 builds onto `roles_common`:
  - `PartSpec.tools` — per-part tool grants (empty default; existing configs
    unchanged);
  - `RoleConfig.mandate` — promoted from the old `persona["mandate"]` stash to
    ONE role-level home (SoT collision resolved), parsed into `MandateSpec`;
  - `RoleConfig.triggers` — OR-combined `TriggerSpec` list, absent → ungated;
  - `RoleConfig.emit_inbox` — inbox emission opt-in;
  - the new `ROLE_CLARIFICATION_TYPES` entries the tools engine raises.

Isolated to a tempdir config — no env mutation, no LLM, no network.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_common as rc  # noqa: E402


def _write_config(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class _ConfigCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.yml"

    def load(self, body: str) -> rc.RoleConfig:
        _write_config(self.path, body)
        return rc.load_role_config_file(self.path)


class BackCompatTest(_ConfigCase):
    """An existing schema_version:2 config parses unchanged — additive only."""

    def test_existing_config_parses_with_empty_new_defaults(self) -> None:
        cfg = self.load(
            "id: minder-pm\n"
            "parts:\n"
            "  - {id: purpose, kind: narrative}\n"
            "  - {id: workstreams, kind: ledger}\n"
            "remit: {project_ids: [minder]}\n"
            "cadence: weekly\ncadence_anchor: monday\nstatus: active\n"
        )
        # New fields default empty — no hands, no mandate, no triggers, no emit.
        self.assertEqual(tuple(p.tools for p in cfg.parts), ((), ()))
        self.assertIsNone(cfg.mandate)
        self.assertEqual(cfg.triggers, ())
        self.assertFalse(cfg.emit_inbox)


class PartToolsTest(_ConfigCase):
    def test_part_tools_parse_dedup_first_seen(self) -> None:
        cfg = self.load(
            "id: r\n"
            "parts:\n"
            "  - {id: p1, kind: ledger, tools: [notion-board, gdrive, notion-board]}\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        )
        self.assertEqual(cfg.parts[0].tools, ("notion-board", "gdrive"))

    def test_part_tools_absent_defaults_empty(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        )
        self.assertEqual(cfg.parts[0].tools, ())

    def test_part_tools_non_list_fail_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger, tools: notion-board}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
            )
        self.assertIn("tools", str(ctx.exception))


class MandateTest(_ConfigCase):
    def test_mandate_promoted_to_role_level_home(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
            "mandate:\n"
            "  autonomy: advisory\n"
            "  until: 2027-01-01\n"
            "  scope:\n"
            "    - {target: notion-write, surface: staging-page, mode: read-modify-write, blast: bounded}\n"
        )
        self.assertIsNotNone(cfg.mandate)
        self.assertEqual(cfg.mandate.autonomy, "advisory")
        self.assertEqual(cfg.mandate.until, "2027-01-01")
        self.assertEqual(len(cfg.mandate.scope), 1)
        tgt = cfg.mandate.scope[0]
        self.assertEqual(tgt.target, "notion-write")
        self.assertEqual(tgt.surface, "staging-page")
        self.assertEqual(tgt.mode, "read-modify-write")
        self.assertEqual(tgt.blast, "bounded")

    def test_mandate_absent_is_none_read_only(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        )
        self.assertIsNone(cfg.mandate)

    def test_persona_mandate_no_longer_stashed(self) -> None:
        # The old persona["mandate"] home is gone — one home only (SoT).
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
            "persona: {voice: own}\n"
        )
        self.assertNotIn("mandate", cfg.persona)

    def test_malformed_mandate_autonomy_fail_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "mandate: {autonomy: cowboy, scope: [{target: t, surface: s, mode: write, blast: bounded}]}\n"
            )
        self.assertIn("autonomy", str(ctx.exception))

    def test_malformed_mandate_scope_mode_fail_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError):
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "mandate: {autonomy: advisory, scope: [{target: t, surface: s, mode: nuke, blast: bounded}]}\n"
            )

    def test_mandate_requires_nonempty_scope(self) -> None:
        with self.assertRaises(rc.RoleConfigError):
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "mandate: {autonomy: advisory, scope: []}\n"
            )


class TriggersTest(_ConfigCase):
    def test_triggers_parse_or_combined_entries(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
            "triggers:\n"
            "  - {kind: zone-mention, match: [minder, миндер]}\n"
            "  - {kind: external-state, probe: notion-board.last_edited_time, state: watermark}\n"
        )
        self.assertEqual(len(cfg.triggers), 2)
        self.assertEqual(cfg.triggers[0].kind, "zone-mention")
        self.assertEqual(cfg.triggers[0].match, ("minder", "миндер"))
        self.assertEqual(cfg.triggers[1].kind, "external-state")
        self.assertEqual(cfg.triggers[1].probe, "notion-board.last_edited_time")

    def test_triggers_absent_is_empty_ungated(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        )
        self.assertEqual(cfg.triggers, ())

    def test_zone_mention_requires_match(self) -> None:
        with self.assertRaises(rc.RoleConfigError):
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "triggers: [{kind: zone-mention, match: []}]\n"
            )

    def test_external_state_requires_probe(self) -> None:
        with self.assertRaises(rc.RoleConfigError):
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "triggers: [{kind: external-state, state: watermark}]\n"
            )

    def test_unknown_trigger_kind_fail_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "triggers: [{kind: telepathy, match: [x]}]\n"
            )
        self.assertIn("kind", str(ctx.exception))


class EmitInboxTest(_ConfigCase):
    def test_emit_inbox_true(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
            "emit_inbox: true\n"
        )
        self.assertTrue(cfg.emit_inbox)

    def test_emit_inbox_absent_defaults_false(self) -> None:
        cfg = self.load(
            "id: r\nparts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        )
        self.assertFalse(cfg.emit_inbox)

    def test_emit_inbox_non_bool_fail_closed(self) -> None:
        # The string trap: bool("false") is True — a non-bool must surface.
        with self.assertRaises(rc.RoleConfigError):
            self.load(
                "id: r\nparts: [{id: p1, kind: ledger}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"
                "emit_inbox: nope\n"
            )


class ClarificationTypesTest(unittest.TestCase):
    def test_plan1_clarification_types_registered(self) -> None:
        for ctype in (
            "role-trigger-skip-streak",
            "role-tool-reauth",
            "role-emission-confirm",
            "role-budget-exhausted",
        ):
            self.assertIn(ctype, rc.ROLE_CLARIFICATION_TYPES)


if __name__ == "__main__":
    unittest.main()
