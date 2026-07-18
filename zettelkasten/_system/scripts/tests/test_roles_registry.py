"""Tests for roles_archetype_registry.py — the Registry archetype plugin.

Covers the validator (records grounding rejects uncited citations, mode gating,
append-not-replace refuses engine-owned fields, schema conformance, churn-guard trips
on a catalog mutation/retire burst but EXEMPTS a log append burst), the pure persist
transform (catalog upsert add + update-by-key, grow-only field history, set-field,
retire flags-not-deletes, log append mints a fresh entry each time and never mutates
an existing one), the render (set fields only, grouped, retired flagged), the
composite-seam hooks (content_view/adopt round-trip, consumed_records, registry_summary,
build_decisions), and identity (exact-key, no anchor guessing).

A final block proves the config threading end-to-end: a registry part loads through the
REAL `roles_common._parse_parts`, a malformed schema fails closed, and the writer
overlays the schema onto fresh + loaded part state.

No I/O for the plugin tests — validate/persist are pure in-memory transforms.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_archetype_registry as x  # noqa: E402
import roles_common as rc  # noqa: E402
import roles_persist as rp  # noqa: E402
from roles_common import KeyMinter  # noqa: E402


_CATALOG_FIELDS = [
    {"name": "location", "type": "text"},
    {"name": "quantity", "type": "number"},
    {"name": "category", "type": "text"},
]


def _schema(key="item", fields=None, append_only=False,
            grounding="records", grounding_check=False) -> dict:
    return {
        "key": key,
        "fields": _CATALOG_FIELDS if fields is None else fields,
        "append_only": append_only,
        "grounding": grounding,
        "grounding_check": grounding_check,
    }


def _entry(key: str, fields=None, *, provenance=None, history=None,
           retired=False, retire_reason="", first_seen="2026-01-01") -> dict:
    entry = {
        "key": key,
        "fields": dict(fields or {}),
        "history": list(history or []),
        "provenance": list(provenance if provenance is not None else [f"[[{key}-rec]]"]),
        "retired": retired,
        "first_seen": first_seen,
        "last_updated": first_seen,
    }
    if retired:
        entry["retire_reason"] = retire_reason
    return entry


def _registry(schema: dict, *entries: dict, **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "registry",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": 5,
        "schema": schema,
        "entries": list(entries),
    }
    state.update(top)
    return state


def _payload(read_records, *deltas) -> dict:
    return {
        "role_id": "r",
        "hook": "tick",
        "read_records": list(read_records),
        "deltas": list(deltas),
    }


# =============================================================================
# Catalog mode
# =============================================================================

class CatalogUpsertTest(unittest.TestCase):
    def test_upsert_creates_new_entry_by_key(self) -> None:
        payload = _payload(["rec-a"], {
            "op": "upsert", "key": "drill",
            "fields": {"location": "garage", "quantity": 2}, "evidence": ["[[rec-a]]"]})
        res = x.validate(_registry(_schema()), payload)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)
        state = x.persist(_registry(_schema()), res.approved_deltas, None)
        self.assertEqual(len(state["entries"]), 1)
        entry = state["entries"][0]
        self.assertEqual(entry["key"], "drill")
        self.assertEqual(entry["fields"], {"location": "garage", "quantity": 2})
        self.assertFalse(entry["retired"])
        self.assertEqual(entry["provenance"], ["[[rec-a]]"])

    def test_upsert_updates_existing_entry_in_place(self) -> None:
        prior = _registry(_schema(),
                           _entry("drill", {"location": "shelf A"}, provenance=["[[r0]]"]))
        payload = _payload(["rec-a"], {
            "op": "upsert", "key": "drill",
            "fields": {"location": "shelf B"}, "evidence": ["[[rec-a]]"]})
        res = x.validate(prior, payload)
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(prior, res.approved_deltas, None)
        # Still ONE entry (updated in place by natural key), not a second.
        self.assertEqual(len(state["entries"]), 1)
        entry = state["entries"][0]
        self.assertEqual(entry["fields"]["location"], "shelf B")
        # provenance grew append-only.
        self.assertEqual(entry["provenance"], ["[[r0]]", "[[rec-a]]"])

    def test_upsert_update_grows_field_history(self) -> None:
        prior = _registry(_schema(),
                          _entry("drill", {"location": "shelf A"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "shelf B"},
            "evidence": ["[[rec-a]]"]}))
        state = x.persist(prior, res.approved_deltas, None)
        history = state["entries"][0]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["field"], "location")
        self.assertEqual(history[0]["from"], "shelf A")   # prior value preserved
        self.assertEqual(history[0]["to"], "shelf B")

    def test_repeated_updates_accumulate_grow_only_history(self) -> None:
        prior = _registry(_schema(),
                          _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        state = prior
        for loc, rec in (("B", "rec-b"), ("C", "rec-c")):
            res = x.validate(state, _payload([rec], {
                "op": "upsert", "key": "drill", "fields": {"location": loc},
                "evidence": [f"[[{rec}]]"]}))
            state = x.persist(state, res.approved_deltas, None)
        entry = state["entries"][0]
        self.assertEqual(entry["fields"]["location"], "C")
        # The whole A→B→C trail survives (grow-only, never blanked).
        self.assertEqual([(h["from"], h["to"]) for h in entry["history"]],
                         [("A", "B"), ("B", "C")])

    def test_upsert_noop_value_does_not_grow_history(self) -> None:
        prior = _registry(_schema(),
                          _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "A"},  # unchanged
            "evidence": ["[[rec-a]]"]}))
        state = x.persist(prior, res.approved_deltas, None)
        self.assertEqual(state["entries"][0]["history"], [])  # no real change → no history

    def test_persist_does_not_mutate_input(self) -> None:
        prior = _registry(_schema(),
                          _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        snapshot = copy.deepcopy(prior)
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "B"},
            "evidence": ["[[rec-a]]"]}))
        x.persist(prior, res.approved_deltas, None)
        self.assertEqual(prior, snapshot, "persist must not mutate its input")


class CatalogSetFieldTest(unittest.TestCase):
    def _prior(self) -> dict:
        return _registry(_schema(),
                        _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))

    def test_set_field_updates_one_field_and_grows_history(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], {
            "op": "set-field", "key": "drill", "field": "quantity", "value": 5,
            "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(self._prior(), res.approved_deltas, None)
        entry = state["entries"][0]
        self.assertEqual(entry["fields"]["quantity"], 5)
        self.assertEqual(entry["fields"]["location"], "A")   # untouched
        self.assertEqual(entry["history"][0]["field"], "quantity")

    def test_set_field_unknown_key_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], {
            "op": "set-field", "key": "nope", "field": "quantity", "value": 1,
            "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_set_field_undeclared_field_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], {
            "op": "set-field", "key": "drill", "field": "colour", "value": "red",
            "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("declared field", res.rejections[0]["reason"])

    def test_set_field_bad_number_type_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], {
            "op": "set-field", "key": "drill", "field": "quantity", "value": "lots",
            "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("number", res.rejections[0]["reason"])

    def test_set_field_null_clears(self) -> None:
        prior = _registry(_schema(),
                         _entry("drill", {"location": "A", "quantity": 3}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "set-field", "key": "drill", "field": "quantity", "value": None,
            "evidence": ["[[rec-a]]"]}))
        state = x.persist(prior, res.approved_deltas, None)
        self.assertNotIn("quantity", state["entries"][0]["fields"])   # cleared
        self.assertEqual(state["entries"][0]["history"][0]["to"], None)


class CatalogRetireTest(unittest.TestCase):
    def test_retire_flags_not_deletes(self) -> None:
        prior = _registry(_schema(),
                         _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "retire", "key": "drill", "reason": "gave it away",
            "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(prior, res.approved_deltas, None)
        # The entry is STILL there (flagged), never deleted.
        self.assertEqual(len(state["entries"]), 1)
        entry = state["entries"][0]
        self.assertTrue(entry["retired"])
        self.assertEqual(entry["retire_reason"], "gave it away")
        self.assertEqual(entry["provenance"], ["[[r0]]", "[[rec-a]]"])

    def test_retire_requires_reason(self) -> None:
        prior = _registry(_schema(), _entry("drill", provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "retire", "key": "drill", "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("reason", res.rejections[0]["reason"])

    def test_retire_unknown_key_rejected(self) -> None:
        prior = _registry(_schema(), _entry("drill", provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "retire", "key": "hammer", "reason": "x", "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_upsert_of_retired_key_creates_new_live_entry(self) -> None:
        # A retired entry is "gone"; a fresh upsert of the same key makes a NEW live
        # entry (the retired one stays as history — never revived, never deleted).
        prior = _registry(_schema(),
                         _entry("drill", {"location": "A"}, provenance=["[[r0]]"],
                                retired=True, retire_reason="lost"))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "B"},
            "evidence": ["[[rec-a]]"]}))
        state = x.persist(prior, res.approved_deltas, None)
        self.assertEqual(len(state["entries"]), 2)
        live = [e for e in state["entries"] if not e["retired"]]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["fields"]["location"], "B")


class CatalogModeGatingTest(unittest.TestCase):
    def test_append_rejected_on_catalog(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "append", "key": "drill", "fields": {}, "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("catalog registry", res.rejections[0]["reason"])

    def test_same_key_touched_twice_conflict(self) -> None:
        prior = _registry(_schema(), _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"],
            {"op": "set-field", "key": "drill", "field": "location", "value": "B",
             "evidence": ["[[rec-a]]"]},
            {"op": "set-field", "key": "drill", "field": "quantity", "value": 1,
             "evidence": ["[[rec-a]]"]}))
        self.assertEqual(len(res.approved_deltas), 1)
        self.assertIn("already created/mutated", res.rejections[0]["reason"])

    def test_engine_owned_field_refused(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {}, "provenance": ["[[rec-a]]"],
            "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("append-not-replace", res.rejections[0]["reason"])

    def test_undeclared_field_in_upsert_rejected(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"colour": "red"},
            "evidence": ["[[rec-a]]"]}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("not in the declared schema", res.rejections[0]["reason"])


# =============================================================================
# Log mode
# =============================================================================

def _log_schema(**kw) -> dict:
    kw.setdefault("key", "ts")
    kw.setdefault("fields", [{"name": "meal", "type": "text"},
                             {"name": "kcal", "type": "number"}])
    kw["append_only"] = True
    return _schema(**kw)


class LogAppendTest(unittest.TestCase):
    def test_append_mints_a_fresh_entry_each_time(self) -> None:
        prior = _registry(_log_schema())
        res = x.validate(prior, _payload(["rec-a"],
            {"op": "append", "key": "2026-07-01", "fields": {"meal": "eggs"},
             "evidence": ["[[rec-a]]"]},
            {"op": "append", "key": "2026-07-01", "fields": {"meal": "toast"},
             "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok and len(res.approved_deltas) == 2)
        state = x.persist(prior, res.approved_deltas, None)
        # Two DISTINCT entries even though they share the same natural key (a log
        # never dedups by key — every append is fresh).
        self.assertEqual(len(state["entries"]), 2)
        self.assertEqual([e["fields"]["meal"] for e in state["entries"]], ["eggs", "toast"])

    def test_append_never_updates_an_existing_entry(self) -> None:
        prior = _registry(_log_schema(),
                         _entry("2026-07-01", {"meal": "eggs"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "append", "key": "2026-07-01", "fields": {"meal": "lunch"},
            "evidence": ["[[rec-a]]"]}))
        state = x.persist(prior, res.approved_deltas, None)
        self.assertEqual(len(state["entries"]), 2)
        # The prior entry is untouched — no in-place mutation in a log.
        self.assertEqual(state["entries"][0]["fields"]["meal"], "eggs")
        self.assertEqual(state["entries"][0]["history"], [])

    def test_upsert_and_set_field_rejected_on_log(self) -> None:
        prior = _registry(_log_schema(),
                         _entry("2026-07-01", {"meal": "eggs"}, provenance=["[[r0]]"]))
        for op, delta in (
            ("upsert", {"op": "upsert", "key": "2026-07-01", "fields": {"meal": "x"},
                        "evidence": ["[[rec-a]]"]}),
            ("set-field", {"op": "set-field", "key": "2026-07-01", "field": "meal",
                           "value": "x", "evidence": ["[[rec-a]]"]}),
        ):
            res = x.validate(prior, _payload(["rec-a"], delta))
            self.assertEqual(res.approved_deltas, (), op)
            self.assertIn("append-only registry", res.rejections[0]["reason"], op)

    def test_retire_allowed_on_log(self) -> None:
        prior = _registry(_log_schema(),
                         _entry("2026-07-01", {"meal": "eggs"}, provenance=["[[r0]]"]))
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "retire", "key": "2026-07-01", "reason": "mis-logged",
            "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(prior, res.approved_deltas, None)
        self.assertTrue(state["entries"][0]["retired"])

    def test_churn_exempts_a_log_append_burst(self) -> None:
        # An ESTABLISHED log (one live entry) with a big fresh-append burst must NOT
        # trip the churn guard — a busy logging day is normal (§1). Ten appends over a
        # threshold of 5 stay accepted because appends are exempt from the count.
        prior = _registry(_log_schema(),
                         _entry("2026-07-00", {"meal": "seed"}, provenance=["[[r0]]"]),
                         churn_threshold=5)
        deltas = [{"op": "append", "key": f"2026-07-{i:02d}", "fields": {"meal": f"m{i}"},
                   "evidence": ["[[rec-a]]"]} for i in range(1, 11)]
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertTrue(res.ok)
        self.assertEqual(res.clarifications, ())
        self.assertEqual(len(res.approved_deltas), 10)

    def test_churn_trips_on_log_retire_burst(self) -> None:
        # Retires DO count toward the log's churn — retiring every live entry is a
        # wholesale rewrite and is held.
        entries = [_entry(f"2026-07-0{i}", {"meal": f"m{i}"}, provenance=["[[r0]]"])
                   for i in range(1, 4)]
        prior = _registry(_log_schema(), *entries, churn_threshold=5)
        deltas = [{"op": "retire", "key": f"2026-07-0{i}", "reason": "purge",
                   "evidence": ["[[rec-a]]"]} for i in range(1, 4)]
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertFalse(res.ok)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")


# =============================================================================
# Grounding (records)
# =============================================================================

class GroundingTest(unittest.TestCase):
    def test_uncited_op_rejected(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "A"},
            "evidence": ["[[rec-b]]"]}))  # rec-b not in read_records
        self.assertTrue(res.ok)  # non-blocking on empty prior; the op is dropped
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_missing_evidence_rejected(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "A"}}))
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("evidence", res.rejections[0]["reason"])

    def test_cited_op_accepted(self) -> None:
        res = x.validate(_registry(_schema()), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "A"},
            "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)


# =============================================================================
# Churn-guard (catalog)
# =============================================================================

class CatalogChurnTest(unittest.TestCase):
    def test_no_churn_on_empty_catalog(self) -> None:
        # A burst of creates over an empty registry is cold-start, not churn.
        deltas = [{"op": "upsert", "key": f"k{i}", "fields": {"location": "A"},
                   "evidence": ["[[rec-a]]"]} for i in range(8)]
        res = x.validate(_registry(_schema()), _payload(["rec-a"], *deltas))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 8)

    def test_churn_trips_on_retire_burst_all_keys(self) -> None:
        # Retiring EVERY live entry is a wholesale rewrite → all-keys-changed hold,
        # even below the volume threshold (3 retires < 5).
        entries = [_entry(f"k{i}", {"location": "A"}, provenance=["[[r0]]"]) for i in range(3)]
        prior = _registry(_schema(), *entries, churn_threshold=5)
        deltas = [{"op": "retire", "key": f"k{i}", "reason": "gone",
                   "evidence": ["[[rec-a]]"]} for i in range(3)]
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertFalse(res.ok)
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_churn_trips_over_volume_threshold(self) -> None:
        # Established catalog (one live entry) + 6 new creates > threshold 5 → volume
        # hold (mirrors the ledger burst guard).
        prior = _registry(_schema(), _entry("seed", provenance=["[[r0]]"]),
                         churn_threshold=5)
        deltas = [{"op": "upsert", "key": f"n{i}", "fields": {"location": "A"},
                   "evidence": ["[[rec-a]]"]} for i in range(6)]
        res = x.validate(prior, _payload(["rec-a"], *deltas))
        self.assertFalse(res.ok)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_small_normal_tick_does_not_trip(self) -> None:
        prior = _registry(_schema(), *[_entry(f"k{i}", provenance=["[[r0]]"]) for i in range(6)])
        res = x.validate(prior, _payload(["rec-a"],
            {"op": "set-field", "key": "k0", "field": "location", "value": "A",
             "evidence": ["[[rec-a]]"]},
            {"op": "retire", "key": "k1", "reason": "gone", "evidence": ["[[rec-a]]"]}))
        self.assertTrue(res.ok)
        self.assertEqual(res.clarifications, ())
        self.assertEqual(len(res.approved_deltas), 2)


# =============================================================================
# Render
# =============================================================================

class RenderTest(unittest.TestCase):
    def test_empty_state(self) -> None:
        self.assertEqual(x.render(_registry(_schema())), "_No entries yet._")

    def test_render_shows_only_set_fields_grouped_by_category(self) -> None:
        prior = _registry(_schema(),
            _entry("drill", {"location": "shelf A", "quantity": 2, "category": "power"}),
            _entry("hammer", {"location": "box", "category": "hand"}),
            _entry("bare", {}))  # no fields set
        out = x.render(prior)
        # Grouped by the declared `category` field (with a "—" group for unset).
        self.assertIn("### power", out)
        self.assertIn("### hand", out)
        self.assertIn("### —", out)
        # Only SET fields appear; the category is the group header, not repeated inline.
        drill_line = [ln for ln in out.splitlines() if "drill" in ln][0]
        self.assertIn("location:shelf A", drill_line)
        self.assertIn("quantity:2", drill_line)
        self.assertNotIn("category:", drill_line)
        # The bare entry has no field bits.
        bare_line = [ln for ln in out.splitlines() if "bare" in ln][0]
        self.assertNotIn("location:", bare_line)

    def test_render_flags_retired(self) -> None:
        prior = _registry(_schema(),
            _entry("drill", {"location": "A"}, retired=True, retire_reason="lost"))
        out = x.render(prior)
        self.assertIn("retired (lost)", out)

    def test_render_flat_when_no_category_field(self) -> None:
        schema = _schema(fields=[{"name": "note", "type": "text"}])
        prior = _registry(schema, _entry("a", {"note": "x"}), _entry("b", {"note": "y"}))
        out = x.render(prior)
        self.assertNotIn("###", out)  # no grouping headers
        self.assertIn("- a · note:x", out)
        self.assertIn("- b · note:y", out)


# =============================================================================
# Identity — exact key, no anchor guessing
# =============================================================================

class IdentityTest(unittest.TestCase):
    def test_identity_is_anchored_never_fabricates(self) -> None:
        result = x.identity({"key": "drill"})
        self.assertTrue(result.anchored)
        self.assertIsNone(result.anchor)
        self.assertFalse(result.needs_hitl)

    def test_gate_identity_is_passthrough(self) -> None:
        add = {"op": "upsert", "key": "drill", "fields": {}, "evidence": ["[[rec-a]]"]}
        kept, signals = x.gate_identity("r", "tools", _registry(_schema()), [add])
        self.assertEqual(kept, [add])
        self.assertEqual(signals, [])


# =============================================================================
# Composite-seam hooks
# =============================================================================

class SeamHooksTest(unittest.TestCase):
    def test_known_key_numbers_empty(self) -> None:
        state = _registry(_schema(), _entry("drill"))
        self.assertEqual(list(x.known_key_numbers(state)), [])

    def test_content_view_and_adopt_staging_round_trip(self) -> None:
        state = _registry(_schema(), _entry("drill", {"location": "A"}),
                        _entry("hammer", {"location": "B"}))
        content = x.content_view(state)
        self.assertEqual({e["key"] for e in content["entries"]}, {"drill", "hammer"})
        staging = {"drafted_at": "t", **content}
        # Adopt onto a fresh state that carries the (config-overlaid) schema.
        fresh = _registry(_schema())
        adopted = x.adopt_staging(fresh, staging)
        self.assertEqual({e["key"] for e in adopted["entries"]}, {"drill", "hammer"})
        # The schema survives adoption (not frozen into staging — comes from prior).
        self.assertEqual(adopted["schema"]["key"], "item")

    def test_content_summary_and_consumed_records(self) -> None:
        state = _registry(_schema(),
            _entry("drill", {"location": "A"}, provenance=["[[rec-a]]", "[[rec-b]]"]),
            _entry("gone", {}, provenance=["[[rec-c]]"], retired=True, retire_reason="x"))
        summary = x.content_summary(state)
        self.assertEqual(summary[0], "drill: location=A")
        self.assertTrue(summary[1].endswith("(retired)"))
        self.assertEqual(sorted(x.consumed_records(state)), ["rec-a", "rec-b", "rec-c"])

    def test_registry_summary(self) -> None:
        state = _registry(_schema(),
            _entry("a"), _entry("b"),
            _entry("c", retired=True, retire_reason="x"))
        summary = x.registry_summary(state)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["breakdown"], [["live", 2], ["retired", 1]])
        self.assertEqual(summary["staged"], 0)

    def test_registry_summary_counts_staged(self) -> None:
        state = _registry(_schema(), staging={"drafted_at": "t",
                                              "entries": [_entry("a"), _entry("b")]})
        self.assertEqual(x.registry_summary(state)["staged"], 2)

    def test_delta_counts(self) -> None:
        deltas = [{"op": "upsert"}, {"op": "append"}, {"op": "set-field"}, {"op": "retire"}]
        self.assertEqual(x.delta_counts(deltas), (2, 2))

    def test_build_decisions_kinds(self) -> None:
        prior = _registry(_schema(), _entry("drill", {"location": "A"}, provenance=["[[r0]]"]))
        deltas = [
            {"op": "upsert", "key": "drill", "fields": {"location": "B"}, "evidence": ["[[rec-a]]"]},
            {"op": "upsert", "key": "hammer", "fields": {}, "evidence": ["[[rec-a]]"]},
            {"op": "set-field", "key": "drill", "field": "quantity", "value": 2, "evidence": ["[[rec-a]]"]},
            {"op": "retire", "key": "drill", "reason": "gone", "evidence": ["[[rec-a]]"]},
        ]
        rows = x.build_decisions(deltas, [], prior, "r", "tools", "tick",
                                 "2026-07-01T00:00:00Z")
        kinds = [r["kind"] for r in rows]
        # drill exists → entry-update; hammer is new → entry-create.
        self.assertEqual(kinds, ["entry-update", "entry-create", "entry-field-set", "entry-retire"])
        self.assertTrue(all(r["part"] == "tools" for r in rows))
        self.assertEqual(rows[0]["key"], "drill")

    def test_build_decisions_append_kind(self) -> None:
        rows = x.build_decisions(
            [{"op": "append", "key": "2026-07-01", "fields": {}, "evidence": ["[[rec-a]]"]}],
            [], _registry(_log_schema()), "r", "diary", "tick", "2026-07-01T00:00:00Z")
        self.assertEqual(rows[0]["kind"], "entry-append")
        self.assertEqual(rows[0]["key"], "2026-07-01")  # natural key carried

    def test_cold_materialize_decisions(self) -> None:
        state = _registry(_schema(), _entry("a", provenance=["[[rec-a]]"]), _entry("b"))
        rows = x.cold_materialize_decisions(state, "r", "tools", "2026-07-01T00:00:00Z")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["kind"] == "cold-materialize" for r in rows))
        self.assertEqual(rows[0]["key"], "a")

    def test_persist_ignores_key_minter(self) -> None:
        # Registry mints no lk key — persist must not consume the minter.
        prior = _registry(_schema())
        res = x.validate(prior, _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "A"},
            "evidence": ["[[rec-a]]"]}))
        minter = KeyMinter(1)
        x.persist(prior, res.approved_deltas, minter)
        self.assertEqual(minter.peek(), "lk-0001")  # never minted


# =============================================================================
# Config threading — the honest writer delta (real _parse_parts + writer overlay)
# =============================================================================

_REGISTRY_CONFIG = """id: keeper
name: Workshop Keeper
parts:
  - id: tools
    kind: registry
    schema:
      key: item
      fields:
        - {name: location, type: text}
        - {name: quantity, type: number}
        - {name: category, type: text}
      append_only: false
      grounding: records
      grounding_check: false
