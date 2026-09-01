#!/usr/bin/env python3
"""Migration-coverage gate — every migration has a suite that RUNS it, or a
declared exemption that carries a reason.

Why this exists. Coverage of migrations was a habit rather than a rule: six of
twenty-eight had a suite, and the gap grew by three across two releases. Nothing
in the engine fails when a migration arrives untested, so the practice ran on
the author's memory and stopped without any artifact looking wrong — the same
shape as every other step described in a document and implemented nowhere.

Why a migration in particular. A `heal` migration that FAILS is recorded and
retried on the next update, so its failure is loud and recoverable. A `heal`
that SUCCEEDS while doing the wrong thing is marked `applied` and never runs
again — not on this clone, not after a corrected version ships. That is the
expensive case, it is silent, and only a test that executes the script can see
it. So the gate asks for execution, not for a declaration of intent.

What counts as coverage. A test class that:

  1. declares `NAME = "<migration file name>"`,
  2. holds at least one `test_*` method, and
  3. calls the shared runner that executes that script in a subprocess.

All three are read out of the test module's syntax tree, never out of its text:
a `NAME` line is trivial to write beside no test at all, and grep cannot tell
the difference. Inheritance is resolved within the module, because a suite may
park its runner and its tests on a fixture class it mixes in.

The exemption list is a CLOSED legacy baseline, not an inbox. Its `watermark:`
line names the highest migration number that existed when the gate was
introduced; anything above it cannot be exempted at all. An entry needs a reason
and a date, an entry for a migration that is not on disk is a finding, and an
entry for a migration that IS covered is a stale finding — so the list can only
shrink.

Usage:
  scripts/check_migration_coverage.py            # exit 1 on any finding
  scripts/check_migration_coverage.py --report   # list findings, always exit 0
  (imported)  findings(root) -> list[str]
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.portable import configure_std_streams  # noqa: E402

MIGRATIONS_REL = "scripts/migrations"
TESTS_REL = "zettelkasten/_system/scripts/tests"
ALLOWLIST_REL = "scripts/migration-coverage-allowlist.txt"

# The names a suite may use for its migration runner. A name alone proves
# nothing — the function it resolves to must itself shell out, which is checked
# below. Without that, a suite can satisfy the gate with `def _run(m): pass`.
RUNNER_NAMES = frozenset({"_run", "_run_migration"})

# Modules whose functions count as executing a migration.
_SUBPROCESS_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})

# The highest migration number that existed when this gate was introduced.
# It lives HERE, not in the allowlist: a limit a file declares about itself is
# raised by editing that file, which is exactly the move it exists to prevent.
WATERMARK = 29

_MIGRATION_RE = re.compile(r"^(\d{3})-[a-z0-9-]+\.sh$")


def _migrations(root: Path) -> list[str]:
    """Every shell script the runner would execute — its glob, not a stricter one.

    `lib.migrations` runs `sorted(migrations_dir.glob("*.sh"))`. A gate that
    enumerated a narrower set would leave anything outside its pattern executed
    on every clone and counted by nothing, which is the shape of hole this gate
    exists to close. Names that break the convention are reported rather than
    skipped.
    """
    d = root / MIGRATIONS_REL
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*.sh"))


def _number(name: str) -> int | None:
    m = _MIGRATION_RE.match(name)
    return int(m.group(1)) if m else None


def _executes_a_subprocess(node: ast.AST) -> bool:
    """The function body actually shells out."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in _SUBPROCESS_CALLS:
                owner = sub.func.value
                if isinstance(owner, ast.Name) and owner.id == "subprocess":
                    return True
    return False


