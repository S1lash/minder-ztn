"""Tests for roles_log — the run line (CORE-SPEC §5).

Proves the exact log-line schema (one `outcome` field, no `gate`, no
`status`), that an append is one physical LF-terminated line written UTF-8
with `ensure_ascii=False`, that `ts` is used exactly as injected, and that
`last_run` tolerates corruption — because a corrupt log that made a role undue
forever is precisely the failure this subsystem was rebuilt to prevent.

The `ensure_ascii=False` clause is not cosmetic: a Cyrillic `note` raising
`UnicodeEncodeError` would leave the run unlogged, `last_run` at `None`, and
the role re-running every tick forever.
"""

from __future__ import annotations

import inspect
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests._roles_fixture import (  # type: ignore
    make_base,
    role_config,
    write_bytes,
    write_text,
)
import roles_log as rlog  # type: ignore

UTC = timezone.utc
WEST = timezone(timedelta(hours=-5))
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FIELDS = {"ts", "role", "outcome", "writes", "reverted", "reported_only", "ms", "note"}

TS = datetime(2026, 7, 28, 7, 0, 11, tzinfo=UTC)
TS_LATER = datetime(2026, 7, 29, 7, 0, 11, tzinfo=UTC)


def _lines(cfg) -> list[str]:
    return cfg.log_path.read_text(encoding="utf-8").splitlines()


def _entries(cfg) -> list[dict]:
    return [json.loads(ln) for ln in _lines(cfg) if ln.strip()]


def _append(cfg, **kwargs) -> None:
    payload = {
        "ts": TS,
        "outcome": "ok",
        "writes": 0,
        "reverted": [],
        "reported_only": [],
        "ms": 41200,
        "note": None,
    }
    payload.update(kwargs)
    rlog.append_run(cfg, **payload)


def _line(ts: str, **over) -> str:
    entry = {
        "ts": ts,
        "role": "notion-sync",
        "outcome": "ok",
        "writes": 0,
        "reverted": [],
        "reported_only": [],
        "ms": 100,
        "note": None,
    }
    entry.update(over)
    return json.dumps(entry, ensure_ascii=False)


def _seed(cfg, lines: list[str]) -> Path:
    return write_text(cfg.log_path, "".join(ln + "\n" for ln in lines))


# ==========================================================================
# append shape
# ==========================================================================

class AppendShapeTests(unittest.TestCase):
    def test_append_writes_exactly_the_schema_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, writes=2)
            entries = _entries(cfg)
            self.assertEqual(len(entries), 1)
            self.assertEqual(set(entries[0]), FIELDS)

    def test_log_line_has_no_status_or_gate_field(self):
        """§5: `status` + `gate` collapsed into one `outcome`. A separate gate
        field is deliberately absent — whether the role's own check found work
        is knowledge only the model has, folded into `outcome` by the tick."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            entry = _entries(cfg)[0]
            self.assertNotIn("gate", entry)
            self.assertNotIn("status", entry)
            self.assertIn("outcome", entry)

    def test_append_records_the_values_it_was_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(
                cfg,
                outcome="error",
                writes=3,
                reverted=["zettelkasten/1_projects/rogue.md"],
                reported_only=["zettelkasten/1_projects/owner-wip.md"],
                ms=1234,
                note="notion returned 429",
            )
            entry = _entries(cfg)[0]
            self.assertEqual(entry["role"], "notion-sync")
            self.assertEqual(entry["outcome"], "error")
            self.assertEqual(entry["writes"], 3)
            self.assertEqual(entry["reverted"], ["zettelkasten/1_projects/rogue.md"])
            self.assertEqual(entry["reported_only"],
                             ["zettelkasten/1_projects/owner-wip.md"])
            self.assertEqual(entry["ms"], 1234)
            self.assertEqual(entry["note"], "notion returned 429")

    def test_accepts_every_legal_outcome_value(self):
        """SIBLING — `ok`, `idle` and `error` are three real outcomes and all
        three must round-trip."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            for outcome in ("ok", "idle", "error"):
                _append(cfg, outcome=outcome)
            self.assertEqual([e["outcome"] for e in _entries(cfg)],
                             ["ok", "idle", "error"])

    def test_idle_run_with_a_reason_note_is_logged(self):
        """SIBLING — `idle` is a normal, successful outcome, not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="idle", note="board unchanged", ms=800)
            entry = _entries(cfg)[0]
            self.assertEqual(entry["outcome"], "idle")
            self.assertEqual(entry["note"], "board unchanged")

    def test_note_null_and_empty_lists_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            entry = _entries(cfg)[0]
            self.assertIsNone(entry["note"])
            self.assertEqual(entry["reverted"], [])
            self.assertEqual(entry["reported_only"], [])

    def test_writes_is_an_int_and_the_path_lists_are_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, writes=2, reverted=["a.md"], reported_only=["b.md"])
            entry = _entries(cfg)[0]
            self.assertIsInstance(entry["writes"], int)
            self.assertIsInstance(entry["reverted"], list)
            self.assertIsInstance(entry["reported_only"], list)

    def test_log_lands_at_the_role_configs_log_path(self):
        """SoT: the path comes from `RoleConfig.log_path`, never rebuilt."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            self.assertTrue(cfg.log_path.exists())
            self.assertEqual(cfg.log_path.name, "log.jsonl")


