"""Tests for identity_gate.py — the observation, not a second opinion.

The gate exists so that «the scan returned zero for this identity» is something
a script watched rather than something a model wrote about itself. So what is
worth pinning is exactly that: the exit code passes through untouched, the line
records the command that actually ran, and the log only ever grows.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import identity_gate as ig  # type: ignore

_REGISTRY = """# Project Registry

## Active Projects

| ID | Name | Status |
|----|------|--------|
| alpha-app | Alpha | active |

## Retired Identifiers

| Old ID | Kind | Successor | Date | Reason |
|--------|------|-----------|------|--------|
| legacy-thing | merge | `alpha-app` | 2026-01-02 | folded in |
| old-tool | merge | `alpha-app` | 2026-01-02 | folded in |
"""


def _base(tmp: str) -> Path:
    root = Path(tmp)
    for sub in ("1_projects", "2_areas", "_system/state"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "1_projects" / "PROJECTS.md").write_text(_REGISTRY, encoding="utf-8")
    return root


def _write_note(root: Path, rel: str, tags: list[str]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = "id: n\ntags:\n" + "".join(f"  - {t}\n" for t in tags)
    path.write_text(f"---\n{fm}---\nbody\n", encoding="utf-8")


def _run(root: Path, argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ig.main(["--root", str(root)] + argv)
    return code, json.loads(buf.getvalue())


def _log_lines(root: Path) -> list[dict]:
    path = root.joinpath(*ig.GATE_LOG)
    if not path.exists():
        return []
    return [
        json.loads(ln) for ln in
        path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]


class GateTests(unittest.TestCase):
    def test_clean_identity_records_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", ["project/alpha-app"])
            code, record = _run(root, ["--identity", "legacy-thing"])
            self.assertEqual(code, 0)
            self.assertEqual(record["exit_code"], 0)
            self.assertEqual(record["residue_count"], 0)
            self.assertTrue(record["clean"])
            self.assertEqual([r["identity"] for r in _log_lines(root)],
                             ["legacy-thing"])

    def test_residue_passes_the_audits_exit_code_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", ["project/legacy-thing"])
            code, record = _run(root, ["--identity", "legacy-thing"])
            self.assertEqual(code, 2)
            self.assertEqual(record["exit_code"], 2)
            self.assertEqual(record["residue_count"], 1)

    def test_another_identitys_residue_does_not_fail_this_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _write_note(root, "2_areas/a.md", ["project/legacy-thing"])
            code, _ = _run(root, ["--identity", "old-tool"])
            self.assertEqual(code, 0)

    def test_unknown_identifier_is_one_and_is_recorded_as_such(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            code, record = _run(root, ["--identity", "never-existed"])
            self.assertEqual(code, 1)
            self.assertEqual(record["exit_code"], 1)
            self.assertIsNone(record["residue_count"])
            self.assertIn("error", record)

    def test_the_command_recorded_is_the_command_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _, record = _run(root, ["--identity", "old-tool"])
            self.assertIn("--identity old-tool", record["command"])
            self.assertIn("--fail-on-residue", record["command"])
            self.assertTrue(record["command"].startswith("identity_audit.py"))

    def test_log_is_append_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _run(root, ["--identity", "old-tool"])
            _run(root, ["--identity", "legacy-thing"])
            self.assertEqual(
                [r["identity"] for r in _log_lines(root)],
                ["old-tool", "legacy-thing"],
            )

    def test_no_record_leaves_no_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            code, _ = _run(root, ["--identity", "old-tool", "--no-record"])
            self.assertEqual(code, 0)
            self.assertEqual(_log_lines(root), [])

    def test_log_lines_end_in_lf_on_every_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base(tmp)
            _run(root, ["--identity", "old-tool"])
            raw = root.joinpath(*ig.GATE_LOG).read_bytes()
            self.assertTrue(raw.endswith(b"}\n"))
            self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
