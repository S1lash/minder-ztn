"""Tests for roles_archetype_metrics.py — the Metrics reference archetype plugin.

Covers the schema hook (fail-closed on every malformed shape), the deterministic
compute (gap sign convention for BOTH directions, trend verdict from the injected
reading, config-only targets the body cannot move), cold-start / no-data honesty
(current/gap/trend null — never a fabricated value), the SoT guarantee (state holds
only derived scalars, never the daily series), the records grounding of a body
`note`, and the composite-seam hooks (content_view/adopt round-trip,
consumed_records, registry_summary, build_decisions, identity).

A config-threading block proves the schema loads end-to-end through the REAL
`roles_common._parse_parts` + writer overlay. A readings-lane block drives the full
`roles_persist.run` seam against real metric-day baselines on disk: the runner
injects the latest reading, the plugin computes the progress view, the target comes
only from config, and a role with no reading-needing part gets no readings lane.

No I/O for the plugin tests — validate/persist are pure in-memory transforms.
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

import roles_archetype_metrics as x  # noqa: E402
import roles_common as rc  # noqa: E402
import roles_persist as rp  # noqa: E402


_METRICS = [
    {"key": "w", "source": "w_src", "target": 78, "direction": "lower", "unit": "kg"},
    {"key": "s", "source": "s_src", "target": 8, "direction": "higher", "unit": "h"},
]


def _schema(metrics=None, grounding="records") -> dict:
    return {
        "metrics": [dict(m) for m in (metrics if metrics is not None else _METRICS)],
        "grounding": grounding,
        "grounding_check": False,
    }


def _state(metrics=None, schema=None, **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "metrics",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": schema if schema is not None else _schema(),
        "metrics": list(metrics or []),
    }
    state.update(top)
    return state


def _reading(current, prior=None, mu=None, sigma=None,
             at="2026-07-09", stem="2026-07-09") -> dict:
    return {"current": current, "prior": prior, "mu": mu, "sigma": sigma,
            "at": at, "stem": stem}


def _payload(read_records, readings, *deltas) -> dict:
    return {
        "role_id": "r",
        "hook": "tick",
        "read_records": list(read_records),
        "readings": dict(readings),
        "deltas": list(deltas),
    }


def _metric(key, current=None, trend=None, at=None, provenance=None, note=None) -> dict:
    m = {"key": key, "current": current, "trend": trend,
         "last_reading_at": at, "provenance": list(provenance or [])}
    if note is not None:
        m["note"] = note
    return m


# =============================================================================
# validate_schema — fail-closed on every malformed shape
# =============================================================================

class ValidateSchemaTest(unittest.TestCase):
    def test_happy_path_returns_canonical(self) -> None:
        sch = x.validate_schema({"metrics": _METRICS, "grounding": "records"})
        self.assertEqual([m["key"] for m in sch["metrics"]], ["w", "s"])
        self.assertEqual(sch["metrics"][0]["direction"], "lower")
        self.assertEqual(sch["grounding"], "records")
        self.assertFalse(sch["grounding_check"])       # Stage 2.5 OFF for metrics

    def test_unit_optional_defaults_empty(self) -> None:
        sch = x.validate_schema({"metrics": [
            {"key": "k", "source": "s", "target": 1, "direction": "higher"}]})
        self.assertEqual(sch["metrics"][0]["unit"], "")

    def _fails(self, raw, needle) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            x.validate_schema(raw)
        self.assertIn(needle, str(ctx.exception))

    def test_not_a_mapping_fails(self) -> None:
        self._fails("nope", "schema")

    def test_empty_metrics_fails(self) -> None:
        self._fails({"metrics": []}, "metrics")

    def test_missing_key_fails(self) -> None:
        self._fails({"metrics": [{"source": "s", "target": 1, "direction": "lower"}]}, "key")

    def test_missing_source_fails(self) -> None:
        self._fails({"metrics": [{"key": "k", "target": 1, "direction": "lower"}]}, "source")

    def test_non_numeric_target_fails(self) -> None:
        self._fails({"metrics": [{"key": "k", "source": "s", "target": "x",
                                  "direction": "lower"}]}, "target")

    def test_bool_target_fails(self) -> None:
        # bool is an int subclass — must be rejected, not silently treated as 0/1.
        self._fails({"metrics": [{"key": "k", "source": "s", "target": True,
                                  "direction": "lower"}]}, "target")

    def test_bad_direction_fails(self) -> None:
        self._fails({"metrics": [{"key": "k", "source": "s", "target": 1,
                                  "direction": "sideways"}]}, "direction")

    def test_duplicate_key_fails(self) -> None:
        self._fails({"metrics": [
            {"key": "k", "source": "a", "target": 1, "direction": "lower"},
            {"key": "k", "source": "b", "target": 2, "direction": "higher"}]}, "duplicate")

    def test_non_records_grounding_fails(self) -> None:
        self._fails({"metrics": [{"key": "k", "source": "s", "target": 1,
                                  "direction": "lower"}], "grounding": "owner-confirm"},
                    "grounding")


# =============================================================================
# Deterministic compute — gap sign convention (both directions) + trend
# =============================================================================

class GapSignTest(unittest.TestCase):
    def test_lower_above_target_positive_gap(self) -> None:
        self.assertEqual(x._gap(80, 78, "lower"), 2)     # still to lose

    def test_lower_below_target_negative_gap(self) -> None:
        self.assertEqual(x._gap(76, 78, "lower"), -2)    # passed the target

    def test_higher_below_target_positive_gap(self) -> None:
        self.assertEqual(x._gap(6, 8, "higher"), 2)      # still to gain

    def test_higher_above_target_negative_gap(self) -> None:
        self.assertEqual(x._gap(9, 8, "higher"), -1)     # passed the target

    def test_gap_none_when_no_current(self) -> None:
        self.assertIsNone(x._gap(None, 8, "higher"))


class ComputeTest(unittest.TestCase):
    def _refresh_view(self, metrics, readings, key) -> dict:
        state = _state(schema=_schema(metrics))
        deltas = [{"part": "p", "op": "refresh", "key": m["key"]} for m in metrics]
        res = x.validate(state, _payload(["2026-07-09"], readings, *deltas))
        self.assertTrue(res.ok)
        ns = x.persist(state, res.approved_deltas, None)
        return next(v for v in x._view(ns) if v["key"] == key), ns

    def test_lower_direction_improving_when_dropping(self) -> None:
        m = [{"key": "w", "source": "w_src", "target": 78, "direction": "lower", "unit": "kg"}]
        view, _ = self._refresh_view(m, {"w_src": _reading(80.0, mu=82.0)}, "w")
        self.assertEqual(view["current"], 80.0)
        self.assertEqual(view["gap"], 2.0)               # above target → still to lose
        self.assertEqual(view["trend"], "improving")     # 80 < mu 82 → dropping toward lower target

    def test_higher_direction_improving_when_rising(self) -> None:
        m = [{"key": "s", "source": "s_src", "target": 8, "direction": "higher", "unit": "h"}]
        view, _ = self._refresh_view(m, {"s_src": _reading(6.0, mu=5.5)}, "s")
        self.assertEqual(view["gap"], 2.0)               # below target → still to gain
        self.assertEqual(view["trend"], "improving")     # 6 > mu 5.5 → rising toward higher target

    def test_regressing_when_moving_away(self) -> None:
        m = [{"key": "w", "source": "w_src", "target": 78, "direction": "lower", "unit": "kg"}]
        view, _ = self._refresh_view(m, {"w_src": _reading(85.0, mu=80.0)}, "w")
        self.assertEqual(view["trend"], "regressing")    # 85 > mu 80 → rising, wrong way for lower

    def test_stalling_when_flat(self) -> None:
        m = [{"key": "w", "source": "w_src", "target": 78, "direction": "lower", "unit": "kg"}]
        view, _ = self._refresh_view(m, {"w_src": _reading(80.0, mu=80.0)}, "w")
        self.assertEqual(view["trend"], "stalling")

    def test_prior_used_when_mu_absent(self) -> None:
        m = [{"key": "s", "source": "s_src", "target": 8, "direction": "higher", "unit": "h"}]
        view, _ = self._refresh_view(m, {"s_src": _reading(6.0, prior=5.0, mu=None)}, "s")
        self.assertEqual(view["trend"], "improving")     # falls back to prior (6 > 5 → rising)

    def test_no_reference_is_stalling(self) -> None:
        m = [{"key": "s", "source": "s_src", "target": 8, "direction": "higher", "unit": "h"}]
        view, _ = self._refresh_view(m, {"s_src": _reading(6.0, prior=None, mu=None)}, "s")
        self.assertEqual(view["trend"], "stalling")      # nothing to compare → not a trend

    def test_config_target_overlaid_body_cannot_move_it(self) -> None:
        # The target lives ONLY in the schema (config). The same stored reading viewed
        # under a DIFFERENT config target yields a different gap — proof the target is
        # not persisted in per-metric state and the body cannot move it.
        m1 = [{"key": "w", "source": "w_src", "target": 78, "direction": "lower", "unit": "kg"}]
        _, ns = self._refresh_view(m1, {"w_src": _reading(80.0, mu=82.0)}, "w")
        # Re-overlay a NEW config target (as the writer does every load) onto the same
        # stored reading — the gap follows config, not any stored copy.
        ns["schema"] = _schema([{"key": "w", "source": "w_src", "target": 90,
                                 "direction": "lower", "unit": "kg"}])
        view = next(v for v in x._view(ns) if v["key"] == "w")
        self.assertEqual(view["target"], 90)
        self.assertEqual(view["gap"], -10.0)             # 80 vs new target 90


# =============================================================================
# Cold-start / no-data honesty
# =============================================================================

class ColdStartTest(unittest.TestCase):
    def test_no_reading_is_no_data_never_fabricated(self) -> None:
        state = _state()
        res = x.validate(state, _payload([], {}, {"part": "p", "op": "refresh", "key": "w"}))
        self.assertTrue(res.ok)
        ns = x.persist(state, res.approved_deltas, None)
        stored = ns["metrics"][0]
        self.assertIsNone(stored["current"])             # never a fabricated 0
        view = next(v for v in x._view(ns) if v["key"] == "w")
        self.assertIsNone(view["current"])
        self.assertIsNone(view["gap"])                   # no spurious target-hit
        self.assertIsNone(view["trend"])

    def test_no_reading_preserves_existing_value(self) -> None:
        # A refresh with no data must NOT null out a metric that already has a reading.
        prior = _state(metrics=[_metric("w", current=80.0, trend="improving",
                                        at="2026-07-08", provenance=["[[2026-07-08]]"])])
        res = x.validate(prior, _payload([], {}, {"part": "p", "op": "refresh", "key": "w"}))
        ns = x.persist(prior, res.approved_deltas, None)
        self.assertEqual(ns["metrics"][0]["current"], 80.0)   # preserved

    def test_stem_not_in_corpus_is_no_data(self) -> None:
        # Defence in depth: a reading whose record stem is NOT in read_records is not
        # asserted (a metric never claims a number from a record outside the zone).
        state = _state()
        readings = {"w_src": _reading(80.0, mu=82.0, stem="2026-07-09")}
        res = x.validate(state, _payload([], readings,     # read_records EMPTY
                                         {"part": "p", "op": "refresh", "key": "w"}))
        ns = x.persist(state, res.approved_deltas, None)
        self.assertIsNone(ns["metrics"][0]["current"])


# =============================================================================
# SoT — state holds only derived scalars, never the series or the config target
# =============================================================================

class SotTest(unittest.TestCase):
    def test_persisted_metric_holds_no_series_and_no_config_fields(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"], {"w_src": _reading(80.0, mu=82.0)},
                                         {"part": "p", "op": "refresh", "key": "w"}))
        ns = x.persist(state, res.approved_deltas, None)
        stored = ns["metrics"][0]
        # No copy of the daily series (that duplicates the records SoT).
        for banned in ("values", "series", "history", "mu", "sigma"):
            self.assertNotIn(banned, stored)
        # Target / direction / unit / gap live in the schema (config) / the view, not
        # in per-metric state — one home for the target.
        for config_owned in ("target", "direction", "unit", "gap"):
            self.assertNotIn(config_owned, stored)
        self.assertEqual(set(stored), {"key", "current", "trend",
                                       "last_reading_at", "provenance"})

    def test_view_is_the_full_progress_projection(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"], {"w_src": _reading(80.0, mu=82.0)},
                                         {"part": "p", "op": "refresh", "key": "w"}))
        ns = x.persist(state, res.approved_deltas, None)
        view = next(v for v in x._view(ns) if v["key"] == "w")
        self.assertEqual(set(view) >= {"key", "current", "target", "direction",
                                       "unit", "gap", "trend", "last_reading_at",
                                       "provenance"}, True)

    def test_consumed_records_yields_cited_stems(self) -> None:
        state = _state(metrics=[
            _metric("w", current=80.0, provenance=["[[2026-07-09]]"]),
            _metric("s", current=7.0, provenance=["[[2026-07-08]]"])])
        self.assertEqual(sorted(x.consumed_records(state)), ["2026-07-08", "2026-07-09"])


# =============================================================================
# Body may never author a number or move a target
# =============================================================================

class BodyForbiddenTest(unittest.TestCase):
    def _rejected(self, delta) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"], {"w_src": _reading(80.0)}, delta))
        self.assertTrue(res.ok)                          # tick not blocked
        self.assertEqual(res.approved_deltas, ())        # but the delta is dropped
        self.assertEqual(len(res.rejections), 1)

    def test_body_cannot_set_current(self) -> None:
        self._rejected({"part": "p", "op": "refresh", "key": "w", "current": 5})

    def test_body_cannot_set_target(self) -> None:
        self._rejected({"part": "p", "op": "refresh", "key": "w", "target": 1})

    def test_body_cannot_set_gap_or_trend(self) -> None:
        self._rejected({"part": "p", "op": "refresh", "key": "w", "gap": 0})
        self._rejected({"part": "p", "op": "refresh", "key": "w", "trend": "improving"})

    def test_body_cannot_smuggle_reading(self) -> None:
        self._rejected({"part": "p", "op": "refresh", "key": "w",
                        "_reading": {"current": 1}})


# =============================================================================
# Structural gate — op / key / one-touch
# =============================================================================

class StructuralTest(unittest.TestCase):
    def test_unknown_op_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload([], {}, {"part": "p", "op": "bump", "key": "w"}))
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("unknown op", res.rejections[0]["reason"])

    def test_undeclared_key_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload([], {}, {"part": "p", "op": "refresh", "key": "zzz"}))
        self.assertIn("not a declared metric", res.rejections[0]["reason"])

    def test_key_touched_twice_rejected(self) -> None:
        state = _state()
        res = x.validate(state, _payload(["2026-07-09"], {"w_src": _reading(80.0)},
                                         {"part": "p", "op": "refresh", "key": "w"},
                                         {"part": "p", "op": "refresh", "key": "w"}))
        self.assertEqual(len(res.approved_deltas), 1)
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("already touched", res.rejections[0]["reason"])

    def test_empty_schema_holds(self) -> None:
        state = _state(schema={"metrics": [], "grounding": "records"})
        res = x.validate(state, _payload([], {}, {"part": "p", "op": "refresh", "key": "w"}))
        self.assertFalse(res.ok)                          # nothing to validate against


# =============================================================================
# Note op — body-authored prose, records-grounded
# =============================================================================

class NoteTest(unittest.TestCase):
    def test_cited_note_sets_prose_and_grows_provenance(self) -> None:
        prior = _state(metrics=[_metric("w", current=80.0, provenance=["[[2026-07-08]]"])])
        res = x.validate(prior, _payload(["2026-07-09"], {},
                                         {"part": "p", "op": "note", "key": "w",
                                          "text": "plateaued after travel",
                                          "evidence": ["[[2026-07-09]]"]}))
        self.assertTrue(res.ok)
        ns = x.persist(prior, res.approved_deltas, None)
        stored = ns["metrics"][0]
        self.assertEqual(stored["note"], "plateaued after travel")
        self.assertEqual(stored["provenance"], ["[[2026-07-08]]", "[[2026-07-09]]"])
        self.assertEqual(stored["current"], 80.0)         # numbers untouched by a note

    def test_uncited_note_rejected(self) -> None:
        prior = _state(metrics=[_metric("w", current=80.0)])
        res = x.validate(prior, _payload([], {}, {"part": "p", "op": "note", "key": "w",
                                                  "text": "guess"}))
        self.assertIn("evidence", res.rejections[0]["reason"])

    def test_note_citing_out_of_zone_record_rejected(self) -> None:
        prior = _state(metrics=[_metric("w", current=80.0)])
        res = x.validate(prior, _payload(["2026-07-09"], {},
                                         {"part": "p", "op": "note", "key": "w",
                                          "text": "x", "evidence": ["[[not-in-zone]]"]}))
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_note_missing_text_rejected(self) -> None:
        prior = _state(metrics=[_metric("w", current=80.0)])
        res = x.validate(prior, _payload(["2026-07-09"], {},
                                         {"part": "p", "op": "note", "key": "w",
                                          "evidence": ["[[2026-07-09]]"]}))
        self.assertIn("text", res.rejections[0]["reason"])


# =============================================================================
# Render
# =============================================================================

class RenderTest(unittest.TestCase):
    def test_empty_schema(self) -> None:
        self.assertEqual(x.render(_state(schema={"metrics": [], "grounding": "records"})),
                         "_No metrics configured._")

    def test_render_data_and_no_data_lines(self) -> None:
        state = _state(metrics=[_metric("w", current=80.0, trend="improving",
                                        at="2026-07-09", provenance=["[[2026-07-09]]"])])
        out = x.render(state)
        self.assertIn("w: 80 kg → 78 kg", out)
        self.assertIn("gap 2 kg", out)
        self.assertIn("improving", out)
        self.assertIn("s: no data yet (target 8 h)", out)  # declared but unrefreshed

    def test_render_note_line(self) -> None:
        state = _state(metrics=[_metric("w", current=80.0, trend="stalling",
                                        at="2026-07-09", provenance=["[[2026-07-09]]"],
                                        note="held flat")])
        self.assertIn("note: held flat", x.render(state))


# =============================================================================
# Composite-seam hooks
# =============================================================================

class SeamHooksTest(unittest.TestCase):
    def test_known_key_numbers_empty(self) -> None:
        self.assertEqual(list(x.known_key_numbers(_state())), [])

    def test_reading_sources(self) -> None:
        self.assertEqual(x.reading_sources(_schema()), ["w_src", "s_src"])
        self.assertEqual(x.reading_sources({}), [])

    def test_identity_anchored_never_fabricates(self) -> None:
        idr = x.identity({"key": "w"}, None)
        self.assertTrue(idr.anchored)
        self.assertIsNone(idr.anchor)

    def test_gate_identity_passthrough(self) -> None:
        kept, sigs = x.gate_identity("r", "p", _state(), [{"op": "refresh", "key": "w"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(sigs, [])

    def test_content_view_and_adopt_round_trip(self) -> None:
        stored = [_metric("w", current=80.0, provenance=["[[2026-07-09]]"])]
        cv = x.content_view(_state(metrics=stored))
        self.assertEqual(cv["metrics"], stored)
        # Adopt spreads the frozen draft's metrics into a live state; schema NOT frozen.
        adopted = x.adopt_staging(_state(metrics=[]), cv)
        self.assertEqual(adopted["metrics"], stored)

    def test_content_summary(self) -> None:
        state = _state(metrics=[_metric("w", current=80.0, trend="improving"),
                                _metric("s", current=None)])
        labels = x.content_summary(state)
        self.assertIn("w: 80, improving", labels[0])
        self.assertIn("s: no data yet", labels[1])

    def test_registry_summary_with_and_without_data(self) -> None:
        state = _state(metrics=[_metric("w", current=80.0)])   # s declared, no data
        summ = x.registry_summary(state)
        self.assertEqual(summ["total"], 2)                     # both declared metrics
        self.assertIn(["with-data", 1], summ["breakdown"])
        self.assertIn(["no-data", 1], summ["breakdown"])

    def test_registry_summary_counts_staged(self) -> None:
        state = _state(metrics=[], staging={"metrics": [_metric("w", current=80.0)]})
        self.assertEqual(x.registry_summary(state)["staged"], 1)

    def test_delta_counts(self) -> None:
        added, advanced = x.delta_counts([{"op": "refresh"}, {"op": "refresh"},
                                          {"op": "note"}])
        self.assertEqual((added, advanced), (2, 1))

    def test_build_decisions_kinds(self) -> None:
        approved = [
            {"op": "refresh", "key": "w", "_reading": {"current": 80.0, "at": "2026-07-09",
                                                       "stem": "2026-07-09"}},
            {"op": "refresh", "key": "s", "_reading": None},          # no-data refresh
            {"op": "note", "key": "w", "evidence": ["[[2026-07-09]]"]},
        ]
        rows = x.build_decisions(approved, [], _state(), "r", "p", "tick", "ts")
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds, ["metric-refresh", "metric-refresh", "metric-note"])
        self.assertTrue(rows[0]["had_data"])
        self.assertFalse(rows[1]["had_data"])

    def test_cold_materialize_decisions(self) -> None:
        state = _state(metrics=[_metric("w", current=80.0, provenance=["[[2026-07-09]]"])])
        rows = x.cold_materialize_decisions(state, "r", "p", "ts")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "cold-materialize")
        self.assertTrue(rows[0]["has_data"])


# =============================================================================
# Config threading — real _parse_parts + writer overlay
# =============================================================================

_METRICS_CONFIG = """id: numbers
name: My Numbers
parts:
  - id: nums
    kind: metrics
    schema:
      metrics:
        - {key: w, source: w_src, target: 78, direction: lower, unit: kg}
        - {key: s, source: s_src, target: 8, direction: higher, unit: h}
      grounding: records
