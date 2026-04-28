"""Tests for append_candidate.py — buffer append correctness."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tests._fixture import clear_ztn_env, make_fixture  # type: ignore
import append_candidate as a  # type: ignore


def _read_buffer(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class AppendCandidateTests(unittest.TestCase):
    def test_happy_path_writes_one_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            rc = a.main([
                "--situation", "Owner extended the migration window",
                "--observation", "«лучше 6 часов ночью чем 2 часа в прайм-тайм»",
                "--hypothesis", "prefer-higher-quality-path",
                "--suggested-type", "principle",
                "--suggested-domain", "work",
                "--session-id", "session-test-001",
                "--buffer", str(buf),
            ])
            self.assertEqual(rc, 0)
            entries = _read_buffer(buf)
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["suggested_type"], "principle")
            self.assertEqual(entry["suggested_domain"], "work")
            self.assertEqual(entry["session_id"], "session-test-001")
            self.assertEqual(entry["captured_by"], "ztn:capture-candidate")
            self.assertEqual(entry["hypothesis"], "prefer-higher-quality-path")
            self.assertIn("лучше", entry["observation"])  # unicode
        clear_ztn_env()

    def test_default_origin_is_personal(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            a.main([
                "--situation", "any situation",
                "--suggested-type", "principle",
                "--suggested-domain", "tech",
                "--buffer", str(buf),
            ])
            entries = _read_buffer(buf)
            self.assertEqual(entries[-1]["origin"], "personal")
        clear_ztn_env()

    def test_multiple_appends_accumulate(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            for i in range(3):
                a.main([
                    "--situation", f"scenario {i}",
                    "--suggested-type", "principle",
                    "--suggested-domain", "tech",
                    "--session-id", f"session-test-{i:03d}",
                    "--buffer", str(buf),
                ])
            entries = _read_buffer(buf)
            self.assertEqual(len(entries), 3)
            self.assertEqual(
                [e["session_id"] for e in entries],
                ["session-test-000", "session-test-001", "session-test-002"],
            )
        clear_ztn_env()

    def test_bogus_type_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            with self.assertRaises(SystemExit):
                a.main([
                    "--situation", "x",
                    "--suggested-type", "heuristic",  # not in enum
                    "--suggested-domain", "tech",
                    "--buffer", str(buf),
                ])
        clear_ztn_env()

    def test_bogus_domain_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            with self.assertRaises(SystemExit):
                a.main([
                    "--situation", "x",
                    "--suggested-type", "principle",
                    "--suggested-domain", "random",  # bogus
                    "--buffer", str(buf),
                ])
        clear_ztn_env()

    def test_empty_situation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            with self.assertRaises(SystemExit):
                a.main([
                    "--situation", "   ",
                    "--suggested-type", "principle",
                    "--suggested-domain", "tech",
                    "--buffer", str(buf),
                ])
        clear_ztn_env()

    def test_unknown_as_type_and_domain_accepted(self):
        """Explicit 'unknown' is legit when caller cannot confidently
        pick type/domain — review resolves later."""
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            rc = a.main([
                "--situation", "something unclassified",
                "--suggested-type", "unknown",
                "--suggested-domain", "unknown",
                "--buffer", str(buf),
            ])
            self.assertEqual(rc, 0)
            entry = _read_buffer(buf)[-1]
            self.assertEqual(entry["suggested_type"], "unknown")
            self.assertEqual(entry["suggested_domain"], "unknown")
        clear_ztn_env()

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            rc = a.main([
                "--situation", "preview only",
                "--suggested-type", "principle",
                "--suggested-domain", "tech",
                "--buffer", str(buf),
                "--dry-run",
            ])
            self.assertEqual(rc, 0)
            self.assertFalse(buf.exists())
        clear_ztn_env()

    def test_concurrent_appends_do_not_interleave(self):
        """Concurrent writers must not produce partial or interleaved lines
        in the JSONL buffer — each write lands as one complete JSON object."""
        import subprocess
        import sys as _sys
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            scripts_dir = Path(__file__).resolve().parent.parent
            # Launch 10 appenders in parallel with a long observation
            # that would exceed PIPE_BUF without the fcntl lock.
            long_text = "x" * 6000  # > typical 4096 PIPE_BUF
            procs = []
            for i in range(10):
                p = subprocess.Popen(
                    [
                        _sys.executable,
                        str(scripts_dir / "append_candidate.py"),
                        "--situation", f"s{i}",
                        "--observation", long_text,
                        "--suggested-type", "principle",
                        "--suggested-domain", "tech",
                        "--session-id", f"concurrent-{i}",
                        "--buffer", str(buf),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                procs.append(p)
            for p in procs:
                p.wait()
                self.assertEqual(p.returncode, 0)
            # Every line should parse as JSON — no interleaving.
            entries = _read_buffer(buf)
            self.assertEqual(len(entries), 10)
            session_ids = {e["session_id"] for e in entries}
            self.assertEqual(len(session_ids), 10,
                             "concurrent writes produced duplicate or missing entries")
        clear_ztn_env()

    def test_explicit_origin_overrides_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = make_fixture(Path(tmp))
            buf = fx.system / "state" / "principle-candidates.jsonl"
            a.main([
                "--situation", "x",
                "--suggested-type", "principle",
                "--suggested-domain", "tech",
                "--origin", "external",
                "--buffer", str(buf),
            ])
            entry = _read_buffer(buf)[-1]
            self.assertEqual(entry["origin"], "external")
        clear_ztn_env()


if __name__ == "__main__":
    unittest.main()