def _executing_runners(tree: ast.AST) -> set[str]:
    """Runner names in this module whose own body runs a subprocess.

    A call to something called `_run` is not evidence: `def _run(m): pass`
    satisfies a name check while executing nothing, and a suite built that way
    would report a destructive migration as covered. So the name is resolved to
    its definition and the definition has to shell out.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in RUNNER_NAMES and _executes_a_subprocess(node):
                out.add(node.name)
    return out


def _calls_runner(node: ast.AST, executing: set[str]) -> bool:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id in executing:
            return True
        if isinstance(func, ast.Attribute) and func.attr in executing:
            return True
    return False


def _has_test_method(node: ast.ClassDef) -> bool:
    return any(
        isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name.startswith("test_")
        for b in node.body
    )


def _declared_name(node: ast.ClassDef) -> str | None:
    for b in node.body:
        if not isinstance(b, ast.Assign):
            continue
        for t in b.targets:
            if isinstance(t, ast.Name) and t.id == "NAME" and isinstance(b.value, ast.Constant):
                if isinstance(b.value.value, str):
                    return b.value.value
    return None


def _local_bases(node: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    """Base classes defined in the same module, transitively.

    A suite may keep its runner and its tests on a fixture it mixes in, so a
    class judged only on its own body would read as uncovered while its tests
    genuinely execute the migration.
    """
    out: list[ast.ClassDef] = []
    seen: set[str] = set()
    stack = [b.id for b in node.bases if isinstance(b, ast.Name)]
    while stack:
        name = stack.pop()
        if name in seen or name not in classes:
            continue
        seen.add(name)
        base = classes[name]
        out.append(base)
        stack.extend(b.id for b in base.bases if isinstance(b, ast.Name))
    return out


def covered(root: Path) -> dict[str, str]:
    """migration file name -> the test class that proves it runs."""
    found: dict[str, str] = {}
    tests_dir = root / TESTS_REL
    if not tests_dir.is_dir():
        return found
    for path in sorted(tests_dir.glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        executing = _executing_runners(tree)
        if not executing:
            continue
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        for node in classes.values():
            family = [node] + _local_bases(node, classes)
            # `NAME` is resolved through the family, nearest first: a suite may
            # park the fixture — and the name with it — on a mixin, and the
            # class that actually holds the tests then declares nothing.
            name = next((n for n in (_declared_name(c) for c in family) if n), None)
            if not name:
                continue
            if not any(_has_test_method(c) for c in family):
                continue
            if not any(_calls_runner(c, executing) for c in family):
                continue
            found.setdefault(name, node.name)
    return found


def _parse_allowlist(root: Path) -> tuple[dict[str, str], int | None, list[str]]:
    """(name -> reason, watermark, findings about the list itself)."""
    path = root / ALLOWLIST_REL
    entries: dict[str, str] = {}
    watermark: int | None = None
    problems: list[str] = []
    if not path.is_file():
        return entries, watermark, problems
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("watermark:"):
            tail = line.split(":", 1)[1].strip()
            if not tail.isdigit():
                problems.append(f"{ALLOWLIST_REL}:{lineno}: watermark must be a number, got `{tail}`")
            elif int(tail) != WATERMARK:
                # The authority is the constant in this file. The line exists so
                # a reader of the list sees the limit without opening the gate —
                # if the two disagree, the list is trying to raise its own
                # ceiling, which is the one move it must not be able to make.
                problems.append(
                    f"{ALLOWLIST_REL}:{lineno}: declares watermark {tail}, but the "
                    f"gate's own is {WATERMARK}. The list cannot raise its ceiling — "
                    f"write the suite instead"
                )
            else:
                watermark = int(tail)
            continue
        parts = [p.strip() for p in line.split("|")]
        name = parts[0]
        reason = parts[1] if len(parts) > 1 else ""
        date = parts[2] if len(parts) > 2 else ""
        if not reason:
            problems.append(
                f"{ALLOWLIST_REL}:{lineno}: `{name}` is exempted with no reason — "
                "an exemption without one is how the list becomes an inbox"
            )
            continue
        if not date:
            problems.append(f"{ALLOWLIST_REL}:{lineno}: `{name}` is exempted with no date")
            continue
        entries[name] = reason
    return entries, watermark, problems


def findings(root: Path) -> list[str]:
    root = Path(root)
    migrations = _migrations(root)
    on_disk = set(migrations)
    have = covered(root)
    exempt, declared_watermark, out = _parse_allowlist(root)
    # A missing line is not permission: the ceiling is the constant either way.
    if exempt and declared_watermark is None:
        out.append(
            f"{ALLOWLIST_REL}: no `watermark:` line. It must be present and equal "
            f"{WATERMARK}, so a reader of the list can see the ceiling"
        )

    for name in migrations:
        if not _MIGRATION_RE.match(name):
            out.append(
                f"{name}: name breaks the `NNN-slug.sh` convention. The runner "
                f"globs `*.sh`, so this IS executed on every clone — rename it"
            )

    for name in sorted(exempt):
        if name not in on_disk:
            out.append(
                f"{name}: exempted but not on disk — drop the row, it silences nothing"
            )
            continue
        if name in have:
            out.append(
                f"{name}: exemption is stale — covered by `{have[name]}`. "
                "The list only shrinks; remove the row"
            )
            continue
        num = _number(name)
        if num is not None and num > WATERMARK:
            out.append(
                f"{name}: above the watermark ({WATERMARK}) — a migration added after "
                "this gate cannot be exempted. Write the suite"
            )

    for name in migrations:
        if name in have or name in exempt:
            continue
        out.append(
            f"{name}: no suite runs it, and it is not exempted. A test class needs "
            f'`NAME = "{name}"`, a `test_*` method, and a call to the shared runner'
        )
    return out


def main() -> int:
    # An exemption reason or a migration name can carry non-ASCII text, and a
    # Windows console encodes stdout through the platform code page unless it
    # is told otherwise — one such character would end the run in a traceback.
    configure_std_streams()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="repo root (default: this file's repo)")
    ap.add_argument("--report", action="store_true", help="list findings, always exit 0")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    found = findings(root)
    total = len(_migrations(root))
    have = len(covered(root))
    if not found:
        print(f"migration coverage: {have}/{total} covered by a suite, rest exempted — clean")
        return 0

    print(f"migration coverage: {len(found)} finding(s) ({have}/{total} covered)")
    print("")
    for f in found:
        print(f"  {f}")
    print("")
    print("A migration that no test executes can succeed at the wrong thing, be marked")
    print("`applied`, and never run again — on this clone or on a friend's.")
    return 0 if args.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