cadence: daily
status: active
schema_version: 2
remit:
  globs: ["_records/biometric/garmin/**"]
"""


class MetricsConfigThreadingTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_metrics_part_loads_through_real_parse_parts(self) -> None:
        cfg = rc.load_role_config_file(self._write(_METRICS_CONFIG))
        self.assertEqual(cfg.part_ids, ("nums",))
        part = cfg.parts[0]
        self.assertEqual(part.kind, "metrics")
        self.assertEqual(part.grounding, "records")
        self.assertFalse(part.grounding_check)           # metrics: Stage 2.5 OFF
        self.assertEqual([m["key"] for m in part.schema["metrics"]], ["w", "s"])
        self.assertEqual(x.reading_sources(part.schema), ["w_src", "s_src"])

    def test_missing_schema_fails_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts: [{id: p, kind: metrics}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("schema", str(ctx.exception))

    def test_malformed_schema_fails_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts:\n  - id: p\n    kind: metrics\n    schema:\n"
                "      metrics: [{key: k, source: s, target: nope, direction: lower}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("target", str(ctx.exception))

    def test_writer_overlays_schema_on_fresh_and_loaded_state(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / "numbers"
        rdir.mkdir(parents=True)
        (rdir / "config.yml").write_text(_METRICS_CONFIG, encoding="utf-8")
        cfg = rc.load_role_config("numbers", base)
        part = cfg.parts[0]

        fresh = rp._load_part_state("numbers", part, base)
        self.assertEqual([m["key"] for m in fresh["schema"]["metrics"]], ["w", "s"])
        self.assertEqual(fresh["metrics"], [])

        # A stored state with a STALE target is re-overlaid from config on load.
        stale = dict(fresh)
        stale["schema"] = {"metrics": [{"key": "w", "source": "w_src", "target": 999,
                                        "direction": "lower", "unit": "kg"}],
                           "grounding": "records"}
        (rdir / "parts").mkdir(exist_ok=True)
        (rdir / "parts" / "nums.json").write_text(json.dumps(stale), encoding="utf-8")
        loaded = rp._load_part_state("numbers", part, base)
        self.assertEqual(loaded["schema"]["metrics"][0]["target"], 78)   # config wins


# =============================================================================
# Readings-injection lane — the full runner seam against real baselines on disk
# =============================================================================

class ReadingsLaneTest(unittest.TestCase):
    ROLE = "numbers"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.rdir = self.base / "_system" / "roles" / self.ROLE
        self.rdir.mkdir(parents=True)
        (self.rdir / "config.yml").write_text(_METRICS_CONFIG, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mkrec(self, *dates: str) -> None:
        d = self.base / "_records" / "biometric" / "garmin"
        d.mkdir(parents=True, exist_ok=True)
        for date in dates:
            (d / f"{date}.md").write_text(
                "---\ntype: biometric\ndevice: garmin\n---\nbody\n", encoding="utf-8")

    def _baselines(self, **metrics) -> None:
        d = self.base / "_system" / "state" / "biometric" / "garmin"
        d.mkdir(parents=True, exist_ok=True)
        (d / "baselines.json").write_text(
            json.dumps({"last_updated": "2026-07-09", "metrics": metrics}),
            encoding="utf-8")

    def _part(self) -> dict:
        return json.loads((self.rdir / "parts" / "nums.json").read_text(encoding="utf-8"))

    def _run(self, deltas=None, approve=False) -> dict:
        payload = None if approve else {"role_id": self.ROLE, "hook": "tick",
                                        "deltas": deltas or []}
        return rp.run(self.ROLE, payload, approve_coldstart=approve, base=self.base)

    def _bootstrap_live(self, deltas) -> None:
        self._run(deltas)            # cold-start stage
        self._run(approve=True)      # adopt live

    def test_readings_injected_and_computed_both_directions(self) -> None:
        self._mkrec("2026-07-08", "2026-07-09")
        self._baselines(
            w_src={"mu": 82.0, "sigma": 2.0, "n": 2, "window": 42,
                   "values": [{"date": "2026-07-08", "value": 83.0},
                              {"date": "2026-07-09", "value": 80.0}]},
            s_src={"mu": 6.5, "sigma": 0.5, "n": 2, "window": 28,
                   "values": [{"date": "2026-07-08", "value": 6.0},
                              {"date": "2026-07-09", "value": 7.0}]})
        self._bootstrap_live([{"part": "nums", "op": "refresh", "key": "w"},
                              {"part": "nums", "op": "refresh", "key": "s"}])
        stored = {m["key"]: m for m in self._part()["metrics"]}
        # lower: current 80 (latest in-remit reading), improving (< mu 82)
        self.assertEqual(stored["w"]["current"], 80.0)
        self.assertEqual(stored["w"]["trend"], "improving")
        self.assertEqual(stored["w"]["provenance"], ["[[2026-07-09]]"])
        # higher: current 7, improving (> mu 6.5)
        self.assertEqual(stored["s"]["current"], 7.0)
        self.assertEqual(stored["s"]["trend"], "improving")
        # state.md carries the computed gap under the config target.
        state_md = (self.rdir / "state.md").read_text(encoding="utf-8")
        self.assertIn("w: 80 kg → 78 kg · gap 2 kg", state_md)   # lower: still to lose
        self.assertIn("s: 7 h → 8 h · gap 1 h", state_md)        # higher: still to gain

    def test_watermark_rides_records_watermark(self) -> None:
        self._mkrec("2026-07-08", "2026-07-09")
        self._baselines(w_src={"mu": 82.0, "sigma": 2.0, "n": 2, "window": 42,
                               "values": [{"date": "2026-07-09", "value": 80.0}]})
        self._bootstrap_live([{"part": "nums", "op": "refresh", "key": "w"}])
        # The metrics part advances the SAME records watermark (no seam change): the
        # adopted reading's stem is the high-water mark.
        self.assertEqual(self._part()["seen_watermark"], "2026-07-09")

    def test_no_baselines_is_cold_start_no_data(self) -> None:
        self._mkrec("2026-07-09")                 # record exists, but no baselines file
        summary = self._run([{"part": "nums", "op": "refresh", "key": "w"},
                             {"part": "nums", "op": "refresh", "key": "s"}])
        self.assertEqual(summary["outcome"], "cold-start-staged")
        staged = {m["key"]: m for m in self._part()["staging"]["metrics"]}
        self.assertIsNone(staged["w"]["current"])          # honest no-data
        self.assertIsNone(staged["s"]["current"])

    def test_established_refresh_updates_from_new_reading(self) -> None:
        self._mkrec("2026-07-09")
        self._baselines(w_src={"mu": 82.0, "sigma": 2.0, "n": 1, "window": 42,
                               "values": [{"date": "2026-07-09", "value": 80.0}]})
        self._bootstrap_live([{"part": "nums", "op": "refresh", "key": "w"}])
        # A newer record + baseline value arrives; an established refresh recomputes.
        self._mkrec("2026-07-10")
        self._baselines(w_src={"mu": 79.0, "sigma": 2.0, "n": 2, "window": 42,
                               "values": [{"date": "2026-07-09", "value": 80.0},
                                          {"date": "2026-07-10", "value": 77.0}]})
        summary = self._run([{"part": "nums", "op": "refresh", "key": "w"}])
        self.assertEqual(summary["outcome"], "progress")
        stored = {m["key"]: m for m in self._part()["metrics"]}
        self.assertEqual(stored["w"]["current"], 77.0)          # latest reading
        self.assertEqual(stored["w"]["provenance"], ["[[2026-07-10]]"])

    def test_inject_readings_noop_for_non_reading_role(self) -> None:
        # A role whose parts do NOT declare REQUIRES_READINGS gets no readings lane —
        # the payload is returned unchanged (the flag, not the kind, drives dispatch).
        led_dir = self.base / "_system" / "roles" / "led"
        led_dir.mkdir(parents=True)
        (led_dir / "config.yml").write_text(
            "id: led\nparts: [{id: p, kind: ledger}]\n"
            "remit: {globs: [\"_records/biometric/garmin/**\"]}\n"
            "cadence: daily\nstatus: active\n", encoding="utf-8")
        cfg = rc.load_role_config("led", self.base)
        plugins = {p.id: rc.import_archetype(p.kind) for p in cfg.parts}
        payload = {"role_id": "led", "deltas": []}
        out = rp._inject_readings(cfg, plugins, payload, self.base)
        self.assertIs(out, payload)                        # unchanged, no readings key

    def test_metric_day_ref_matcher(self) -> None:
        self.assertEqual(rp._metric_day_ref("_records/biometric/garmin/2026-07-09.md"),
                         ("biometric", "garmin", "2026-07-09"))
        self.assertIsNone(rp._metric_day_ref("_records/meetings/2026-07-09.md"))
        self.assertIsNone(rp._metric_day_ref("_records/biometric/garmin/not-a-date.md"))


if __name__ == "__main__":
    unittest.main()
