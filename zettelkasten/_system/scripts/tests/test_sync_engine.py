"""End-to-end tests for `scripts/sync_engine.sh` — the engine update channel.

Every test here pins a failure that was real, and each shares one shape: the
update reported success while doing nothing, or refused to proceed on exactly
the clone it was supposed to rescue. A channel whose failure looks like its
success is worse than one that is simply broken, because nobody goes looking.

The upstream in these tests is a tiny hand-built repo rather than a real
release: what is under test is the script's control flow, not the manifest's
contents.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[4]
_SCRIPTS = _REPO_ROOT / "scripts"

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

_MANIFEST = textwrap.dedent(
    """\
    version: 1

    engine:
      - integrations/VERSION
      - scripts/
      - engine-doc.md

    template: []

    exclude: []
    """
)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True, encoding="utf-8", env=_ENV
    )


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/sync_engine.sh", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=_ENV,
    )


def _seed_upstream(tmp: Path, version: str = "0.55.0") -> Path:
    up = tmp / "upstream"
    (up / "integrations").mkdir(parents=True)
    (up / "integrations" / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (up / "engine-doc.md").write_text("current\n", encoding="utf-8")
    # `__pycache__` is regenerated with different bytes the moment python runs,
    # which would make `scripts/` legitimately dirty and abort every sync here.
    shutil.copytree(_SCRIPTS, up / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (up / ".engine-manifest.yml").write_text(_MANIFEST, encoding="utf-8")
    _git(up, "init", "-q", "-b", "main")
    _git(up, "add", "-A")
    _git(up, "commit", "-q", "-m", "engine")
    return up


def _clone(tmp: Path, up: Path, *, version: str) -> Path:
    clone = tmp / "clone"
    subprocess.run(["git", "clone", "-q", str(up), str(clone)], check=True, env=_ENV)
    _git(clone, "remote", "rename", "origin", "upstream")
    (clone / "integrations" / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (clone / "engine-doc.md").write_text("stale\n", encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "older engine")
    return clone


class SyncEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.up = _seed_upstream(self.tmp)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ordinary_sync_applies_and_moves_the_version(self):
        clone = _clone(self.tmp, self.up, version="0.51.0")
        result = _run(clone)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / "integrations" / "VERSION").read_text(encoding="utf-8").strip(),
                         "0.55.0")
        self.assertEqual((clone / "engine-doc.md").read_text(encoding="utf-8"), "current\n")
        self.assertIn("0.51.0 → 0.55.0", result.stdout)

    def test_a_sync_that_resolves_nothing_fails_loudly(self):
        """The Windows failure: a mangled path list read as 'absent upstream'.

        Simulated at the boundary it actually broke — the manifest reader's
        stdout, which on Git Bash carried a trailing `\\r` on every line.
        """
        clone = _clone(self.tmp, self.up, version="0.51.0")
        reader = clone / "scripts" / "manifest_paths.py"
        src = reader.read_text(encoding="utf-8")
        src = src.replace(
            '    emit_lines(str(p).rstrip("/") for p in manifest.get(args.section, []) or [])',
            '    for _p in manifest.get(args.section, []) or []:\n'
            '        sys.stdout.write(str(_p).rstrip("/") + "\\r\\n")',
        )
        reader.write_text(src, encoding="utf-8", newline="")
        _git(clone, "commit", "-q", "-am", "simulate Git Bash CRLF")

        result = _run(clone)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not one of the", result.stderr)
        self.assertIn("--self-heal", result.stderr)
        self.assertEqual((clone / "integrations" / "VERSION").read_text(encoding="utf-8").strip(),
                         "0.51.0", "a failed sync must not claim a version it did not apply")

    def test_self_heal_recovers_a_clone_with_no_shared_lib(self):
        """A clone old enough to need recovering PREDATES `scripts/lib/`.

        Sourcing the library at the top of the script killed it on line one —
        on exactly the clone the recovery path exists for.
        """
        clone = _clone(self.tmp, self.up, version="0.51.0")
        shutil.rmtree(clone / "scripts" / "lib")
        _git(clone, "commit", "-q", "-am", "pre-lib clone")

        plain = _run(clone)
        self.assertEqual(plain.returncode, 2)
        self.assertIn("--self-heal", plain.stderr,
                      "the refusal must name the way out, not just fail")

        healed = _run(clone, "--self-heal")
        self.assertEqual(healed.returncode, 0, healed.stderr)
        self.assertTrue((clone / "scripts" / "lib" / "git.sh").is_file())
        self.assertEqual((clone / "integrations" / "VERSION").read_text(encoding="utf-8").strip(),
                         "0.55.0")

    def test_a_path_dirty_but_identical_to_upstream_is_not_an_abort(self):
        """Otherwise the self-heal deadlocks against the script's own dirty check."""
        clone = _clone(self.tmp, self.up, version="0.51.0")
        subprocess.run(["git", "checkout", "upstream/main", "--", "engine-doc.md"],
                       cwd=clone, check=True, env=_ENV)
        result = _run(clone)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_real_local_customisation_still_aborts(self):
        clone = _clone(self.tmp, self.up, version="0.51.0")
        (clone / "engine-doc.md").write_text("my own edit\n", encoding="utf-8")
        result = _run(clone)
        self.assertEqual(result.returncode, 2)
        self.assertIn("uncommitted changes", result.stderr)

    def test_dry_run_changes_nothing(self):
        clone = _clone(self.tmp, self.up, version="0.51.0")
        result = _run(clone, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((clone / "integrations" / "VERSION").read_text(encoding="utf-8").strip(),
                         "0.51.0")


if __name__ == "__main__":
    unittest.main()
