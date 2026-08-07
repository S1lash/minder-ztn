"""Tests for the shared engine primitives under `scripts/lib/`.

These exist because each concern here was previously re-derived at every call
site and got it wrong in the same way at several of them — LF-forcing on the
shell boundary, the `exclude:` subtraction, branch identity. A shared owner is
only an improvement if the owner is pinned.
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib import manifest as lm  # noqa: E402
from lib import portable as lp  # noqa: E402


class PortableTests(unittest.TestCase):
    def test_emit_lines_writes_lf_only(self):
        """The whole point: a `\\r` here fails every path a shell builds from it."""
        buf = io.StringIO()
        real, sys.stdout = sys.stdout, buf
        try:
            lp.emit_lines(["a/b", "c d", "кириллица"])
        finally:
            sys.stdout = real
        self.assertEqual(buf.getvalue(), "a/b\nc d\nкириллица\n")
        self.assertNotIn("\r", buf.getvalue())

    def test_emit_lines_does_not_strip_or_quote(self):
        buf = io.StringIO()
        real, sys.stdout = sys.stdout, buf
        try:
            lp.emit_lines(["  padded  "])
        finally:
            sys.stdout = real
        self.assertEqual(buf.getvalue(), "  padded  \n")

    def test_configure_stream_tolerates_a_stream_without_reconfigure(self):
        lp.configure_stream(io.StringIO())  # must not raise

    def test_write_text_utf8_stores_lf_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.sh"
            lp.write_text_utf8(p, "a\nb\n")
            self.assertEqual(p.read_bytes(), b"a\nb\n")

    def test_read_text_utf8_is_utf8_regardless_of_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.md"
            p.write_bytes("тире — em dash\n".encode("utf-8"))
            self.assertEqual(lp.read_text_utf8(p), "тире — em dash\n")

    def test_read_text_utf8_default_covers_a_missing_file(self):
        self.assertEqual(lp.read_text_utf8(Path("/nope/nope.md"), default="!"), "!")


class ManifestTests(unittest.TestCase):
    def test_lite_matches_yaml_on_every_list_section(self):
        """Two readers exist only because the scheduler sandbox has no PyYAML.

        They must never disagree about what ships.
        """
        root = lm.repo_root()
        full = lm.load_manifest(root)
        path = root / ".engine-manifest.yml"
        for section in lm.LIST_SECTIONS:
            with self.subTest(section=section):
                self.assertEqual(
                    lm.read_section_lite(path, section),
                    [str(x) for x in (full.get(section) or [])],
                )

    def test_read_section_lite_rejects_a_non_list_section(self):
        with self.assertRaises(ValueError):
            lm.read_section_lite(lm.repo_root() / ".engine-manifest.yml", "version")

    def test_scan_targets_subtracts_exclude(self):
        """The bug this fixes: excluding a file had no observable effect."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "keep.py").write_text("x\n", encoding="utf-8")
            (root / "scripts" / "personal.py").write_text("x\n", encoding="utf-8")
            manifest = {"engine": ["scripts/"], "exclude": ["scripts/personal.py"]}

            names = {p.name for p in lm.scan_targets(root, manifest)}
            self.assertEqual(names, {"keep.py"})

    def test_scan_targets_skips_a_manifested_path_that_does_not_exist_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"engine": ["integrations/VERSION"]}
            self.assertEqual(lm.scan_targets(root, manifest), [])

    def test_expand_paths_can_return_every_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "d").mkdir()
            (root / "d" / "a.png").write_bytes(b"\x89PNG")
            (root / "d" / "b.md").write_text("x\n", encoding="utf-8")
            self.assertEqual(
                {p.name for p in lm.expand_paths(root, ["d/"], suffixes=None)},
                {"a.png", "b.md"},
            )
            self.assertEqual({p.name for p in lm.expand_paths(root, ["d/"])}, {"b.md"})


class GitShellLibTests(unittest.TestCase):
    """`scripts/lib/git.sh` — sourced by every scheduler script."""

    LIB = REPO_ROOT / "scripts" / "lib" / "git.sh"

    def _run(self, snippet: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f'. "{self.LIB}"; {snippet}'],
            capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
        )

    def test_is_branch_name_rejects_every_non_branch_value(self):
        for value in ("", "DETACHED", "HEAD"):
            with self.subTest(value=value):
                self.assertNotEqual(
                    self._run(f'git_is_branch_name "{value}"').returncode, 0
                )

    def test_is_branch_name_accepts_a_real_branch(self):
        for value in ("main", "claude/admiring-shannon-ETCE3"):
            with self.subTest(value=value):
                self.assertEqual(self._run(f'git_is_branch_name "{value}"').returncode, 0)

    def test_current_branch_or_falls_back(self):
        out = self._run('cd /tmp && git_current_branch_or DETACHED')
        self.assertEqual(out.stdout.strip(), "DETACHED")
        self.assertEqual(out.returncode, 0)

    def test_syntax_is_bash_3_2_clean(self):
        """macOS ships bash 3.2 — the library must parse there."""
        self.assertEqual(
            subprocess.run(["/bin/bash", "-n", str(self.LIB)]).returncode, 0
        )


if __name__ == "__main__":
    unittest.main()
