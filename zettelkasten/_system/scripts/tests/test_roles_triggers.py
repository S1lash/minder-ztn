"""Tests for the trigger-gate + cross-tick watermark (CONTRACT §1.3/§7, INV-18/26/27)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_common as rc  # noqa: E402
import roles_triggers as tg  # noqa: E402


def _cfg(tmp: Path, triggers_yaml: str) -> rc.RoleConfig:
    d = tmp / "_system" / "roles" / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(
        "id: r\nparts: [{id: p1, kind: ledger}]\n"
        "remit: {all: true}\ncadence: daily\nstatus: active\n" + triggers_yaml,
        encoding="utf-8")
    return rc.load_role_config("r", tmp)


def _unit(path: str, **fm) -> dict:
    return {"path": path, "type": "note", "trio": {}, "frontmatter_subset": fm}


class SttMatchTest(unittest.TestCase):
    def test_transliteration_and_declension_match(self):
        self.assertTrue(rc.stt_token_equal("minder", "миндер"))
        self.assertTrue(rc.stt_token_equal("minder", "миндера"))   # RU declension (suffix)
        self.assertTrue(rc.stt_token_equal("minder", "миндеру"))   # RU declension (suffix)
        self.assertTrue(rc.stt_token_equal("Minder", "minder"))

    def test_unrelated_real_words_do_not_match(self):
        # The precision bar: NO single-substitution neighbour or containing word fires.
        for w in ("reminder", "calendar", "finder", "tinder", "kinder", "binder",
                  "minter", "mender"):
            self.assertFalse(rc.stt_token_equal("minder", w), w)

    def test_short_prefix_does_not_match_everything(self):
        self.assertFalse(rc.stt_token_equal("min", "minder"))  # min-length guard

    def test_short_token_matches_exact_only(self):
        # A short entity (<5) matches exact-only — no coincidental prefix over-fire.
        self.assertFalse(rc.stt_token_equal("card", "cardio"))
        self.assertTrue(rc.stt_token_equal("card", "card"))
        self.assertTrue(rc.stt_token_equal("oura", "oura"))


class RoleAuthoredSourceTest(unittest.TestCase):
    def test_matches_raw_and_processed_forms(self):
        self.assertTrue(rc.is_role_authored_source("role:minder-pm", "minder-pm"))
        self.assertTrue(rc.is_role_authored_source(
            "_sources/processed/roles/minder-pm--2026-07-19-abcd1234.md", "minder-pm"))

    def test_does_not_match_other_roles_or_sources(self):
        self.assertFalse(rc.is_role_authored_source("role:other", "minder-pm"))
        self.assertFalse(rc.is_role_authored_source("plaud", "minder-pm"))
        # Precise: `roles/minder--` is NOT a substring of `roles/minder-pm--…`.
        self.assertFalse(rc.is_role_authored_source(
            "_sources/processed/roles/minder-pm--x.md", "minder"))
        self.assertFalse(rc.is_role_authored_source(None, "minder-pm"))


class UngatedTest(unittest.TestCase):
    def test_no_triggers_passes(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = _cfg(Path(t), "")
            r = tg.evaluate_gate(cfg, [], base=Path(t))
            self.assertTrue(r.passed)
            self.assertIn("ungated", r.reasons)


class ZoneMentionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.cfg = _cfg(self.tmp, "triggers: [{kind: zone-mention, match: [minder]}]\n")

    def test_fires_on_project_tag(self):
        units = [_unit("1_projects/x.md", projects=["minder"])]
        r = tg.evaluate_gate(self.cfg, units, base=self.tmp)
        self.assertTrue(r.passed)
        self.assertIn("zone-mention:minder", r.reasons)

    def test_fires_on_garbled_title(self):
        units = [_unit("_records/m.md", title="Созвон по миндеру")]
        self.assertTrue(tg.evaluate_gate(self.cfg, units, base=self.tmp).passed)

    def test_no_fire_on_unrelated_zone(self):
        units = [_unit("_records/y.md", title="reminder about groceries", tags=["home"])]
        self.assertFalse(tg.evaluate_gate(self.cfg, units, base=self.tmp).passed)

    def test_self_authored_excluded_raw_emission(self):
        # A record THIS role emitted must NOT trigger it (INV-27 no-self-feed).
        units = [_unit("_records/self.md", projects=["minder"], source="role:r")]
        self.assertFalse(tg.evaluate_gate(self.cfg, units, base=self.tmp).passed)

    def test_self_authored_excluded_processed_round_trip(self):
        # The REAL loop guard: /ztn:process stamps the derived record's source with
        # the processed PATH (…/roles/{id}--…), NOT role:{id}. That record is what the
        # role re-reads — it must still be excluded (INV-27, the load-bearing case).
        units = [_unit("_records/observations/o.md", projects=["minder"],
                       source="_sources/processed/roles/r--2026-07-19-abcd1234.md")]
        self.assertFalse(tg.evaluate_gate(self.cfg, units, base=self.tmp).passed)

    def test_self_authored_by_other_role_still_fires(self):
        units = [_unit("_records/o.md", projects=["minder"], source="role:other")]
        self.assertTrue(tg.evaluate_gate(self.cfg, units, base=self.tmp).passed)


class ExternalStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.cfg = _cfg(
            self.tmp,
            "triggers: [{kind: external-state, probe: notion-board.last_edited_time}]\n")

    def test_fires_when_probe_moved_past_watermark(self):
        r = tg.evaluate_gate(
            self.cfg, [], {"notion-board.last_edited_time": "2026-07-19T10:00Z"},
            base=self.tmp, device="dev1")
        self.assertTrue(r.passed)
        self.assertIn("notion-board.last_edited_time@dev1", r.pending_watermarks)

    def test_no_fire_when_probe_equals_watermark(self):
        # Commit the value first, then re-evaluate with the same value → no fire.
        tg.commit_gate_pass(
            "r", {"notion-board.last_edited_time@dev1": "2026-07-19T10:00Z"}, self.tmp)
        r = tg.evaluate_gate(
            self.cfg, [], {"notion-board.last_edited_time": "2026-07-19T10:00Z"},
            base=self.tmp, device="dev1")
        self.assertFalse(r.passed)

    def test_probe_unavailable_cannot_fire(self):
        # No probe value (tool down / not obtained) → honest no-fire, never a guess.
        r = tg.evaluate_gate(self.cfg, [], {}, base=self.tmp, device="dev1")
        self.assertFalse(r.passed)

    def test_watermark_keyed_by_device(self):
        tg.commit_gate_pass(
            "r", {"notion-board.last_edited_time@dev1": "v1"}, self.tmp)
        # A different device has NOT seen v1 → still fires (multi-clone, INV-26).
        r = tg.evaluate_gate(
            self.cfg, [], {"notion-board.last_edited_time": "v1"},
            base=self.tmp, device="dev2")
        self.assertTrue(r.passed)


class SkipStreakTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_streak_increments_and_resets(self):
        for i in range(1, 6):
            self.assertEqual(tg.commit_gate_skip("r", "gate:skip:no-trigger", self.tmp), i)
        self.assertTrue(tg.skip_streak_exceeded(
            tg.commit_gate_skip("r", "gate:skip:no-trigger", self.tmp)))
        # A pass resets streak AND reasons.
        tg.commit_gate_pass("r", {}, self.tmp)
        self.assertEqual(tg.load_trigger_state("r", self.tmp)["skip_streak"], 0)
        self.assertEqual(tg.recent_skip_reasons("r", self.tmp), [])

    def test_skip_reasons_stored_bounded(self):
        for i in range(8):
            tg.commit_gate_skip("r", f"gate:skip:reason-{i}", self.tmp)
        reasons = tg.recent_skip_reasons("r", self.tmp)
        self.assertEqual(len(reasons), tg.MAX_SKIP_REASONS)  # last 5 only
        self.assertEqual(reasons[-1], "gate:skip:reason-7")

    def test_limit_is_five(self):
        self.assertEqual(tg.SKIP_STREAK_LIMIT, 5)
        self.assertFalse(tg.skip_streak_exceeded(4))
        self.assertTrue(tg.skip_streak_exceeded(5))


class DeviceIdTest(unittest.TestCase):
    def test_env_var_wins(self):
        import unittest.mock, os
        with unittest.mock.patch.dict(os.environ, {"ZTN_DEVICE_ID": "laptop-a"}):
            self.assertEqual(tg.default_device(), "laptop-a")

    def test_derives_stable_nonempty_id_when_unset(self):
        import unittest.mock, os
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            dev = tg.default_device()
        # Derived from hostname (slug), stable + ASCII — not the shared "default"
        # constant unless the hostname is truly unavailable.
        self.assertTrue(dev)
        self.assertTrue(all(c.isalnum() or c == "-" for c in dev))


class OrCombinedTest(unittest.TestCase):
    def test_either_trigger_fires(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            cfg = _cfg(
                tmp,
                "triggers:\n"
                "  - {kind: zone-mention, match: [minder]}\n"
                "  - {kind: external-state, probe: notion.last}\n")
            # zone quiet, but external moved → still passes (OR).
            r = tg.evaluate_gate(cfg, [_unit("x.md", tags=["home"])],
                                 {"notion.last": "v2"}, base=tmp)
            self.assertTrue(r.passed)


if __name__ == "__main__":
    unittest.main()
