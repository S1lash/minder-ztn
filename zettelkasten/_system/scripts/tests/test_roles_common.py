"""Tests for roles_common.py foundation primitives.

Isolated to a tempdir CLARIFICATIONS.md — no env mutation, no LLM, no network.
Focuses on the four regression-prone seams:

  - dedup survives an interleaved producer sub-group H2 (`## process …`)
    prepended above the role block — the frozen question must not re-insert;
  - a read failure on an EXISTING queue raises instead of overwriting it;
  - an owner subject carrying the word «resolved» emits fine (the RESOLVED
    guard is on the engine-controlled ctype/title_hint only);
  - `as_str_list` coercion — the single home for string-list coercion.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_common as rc  # noqa: E402


_EMIT_KW = dict(
    ctype="role-cold-start",
    subject="minder-pm cold start",
    context="First tick over an empty ledger.",
    source="ztn-roles tick",
    suggested_action="Approve the frozen draft.",
    action_taken="Held frozen draft in staging.",
)


class DedupInterleavedProducerH2Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "CLARIFICATIONS.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dedup_survives_interleaved_producer_h2(self) -> None:
        # First emit — writes the role block under `## Open Items`.
        self.assertTrue(rc.emit_clarification(path=self.path, **_EMIT_KW))
        marker = rc._dedup_marker(_EMIT_KW["ctype"], _EMIT_KW["subject"])
        self.assertEqual(self.path.read_text(encoding="utf-8").count(marker), 1)

        # A producer (process / lint) prepends its own sub-group H2 INSIDE Open
        # Items, above the role block — the classic interleave that the old
        # first-`## ` span bound missed.
        text = self.path.read_text(encoding="utf-8")
        needle = "## Open Items\n"
        idx = text.index(needle) + len(needle)
        producer = "\n## process 2026-07-11 batch\n\n- some producer item\n"
        tampered = text[:idx] + producer + text[idx:]
        with open(self.path, "w", encoding="utf-8", newline="\n") as _f:
            _f.write(tampered)

        # Re-emit the SAME frozen question — dedup must fire (marker sits below
        # the producer H2 but still inside the Open Items span, which is now
        # bounded by `## Resolved Items`, not the first following `## `).
        self.assertFalse(rc.emit_clarification(path=self.path, **_EMIT_KW))
        self.assertEqual(
            self.path.read_text(encoding="utf-8").count(marker),
            1,
            "frozen question re-inserted despite an interleaved producer H2",
        )

    def test_open_items_span_bounded_by_resolved_items(self) -> None:
        text = (
            "# Clarifications Needed\n\n## Open Items\n\n"
            "## process 2026-07-11 batch\n\n<!-- role-clarif: role-cold-start/x -->\n\n"
            "## Resolved Items\n\n### old — role-cold-start: y\n"
        )
        span = rc._open_items_span(text)
        self.assertIsNotNone(span)
        start, end = span
        # The role marker (below a producer H2) is inside the span…
        self.assertIn("<!-- role-clarif: role-cold-start/x -->", text[start:end])
        # …and the Resolved Items region is excluded.
        self.assertNotIn("Resolved Items", text[start:end])


class ReadFailureDoesNotOverwriteTest(unittest.TestCase):
    def test_existing_unreadable_queue_raises_not_overwrites(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "CLARIFICATIONS.md"
        # Seed a real queue with owner content, then make the read fail.
        self.assertTrue(rc.emit_clarification(path=path, **_EMIT_KW))
        before = path.read_text(encoding="utf-8")
        self.assertIn("Open Items", before)

        original_read_text = Path.read_text

        def boom(self_path, *args, **kwargs):  # noqa: ANN001
            if self_path == path:
                raise OSError("simulated read failure")
            return original_read_text(self_path, *args, **kwargs)

        with unittest.mock.patch.object(Path, "read_text", boom):
            with self.assertRaises(rc.RoleClarificationError):
                rc.emit_clarification(path=path, **_EMIT_KW)

        # The queue must be untouched — never overwritten with the skeleton.
        self.assertEqual(path.read_text(encoding="utf-8"), before)


class ResolvedSubjectEmitsTest(unittest.TestCase):
    def test_owner_subject_with_resolved_word_emits(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "CLARIFICATIONS.md"
        kw = dict(_EMIT_KW)
        kw["subject"] = "Resolved billing disputes"
        # Must NOT raise on the owner-derived subject.
        self.assertTrue(rc.emit_clarification(path=path, **kw))
        text = path.read_text(encoding="utf-8")
        self.assertIn("Resolved billing disputes", text)

    def test_resolved_in_title_hint_still_raises(self) -> None:
        with self.assertRaises(rc.RoleClarificationError):
            rc.build_clarification_block(
                title_hint="already resolved upstream", **_EMIT_KW
            )


class ResolveClarificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "CLARIFICATIONS.md"

    def _emit(self, **over) -> None:
        kw = dict(_EMIT_KW)
        kw.update(over)
        self.assertTrue(rc.emit_clarification(path=self.path, **kw))

    def test_moves_open_item_to_resolved_with_reason(self) -> None:
        self._emit()
        self.assertTrue(
            rc.resolve_clarification(
                _EMIT_KW["ctype"], _EMIT_KW["subject"], "adopted", path=self.path
            )
        )
        text = self.path.read_text(encoding="utf-8")
        open_part, _, resolved_part = text.partition("## Resolved Items")
        marker = rc._dedup_marker(_EMIT_KW["ctype"], _EMIT_KW["subject"])
        self.assertNotIn(marker, open_part)
        self.assertIn(marker, resolved_part)
        self.assertIn("**Resolved:** adopted", resolved_part)

    def test_missing_queue_and_missing_item_return_false(self) -> None:
        # No file yet.
        self.assertFalse(
            rc.resolve_clarification("role-cold-start", "x", "r", path=self.path)
        )
        # File exists, wrong subject.
        self._emit()
        self.assertFalse(
            rc.resolve_clarification("role-cold-start", "nope", "r", path=self.path)
        )

    def test_header_fallback_when_marker_stripped(self) -> None:
        # A hand-touched queue whose dedup marker was removed still resolves via
        # the `### {date} — {ctype}: {subject}` header.
        self._emit()
        marker = rc._dedup_marker(_EMIT_KW["ctype"], _EMIT_KW["subject"])
        stripped = self.path.read_text(encoding="utf-8").replace(marker + "\n", "")
        self.path.write_text(stripped, encoding="utf-8")
        self.assertTrue(
            rc.resolve_clarification(
                _EMIT_KW["ctype"], _EMIT_KW["subject"], "via header", path=self.path
            )
        )
        _, _, resolved_part = self.path.read_text(
            encoding="utf-8"
        ).partition("## Resolved Items")
        self.assertIn(f"{_EMIT_KW['ctype']}: {_EMIT_KW['subject']}", resolved_part)

    def test_sibling_open_item_survives_resolution(self) -> None:
        # Resolving one item must not touch a second open item (block bounds are
        # exact — no over-capture into the neighbour).
        self._emit(subject="alpha")
        self._emit(subject="beta")
        self.assertTrue(
            rc.resolve_clarification("role-cold-start", "alpha", "r", path=self.path)
        )
        text = self.path.read_text(encoding="utf-8")
        open_part, _, resolved_part = text.partition("## Resolved Items")
        self.assertIn(rc._dedup_marker("role-cold-start", "beta"), open_part)
        self.assertNotIn(rc._dedup_marker("role-cold-start", "alpha"), open_part)
        self.assertIn(rc._dedup_marker("role-cold-start", "alpha"), resolved_part)


class AsStrListTest(unittest.TestCase):
    def test_coercion_strips_dedups_and_drops_non_strings(self) -> None:
        self.assertEqual(
            rc.as_str_list(["  a ", "b", "a", "", "  ", 3, None, "b", "c"]),
            ["a", "b", "c"],
        )

    def test_non_sequence_input_is_empty(self) -> None:
        self.assertEqual(rc.as_str_list(None), [])
        self.assertEqual(rc.as_str_list("abc"), [])
        self.assertEqual(rc.as_str_list({"a": 1}), [])

    def test_tuple_input_accepted(self) -> None:
        self.assertEqual(rc.as_str_list(("x", "x", "y")), ["x", "y"])

    def test_parse_remit_routes_through_as_str_list(self) -> None:
        remit = rc.parse_remit({"tags": ["  t1", "t1", "t2", 9]})
        self.assertEqual(remit.tags, ("t1", "t2"))


class NormalizeRecordRefTest(unittest.TestCase):
    def test_all_three_forms_collapse_to_same_stem(self) -> None:
        for raw in ("[[2026-01-05-standup]]", "2026-01-05-standup", "2026-01-05-standup.md"):
            self.assertEqual(rc.normalize_record_ref(raw), "2026-01-05-standup")

    def test_wikilink_wrapper_stripped(self) -> None:
        self.assertEqual(rc.normalize_record_ref("[[x]]"), "x")

    def test_md_suffix_stripped(self) -> None:
        self.assertEqual(rc.normalize_record_ref("x.md"), "x")

    def test_bare_stem_unchanged(self) -> None:
        self.assertEqual(rc.normalize_record_ref("x"), "x")

    def test_degenerate_empty_wrapper_normalises_to_empty(self) -> None:
        # The canonical drift-killer: '[[]]' collapses to '' (not the literal).
        self.assertEqual(rc.normalize_record_ref("[[]]"), "")
        self.assertEqual(rc.normalize_record_ref("[[   ]]"), "")
        self.assertEqual(rc.normalize_record_ref(""), "")
        self.assertEqual(rc.normalize_record_ref("   "), "")
        self.assertEqual(rc.normalize_record_ref(".md"), "")

    def test_surrounding_whitespace_trimmed(self) -> None:
        self.assertEqual(rc.normalize_record_ref("  [[x]]  "), "x")


class _StubPlugin:
    """A minimal part-plugin stand-in exposing only `known_key_numbers`.

    The common-layer test stays archetype-agnostic on purpose (SoT: the common
    layer never names a concrete part-kind), so the key-minter contract is
    exercised through this stub rather than importing `roles_archetype_ledger`.
    """

    def __init__(self, numbers) -> None:
        self._numbers = list(numbers)

    def known_key_numbers(self, state):  # noqa: ANN001 — state is unused by the stub
        return list(self._numbers)


def _write_config(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class PartsLoaderTest(unittest.TestCase):
    """The composite `parts[]` loader — the core-a seam (BUILD-CONTRACT §1)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "config.yml"

    def test_ordered_parts_load_with_kinds_brief_and_schema_v2(self) -> None:
        _write_config(self.path, (
            "id: minder-pm\n"
            "name: Minder PM\n"
            "parts:\n"
            "  - {id: workstreams, kind: ledger}\n"
            "  - {id: backlog, kind: ledger}\n"
            "remit: {project_ids: [minder]}\n"
            "cadence: weekly\n"
            "cadence_anchor: monday\n"
            "brief: brief.md\n"
            "status: active\n"
            "schema_version: 2\n"
        ))
        cfg = rc.load_role_config_file(self.path)
        # Declared order is preserved (drives sub-zone + cold-start staging order).
        self.assertEqual(cfg.part_ids, ("workstreams", "backlog"))
        self.assertEqual([p.kind for p in cfg.parts], ["ledger", "ledger"])
        self.assertEqual(cfg.brief, "brief.md")
        self.assertEqual(cfg.schema_version, 2)
        self.assertEqual(cfg.name, "Minder PM")

    def test_brief_optional_defaults_none(self) -> None:
        _write_config(self.path, (
            "id: r\n"
            "parts: [{id: p1, kind: ledger}]\n"
            "remit: {all: true}\n"
            "cadence: daily\n"
            "status: active\n"
        ))
        cfg = rc.load_role_config_file(self.path)
        self.assertIsNone(cfg.brief)

    def test_v1_scalar_archetype_is_fail_closed_with_rebuild_pointer(self) -> None:
        # There is NO scalar path: a v1 `archetype:` config is invalid and the
        # error names the removed field + shows the composite replacement.
        _write_config(self.path, (
            "id: r\n"
            "archetype: ledger\n"
            "remit: {all: true}\n"
            "cadence: daily\n"
            "status: active\n"
        ))
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self.path)
        msg = str(ctx.exception)
        self.assertIn("scalar", msg)
        self.assertIn("parts", msg)

    def test_missing_parts_fail_closed(self) -> None:
        _write_config(self.path, (
            "id: r\nremit: {all: true}\ncadence: daily\nstatus: active\n"
        ))
        with self.assertRaises(rc.RoleConfigError):
            rc.load_role_config_file(self.path)

    def test_duplicate_part_id_fail_closed(self) -> None:
        _write_config(self.path, (
            "id: r\n"
            "parts:\n"
            "  - {id: dup, kind: ledger}\n"
            "  - {id: dup, kind: ledger}\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        ))
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self.path)
        self.assertIn("duplicate part id", str(ctx.exception))

    def test_unknown_kind_fail_closed_at_load(self) -> None:
        # A kind that does not resolve to an installed plugin is caught at LOAD
        # (via import_archetype), not deferred to first tick.
        _write_config(self.path, (
            "id: r\n"
            "parts: [{id: p1, kind: nonesuch}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        ))
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.load_role_config_file(self.path)
        self.assertIn("does not resolve to a", str(ctx.exception))

    def test_malformed_part_kind_fail_closed(self) -> None:
        _write_config(self.path, (
            "id: r\n"
            "parts: [{id: p1, kind: '  '}]\n"
            "remit: {all: true}\ncadence: daily\nstatus: active\n"
        ))
        with self.assertRaises(rc.RoleConfigError):
            rc.load_role_config_file(self.path)


class KeyMinterForPartTest(unittest.TestCase):
    """Per-part key minter — mints in THIS part's namespace via the plugin hook."""

    def test_seeds_past_every_known_number_never_reusing_retired(self) -> None:
        # The stub reports a retired/superseded number (9) the plugin still holds;
        # the minter must seed past it so a retired key is never re-minted.
        plugin = _StubPlugin([3, 5, 9, 12])
        minter = rc.KeyMinter.for_part(plugin, {"any": "state"})
        self.assertEqual(minter.peek(), "lk-0013")
        self.assertEqual(minter.mint(), "lk-0013")
        self.assertEqual(minter.mint(), "lk-0014")

    def test_fresh_part_starts_at_one(self) -> None:
        minter = rc.KeyMinter.for_part(_StubPlugin([]), {})
        self.assertEqual(minter.peek(), "lk-0001")

    def test_two_parts_mint_in_independent_namespaces(self) -> None:
        # Each part scans only its own state, so composite parts never collide.
        a = rc.KeyMinter.for_part(_StubPlugin([7]), {})
        b = rc.KeyMinter.for_part(_StubPlugin([2]), {})
        self.assertEqual(a.mint(), "lk-0008")
        self.assertEqual(b.mint(), "lk-0003")


class DeltaPartTest(unittest.TestCase):
    """The `part` field accessor — the single home for payload-v2 routing."""

    def test_valid_part_is_stripped(self) -> None:
        self.assertEqual(rc.delta_part({"part": " workstreams ", "op": "add"}), "workstreams")

    def test_missing_blank_or_non_string_part_is_unroutable(self) -> None:
        self.assertIsNone(rc.delta_part({"op": "add"}))
        self.assertIsNone(rc.delta_part({"part": "   "}))
        self.assertIsNone(rc.delta_part({"part": 3}))
        self.assertIsNone(rc.delta_part("not-a-dict"))

    def test_payload_schema_version_is_two(self) -> None:
        self.assertEqual(rc.PAYLOAD_SCHEMA_VERSION, 2)


class GroundingOracleTest(unittest.TestCase):
    """The shared records-grounding oracle (read_record_corpus / ungrounded_refs)
    must never let a citation that resolves to NO basename count as grounded."""

    def test_degenerate_ref_never_enters_corpus(self) -> None:
        # A raw ref that normalises to "" (names no record) is dropped from the
        # corpus — its non-blank raw form must not smuggle "" into the grounded set.
        corpus = rc.read_record_corpus({"read_records": ["real-stem", "[[]]", ".md", "  "]})
        self.assertEqual(corpus, {"real-stem"})

    def test_degenerate_evidence_reported_ungrounded(self) -> None:
        # Even against a corpus that (hypothetically) contained "", a degenerate
        # evidence ref is reported missing — it can never be grounded.
        corpus = rc.read_record_corpus({"read_records": ["real-stem"]})
        self.assertEqual(rc.ungrounded_refs(["[[]]"], corpus), ["[[]]"])
        self.assertEqual(rc.ungrounded_refs([".md"], corpus), [".md"])
        # The end-to-end bypass the adversary found is closed: a degenerate corpus
        # entry + a degenerate citation no longer mutually validate.
        poisoned = rc.read_record_corpus({"read_records": ["[[]]"]})
        self.assertEqual(rc.ungrounded_refs(["[[]]"], poisoned), ["[[]]"])

    def test_real_ref_forms_ground_identically(self) -> None:
        corpus = rc.read_record_corpus({"read_records": ["2026-07-01-standup"]})
        for form in ("2026-07-01-standup", "[[2026-07-01-standup]]",
                     "2026-07-01-standup.md", "  [[2026-07-01-standup]]  "):
            self.assertEqual(rc.ungrounded_refs([form], corpus), [])


class ResolveRoleReferenceTest(unittest.TestCase):
    """The STT-tolerant reference resolver — deterministic, never guesses."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._mk("minder-pm", "Руди")
        self._mk("diet-coach", "Diet Coach")

    def _mk(self, rid: str, name: str) -> None:
        d = self.base / "_system" / "roles" / rid
        d.mkdir(parents=True)
        (d / "config.yml").write_text(
            f'id: {rid}\nname: "{name}"\nparts:\n  - {{ id: b, kind: ledger }}\n'
            "cadence: weekly\ncadence_anchor: monday\nstatus: active\n"
            'schema_version: 2\nremit:\n  globs: ["x/**"]\n', encoding="utf-8")

    def _ids(self, q):
        return [(c.role_id, c.match) for c in rc.resolve_role_reference(q, base=self.base)]

    def test_normalize_folds_case_dashes_and_cyrillic(self) -> None:
        self.assertEqual(rc.normalize_role_ref("Minder-PM"), "minderpm")
        self.assertEqual(rc.normalize_role_ref("миндер пм"), "minderpm")
        self.assertEqual(rc.normalize_role_ref("Руди"), "rudi")

    def test_id_and_name_exact(self) -> None:
        self.assertEqual(self._ids("minder-pm"), [("minder-pm", "id-exact")])
        # Cyrillic display name resolves via transliteration.
        self.assertEqual(self._ids("Руди"), [("minder-pm", "name-exact")])
        self.assertEqual(self._ids("rudi"), [("minder-pm", "name-exact")])

    def test_fuzzy_substring_and_edit_distance(self) -> None:
        self.assertEqual(self._ids("рудик"), [("minder-pm", "fuzzy")])  # substring
        self.assertEqual(self._ids("rudy"), [("minder-pm", "fuzzy")])   # 1-edit
        self.assertEqual(self._ids("coach"), [("diet-coach", "fuzzy")])

    def test_generic_and_unknown_yield_no_candidate(self) -> None:
        # A generic phrase normalises to a non-name → no match; the caller enumerates.
        self.assertEqual(self._ids("узнай у роли в зтн"), [])
        self.assertEqual(self._ids("xyzzy"), [])
        # Too-short a token is not fuzzed (would match everything) — surfaced, not guessed.
        self.assertEqual(self._ids("pm"), [])

    def test_candidates_ranked_exact_before_fuzzy(self) -> None:
        self._mk("rudi-notes", "Rudi Notes")  # 'rudi' is a substring of its name
        ids = self._ids("rudi")
        self.assertEqual(ids[0], ("minder-pm", "name-exact"))  # exact ranks first
        self.assertIn(("rudi-notes", "fuzzy"), ids)

    def test_non_string_reference_yields_no_candidate(self) -> None:
        # A non-string reference must NOT be str()-coerced into a matchable token
        # (str(None)=="none" could phantom-match a role id "none" as id-exact).
        self._mk("none", "Noni")  # a role whose id collides with str(None)
        for bad in (None, ["xyz"], b"rudi", 123, True):
            self.assertEqual(rc.normalize_role_ref(bad), "")
            self.assertEqual(rc.resolve_role_reference(bad, base=self.base), [])

    def test_cyrillic_yi_ending_names_resolve_name_exact(self) -> None:
        # -й / -y is the common Russian ending; the 'й':'y' translit must fire
        # (translit before NFKD) so a Cyrillic name resolves name-exact to Latin.
        self._mk("nikolay-role", "Nikolay")
        self.assertEqual(rc.normalize_role_ref("Николай"), "nikolay")
        self.assertEqual(
            [(c.role_id, c.match) for c in rc.resolve_role_reference("Николай", base=self.base)],
            [("nikolay-role", "name-exact")],
        )


class RoleClarificationTypeTest(unittest.TestCase):
    def test_new_role_clarification_types_registered_and_conformant(self) -> None:
        for ctype in ("role-unroutable", "role-remit-changed"):
            self.assertIn(ctype, rc.ROLE_CLARIFICATION_TYPES)
            block = rc.build_clarification_block(
                ctype=ctype, subject="r", context="c", source="s",
                suggested_action="a", action_taken="t")
            self.assertIn(f"**Type:** {ctype}", block)


if __name__ == "__main__":
    unittest.main()
