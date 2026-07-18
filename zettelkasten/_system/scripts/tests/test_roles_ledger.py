"""Tests for roles_archetype_ledger.py — the Ledger archetype plugin.

Covers the validator (grounding rejects uncited citations, append-not-replace
refuses immutable/replacement fields, churn-guard trips on a wholesale rewrite,
status + archive_reason enforcement) and the pure persist transform (merge /
split / rename preserve history append-only and never mutate the input).

No I/O, no LLM — validate/persist are pure in-memory transforms.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_archetype_ledger as x  # noqa: E402
from roles_common import KeyMinter  # noqa: E402


def _item(key: str, *, title: str = "T", status: str = "active",
          provenance=None, first_seen: str = "2026-01-01") -> dict:
    return {
        "key": key,
        "title": title,
        "status": status,
        "anchor": None,
        "provenance": list(provenance if provenance is not None else [f"[[{key}-rec]]"]),
        "superseded_by": None,
        "first_seen": first_seen,
        "last_updated": first_seen,
    }


def _ledger(*items: dict, **top) -> dict:
    state = {
        "version": 1,
        "role_id": "r",
        "archetype": "ledger",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": 5,
        "identity_strictness": "strict",
        "items": list(items),
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


class LedgerValidatorTest(unittest.TestCase):
    # -- grounding --------------------------------------------------------

    def test_grounded_add_accepted(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "anchor": "project:minder", "status": "new",
             "provenance": ["[[rec-a]]"]},
        )
        res = x.validate(_ledger(), payload)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)
        self.assertEqual(res.rejections, ())

    def test_ungrounded_add_rejected(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "anchor": "project:minder", "status": "new",
             "provenance": ["[[rec-b]]"]},  # rec-b not in read_records
        )
        res = x.validate(_ledger(), payload)
        # Not blocking (empty prior), but the add is dropped as ungrounded.
        self.assertTrue(res.ok)
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.rejections), 1)
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_advance_evidence_grounded(self) -> None:
        prior = _ledger(_item("lk-0001", status="new"))
        payload = _payload(
            ["rec-x"],
            {"op": "advance", "key": "lk-0001", "to_status": "active",
             "evidence": ["[[rec-x]]"]},
        )
        res = x.validate(prior, payload)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_advance_evidence_ungrounded_rejected(self) -> None:
        prior = _ledger(_item("lk-0001", status="new"))
        payload = _payload(
            ["rec-x"],
            {"op": "advance", "key": "lk-0001", "to_status": "active",
             "evidence": ["[[rec-z]]"]},
        )
        res = x.validate(prior, payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    # -- append-not-replace ----------------------------------------------

    def test_add_first_seen_is_immutable(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "provenance": ["[[rec-a]]"], "first_seen": "2020-01-01"},
        )
        res = x.validate(_ledger(), payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("first_seen", res.rejections[0]["reason"])

    def test_mutating_op_cannot_carry_provenance(self) -> None:
        prior = _ledger(_item("lk-0001"))
        payload = _payload(
            ["rec-x"],
            {"op": "advance", "key": "lk-0001", "to_status": "done",
             "evidence": ["[[rec-x]]"], "provenance": ["[[rec-x]]"]},
        )
        res = x.validate(prior, payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("append-not-replace", res.rejections[0]["reason"])

    # -- status + archive_reason -----------------------------------------

    def test_add_archived_requires_reason(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "status": "archived", "provenance": ["[[rec-a]]"]},
        )
        res = x.validate(_ledger(), payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("archive_reason", res.rejections[0]["reason"])

    def test_add_archived_with_reason_accepted(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "status": "archived", "archive_reason": "dropped",
             "provenance": ["[[rec-a]]"]},
        )
        res = x.validate(_ledger(), payload)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 1)

    def test_advance_to_archived_requires_reason(self) -> None:
        prior = _ledger(_item("lk-0001"))
        payload = _payload(
            ["rec-x"],
            {"op": "advance", "key": "lk-0001", "to_status": "archived",
             "evidence": ["[[rec-x]]"]},
        )
        res = x.validate(prior, payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("archive_reason", res.rejections[0]["reason"])

    def test_body_cannot_set_engine_only_merged_status(self) -> None:
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "A",
             "status": "merged", "provenance": ["[[rec-a]]"]},
        )
        res = x.validate(_ledger(), payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("status", res.rejections[0]["reason"])

    # -- churn-guard ------------------------------------------------------

    def test_churn_guard_trips_on_all_keys_retired(self) -> None:
        prior = _ledger(_item("lk-0001"), _item("lk-0002"))
        payload = _payload(
            ["rec-x"],
            {"op": "merge", "keys": ["lk-0001", "lk-0002"],
             "into_title": "AB", "evidence": ["[[rec-x]]"]},
        )
        res = x.validate(prior, payload)
        self.assertFalse(res.ok)  # blocking hold — nothing persists
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.clarifications), 1)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_churn_guard_trips_over_threshold_new_adds(self) -> None:
        # Established ledger (one live item) + 6 grounded adds > threshold 5.
        prior = _ledger(_item("lk-0001"), churn_threshold=5)
        adds = [
            {"op": "add", "provisional_key": f"p{i}", "title": f"T{i}",
             "anchor": "project:minder", "provenance": ["[[rec-x]]"]}
            for i in range(6)
        ]
        res = x.validate(prior, _payload(["rec-x"], *adds))
        self.assertFalse(res.ok)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_no_churn_on_empty_prior_ledger(self) -> None:
        # Burst of adds over an empty ledger is cold-start, not churn.
        adds = [
            {"op": "add", "provisional_key": f"p{i}", "title": f"T{i}",
             "anchor": "project:minder", "provenance": ["[[rec-x]]"]}
            for i in range(8)
        ]
        res = x.validate(_ledger(), _payload(["rec-x"], *adds))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 8)

    def test_churn_guard_trips_on_mass_advance_to_archived(self) -> None:
        # Evasion guard (§11.8): advancing EVERY live item to `archived` empties
        # the live set without a single supersede/merge/split. It must still trip
        # the all-keys-touched churn hold. Three items keep total mutations (3)
        # below the threshold (5), so ONLY the all-keys-changed path can fire —
        # isolating the advance-into-changed-keys fix, not the volume path.
        prior = _ledger(_item("lk-0001"), _item("lk-0002"), _item("lk-0003"))
        deltas = [
            {"op": "advance", "key": k, "to_status": "archived",
             "archive_reason": "closed out", "evidence": ["[[rec-x]]"]}
            for k in ("lk-0001", "lk-0002", "lk-0003")
        ]
        res = x.validate(prior, _payload(["rec-x"], *deltas))
        self.assertFalse(res.ok)  # blocking hold — nothing persists
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(len(res.clarifications), 1)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_churn_guard_trips_on_mass_rename(self) -> None:
        # Evasion guard (§11.8): renaming EVERY live item touches all keys with no
        # retirement at all. It must trip the all-keys-touched hold. Three renames
        # (total mutations 3 < threshold 5) isolate the changed-keys path.
        prior = _ledger(_item("lk-0001"), _item("lk-0002"), _item("lk-0003"))
        deltas = [
            {"op": "rename", "key": k, "title": f"Renamed {k}"}
            for k in ("lk-0001", "lk-0002", "lk-0003")
        ]
        res = x.validate(prior, _payload([], *deltas))
        self.assertFalse(res.ok)
        self.assertEqual(res.approved_deltas, ())
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_small_normal_tick_does_not_trip_churn(self) -> None:
        # A small tick touching 1-2 of MANY live items is normal, not churn:
        # neither all-keys-changed (2 of 6) nor over-threshold (2 <= 5).
        prior = _ledger(*[_item(f"lk-000{i}") for i in range(1, 7)])
        deltas = [
            {"op": "advance", "key": "lk-0001", "to_status": "done",
             "evidence": ["[[rec-x]]"]},
            {"op": "rename", "key": "lk-0002", "title": "Tweaked"},
        ]
        res = x.validate(prior, _payload(["rec-x"], *deltas))
        self.assertTrue(res.ok)
        self.assertEqual(res.clarifications, ())
        self.assertEqual(len(res.approved_deltas), 2)

    def test_churn_guard_trips_on_mass_advance_volume(self) -> None:
        # Volume path (§11.8): a mass advance with zero adds must trip the
        # threshold on total mutations. Seven advances over a large ledger touch
        # only a subset of keys (so all-keys-changed is FALSE), isolating the
        # `total_mutations > threshold` path that the old new-adds-only count
        # missed entirely.
        prior = _ledger(*[_item(f"lk-{i:04d}") for i in range(1, 11)])
        deltas = [
            {"op": "advance", "key": f"lk-{i:04d}", "to_status": "done",
             "evidence": ["[[rec-x]]"]}
            for i in range(1, 8)  # 7 advances > threshold 5
        ]
        res = x.validate(prior, _payload(["rec-x"], *deltas))
        self.assertFalse(res.ok)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    # -- structural integrity --------------------------------------------

    def test_supersede_target_must_resolve(self) -> None:
        prior = _ledger(_item("lk-0001"))
        payload = _payload(
            ["rec-x"],
            {"op": "supersede", "key": "lk-0001", "by": "lk-9999",
             "evidence": ["[[rec-x]]"]},
        )
        res = x.validate(prior, payload)
        self.assertEqual(res.approved_deltas, ())
        self.assertIn("does not resolve", res.rejections[0]["reason"])

    def test_duplicate_prior_keys_block(self) -> None:
        prior = _ledger(_item("lk-0001"), _item("lk-0001"))
        res = x.validate(prior, _payload(["rec-x"]))
        self.assertFalse(res.ok)
        self.assertIn("duplicate keys", res.rejections[0]["reason"])


class LedgerPersistHistoryTest(unittest.TestCase):
    def _prior(self) -> dict:
        return _ledger(
            _item("lk-0001", title="A", provenance=["[[r1]]"], first_seen="2026-01-01"),
            _item("lk-0002", title="B", provenance=["[[r2]]"], first_seen="2026-02-01"),
        )

    def test_merge_preserves_history_append_only(self) -> None:
        prior = self._prior()
        prior_snapshot = copy.deepcopy(prior)
        delta = {"op": "merge", "keys": ["lk-0001", "lk-0002"],
                 "into_title": "AB", "evidence": ["[[r3]]"]}
        minter = KeyMinter.for_part(x, prior)  # next → 3
        new = x.persist(prior, [delta], minter)

        self.assertEqual(prior, prior_snapshot, "persist must not mutate its input")

        by_key = {it["key"]: it for it in new["items"]}
        merged = by_key["lk-0003"]
        self.assertEqual(merged["title"], "AB")
        self.assertEqual(merged["status"], "active")
        # first_seen is the min of the sources (history never blanks).
        self.assertEqual(merged["first_seen"], "2026-01-01")
        # provenance is the union of both sources plus the merge evidence.
        self.assertEqual(merged["provenance"], ["[[r1]]", "[[r2]]", "[[r3]]"])
        # sources retired into the successor with their trail intact.
        self.assertEqual(by_key["lk-0001"]["status"], "merged")
        self.assertEqual(by_key["lk-0001"]["superseded_by"], "lk-0003")
        self.assertEqual(by_key["lk-0001"]["provenance"], ["[[r1]]", "[[r3]]"])

    def test_split_children_carry_parent_history(self) -> None:
        prior = self._prior()
        delta = {"op": "split", "key": "lk-0001",
                 "into": [{"title": "X"}, {"title": "Y"}], "evidence": ["[[r3]]"]}
        minter = KeyMinter.for_part(x, prior)  # next → 3
        new = x.persist(prior, [delta], minter)

        by_key = {it["key"]: it for it in new["items"]}
        x_child, y_child = by_key["lk-0003"], by_key["lk-0004"]
        self.assertEqual((x_child["title"], y_child["title"]), ("X", "Y"))
        self.assertEqual(x_child["status"], "active")
        # children inherit the parent first_seen + provenance grown with evidence.
        self.assertEqual(x_child["first_seen"], "2026-01-01")
        self.assertEqual(x_child["provenance"], ["[[r1]]", "[[r3]]"])
        # parent retired, canonical pointer at the first child.
        self.assertEqual(by_key["lk-0001"]["status"], "merged")
        self.assertEqual(by_key["lk-0001"]["superseded_by"], "lk-0003")

    def test_rename_only_touches_title(self) -> None:
        prior = self._prior()
        delta = {"op": "rename", "key": "lk-0001", "title": "Renamed"}
        minter = KeyMinter.for_part(x, prior)
        new = x.persist(prior, [delta], minter)
        item = {it["key"]: it for it in new["items"]}["lk-0001"]
        self.assertEqual(item["title"], "Renamed")
        self.assertEqual(item["status"], "active")  # unchanged
        self.assertEqual(item["first_seen"], "2026-01-01")  # unchanged
        self.assertEqual(item["provenance"], ["[[r1]]"])  # unchanged

    def test_advance_grows_provenance(self) -> None:
        prior = self._prior()
        delta = {"op": "advance", "key": "lk-0001", "to_status": "done",
                 "evidence": ["[[r9]]"]}
        minter = KeyMinter.for_part(x, prior)
        new = x.persist(prior, [delta], minter)
        item = {it["key"]: it for it in new["items"]}["lk-0001"]
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["provenance"], ["[[r1]]", "[[r9]]"])


class LedgerSupersedePhantomTest(unittest.TestCase):
    """A supersede whose provisional successor was rejected must not corrupt the
    ledger — neither at validate (primary) nor at persist (defense-in-depth)."""

    def _prior(self) -> dict:
        return _ledger(
            _item("lk-0001", title="A", provenance=["[[r1]]"]),
            _item("lk-0002", title="B", provenance=["[[r2]]"]),
        )

    def test_supersede_by_rejected_add_is_rejected(self) -> None:
        # add p1 is ungrounded → rejected in Pass 1; the paired supersede cannot
        # resolve against a phantom successor and must itself be rejected, leaving
        # lk-0001 live (status unchanged, superseded_by null).
        prior = self._prior()
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p1", "title": "Ghost",
             "provenance": ["[[rec-b]]"]},  # rec-b not in read_records → ungrounded
            {"op": "supersede", "key": "lk-0001", "by": "p1",
             "evidence": ["[[rec-a]]"]},
        )
        res = x.validate(prior, payload)
        # Not blocking (bad deltas simply drop), but NOTHING is approved.
        self.assertTrue(res.ok)
        self.assertEqual(res.approved_deltas, ())
        reasons = " ".join(r["reason"] for r in res.rejections)
        self.assertIn("ungrounded", reasons)
        self.assertIn("does not resolve", reasons)

        # Persisting the approved (empty) set leaves lk-0001 live and clean, and
        # no item anywhere carries a non-`lk-` superseded_by (no phantom pointer).
        minter = KeyMinter.for_part(x, prior)
        new = x.persist(prior, res.approved_deltas, minter)
        by_key = {it["key"]: it for it in new["items"]}
        self.assertEqual(by_key["lk-0001"]["status"], "active")
        self.assertIsNone(by_key["lk-0001"]["superseded_by"])
        for it in new["items"]:
            sb = it.get("superseded_by")
            self.assertTrue(sb is None or str(sb).startswith("lk-"))

    def test_persist_never_writes_unresolved_provisional(self) -> None:
        # Defense-in-depth: even if a supersede with an unresolved provisional
        # `by` reached persist directly (validate bypassed), the source stays live
        # and no phantom pointer is written (empty provisional_map, `p1` absent).
        prior = self._prior()
        delta = {"op": "supersede", "key": "lk-0001", "by": "p1",
                 "evidence": ["[[r1]]"]}
        minter = KeyMinter.for_part(x, prior)
        new = x.persist(prior, [delta], minter)
        by_key = {it["key"]: it for it in new["items"]}
        self.assertEqual(by_key["lk-0001"]["status"], "active")
        self.assertIsNone(by_key["lk-0001"]["superseded_by"])

    def test_supersede_by_grounded_add_still_works(self) -> None:
        # Clean case: add p2 grounded → approved; the paired supersede resolves p2
        # to the minted key and retires lk-0001 into it (never the raw 'p2').
        prior = self._prior()
        payload = _payload(
            ["rec-a"],
            {"op": "add", "provisional_key": "p2", "title": "Successor",
             "anchor": "project:minder", "provenance": ["[[rec-a]]"]},
            {"op": "supersede", "key": "lk-0001", "by": "p2",
             "evidence": ["[[rec-a]]"]},
        )
        res = x.validate(prior, payload)
        self.assertTrue(res.ok)
        self.assertEqual(res.rejections, ())
        self.assertEqual(len(res.approved_deltas), 2)

        minter = KeyMinter.for_part(x, prior)  # next → 3
        new = x.persist(prior, res.approved_deltas, minter)
        by_key = {it["key"]: it for it in new["items"]}
        # p2 minted as lk-0003 and live (not retired).
        self.assertIn("lk-0003", by_key)
        self.assertTrue(x._is_live(by_key["lk-0003"]))
        self.assertIsNone(by_key["lk-0003"]["superseded_by"])
        # lk-0001 retired into the real minted successor, not the raw 'p2'.
        self.assertEqual(by_key["lk-0001"]["status"], "merged")
        self.assertEqual(by_key["lk-0001"]["superseded_by"], "lk-0003")


class LedgerRenderSupersededTest(unittest.TestCase):
    """render() must EXPOSE the `superseded_by` chain of a retired item in the
    state.md AUTO zone (C7). The ask path answers from state.md, so a query on a
    retired key can only resolve to its successor if that pointer is rendered.
    Confirms render shows the `→ superseded by {key}` pointer for merged/split
    items."""

    def test_render_exposes_superseded_by_for_merged_items(self) -> None:
        # Merge lk-0001 + lk-0002 → a fresh successor; both sources retire with a
        # `superseded_by` pointing at the minted successor.
        prior = _ledger(
            _item("lk-0001", title="A", provenance=["[[r1]]"]),
            _item("lk-0002", title="B", provenance=["[[r2]]"]),
        )
        delta = {"op": "merge", "keys": ["lk-0001", "lk-0002"],
                 "into_title": "AB", "evidence": ["[[r3]]"]}
        minter = KeyMinter.for_part(x, prior)  # next → 3
        new = x.persist(prior, [delta], minter)

        successor = next(it["key"] for it in new["items"] if it["title"] == "AB")
        rendered = x.render(new)

        # Each retired source exposes the forward pointer to the successor.
        self.assertIn(f"superseded by `{successor}`", rendered)
        # The pointer appears once per retired source (both lk-0001 + lk-0002).
        self.assertEqual(rendered.count(f"superseded by `{successor}`"), 2)
        # The chain is resolvable from the rendered text: a query on the retired
        # key lands on a line that names its successor.
        for retired in ("lk-0001", "lk-0002"):
            pointer_line = next(
                ln for ln in rendered.splitlines()
                if f"`{retired}`" in ln and "superseded by" in ln
            )
            self.assertIn(f"superseded by `{successor}`", pointer_line)

    def test_render_exposes_superseded_by_for_split_parent(self) -> None:
        # Split retires the parent with a `superseded_by` at the first child.
        prior = _ledger(_item("lk-0001", title="Parent", provenance=["[[r1]]"]))
        delta = {"op": "split", "key": "lk-0001",
                 "into": [{"title": "X"}, {"title": "Y"}], "evidence": ["[[r3]]"]}
        minter = KeyMinter.for_part(x, prior)  # next → 3
        new = x.persist(prior, [delta], minter)

        parent = {it["key"]: it for it in new["items"]}["lk-0001"]
        rendered = x.render(new)
        self.assertIn(f"superseded by `{parent['superseded_by']}`", rendered)


class LedgerFreshStateTest(unittest.TestCase):
    """`fresh_state()` is the single home for the archetype fresh-state defaults
    (§11.11) — churn_threshold / identity_strictness sourced here, not hardcoded
    in the common writer."""

    def test_fresh_state_carries_default_thresholds(self) -> None:
        state = x.fresh_state()
        self.assertEqual(state["churn_threshold"], x.DEFAULT_CHURN_THRESHOLD)
        self.assertEqual(state["identity_strictness"], x.DEFAULT_IDENTITY_STRICTNESS)
        self.assertEqual(state["archetype"], x.ARCHETYPE)
        self.assertEqual(state["version"], x.LEDGER_VERSION)
        self.assertEqual(state["items"], [])
        self.assertIsNone(state["seen_watermark"])
        self.assertIsNone(state["staging"])
        self.assertEqual(state["consecutive_rejects"], 0)

    def test_fresh_state_returns_independent_dicts(self) -> None:
        a = x.fresh_state()
        a["items"].append({"key": "lk-0001"})
        b = x.fresh_state()
        self.assertEqual(b["items"], [], "fresh_state must not share mutable state")


class LedgerEnrichedFieldsTest(unittest.TestCase):
    """The enriched planning fields (owner / priority / due_date / depends_on) at
    `add` time — accepted when well-formed, rejected (surfaced) when malformed."""

    def _add(self, **extra) -> dict:
        base = {"op": "add", "provisional_key": "p1", "title": "A",
                "anchor": "project:minder", "status": "new",
                "provenance": ["[[rec-a]]"]}
        base.update(extra)
        return base

    def test_add_with_planning_fields_accepted_and_seeded(self) -> None:
        payload = _payload(["rec-a"], self._add(
            owner="ivan", priority="high", due_date="2026-09-01"))
        res = x.validate(_ledger(), payload)
        self.assertTrue(res.ok)
        state = x.persist(_ledger(), res.approved_deltas, KeyMinter(1))
        item = state["items"][0]
        self.assertEqual(item["owner"], "ivan")
        self.assertEqual(item["priority"], "high")
        self.assertEqual(item["due_date"], "2026-09-01")
        self.assertEqual(item["depends_on"], [])

    def test_add_bad_priority_rejected(self) -> None:
        res = x.validate(_ledger(), _payload(["rec-a"], self._add(priority="urgent")))
        self.assertTrue(res.ok)  # non-blocking on empty prior
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("priority", res.rejections[0]["reason"])

    def test_add_bad_due_date_rejected(self) -> None:
        res = x.validate(_ledger(), _payload(["rec-a"], self._add(due_date="tomorrow")))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("due_date", res.rejections[0]["reason"])

    def test_add_depends_on_unknown_key_rejected(self) -> None:
        res = x.validate(_ledger(), _payload(["rec-a"], self._add(depends_on=["lk-0099"])))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("depends_on", res.rejections[0]["reason"])

    def test_add_depends_on_live_prior_key_accepted(self) -> None:
        prior = _ledger(_item("lk-0001", provenance=["[[rec-a]]"]))
        res = x.validate(prior, _payload(["rec-a"], self._add(depends_on=["lk-0001"])))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)

    def test_add_depends_on_retired_key_rejected(self) -> None:
        retired = _item("lk-0001", status="archived")
        retired["archive_reason"] = "done"
        prior = _ledger(retired)
        res = x.validate(prior, _payload(["rec-a"], self._add(depends_on=["lk-0001"])))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("retired", res.rejections[0]["reason"])

    def test_render_shows_planning_fields_only_when_set(self) -> None:
        plain = _item("lk-0001", title="Plain")
        rich = _item("lk-0002", title="Rich")
        rich.update({"owner": "ivan", "priority": "high", "due_date": "2026-09-01",
                     "depends_on": ["lk-0001"]})
        out = x.render(_ledger(plain, rich))
        self.assertIn("prio:high", out)
        self.assertIn("owner:ivan", out)
        self.assertIn("due:2026-09-01", out)
        self.assertIn("needs:lk-0001", out)
        # The plain item's line carries none of the planning bits.
        plain_line = [ln for ln in out.splitlines() if "Plain" in ln][0]
        for token in ("prio:", "owner:", "due:", "needs:"):
            self.assertNotIn(token, plain_line)

    def test_render_filters_retired_dependency(self) -> None:
        # A present-state board shows only LIVE blockers. `depends_on` is set-time
        # validated against live keys, but a dep retired afterward must NOT surface
        # in `needs:` (the set-time contract tolerates the stale reference; the
        # render filters it — the same `_is_live` predicate the validator uses).
        retired = _item("lk-0001", title="Done dep", status="archived")
        superseded = _item("lk-0002", title="Merged dep")
        superseded["superseded_by"] = "lk-0004"
        live = _item("lk-0003", title="Live dep")
        waiter = _item("lk-0009", title="Waiter")
        waiter["depends_on"] = ["lk-0001", "lk-0002", "lk-0003"]
        out = x.render(_ledger(retired, superseded, live, waiter))
        waiter_line = [ln for ln in out.splitlines() if "Waiter" in ln][0]
        # Only the live dependency survives; both retired forms are filtered out.
        self.assertIn("needs:lk-0003", waiter_line)
        self.assertNotIn("lk-0001", waiter_line)
        self.assertNotIn("lk-0002", waiter_line)

    def test_render_drops_needs_when_all_deps_retired(self) -> None:
        # If every dependency is retired, the `needs:` bit disappears entirely —
        # no empty `needs:` scaffold on the line.
        retired = _item("lk-0001", title="Done dep", status="merged")
        waiter = _item("lk-0009", title="Waiter")
        waiter["depends_on"] = ["lk-0001"]
        out = x.render(_ledger(retired, waiter))
        waiter_line = [ln for ln in out.splitlines() if "Waiter" in ln][0]
        self.assertNotIn("needs:", waiter_line)


class LedgerSetFieldTest(unittest.TestCase):
    """The `set-field` delta — grounded update of one planning field on a live item."""

    def _prior(self) -> dict:
        return _ledger(_item("lk-0001", title="A", provenance=["[[rec-a]]"]))

    def _sf(self, field: str, value, key: str = "lk-0001") -> dict:
        return {"op": "set-field", "key": key, "field": field, "value": value,
                "evidence": ["[[rec-a]]"]}

    def test_set_priority_persists_and_grows_provenance(self) -> None:
        payload = _payload(["rec-a", "rec-b"], {
            "op": "set-field", "key": "lk-0001", "field": "priority",
            "value": "high", "evidence": ["[[rec-b]]"]})
        res = x.validate(self._prior(), payload)
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(self._prior(), res.approved_deltas, KeyMinter(9))
        item = state["items"][0]
        self.assertEqual(item["priority"], "high")
        self.assertIn("[[rec-b]]", item["provenance"])
        self.assertIn("[[rec-a]]", item["provenance"])  # append-only, kept

    def test_set_owner_due_depends(self) -> None:
        prior = _ledger(
            _item("lk-0001", provenance=["[[rec-a]]"]),
            _item("lk-0002", provenance=["[[rec-a]]"]),
        )
        payload = _payload(["rec-a"],
            {"op": "set-field", "key": "lk-0002", "field": "owner",
             "value": "ivan", "evidence": ["[[rec-a]]"]},
            {"op": "set-field", "key": "lk-0002", "field": "depends_on",
             "value": ["lk-0001"], "evidence": ["[[rec-a]]"]})
        # Two set-fields target the SAME key → the second is a same-tick conflict.
        res = x.validate(prior, payload)
        self.assertEqual(len(res.approved_deltas), 1)
        self.assertIn("already mutated", res.rejections[0]["reason"])

    def test_set_field_unknown_key_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], self._sf("owner", "x", key="lk-0099")))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("does not exist", res.rejections[0]["reason"])

    def test_set_field_bad_field_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], self._sf("title", "x")))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("field", res.rejections[0]["reason"])

    def test_set_field_ungrounded_rejected(self) -> None:
        bad = {"op": "set-field", "key": "lk-0001", "field": "owner",
               "value": "x", "evidence": ["[[nope]]"]}
        res = x.validate(self._prior(), _payload(["rec-a"], bad))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("ungrounded", res.rejections[0]["reason"])

    def test_set_field_self_dependency_rejected(self) -> None:
        res = x.validate(self._prior(), _payload(["rec-a"], self._sf("depends_on", ["lk-0001"])))
        self.assertEqual(len(res.approved_deltas), 0)
        self.assertIn("self-dependency", res.rejections[0]["reason"])

    def test_impossible_date_rejected(self) -> None:
        # Shape-valid but calendar-impossible dates must be rejected, not rendered.
        for bad in ("2026-13-99", "2026-02-30", "2026-00-10"):
            res = x.validate(self._prior(), _payload(["rec-a"], self._sf("due_date", bad)))
            self.assertEqual(len(res.approved_deltas), 0, bad)
            self.assertIn("valid YYYY-MM-DD", res.rejections[0]["reason"])
        # A real date passes and persists.
        res = x.validate(self._prior(), _payload(["rec-a"], self._sf("due_date", "2026-02-28")))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)

    def test_depends_on_null_clears_uniform_with_other_fields(self) -> None:
        prior = _ledger(_item("lk-0001", provenance=["[[rec-a]]"]))
        prior["items"][0]["depends_on"] = ["lk-0001-x"]  # some prior value
        # null clears depends_on (same API as owner/priority/due_date).
        res = x.validate(prior, _payload(["rec-a"], self._sf("depends_on", None)))
        self.assertTrue(res.ok and len(res.approved_deltas) == 1)
        state = x.persist(prior, res.approved_deltas, KeyMinter(9))
        self.assertEqual(state["items"][0]["depends_on"], [])

    def test_full_board_set_field_matches_advance_semantics(self) -> None:
        # DECIDED behavior (locked): a set-field on every live item is treated like
        # a benign advance-to-live — it annotates work, it does not replace it, so it
        # is NOT a churn "changed_key". It trips ONLY via the volume path (> threshold).
        items = [_item(f"lk-{i:04d}", provenance=["[[rec-a]]"]) for i in range(1, 4)]
        prior = _ledger(*items, churn_threshold=3)
        exactly = [self._sf("owner", "x", key=f"lk-{i:04d}") for i in range(1, 4)]  # == threshold
        self.assertTrue(x.validate(prior, _payload(["rec-a"], *exactly)).ok)  # not held
        over = [self._sf("owner", "x", key=f"lk-{i:04d}") for i in range(1, 4)]
        over.append({"op": "add", "provisional_key": "p", "title": "N",
                     "anchor": "project:m", "status": "new", "provenance": ["[[rec-a]]"]})
        res = x.validate(prior, _payload(["rec-a"], *over))  # 4 mutations > 3
        self.assertFalse(res.ok)
        self.assertEqual(res.clarifications[0].ctype, "role-churn-guard")

    def test_same_tick_dangling_dep_is_set_time_contract(self) -> None:
        # DECIDED behavior (locked + documented): depends_on resolves against the
        # state BEFORE the tick. A dep set to a key retired in the SAME tick persists
        # as a (transiently) stale reference — depends_on is a planning hint, and
        # present-state consumers filter retired deps. The writer does not maintain
        # referential integrity of the hint.
        prior = _ledger(
            _item("lk-0001", provenance=["[[rec-a]]"]),
            _item("lk-0002", provenance=["[[rec-a]]"]),
        )
        res = x.validate(prior, _payload(["rec-a", "rec-b"],
            {"op": "set-field", "key": "lk-0001", "field": "depends_on",
             "value": ["lk-0002"], "evidence": ["[[rec-a]]"]},
            {"op": "advance", "key": "lk-0002", "to_status": "archived",
             "archive_reason": "done", "evidence": ["[[rec-b]]"]}))
        self.assertTrue(res.ok)
        self.assertEqual(len(res.approved_deltas), 2)  # both valid (set-time contract)


class LedgerSeamHooksTest(unittest.TestCase):
    """The composite-seam hooks the writer dispatches through."""

    def test_content_view_and_adopt_staging_round_trip(self) -> None:
        state = _ledger(_item("lk-0001", title="A"), _item("lk-0002", title="B"))
        content = x.content_view(state)
        self.assertEqual({it["key"] for it in content["items"]}, {"lk-0001", "lk-0002"})
        staging = {"drafted_at": "t", **content}
        adopted = x.adopt_staging(x.fresh_state(), staging)
        self.assertEqual({it["key"] for it in adopted["items"]}, {"lk-0001", "lk-0002"})

    def test_content_summary_and_consumed_records(self) -> None:
        state = _ledger(_item("lk-0001", title="A", provenance=["[[rec-a]]"]))
        self.assertEqual(x.content_summary(state), ["A"])
        self.assertEqual(list(x.consumed_records(state)), ["rec-a"])

    def test_gate_identity_holds_unanchored_under_strict(self) -> None:
        # fresh_state carries identity_strictness="strict" — the plugin sources it
        # from prior_state, the writer never passes it.
        add = {"op": "add", "provisional_key": "p1", "title": "A",
               "status": "new", "provenance": ["[[rec-a]]"]}  # no anchor
        kept, signals = x.gate_identity("r", "board", x.fresh_state(), [add])
        self.assertEqual(kept, [])  # held under strict
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].ctype, "role-new-key")

    def test_gate_identity_loose_persists_unanchored(self) -> None:
        prior = _ledger(identity_strictness="loose")
        add = {"op": "add", "provisional_key": "p1", "title": "A",
               "status": "new", "provenance": ["[[rec-a]]"]}  # no anchor
        kept, signals = x.gate_identity("r", "board", prior, [add])
        self.assertEqual(kept, [add])  # loose → persists unanchored
        self.assertEqual(len(signals), 1)  # but still surfaces role-new-key

    def test_gate_identity_passes_anchored(self) -> None:
        add = {"op": "add", "provisional_key": "p1", "title": "A",
               "anchor": "project:minder", "status": "new", "provenance": ["[[rec-a]]"]}
        kept, signals = x.gate_identity("r", "board", x.fresh_state(), [add])
        self.assertEqual(kept, [add])
        self.assertEqual(signals, [])

    def test_delta_counts(self) -> None:
        deltas = [
            {"op": "add"}, {"op": "add"}, {"op": "advance"}, {"op": "set-field"},
        ]
        self.assertEqual(x.delta_counts(deltas), (2, 2))

    def test_build_decisions_field_set_kind(self) -> None:
        prior = _ledger(_item("lk-0001", provenance=["[[rec-a]]"]))
        sf = {"op": "set-field", "key": "lk-0001", "field": "priority",
              "value": "high", "evidence": ["[[rec-a]]"]}
        rows = x.build_decisions([sf], [], prior, "r", "board", "tick", "2026-07-01T00:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "field-set")
        self.assertEqual(rows[0]["field"], "priority")
        self.assertEqual(rows[0]["part"], "board")


if __name__ == "__main__":
    unittest.main()