# ==========================================================================
# ts — injected, UTC, never read from the clock
# ==========================================================================

class TimestampTests(unittest.TestCase):
    def test_ts_is_utc_iso8601_with_z(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            self.assertRegex(_entries(cfg)[0]["ts"], TS_RE)

    def test_injected_ts_is_used_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, ts=datetime(2019, 1, 2, 3, 4, 5, tzinfo=UTC))
            self.assertEqual(_entries(cfg)[0]["ts"], "2019-01-02T03:04:05Z")

    def test_a_non_utc_ts_is_converted_to_utc(self):
        """SIBLING — the tick may pass local time; §5 says the log stores UTC,
        and §2 relies on that being true."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, ts=datetime(2026, 7, 28, 7, 0, 11, tzinfo=WEST))
            self.assertEqual(_entries(cfg)[0]["ts"], "2026-07-28T12:00:11Z")

    def test_module_reads_no_clock(self):
        src = inspect.getsource(rlog)
        for banned in ("datetime.now()", "datetime.utcnow()", "time.time()"):
            with self.subTest(call=banned):
                self.assertNotIn(banned, src)


# ==========================================================================
# append mechanics — one line, append-only, LF, ensure_ascii=False
# ==========================================================================

class AppendMechanicsTests(unittest.TestCase):
    def test_each_append_adds_exactly_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            for i in range(3):
                _append(cfg, ms=i)
            self.assertEqual(len(_lines(cfg)), 3)

    def test_append_preserves_earlier_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _seed(cfg, [_line("2026-07-01T07:00:00Z", ms=1)])
            _append(cfg, ms=2)
            self.assertEqual([e["ms"] for e in _entries(cfg)], [1, 2])

    def test_append_creates_the_role_directory_when_missing(self):
        """SIBLING — a brand new role's very first run must not depend on the
        directory having been created by something else."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)), id="fresh-role")
            self.assertFalse(cfg.dir.exists())
            _append(cfg)
            self.assertEqual(len(_entries(cfg)), 1)

    def test_file_ends_with_a_single_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            raw = cfg.log_path.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertFalse(raw.endswith(b"\n\n"))

    def test_newlines_are_lf_not_crlf_on_every_platform(self):
        """Text-mode `open("a")` translates to CRLF on Windows unless the
        writer pins `newline="\\n"` — this asserts the pin, not the platform."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg)
            _append(cfg, ts=TS_LATER)
            self.assertNotIn(b"\r\n", cfg.log_path.read_bytes())

    def test_cyrillic_note_is_written_as_utf8_not_escaped(self):
        """§5 requires `ensure_ascii=False`; the raw bytes must carry the real
        characters, not `\\u0434` escapes."""
        note = "доска не менялась"
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="idle", note=note)
            raw = cfg.log_path.read_bytes()
            self.assertIn(note.encode("utf-8"), raw)
            self.assertNotIn(b"\\u04", raw)
            self.assertEqual(_entries(cfg)[0]["note"], note)

    def test_note_with_quotes_and_emoji_round_trips(self):
        """SIBLING — the note is short human text and may carry anything."""
        note = 'роль сказала «нет» — API вернул 429 🚫'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="error", note=note)
            self.assertEqual(_entries(cfg)[0]["note"], note)
            self.assertEqual(len(_lines(cfg)), 1)

    def test_note_with_a_newline_still_produces_one_physical_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="error", note="first line\nsecond line")
            self.assertEqual(len(_lines(cfg)), 1)
            self.assertEqual(_entries(cfg)[0]["note"], "first line\nsecond line")

    def test_reverted_paths_with_non_ascii_round_trip(self):
        """SIBLING — a reverted path may be Cyrillic; the log must carry it
        back intact for the morning report."""
        paths = ["zettelkasten/_system/roles/notion-sync/state/расхождения.md"]
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, reverted=paths)
            self.assertEqual(_entries(cfg)[0]["reverted"], paths)

    def test_appends_are_ordered_by_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, ms=1, ts=TS)
            _append(cfg, ms=2, ts=TS_LATER)
            entries = _entries(cfg)
            self.assertEqual([e["ms"] for e in entries], [1, 2])
            self.assertLess(entries[0]["ts"], entries[1]["ts"])


# ==========================================================================
# last_run
# ==========================================================================

class LastRunTests(unittest.TestCase):
    def test_missing_log_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            self.assertIsNone(rlog.last_run(cfg))

    def test_empty_log_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(cfg.log_path, "")
            self.assertIsNone(rlog.last_run(cfg))

    def test_returns_the_last_line_as_a_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _seed(cfg, [_line("2026-07-01T07:00:00Z"),
                        _line("2026-07-27T07:00:00Z", outcome="idle")])
            got = rlog.last_run(cfg)
            self.assertIsInstance(got, dict)
            self.assertEqual(got["ts"], "2026-07-27T07:00:00Z")
            self.assertEqual(got["outcome"], "idle")

    def test_append_then_last_run_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="ok", writes=2, ms=41200)
            got = rlog.last_run(cfg)
            self.assertEqual(got["ts"], "2026-07-28T07:00:11Z")
            self.assertEqual(got["writes"], 2)

    def test_corrupt_trailing_line_still_yields_the_previous_run(self):
        """A corrupt log must never make a role undue forever."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(cfg.log_path,
                       _line("2026-07-26T07:00:00Z") + "\n" + '{"ts":"2026-07-27T07:0')
            got = rlog.last_run(cfg)
            self.assertIsNotNone(got)
            self.assertEqual(got["ts"], "2026-07-26T07:00:00Z")

    def test_several_corrupt_trailing_lines_are_scanned_past(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(
                cfg.log_path,
                _line("2026-07-25T07:00:00Z") + "\n"
                + "not json at all\n"
                + '{"ts": broken\n',
            )
            got = rlog.last_run(cfg)
            self.assertIsNotNone(got)
            self.assertEqual(got["ts"], "2026-07-25T07:00:00Z")

    def test_every_line_corrupt_returns_none_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(cfg.log_path, "garbage\nmore garbage\n")
            self.assertIsNone(rlog.last_run(cfg))

    def test_undecodable_log_returns_none_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_bytes(cfg.log_path, b"\xff\xfe\x00\x01")
            self.assertIsNone(rlog.last_run(cfg))

    def test_trailing_blank_lines_are_tolerated(self):
        """SIBLING — a blank tail is not corruption; the last real run stands."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(cfg.log_path, _line("2026-07-27T07:00:00Z") + "\n\n\n")
            got = rlog.last_run(cfg)
            self.assertIsNotNone(got)
            self.assertEqual(got["ts"], "2026-07-27T07:00:00Z")

    def test_crlf_log_is_tolerated(self):
        """SIBLING — a log that came through a Windows checkout with CRLF must
        still parse; refusing it would make the role undue forever."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_bytes(cfg.log_path,
                        (_line("2026-07-27T07:00:00Z") + "\r\n").encode("utf-8"))
            got = rlog.last_run(cfg)
            self.assertIsNotNone(got)
            self.assertEqual(got["ts"], "2026-07-27T07:00:00Z")

    def test_a_cyrillic_note_in_an_earlier_line_does_not_break_the_scan(self):
        """SIBLING — §0 requires the read to be explicit UTF-8; under the
        locale default this line would raise and the role would re-run forever."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _seed(cfg, [_line("2026-07-26T07:00:00Z", note="доска не менялась"),
                        _line("2026-07-27T07:00:00Z")])
            self.assertEqual(rlog.last_run(cfg)["ts"], "2026-07-27T07:00:00Z")

    def test_line_that_is_valid_json_but_not_a_run_line_is_skipped(self):
        """SIBLING — an unusable tail is skipped like any other, and the
        previous real run still counts."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            write_text(cfg.log_path,
                       _line("2026-07-26T07:00:00Z") + "\n" + '{"role":"notion-sync"}\n')
            got = rlog.last_run(cfg)
            self.assertIsNotNone(got)
            self.assertEqual(got["ts"], "2026-07-26T07:00:00Z")

    def test_last_run_reads_only_this_roles_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            mine = role_config(base)
            theirs = role_config(base, id="other-role")
            _seed(mine, [_line("2026-07-27T07:00:00Z")])
            _seed(theirs, [_line("2026-07-01T07:00:00Z")])
            self.assertEqual(rlog.last_run(theirs)["ts"], "2026-07-01T07:00:00Z")

    def test_last_run_does_not_mutate_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _seed(cfg, [_line("2026-07-27T07:00:00Z")])
            before = cfg.log_path.read_bytes()
            rlog.last_run(cfg)
            self.assertEqual(cfg.log_path.read_bytes(), before)

    def test_last_run_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _seed(cfg, [_line("2026-07-27T07:00:00Z")])
            self.assertEqual(rlog.last_run(cfg), rlog.last_run(cfg))


