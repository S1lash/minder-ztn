"""Tests for scripts/check_retirements.py — the retirement gate.

The gate answers one question: did this engine delete a shipped path without
declaring it in `.engine-manifest.yml → retired:`? An undeclared deletion never
leaves a friend's clone, and a half-declared removal leaves the survivors
importing what was retired — so the gate has to keep working, and a gate that
silently stops finding things is indistinguishable from a clean repo.

Coverage:
- the real repo is clean (the gate's own subject matter stays true)
- a deleted-and-declared path is not reported
- a deleted-but-undeclared path IS reported
- a path deleted under `exclude:` (owner-only) is not reported
- a path that never sat under a shipped area is not reported
- a rename is judged by its OLD name — what a clone is left holding
- a shallow clone REFUSES rather than reporting clean
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO / "scripts"))

import check_retirements as G  # type: ignore


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(tmp: Path, *, retired: list[str]) -> Path:
    """A tiny repo with one shipped dir, one owner-only dir, and one stray dir.

    History: everything is added, then four paths are removed — one that the
    caller may declare, one shipped, one excluded, one outside every section.
    Plus one rename inside the shipped dir.
    """
    root = tmp / "repo"
    root.mkdir()
    _git(root.parent, "init", "--quiet", str(root))
    _git(root, "config", "user.email", "gate@test")
    _git(root, "config", "user.name", "gate")

    _write(root / "shipped" / "keep.py")
    _write(root / "shipped" / "declared.py")
    _write(root / "shipped" / "undeclared.py")
    _write(root / "shipped" / "oldname.py")
    _write(root / "owner" / "private.py")
    _write(root / "stray" / "loose.py")
    _write(root / ".engine-manifest.yml", "engine:\n  - shipped\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "seed")

    for gone in ("shipped/declared.py", "shipped/undeclared.py",
                 "owner/private.py", "stray/loose.py"):
        _git(root, "rm", "--quiet", gone)
    _git(root, "mv", "shipped/oldname.py", "shipped/newname.py")
    _git(root, "commit", "--quiet", "-m", "remove")

    lines = ["engine:", "  - shipped", "exclude:", "  - owner"]
    if retired:
        lines.append("retired:")
        lines += [f"  - {r}" for r in retired]
    _write(root / ".engine-manifest.yml", "\n".join(lines) + "\n")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "declare")
    return root


class RetirementGate(unittest.TestCase):

    @unittest.skipUnless(
        (_REPO / ".git").exists() and (_REPO / "README.template.md").exists(),
        "authoring repo only — a released clone's history is the release lineage",
    )
    def test_real_repo_is_clean(self):
        """Every shipped path this engine deleted is declared. Guards the subject.

        Skipped anywhere but here on purpose. A friend's clone carries the
        SKELETON's history, where every release strips template markers and
        rewrites the tree — so this assertion would fail on their first
        `pytest`, for a question that has no meaning in their repo.
        """
        self.assertEqual(G.undeclared(_REPO), [])

    def test_declared_deletion_is_not_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/undeclared.py", "shipped/oldname.py",
            ])
            self.assertEqual(G.undeclared(root), [])

    def test_undeclared_deletion_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/oldname.py",
            ])
            self.assertEqual(G.undeclared(root), ["shipped/undeclared.py"])

    def test_owner_only_deletion_is_not_reported(self):
        """`exclude:` never shipped, so nothing downstream is holding it."""
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/undeclared.py", "shipped/oldname.py",
            ])
            self.assertNotIn("owner/private.py", G.undeclared(root))

    def test_path_outside_every_section_is_not_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/undeclared.py", "shipped/oldname.py",
            ])
            self.assertNotIn("stray/loose.py", G.undeclared(root))

    def test_rename_is_judged_by_its_old_name(self):
        """Downstream a rename is a delete plus an add; the old name stays behind."""
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/undeclared.py",
            ])
            self.assertIn("shipped/oldname.py", G.undeclared(root))

    def test_directory_entry_covers_everything_beneath_it(self):
        """`retire_paths.py` deletes a declared directory whole; the gate agrees.

        Naming a directory instead of its files is how a removal is declared
        without putting owner concept names — which one-off migrations carry in
        their filenames — into a manifest that ships.
        """
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=["shipped"])
            self.assertEqual(G.undeclared(root), [])

    def test_unshipped_in_the_same_commit_is_still_reported(self):
        """Deleting a file AND its manifest line together is the ordinary sequence.

        Judged against the manifest as it reads now, such a path sits under no
        shipped root — so a gate that reads only the current manifest goes
        blind on the most common way a file stops shipping.
        """
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[
                "shipped/declared.py", "shipped/oldname.py",
            ])
            # unship the whole directory, after the deletions already happened
            _write(root / ".engine-manifest.yml", "engine:\n  - other\nexclude:\n  - owner\n"
                                                  "retired:\n  - shipped/declared.py\n"
                                                  "  - shipped/oldname.py\n")
            _git(root, "add", "-A")
            _git(root, "commit", "--quiet", "-m", "unship")
            self.assertIn("shipped/undeclared.py", G.undeclared(root))

    def test_repo_without_git_refuses_instead_of_crashing(self):
        """An extracted skeleton has no .git; the gate must say so, not traceback."""
        with tempfile.TemporaryDirectory() as td:
            bare = Path(td) / "nogit"
            _write(bare / ".engine-manifest.yml", "engine:\n  - shipped\n")
            with self.assertRaises(G.NotAGitRepo):
                G.undeclared(bare)

    def test_declared_retired_path_that_still_exists_is_a_conflict(self):
        """Checked out by the sync, deleted by the retire — on every update, forever."""
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=["shipped/keep.py"])
            self.assertEqual(G.conflicts(root), ["shipped/keep.py"])

    def test_released_clone_refuses_and_skill_seed_does_not_fool_it(self):
        """A clone has no strip-seed sources; it does still have skill-seed ones.

        Release renames `X.template.md` → `X.md` for strip-seed, but copies a
        skill-seed entry verbatim, suffix intact. Testing «any template path
        exists» would therefore call every clone an authoring repo — which is
        exactly how this discriminator was wrong the first time.
        """
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=[])
            _write(root / "kept.template.md")            # skill-seed, ships as-is
            _write(root / ".engine-manifest.yml",
                   "engine:\n  - shipped\n"
                   "template:\n  - gone.template.md\n  - kept.template.md\n"
                   "seed_skill:\n  - kept.template.md\n")
            _git(root, "add", "-A")
            _git(root, "commit", "--quiet", "-m", "seeds")
            # `gone.template.md` was never created — this tree looks like a clone
            with self.assertRaises(G.NotAuthoringRepo):
                G.undeclared(root)

    def test_shallow_clone_refuses_instead_of_passing(self):
        """A truncated history cannot answer the question — silence is not a pass."""
        with tempfile.TemporaryDirectory() as td:
            root = _fixture(Path(td), retired=["shipped/declared.py"])
            shallow = Path(td) / "shallow"
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1",
                 f"file://{root}", str(shallow)],
                capture_output=True, check=True,
            )
            with self.assertRaises(G.ShallowHistory):
                G.undeclared(shallow)


if __name__ == "__main__":
    unittest.main()