cadence: weekly
cadence_anchor: monday
status: active
schema_version: 2
remit:
  globs: ["1_projects/**"]
"""


class RegistryConfigThreadingTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "config.yml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_registry_part_loads_through_real_parse_parts(self) -> None:
        cfg = rc.load_role_config_file(self._write(_REGISTRY_CONFIG))
        self.assertEqual(cfg.part_ids, ("tools",))
        part = cfg.parts[0]
        self.assertEqual(part.kind, "registry")
        self.assertFalse(part.append_only)
        self.assertEqual(part.grounding, "records")
        self.assertFalse(part.grounding_check)
        self.assertEqual(part.schema["key"], "item")
        self.assertEqual([f["name"] for f in part.schema["fields"]],
                         ["location", "quantity", "category"])
        # The canonical schema the plugin reads carries the mode flags too.
        self.assertEqual(part.schema["append_only"], False)
        self.assertEqual(part.schema["grounding"], "records")

    def test_ledger_part_unaffected_defaults(self) -> None:
        cfg = rc.load_role_config_file(self._write(
            "id: r\nparts: [{id: p, kind: ledger}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        part = cfg.parts[0]
        self.assertEqual(part.schema, {})       # no schema for a non-registry kind
        self.assertEqual(part.grounding, "records")
        self.assertFalse(part.append_only)

    def test_missing_schema_fails_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts: [{id: p, kind: registry}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("schema", str(ctx.exception))

    def test_malformed_schema_missing_key_fails_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts:\n  - id: p\n    kind: registry\n    schema:\n"
                "      fields: [{name: x, type: text}]\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("key", str(ctx.exception))

    def test_malformed_schema_bad_fields_fails_closed(self) -> None:
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts:\n  - id: p\n    kind: registry\n    schema:\n"
                "      key: item\n      fields: []\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("fields", str(ctx.exception))

    def test_unsupported_grounding_fails_closed(self) -> None:
        # `external` (tool-pull) is a reserved Layer-2 seam, not accepted in this build;
        # records + owner-confirm are. An unsupported mode fail-closes, never degrades.
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self._write(
                "id: r\nparts:\n  - id: p\n    kind: registry\n    schema:\n"
                "      key: item\n      fields: [{name: x, type: text}]\n"
                "      grounding: external\n"
                "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertIn("grounding", str(ctx.exception))

    def test_owner_confirm_grounding_accepted(self) -> None:
        cfg = rc.load_role_config_file(self._write(
            "id: r\nparts:\n  - id: p\n    kind: registry\n    schema:\n"
            "      key: item\n      fields: [{name: loc, type: text}]\n"
            "      grounding: owner-confirm\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"))
        self.assertEqual(cfg.parts[0].grounding, "owner-confirm")

    def test_writer_overlays_schema_on_fresh_and_loaded_state(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        rdir = base / "_system" / "roles" / "keeper"
        rdir.mkdir(parents=True)
        (rdir / "config.yml").write_text(_REGISTRY_CONFIG, encoding="utf-8")
        cfg = rc.load_role_config("keeper", base)
        part = cfg.parts[0]

        # Fresh (no state file yet) — the schema is overlaid onto the seed.
        fresh = rp._load_part_state("keeper", part, base)
        self.assertEqual(fresh["schema"]["key"], "item")
        self.assertEqual(fresh["part_id"], "tools")
        self.assertEqual(fresh["entries"], [])

        # A stored state with a STALE schema is re-overlaid from config on load
        # (config is the source of truth — an owner edit propagates).
        stale = dict(fresh)
        stale["schema"] = {"key": "OLD", "fields": [], "append_only": True,
                           "grounding": "records", "grounding_check": False}
        (rdir / "parts").mkdir(exist_ok=True)
        (rdir / "parts" / "tools.json").write_text(json.dumps(stale), encoding="utf-8")
        loaded = rp._load_part_state("keeper", part, base)
        self.assertEqual(loaded["schema"]["key"], "item")   # config wins over disk
        self.assertFalse(loaded["schema"]["append_only"])


class RegistryOwnerConfirmTest(unittest.TestCase):
    """`owner-confirm` grounding: a role NEVER auto-writes an uncited owner-fact — it
    surfaces `role-owner-confirm`; a record-cited op writes exactly like records mode."""

    def _oc(self) -> dict:
        return _registry(_schema(grounding="owner-confirm"))

    def test_uncited_op_is_proposed_not_written(self) -> None:
        # No read_records → the upsert cannot cite a record. It must NOT be written and
        # must NOT be a rejection (no auto-pause pressure) — it surfaces for the owner.
        res = x.validate(self._oc(), _payload([], {
            "op": "upsert", "key": "drill", "fields": {"location": "garage"},
        }))
        self.assertTrue(res.ok)
        self.assertEqual(res.approved_deltas, ())            # nothing written
        self.assertEqual(res.rejections, ())                 # not a reject
        self.assertEqual(len(res.clarifications), 1)
        self.assertEqual(res.clarifications[0].ctype, "role-owner-confirm")
        self.assertIn("drill", res.clarifications[0].context)

    def test_cited_op_writes_in_owner_confirm_mode(self) -> None:
        res = x.validate(self._oc(), _payload(["rec-a"], {
            "op": "upsert", "key": "drill", "fields": {"location": "garage"},
            "evidence": ["[[rec-a]]"],
        }))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)        # written (records-grounded)
        self.assertEqual(res.clarifications, ())

    def test_mixed_tick_writes_cited_proposes_uncited(self) -> None:
        res = x.validate(self._oc(), _payload(["rec-a"],
            {"op": "upsert", "key": "saw", "fields": {"location": "shed"},
             "evidence": ["[[rec-a]]"]},
            {"op": "upsert", "key": "ladder", "fields": {"location": "loft"}}))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)        # only the cited one writes
        self.assertEqual(res.approved_deltas[0]["key"], "saw")
        self.assertEqual(len(res.clarifications), 1)         # the uncited one proposed
        self.assertIn("ladder", res.clarifications[0].context)

    def test_records_mode_still_rejects_uncited(self) -> None:
        # The default (records) mode is UNCHANGED by the owner-confirm branch.
        res = x.validate(_registry(_schema()), _payload([], {
            "op": "upsert", "key": "drill", "fields": {"location": "garage"},
        }))
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.rejections), 1)             # rejected, not proposed
        self.assertEqual(res.clarifications, ())


if __name__ == "__main__":
    unittest.main()
