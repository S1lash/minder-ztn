#!/usr/bin/env python3
"""Retirement gate — every shipped path this engine deleted is declared in `retired:`.

A sync copies what upstream HAS. It cannot express what upstream no longer has:
`sync_engine.sh` walks the manifest's paths, and a path that is gone upstream is
simply never walked, so the local copy is left alone. `retired:` is the only
channel that says «delete this», and `retire_paths.py` runs it on every update.

So an engine file deleted without a `retired:` entry does not disappear from
anyone's clone — it lives there forever. That is bad on its own, and it gets
worse when a removal is declared only in part: the surviving half goes on
importing the retired half, and the update that was supposed to clean the tree
is what breaks it. A dead-but-self-consistent tree becomes a broken one, and the
breakage appears on the friend's machine, at update time, in code neither of you
was touching.

Nothing else notices this. Every other gate reasons about what the engine HAS —
the seed contract, the portability rules, the personal-data linter all scan
shipped files. The absence of a file is not a file, so no content scan can see
it. Only a check that compares the engine's own history against its declaration
can, which is what this is.

Method: every path git ever deleted or renamed away, kept if it (a) is absent
now, (b) sat under a shipped area (`engine:` / `template:`), (c) is not under
`exclude:`, and (d) is not already in `retired:`. Renames count by their OLD
name — to a friend's clone a rename is a delete plus an add, and the old name is
what stays behind.

Deliberately history-wide rather than since-last-release: a clone can be dark for
months and update from any version, so the obligation is the whole set, not the
delta. That is the same reason `retire_paths.py` runs on every sync instead of
once.

Usage:
  scripts/check_retirements.py            # fail (exit 1) on any undeclared retirement
  scripts/check_retirements.py --report   # list findings, always exit 0
  (imported)  undeclared(root) -> list[str]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

from lib.manifest import load_manifest, repo_root  # noqa: E402
from lib.portable import configure_std_streams  # noqa: E402

MANIFEST = ".engine-manifest.yml"


def _under(relpath: str, roots: list[str]) -> bool:
    """True when `relpath` is one of `roots` or sits beneath one of them."""
    return any(relpath == root or relpath.startswith(root + "/") for root in roots)


def _is_migration(relpath: str) -> bool:
    """True for anything living in a migrations directory. These are never retired.

    `sync_engine.sh` runs `retire_paths.py` BEFORE `run_migrations.py`, so
    retiring a migration deletes it in the same update that would have run it.
    On a clone where the chain had not reached that migration yet, the
    obligation is cancelled rather than fulfilled, silently and permanently.
    Keeping the file costs nothing in exchange: the ledger already skips an
    applied migration, so a spent one is inert where it lies.
    """
    return "/migrations/" in f"/{relpath}"


class NotAGitRepo(RuntimeError):
    """Raised when there is no history to read at all."""


def _git(root: Path, *args: str) -> str:
    # `core.quotepath=false` and an explicit encoding: git quotes non-ASCII
    # paths by default and `text=True` would decode with the locale codepage,
    # which on Git Bash is not UTF-8. A path this gate cannot spell is a path
    # it cannot judge.
    try:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
            capture_output=True, encoding="utf-8", check=True,
        ).stdout
    except FileNotFoundError as exc:  # no git binary at all
        raise NotAGitRepo(f"git is not available: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise NotAGitRepo(
            f"not a git repository (or git refused): {(exc.stderr or '').strip()}"
        ) from exc


def _shipped_roots(manifest: dict) -> list[str]:
    roots = {str(p).rstrip("/") for p in (manifest.get("engine") or [])}
    roots |= {str(p).rstrip("/") for p in (manifest.get("template") or [])}
    return sorted(roots)


def _shipped_at(root: Path, commit: str, cache: dict) -> list[str]:
    """Shipped roots as the manifest read at `commit`. Memoised per commit."""
    if commit in cache:
        return cache[commit]
    roots: list[str] = []
    try:
        blob = _git(root, "show", f"{commit}:{MANIFEST}")
        past = yaml.safe_load(blob) or {}
        if isinstance(past, dict):
            roots = _shipped_roots(past)
    except (NotAGitRepo, yaml.YAMLError):
        roots = []  # no manifest yet, or a malformed revision — proves nothing
    cache[commit] = roots
    return roots


def _vanished(root: Path) -> dict[str, str]:
    """Paths git deleted or renamed away → the commit that removed each.

    Keyed by the name a clone would still be holding: for a rename that is the
    OLD name, because downstream a rename is a delete plus an add and the old
    name is what stays behind.
    """
    # -M so a rename reads as R, not delete+add. `--all` so a path removed on a
    # branch that later merged is included. One pass: the commit sha arrives on
    # its own line, the paths under it follow.
    out = _git(root, "log", "--all", "--diff-filter=DR", "--name-status", "-M",
               "--format=%H")
    seen: dict[str, str] = {}
    commit = ""
    for line in out.splitlines():
        if not line:
            continue
        if "\t" not in line:
            commit = line.strip()
            continue
        fields = line.split("\t")
        if len(fields) < 2 or not fields[0]:
            continue
        status = fields[0]
        if status == "D" or status.startswith("R"):
            seen.setdefault(fields[1], commit)  # first (newest) removal wins
    return seen


class ShallowHistory(RuntimeError):
    """Raised when the clone cannot answer the question this gate asks."""


class NotAuthoringRepo(RuntimeError):
    """Raised on a released clone, where the question is meaningless."""


def _is_shallow(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-shallow-repository").strip() == "true"


def _is_authoring_repo(root: Path, manifest: dict) -> bool:
    """True in the repo the engine is authored in, false in a released clone.

    The discriminator is the STRIP-SEED template sources. Those are the entries
    release renames — `X.template.md` here becomes `X.md` in a clone — so their
    presence means upstream and their absence means downstream.

    Skill-seed entries (`template:` ∩ `seed_skill:`) are useless here: release
    copies them verbatim, `.template` and all, so they exist on both sides and
    testing them would call every clone an authoring repo.
    """
    skill_seed = {str(p) for p in (manifest.get("seed_skill") or [])}
    strip_seed = [str(p) for p in (manifest.get("template") or [])
                  if str(p) not in skill_seed]
    if not strip_seed:
        return True  # nothing to discriminate on; assume authoring
    return any((root / t).exists() for t in strip_seed)


def undeclared(root: Path | None = None) -> list[str]:
    """Shipped paths this engine deleted without declaring them in `retired:`.

    Raises `ShallowHistory` on a truncated clone. A shallow checkout — the CI
    default — has no record of the deletions, so the scan would find nothing and
    read as clean: a pass earned by not being able to look. Refusing is the only
    honest answer, and it is the same rule the identity gate follows.
    """
    root = root or repo_root()
    if _is_shallow(root):
        raise ShallowHistory(
            "shallow clone — this gate reads `git log --all` for deleted paths "
            "and a truncated history cannot answer it. Check out with full "
            "history (`fetch-depth: 0` on actions/checkout), or run it locally."
        )
    manifest = load_manifest(root)
    if not _is_authoring_repo(root, manifest):
        raise NotAuthoringRepo(
            "released clone — this gate reasons about the ENGINE's authoring "
            "history, and a clone's history is the release lineage instead. "
            "Every release strips template markers and rewrites the tree, so "
            "the deletions visible here are the release's, not the engine's, "
            "and the question has no meaning. Run it in the repo the engine is "
            "authored in."
        )

    shipped = _shipped_roots(manifest)
    excluded = [str(p).rstrip("/") for p in (manifest.get("exclude") or [])]
    # A directory entry retires everything beneath it — `retire_paths.py` deletes
    # the tree. Matching only exact strings here would report files a directory
    # entry already covers, and the two would disagree about the same manifest.
    retired = [str(p).rstrip("/") for p in (manifest.get("retired") or [])]

    tracked = set(_git(root, "ls-files").splitlines())

    vanished = _vanished(root)
    at_commit: dict[str, list[str]] = {}

    findings = []
    for relpath in sorted(vanished):
        if relpath in tracked or (root / relpath).exists():
            continue  # came back, or was restored under a new commit
        if _under(relpath, excluded):
            continue  # owner-only, never shipped
        # Cheap test first: still under a current shipped root. Only when that
        # fails do we pay a git round-trip to ask whether it was shipped at the
        # moment it was deleted — the case where the manifest line went in the
        # same commit as the file.
        if not _under(relpath, shipped):
            commit = vanished[relpath]
            if not commit or not _under(relpath, _shipped_at(root, f"{commit}^", at_commit)):
                continue
        if _is_migration(relpath):
            continue  # never retired — see _is_migration
        if _under(relpath, retired):
            continue
        findings.append(relpath)
    return findings


def conflicts(root: Path | None = None) -> list[str]:
    """`retired:` entries that exist right now — an authoring conflict.

    `retire_paths.py` runs on every sync, so a path that is both declared
    retired and present upstream is checked out and deleted again on every
    update, forever, on every clone. It reads as a live file here and never
    exists anywhere else. Retiring a path is not a one-time act, which is why
    this cannot be left to whoever notices.
    """
    root = root or repo_root()
    manifest = load_manifest(root)
    tracked = set(_git(root, "ls-files").splitlines())
    return sorted(
        entry for entry in (str(p).rstrip("/") for p in (manifest.get("retired") or []))
        if entry in tracked or (root / entry).exists()
    )


def main() -> int:
    configure_std_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None, help="repo root (default: resolved)")
    parser.add_argument("--report", action="store_true",
                        help="list findings and exit 0 regardless")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else repo_root()
    try:
        findings = undeclared(root)
        clashes = conflicts(root)
    except (ShallowHistory, NotAuthoringRepo, NotAGitRepo) as exc:
        print(f"retirements: cannot run — {exc}", file=sys.stderr)
        return 1

    if not findings and not clashes:
        print("retirements: clean — every deleted shipped path is declared, "
              "and nothing declared retired still exists")
        return 0

    if findings:
        print(f"retirements: {len(findings)} shipped path(s) deleted but not declared "
              f"in `.engine-manifest.yml → retired:`")
        print("")
        for relpath in findings:
            print(f"  {relpath}")
        print("")
        print("Each of these still exists on every clone that ever received it, and a")
        print("partial removal leaves the survivors importing what was retired. Add them")
        print("to `retired:` — grouped under a comment saying what the removal was — or,")
        print("if a path must stay, restore it.")

    if clashes:
        if findings:
            print("")
        print(f"retirements: {len(clashes)} path(s) are declared retired AND exist here")
        print("")
        for relpath in clashes:
            print(f"  {relpath}")
        print("")
        print("`retire_paths.py` runs on every sync, so each of these is checked out")
        print("and deleted again on every update — present here, absent everywhere else.")
        print("Either drop the `retired:` entry or delete the path.")

    return 0 if args.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
