"""Migration-coverage gate — a migration ships with a suite, or with a declared
exemption that carries a reason.

The defect this pins: coverage was a habit, not a rule. Six of twenty-eight
migrations had a suite, and the gap grew by three over two releases, because
nothing anywhere fails when a migration arrives untested. A step described in a
document and implemented nowhere runs on goodwill and then quietly stops.

The tests below fix the two ways a coverage claim can be false: a suite that
names a migration without running it, and an exemption that quietly absorbs
whatever nobody wanted to test.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parents[4] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import check_migration_coverage as cov  # noqa: E402


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _base(tmp: Path, *, migrations: list[str], suites: str = "", allowlist: str | None = None):
    for name in migrations:
        _write(tmp, f"scripts/migrations/{name}", "#!/usr/bin/env bash\n# migration-kind: heal\n")
    _write(tmp, "zettelkasten/_system/scripts/tests/test_migrations.py", suites or "\n")
    if allowlist is not None:
        _write(tmp, cov.ALLOWLIST_REL, allowlist)
    return tmp


_SUITE_REAL = '''
import subprocess

def _run(mig):
    return subprocess.run(["bash", mig])

class MigrationXTests:
    NAME = "030-example.sh"

    def test_it_applies(self):
        _run(self.NAME)
'''

_SUITE_NAME_ONLY = '''
class MigrationXTests:
    NAME = "030-example.sh"
'''

_SUITE_NOOP_RUNNER = '''
def _run(mig):
    return None

class MigrationXTests:
    NAME = "030-example.sh"

    def test_it_applies(self):
        _run(self.NAME)
'''

_SUITE_NO_RUNNER = '''
class MigrationXTests:
    NAME = "030-example.sh"

    def test_it_applies(self):
        assert True
'''


class CoverageTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    # --- the accepting side: a real suite counts -------------------------
    def test_suite_that_runs_the_migration_counts_as_covered(self):
        _base(self.root, migrations=["030-example.sh"], suites=_SUITE_REAL, allowlist="")
        self.assertEqual(cov.findings(self.root), [])

    # --- the refusing side ------------------------------------------------
    def test_migration_without_suite_is_reported_by_name(self):
        _base(self.root, migrations=["030-example.sh"], allowlist="")
        found = cov.findings(self.root)
        self.assertTrue(any("030-example.sh" in f for f in found), found)

    def test_name_without_a_test_method_is_not_coverage(self):
        _base(self.root, migrations=["030-example.sh"], suites=_SUITE_NAME_ONLY, allowlist="")
        self.assertTrue(any("030-example.sh" in f for f in cov.findings(self.root)))

    def test_test_method_that_never_runs_the_migration_is_not_coverage(self):
        _base(self.root, migrations=["030-example.sh"], suites=_SUITE_NO_RUNNER, allowlist="")
        self.assertTrue(any("030-example.sh" in f for f in cov.findings(self.root)))

    # --- the allowlist ----------------------------------------------------
    def test_exemption_with_reason_and_date_silences_the_finding(self):
        _base(self.root, migrations=["003-old.sh"], allowlist="watermark: 29\n003-old.sh | already applied everywhere | 2026-09-01\n")
        self.assertEqual(cov.findings(self.root), [])

    def test_exemption_without_reason_is_itself_a_finding(self):
        _base(self.root, migrations=["003-old.sh"], allowlist="watermark: 29\n003-old.sh\n")
        self.assertTrue(any("reason" in f.lower() for f in cov.findings(self.root)))

    def test_exemption_for_a_migration_that_does_not_exist_is_a_finding(self):
        _base(self.root, migrations=["003-old.sh"], allowlist="watermark: 29\n003-old.sh | r | 2026-09-01\n099-ghost.sh | r | 2026-09-01\n")
        self.assertTrue(any("099-ghost.sh" in f for f in cov.findings(self.root)))

    def test_exemption_above_the_watermark_is_refused(self):
        _base(self.root, migrations=["030-example.sh"], allowlist="watermark: 29\n030-example.sh | too lazy | 2026-09-01\n")
        found = cov.findings(self.root)
        self.assertTrue(any("030-example.sh" in f and "watermark" in f.lower() for f in found), found)

    def test_exemption_for_an_already_covered_migration_is_stale(self):
        _base(self.root, migrations=["003-old.sh"], suites=_SUITE_REAL.replace("030-example", "003-old"),
              allowlist="watermark: 29\n003-old.sh | r | 2026-09-01\n")
        self.assertTrue(any("stale" in f.lower() for f in cov.findings(self.root)))

    def test_a_runner_that_executes_nothing_is_not_coverage(self):
        """`def _run(m): pass` satisfies a name check and runs no migration."""
        _base(self.root, migrations=["030-example.sh"], suites=_SUITE_NOOP_RUNNER, allowlist="")
        self.assertTrue(any("030-example.sh" in f for f in cov.findings(self.root)))

    def test_the_list_cannot_raise_its_own_ceiling(self):
        _base(self.root, migrations=["030-example.sh"],
              allowlist="watermark: 30\n030-example.sh | convenient | 2026-09-01\n")
        found = cov.findings(self.root)
        self.assertTrue(any("ceiling" in f.lower() for f in found), found)

    def test_a_missing_watermark_is_not_permission(self):
        _base(self.root, migrations=["003-old.sh"],
              allowlist="003-old.sh | r | 2026-09-01\n")
        self.assertTrue(any("watermark" in f.lower() for f in cov.findings(self.root)))

    def test_a_script_outside_the_naming_convention_is_reported(self):
        """The runner globs `*.sh`, so it executes this — the gate must see it."""
        _base(self.root, migrations=["not-a-migration.sh"], allowlist="watermark: 29\n")
        self.assertTrue(any("convention" in f.lower() for f in cov.findings(self.root)))


_SUITE_INHERITED_NAME = '''
import subprocess

class _Fixture:
    NAME = "030-example.sh"

    def _run(self, root):
        return subprocess.run(["bash", self.NAME])

class MigrationXTests(_Fixture):
    def test_it_applies(self):
        self._run(".")
'''


class InheritanceTests(unittest.TestCase):
    """A suite may park the fixture — and `NAME` with it — on a mixin.

    Found by the live tier: judging a class only on its own body reported the
    018 suite as absent while it was running the migration through an inherited
    runner. A rule that cannot see the shapes already in the tree would have
    made the gate's first act a false accusation.
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_name_and_runner_inherited_from_a_local_mixin_count(self):
        _base(self.root, migrations=["030-example.sh"],
              suites=_SUITE_INHERITED_NAME, allowlist="")
        self.assertEqual(cov.findings(self.root), [])

    def test_the_mixin_alone_is_not_coverage(self):
        """The fixture holds NAME and the runner but no test — it proves nothing."""
        suite = _SUITE_INHERITED_NAME.split("class MigrationXTests")[0]
        _base(self.root, migrations=["030-example.sh"], suites=suite, allowlist="")
        self.assertTrue(any("030-example.sh" in f for f in cov.findings(self.root)))


class LiveTreeTests(unittest.TestCase):
    """The gate must pass on this repository once the allowlist is filled."""

    def test_repo_is_clean(self):
        root = _THIS.parents[4]
        self.assertEqual(cov.findings(root), [])


if __name__ == "__main__":
    unittest.main()