class DegradedOutcomeTests(unittest.TestCase):
    """`degraded` — the run delivered, but part of the job could not be done.

    The honest failure of a standing role is not a crash. A role whose service
    runs out of quota mid-run still produces most of its output and returns
    successfully, marking what it could not verify. Recorded as `ok`, that is
    indistinguishable from a good night — and a limit hit every night hollows
    out the role's work indefinitely while every run line reads as success.
    """

    def test_degraded_is_an_accepted_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            _append(cfg, outcome="degraded", writes=2,
                    note="board aggregates done; 3 topics unverified — connector quota")
            entry = _entries(cfg)[0]
            self.assertEqual(entry["outcome"], "degraded")
            self.assertEqual(entry["writes"], 2, "a degraded run still did work")

    def test_degraded_is_distinct_from_both_ok_and_error(self):
        """SIBLING — the whole point is that it is neither. Folding it into
        `ok` hides the hole; folding it into `error` trains the owner to
        ignore the word, and the tick's error handling does not apply to a
        run that behaved."""
        self.assertIn("degraded", rlog.OUTCOMES)
        self.assertEqual(
            list(rlog.OUTCOMES), ["ok", "idle", "degraded", "error"],
            "the vocabulary is fixed and ordered by how well the run went",
        )

    def test_an_unknown_outcome_is_still_refused(self):
        """SIBLING — widening the vocabulary must not turn it into a free
        text field, or the probe that watches for repeats matches nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = role_config(make_base(Path(tmp)))
            with self.assertRaises(Exception):
                _append(cfg, outcome="partial")


if __name__ == "__main__":
    unittest.main()
