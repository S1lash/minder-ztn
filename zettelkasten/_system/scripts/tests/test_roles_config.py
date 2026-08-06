"""Tests for roles_config — the role file and the role's paths (CORE-SPEC §1).

Proves the frontmatter schema is enforced exactly, that `writes:` is a
path-prefix allowlist with every §1.1 validation rule live, that the prose
body is never parsed, that `RoleConfig` is the only home for role-relative
paths, and that `discover_roles` is a tolerant lister which never raises on a
malformed role.

Every rejection test has a named SIBLING proving the same check ACCEPTS an
unusual-but-legitimate shape — a validator that refuses what its author has
not seen silently kills a role, which is the failure mode this whole
subsystem exists to prevent.
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from tests._roles_fixture import (  # type: ignore
    DEFAULT_BODY,
    make_base,
    role_md_text,
    roles_dir,
    write_bytes,
    write_role,
    write_text,
)
import roles_config as rc  # type: ignore

STATE_SUGAR = "zettelkasten/_system/roles/notion-sync/state/"
INBOX_SUGAR = "zettelkasten/_sources/inbox/roles/"


def _role_dir(base: Path, name: str) -> Path:
    return roles_dir(base) / name


def _load(base: Path, dir_name: str = "notion-sync", **kwargs):
    rd = write_role(base, dir_name, **kwargs)
    return rc.load_role(rd, base)


def _paths(cfg) -> tuple:
    """The `path` of each expanded `WritePrefix`, in order."""
    return tuple(p.path for p in cfg.write_prefixes)


def _flat(cfg) -> dict:
    return {p.path: p.flat for p in cfg.write_prefixes}


# ==========================================================================
# required fields
# ==========================================================================

class RequiredFieldTests(unittest.TestCase):
    def test_rejects_missing_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, role_id=None)

    def test_rejects_missing_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, name=None)

    def test_rejects_missing_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, cadence=None)

    def test_accepts_minimal_role_with_only_the_three_required_fields(self):
        """SIBLING of the three above — every optional key defaulted."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base)
            self.assertEqual(cfg.id, "notion-sync")
            self.assertEqual(cfg.status, "active")
            self.assertEqual(cfg.write_prefixes, ())
            self.assertEqual(cfg.secrets, ())
            self.assertFalse(cfg.constitution)

    def test_error_message_names_the_file_and_the_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError) as ctx:
                _load(base, cadence=None)
            msg = str(ctx.exception)
            self.assertIn("role.md", msg)
            self.assertIn("cadence", msg)

    def test_rejects_role_dir_without_role_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "empty-role")
            rd.mkdir(parents=True)
            with self.assertRaises(rc.RoleConfigError):
                rc.load_role(rd, base)

    def test_rejects_file_with_no_frontmatter_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_text(rd / "role.md", "## Задача\n\nТекст без шапки.\n")
            with self.assertRaises(rc.RoleConfigError):
                rc.load_role(rd, base)


# ==========================================================================
# id
# ==========================================================================

class IdTests(unittest.TestCase):
    def test_rejects_id_not_matching_dir_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, "notion-sync", role_id="notion-syncc")

    def test_rejects_id_with_uppercase(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, "Notion", role_id="Notion")

    def test_rejects_id_with_leading_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, "-notion", role_id="-notion")

    def test_rejects_id_with_underscore(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, "notion_sync", role_id="notion_sync")

    def test_accepts_id_with_digits(self):
        """SIBLING — `[a-z0-9][a-z0-9-]*` allows digits anywhere, incl. first."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, "3ds-check-v2", role_id="3ds-check-v2").id,
                             "3ds-check-v2")

    def test_accepts_single_character_id(self):
        """SIBLING — the shortest legal slug is one character."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, "x", role_id="x").id, "x")


# ==========================================================================
# name / status / constitution
# ==========================================================================

class NameTests(unittest.TestCase):
    def test_rejects_empty_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, name='""')

    def test_accepts_cyrillic_name(self):
        """SIBLING — the name is the owner's, in the owner's script."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, name="Ноушн-сверщик").name, "Ноушн-сверщик")

    def test_accepts_name_with_punctuation_and_emoji(self):
        """SIBLING — `name` is display text, not an identifier."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, name='"Руди — PM (утренний) 🌅"')
            self.assertEqual(cfg.name, "Руди — PM (утренний) 🌅")


class StatusTests(unittest.TestCase):
    def test_rejects_status_outside_the_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, status="disabled")

    def test_accepts_status_paused(self):
        """SIBLING — `paused` is the whole point of the field."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, status="paused").status, "paused")

    def test_accepts_status_active_stated_explicitly(self):
        """SIBLING — restating the default is not a defect."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, status="active").status, "active")


class TimeoutSecondsTests(unittest.TestCase):
    """§1 / §7.1(b) — the one bound the design commits to. An out-of-range or
    mistyped value must fail at validate time, not hang a nightly tick or
    kill a legitimate long run at second zero."""

    def test_defaults_to_900_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base).timeout_seconds, 900)

    def test_accepts_an_explicit_override(self):
        """SIBLING — the whole point of the key."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, timeout_seconds="1800").timeout_seconds, 1800)

    def test_accepts_the_default_restated_explicitly(self):
        """SIBLING — restating the default is not a defect."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, timeout_seconds="900").timeout_seconds, 900)

    def test_accepts_the_lower_bound_of_one_second(self):
        """SIBLING — boundary of the legal 1..86400 range."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, timeout_seconds="1").timeout_seconds, 1)

    def test_accepts_the_upper_bound_of_86400_seconds(self):
        """SIBLING — a full day is legal; a role doing a heavy monthly sweep
        is exactly why the ceiling is that high."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, timeout_seconds="86400").timeout_seconds, 86400)

    def test_rejects_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="0")

    def test_rejects_a_negative_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="-1")

    def test_rejects_above_the_upper_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="86401")

    def test_rejects_a_string_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds='"900"')

    def test_rejects_a_duration_expression(self):
        """`15m` is what someone reaches for when the key is named in seconds
        but the unit is not in the value; it must fail loudly, not coerce."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="15m")

    def test_rejects_a_float_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="900.5")

    def test_rejects_a_boolean_value(self):
        """YAML reads `true` as a bool, and python's `bool` is an `int`
        subclass — an `isinstance(v, int)` check alone would let `true`
        through as a one-second timeout."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, timeout_seconds="true")

    def test_timeout_seconds_is_an_int_not_a_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            value = _load(base, timeout_seconds="1800").timeout_seconds
            self.assertIsInstance(value, int)
            self.assertNotIsInstance(value, bool)


class ConstitutionFlagTests(unittest.TestCase):
    def test_rejects_non_boolean_constitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, constitution="maybe")

    def test_accepts_constitution_true(self):
        """SIBLING — the flag's whole purpose."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertIs(_load(base, constitution="true").constitution, True)

    def test_accepts_constitution_false_stated_explicitly(self):
        """SIBLING — restating the default is not a defect."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertIs(_load(base, constitution="false").constitution, False)


# ==========================================================================
# cadence (validated here, parsed by roles_cadence)
# ==========================================================================

class CadenceFieldTests(unittest.TestCase):
    def test_rejects_unparseable_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, cadence="fortnightly")

    def test_rejects_manual_cadence_which_the_grammar_no_longer_has(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, cadence="manual")

    def test_accepts_every_tick_cadence(self):
        """SIBLING — the loosest legal cadence, two bare words."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, cadence="every tick").cadence, "every tick")

    def test_accepts_weekly_with_a_time_anchor(self):
        """SIBLING — `weekly mon 09:00` is expressible per §2."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, cadence='"weekly mon 09:00"')
            self.assertEqual(cfg.cadence, "weekly mon 09:00")

    def test_accepts_quoted_time_anchor_cadence(self):
        """SIBLING — quoting the value is what a careful writer emits and must
        change nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, cadence='"daily 07:00"').cadence, "daily 07:00")


# ==========================================================================
# writes — a path-prefix allowlist (§1.1)
# ==========================================================================

class WritesSugarTests(unittest.TestCase):
    def test_state_sugar_expands_to_the_roles_state_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes="[state]")), (STATE_SUGAR,))

    def test_inbox_sugar_expands_to_the_roles_inbox_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes="[inbox]")), (INBOX_SUGAR,))

    def test_state_sugar_uses_the_roles_own_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, "other-role", role_id="other-role", writes="[state]")
            self.assertEqual(
                _paths(cfg), ("zettelkasten/_system/roles/other-role/state/",)
            )

    def test_accepts_explicitly_empty_writes_list(self):
        """SIBLING — a read-only role is legitimate."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, writes="[]").write_prefixes, ())

    def test_accepts_writes_in_yaml_block_style(self):
        """SIBLING — block and flow sequences are the same YAML value."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_text(rd / "role.md", role_md_text(writes="\n  - state\n  - inbox"))
            cfg = rc.load_role(rd, base)
            self.assertEqual(set(_paths(cfg)), {STATE_SUGAR, INBOX_SUGAR})

    def test_write_prefixes_is_a_tuple_of_write_prefix_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            prefixes = _load(base, writes="[state, inbox]").write_prefixes
            self.assertIsInstance(prefixes, tuple)
            for p in prefixes:
                self.assertIsInstance(p, rc.WritePrefix)
                self.assertIsInstance(p.path, str)
                self.assertIsInstance(p.flat, bool)

    def test_write_prefix_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            prefix = _load(base, writes="[state]").write_prefixes[0]
            self.assertTrue(dataclasses.is_dataclass(prefix))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                prefix.flat = True  # type: ignore[misc]

    def test_rejects_writes_given_as_a_bare_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes="state")


class BaseDirectoryNameTests(unittest.TestCase):
    """§1.1 — the `zettelkasten/` component of the sugar is DERIVED from
    `base.name`, and the repo root is `base.parent`. No module carries a
    hardcoded base-directory constant: an owner who renames their base would
    otherwise get sugar that expands to a prefix matching nothing, and every
    in-zone write would be reverted on every run."""

    def test_state_sugar_uses_the_actual_base_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp), dirname="mybrain")
            cfg = _load(base, writes="[state]")
            self.assertEqual(
                _paths(cfg), ("mybrain/_system/roles/notion-sync/state/",)
            )

    def test_inbox_sugar_uses_the_actual_base_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp), dirname="mybrain")
            self.assertEqual(
                _paths(_load(base, writes="[inbox]")), ("mybrain/_sources/inbox/roles/",)
            )

    def test_no_sugar_prefix_mentions_zettelkasten_under_a_renamed_base(self):
        """The sharpest form: nothing may leak the default name through."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp), dirname="второй-мозг")
            cfg = _load(base, writes="[state, inbox]")
            for path in _paths(cfg):
                self.assertNotIn("zettelkasten", path)
                self.assertTrue(path.startswith("второй-мозг/"))

    def test_a_renamed_base_still_resolves_the_role_paths(self):
        """SIBLING — the path properties follow the same rename."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp), dirname="mybrain")
            cfg = _load(base)
            self.assertEqual(cfg.dir, base / "_system" / "roles" / "notion-sync")
            self.assertEqual(cfg.dir.parent.parent.parent.name, "mybrain")

    def test_the_default_base_name_still_works(self):
        """SIBLING — deriving the name must not break the ordinary install."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes="[state]")), (STATE_SUGAR,))


class ResolveBaseTests(unittest.TestCase):
    """§1 — the single door a `--base` passes through, called once where the
    flag is parsed so nothing downstream has to wonder.

    It exists because `--base .` is the house convention for every other
    script in the engine, and the sugar expands from `base.name`:
    `Path(".").name` is `""`, so the prefixes became
    `/_system/roles/{id}/state/`, matched nothing, and every write a role made
    into its own state tree was reverted — its memory destroyed on every run,
    with `validate` reporting `{"ok": true}`.

    Resolution, not rejection. The two hard errors are the shapes where no
    resolution exists: a filesystem root has no `.name` to expand the sugar
    from, and a base whose parent is not a directory has no repo root.
    """

    def test_a_relative_path_resolves_to_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            previous = os.getcwd()
            os.chdir(str(base))
            try:
                resolved = rc.resolve_base(Path("."))
            finally:
                os.chdir(previous)
            self.assertTrue(resolved.is_absolute())
            self.assertEqual(resolved.name, base.name)

    def test_dot_resolves_to_a_base_whose_name_expands_the_sugar(self):
        """The defect in one assertion: the resolved name is what the sugar is
        built from, so an empty one is the whole bug."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            previous = os.getcwd()
            os.chdir(str(base))
            try:
                resolved = rc.resolve_base(Path("."))
            finally:
                os.chdir(previous)
            self.assertNotEqual(resolved.name, "")
            self.assertTrue(resolved.parent.is_dir())

    def test_an_absolute_path_is_returned_unchanged_in_meaning(self):
        """SIBLING — resolving must be a no-op for the shape that already
        works; a normaliser that alters an absolute path would move the base."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            resolved = rc.resolve_base(base)
            self.assertTrue(resolved.is_absolute())
            self.assertEqual(resolved.name, base.name)
            self.assertEqual(resolved, rc.resolve_base(resolved), "idempotent")

    def test_a_named_relative_path_resolves(self):
        """SIBLING — `--base zettelkasten` from the repo root."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            previous = os.getcwd()
            os.chdir(str(base.parent))
            try:
                resolved = rc.resolve_base(Path(base.name))
            finally:
                os.chdir(previous)
            self.assertEqual(resolved.name, base.name)
            self.assertTrue(resolved.is_absolute())

    def test_a_dotdot_relative_path_normalises(self):
        """SIBLING — `--base ../zettelkasten` from a sibling directory. The
        `..` must be normalised away, or it reappears inside every rendered
        path in the run frame."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            elsewhere = base.parent / "elsewhere"
            elsewhere.mkdir()
            previous = os.getcwd()
            os.chdir(str(elsewhere))
            try:
                resolved = rc.resolve_base(Path("..") / base.name)
            finally:
                os.chdir(previous)
            self.assertEqual(resolved.name, base.name)
            self.assertNotIn("..", str(resolved))

    def test_a_trailing_separator_is_accepted(self):
        """SIBLING — a shell tab-completion leaves one, and a string-based
        implementation would take `.name` of the empty segment after it."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            resolved = rc.resolve_base(Path(str(base) + os.sep))
            self.assertEqual(resolved.name, base.name)

    def test_a_base_reached_through_a_symlink_is_accepted(self):
        """SIBLING — a base reached by symlink must work, not be refused. What
        the resolved NAME becomes is deliberately not asserted: both readings
        are defensible and neither is specified. Refusing outright is the one
        outcome that is not."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            link = Path(tmp) / "linked-base"
            try:
                link.symlink_to(base, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable on this platform: {exc}")
            resolved = rc.resolve_base(link)
            self.assertTrue(resolved.is_absolute())
            self.assertNotEqual(resolved.name, "")
            self.assertTrue(resolved.parent.is_dir())

    def test_a_base_that_does_not_exist_yet_still_resolves(self):
        """SIBLING — resolution is a path operation. `validate` on a base that
        has not been created is a legitimate thing to ask, and it should
        report that clearly rather than die inside path handling."""
        with tempfile.TemporaryDirectory() as tmp:
            resolved = rc.resolve_base(Path(tmp) / "not-created-yet")
            self.assertTrue(resolved.is_absolute())
            self.assertEqual(resolved.name, "not-created-yet")

    def test_a_filesystem_root_raises_naming_the_defect(self):
        """No `.name` to expand the sugar from — the exact shape that produced
        `/_system/roles/{id}/state/`."""
        root = Path(Path(tempfile.gettempdir()).anchor)
        self.assertEqual(root.name, "", "premise: a root has no name")
        with self.assertRaises(rc.RoleConfigError) as ctx:
            rc.resolve_base(root)
        self.assertTrue(str(ctx.exception).strip())

    def test_a_base_whose_parent_is_not_a_directory_raises(self):
        """The repo root is `base.parent`; a file there means there is no repo
        to be relative to."""
        with tempfile.TemporaryDirectory() as tmp:
            not_a_dir = Path(tmp) / "a-file"
            not_a_dir.write_text("x\n", encoding="utf-8")
            with self.assertRaises(rc.RoleConfigError):
                rc.resolve_base(not_a_dir / "base")

    def test_resolution_is_not_a_rejection_machine(self):
        """SIBLING for both errors above, stated as a set: every ordinary
        shape an owner or a script can produce resolves without complaint. A
        validator that refuses what its author has not seen is worse than
        none, and this one guards the flag every invocation passes through."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp), dirname="второй-мозг")
            previous = os.getcwd()
            os.chdir(str(base.parent))
            try:
                candidates = [base, Path(base.name), Path("./" + base.name),
                              Path(str(base) + os.sep)]
                for candidate in candidates:
                    with self.subTest(base=str(candidate)):
                        resolved = rc.resolve_base(candidate)
                        self.assertEqual(resolved.name, "второй-мозг")
            finally:
                os.chdir(previous)


class ToRepoRelativeTests(unittest.TestCase):
    """§1 — the single home for path conversion, so no other module does it by
    hand. Returns `None` outside the repo; each caller decides what that means
    (the guard: outside `git status` entirely; the context: fall back to the
    absolute POSIX path in a header line)."""

    def test_returns_a_posix_repo_relative_string_for_a_path_inside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            target = repo / "zettelkasten" / "1_projects" / "PROJECTS.md"
            target.parent.mkdir(parents=True)
            target.write_text("x\n", encoding="utf-8")
            got = rc.to_repo_relative(repo, target)
            self.assertEqual(got, "zettelkasten/1_projects/PROJECTS.md")
            self.assertNotIn("\\", got)

    def test_returns_none_for_a_path_outside_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True)
            outside = Path(tmp) / "elsewhere" / "note.md"
            outside.parent.mkdir(parents=True)
            outside.write_text("x\n", encoding="utf-8")
            self.assertIsNone(rc.to_repo_relative(repo, outside))

    def test_returns_none_for_a_sibling_directory_sharing_a_name_prefix(self):
        """`/tmp/repo-backup/x` is not inside `/tmp/repo` — a string-prefix
        implementation would say it is, and the guard would then classify a
        stranger's file as the owner's."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True)
            sibling = Path(tmp) / "repo-backup" / "note.md"
            sibling.parent.mkdir(parents=True)
            sibling.write_text("x\n", encoding="utf-8")
            self.assertIsNone(rc.to_repo_relative(repo, sibling))

    def test_returns_none_for_a_parent_of_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True)
            self.assertIsNone(rc.to_repo_relative(repo, repo.parent))

    def test_accepts_a_deeply_nested_path(self):
        """SIBLING — depth is not a defect."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            target = repo / "a" / "b" / "c" / "d" / "e.md"
            target.parent.mkdir(parents=True)
            target.write_text("x\n", encoding="utf-8")
            self.assertEqual(rc.to_repo_relative(repo, target), "a/b/c/d/e.md")

    def test_accepts_a_cyrillic_path(self):
        """SIBLING — §0: the owner names their own files, in their own script,
        and the conversion must not mangle or refuse them."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            target = repo / "zettelkasten" / "_system" / "расхождения.md"
            target.parent.mkdir(parents=True)
            target.write_text("x\n", encoding="utf-8")
            self.assertEqual(
                rc.to_repo_relative(repo, target),
                "zettelkasten/_system/расхождения.md",
            )

    def test_accepts_a_path_that_does_not_exist_on_disk(self):
        """SIBLING — it is a pure path conversion, not a filesystem probe; the
        guard calls it for deleted paths, which by definition are not there."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True)
            self.assertEqual(
                rc.to_repo_relative(repo, repo / "gone" / "deleted.md"),
                "gone/deleted.md",
            )

    def test_the_repo_root_itself_resolves_to_dot(self):
        """Pinned to the answer that actually lands. This previously accepted
        `None`, `""` or `"."` — three contradictory contracts, so it could not
        fail. `"."` is what `to_repo_relative` returns, and a caller prefixing
        it onto a path must be able to rely on one of them."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True)
            self.assertEqual(rc.to_repo_relative(repo, repo), ".")

    def test_the_repo_root_is_never_confused_with_a_file_inside_it(self):
        """SIBLING — whatever the root maps to, it must not collide with a
        real entry, or a guard comparison would treat the whole repo as one
        path."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "sub").mkdir(parents=True)
            (repo / "sub" / "f.md").write_text("x\n", encoding="utf-8")
            self.assertNotEqual(rc.to_repo_relative(repo, repo),
                                rc.to_repo_relative(repo, repo / "sub" / "f.md"))

    def test_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            target = repo / "a" / "b.md"
            target.parent.mkdir(parents=True)
            target.write_text("x\n", encoding="utf-8")
            self.assertEqual(
                rc.to_repo_relative(repo, target), rc.to_repo_relative(repo, target)
            )


class WritePrefixFlatnessTests(unittest.TestCase):
    """§3.5 — flatness is a property OF the prefix, so the guard never needs
    its own copy of the inbox path that §1.1 already owns."""

    def test_inbox_sugar_is_flat(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertTrue(_flat(_load(base, writes="[inbox]"))[INBOX_SUGAR])

    def test_state_sugar_is_not_flat(self):
        """SIBLING — a role may build a tree inside its own `state/`."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertFalse(_flat(_load(base, writes="[state]"))[STATE_SUGAR])

    def test_an_explicit_prefix_is_not_flat(self):
        """SIBLING — flatness comes only from the `inbox` sugar; an owner-facing
        directory the role maintains may legitimately hold subdirectories."""
        rel = "zettelkasten/2_areas/team/"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertFalse(_flat(_load(base, writes=f'["{rel}"]'))[rel])

    def test_an_explicit_prefix_spelling_the_inbox_path_is_not_flat(self):
        """The flatness is carried by the SUGAR, not inferred from the string —
        an owner who writes the path out longhand gets a plain prefix, and the
        guard still has no inbox constant of its own."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertFalse(_flat(_load(base, writes=f'["{INBOX_SUGAR}"]'))[INBOX_SUGAR])

    def test_mixed_writes_carry_their_own_flatness(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            flags = _flat(_load(base, writes="[state, inbox]"))
            self.assertTrue(flags[INBOX_SUGAR])
            self.assertFalse(flags[STATE_SUGAR])


class WritesExplicitPrefixTests(unittest.TestCase):
    """§1.1 — every explicit-prefix validation rule, each with an accepts-sibling."""

    def test_accepts_an_explicit_prefix_the_owner_actually_reads(self):
        """SIBLING / the whole reason the set is open: a role that maintains
        `zettelkasten/2_areas/architecture.md` has no legitimate home under
        state or inbox. The path is kept verbatim — appending a trailing `/` to
        a FILE prefix would make it match nothing and kill the motivating case
        (see the report: §1.1 says verbatim, the `WritePrefix` field comment
        says trailing '/'; verbatim is tested)."""
        rel = "zettelkasten/2_areas/architecture.md"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{rel}"]')), (rel,))

    def test_accepts_an_explicit_prefix_deep_in_the_tree(self):
        """SIBLING — depth is not a defect."""
        deep = "zettelkasten/2_areas/team/notes/weekly/"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{deep}"]')), (deep,))

    def test_accepts_an_explicit_directory_prefix_without_a_trailing_slash(self):
        """SIBLING — §1.1: the path is stored VERBATIM, no trailing slash
        added. The matching rule (`p == q` or `p.startswith(q + "/")`) covers a
        file and a directory with one rule, so nothing needs normalising."""
        rel = "zettelkasten/2_areas/team"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{rel}"]')), (rel,))

    def test_accepts_sugar_and_explicit_prefixes_mixed(self):
        """SIBLING — §1.1 says they may be mixed."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, writes='[state, "zettelkasten/2_areas/architecture.md"]')
            self.assertEqual(
                set(_paths(cfg)),
                {STATE_SUGAR, "zettelkasten/2_areas/architecture.md"},
            )

    def test_rejects_absolute_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["/etc/cron.d/"]')

    def test_rejects_windows_drive_letter_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["C:/Windows/Temp/"]')

    def test_rejects_prefix_escaping_the_repo_with_dotdot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/../../etc/"]')

    def test_accepts_filename_containing_two_dots_that_is_not_a_traversal(self):
        """SIBLING — a naive `".." in prefix` check would refuse a legitimate
        filename. The rule is about path components after normalisation."""
        rel = "zettelkasten/2_areas/notes..md"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{rel}"]')), (rel,))

    def test_rejects_prefix_under_git_internals(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='[".git/hooks/"]')

    def test_accepts_prefix_under_dot_github_which_only_looks_like_git(self):
        """SIBLING — only `.git/` is banned; `.github/` is an ordinary
        directory and refusing it is the author's imagination, not the rule."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, writes='[".github/roles/"]')
            self.assertEqual(_paths(cfg), (".github/roles/",))

    def test_rejects_prefix_that_is_the_credential_store(self):
        """The store is COMMITTED ciphertext (§6.2), which makes this a
        strictly worse event than when the credentials sat in a gitignored
        file: a role allowed to write there could put a tampered blob into
        history, and the tick would commit and push it.

        The refusal has to name the store, or the owner reads «invalid prefix»
        and edits the path rather than understanding what was refused."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError) as ctx:
                _load(base, writes='["zettelkasten/_system/state/secrets.enc.json"]')
            self.assertIn("secrets.enc.json", str(ctx.exception))

    def test_rejects_prefix_that_contains_the_credential_store(self):
        """A directory prefix is enough — the role does not have to name the
        file to be able to write it."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/_system/state/"]')

    def test_rejects_prefix_that_contains_the_secrets_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/_system/state/"]')

    def test_accepts_sibling_directory_next_to_the_secrets_file(self):
        """SIBLING — `_system/state/roles-notes/` does not contain the secrets
        file; the rule is a path-boundary test, not a string prefix test."""
        rel = "zettelkasten/_system/state/roles-notes/"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{rel}"]')), (rel,))

    def test_rejects_empty_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='[""]')

    def test_rejects_prefix_that_is_a_roles_own_log(self):
        """§3.4 rule 9 — `log.jsonl` is never an allowed prefix; the tick
        writes it and a role writing its own log is a defect worth catching."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/_system/roles/notion-sync/log.jsonl"]')

    def test_accepts_a_state_file_named_log_jsonl(self):
        """SIBLING — the ban is on the tick's log path, not on the filename. A
        role keeping `state/log.jsonl` as its own journal is legitimate."""
        rel = "zettelkasten/_system/roles/notion-sync/state/log.jsonl"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_paths(_load(base, writes=f'["{rel}"]')), (rel,))


class WritesNormalisationTests(unittest.TestCase):
    """Equivalent spellings of one prefix must behave identically.

    The failure this guards is not a crash: it is a prefix that is ACCEPTED
    and then matches nothing. The role writes into what it believes is its
    zone, the guard classifies every write out-of-zone and reverts it, and
    `validate` stays green — the role's work is destroyed every night and no
    surface says so. Either normalise the spelling or refuse it; silently
    accepting a dead prefix is the one outcome that must not happen.
    """

    EQUIVALENT = (
        "zettelkasten/2_areas",
        "zettelkasten/./2_areas",
        "zettelkasten//2_areas",
        "./zettelkasten/2_areas",
        "zettelkasten/2_areas/.",
    )

    def _prefix_or_error(self, spelling: str):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            try:
                return _paths(_load(base, writes=f'["{spelling}"]'))[0], None
            except rc.RoleConfigError as exc:
                return None, exc

    def test_every_equivalent_spelling_is_normalised_or_refused(self):
        """Never «accepted and inert»."""
        for spelling in self.EQUIVALENT:
            with self.subTest(spelling=spelling):
                prefix, error = self._prefix_or_error(spelling)
                if error is not None:
                    self.assertTrue(str(error).strip(), "a refusal must say why")
                    continue
                self.assertNotIn("/./", prefix)
                self.assertNotIn("//", prefix)
                self.assertFalse(prefix.startswith("./"))
                self.assertFalse(prefix.endswith("/."))

    def test_every_accepted_spelling_yields_the_same_prefix(self):
        """SIBLING — equivalence, not merely tidiness: two spellings of one
        directory must not produce two different zones."""
        accepted = [p for p, e in map(self._prefix_or_error, self.EQUIVALENT)
                    if p is not None]
        self.assertTrue(accepted, "at least the plain spelling must be accepted")
        self.assertEqual(len(set(accepted)), 1, f"spellings diverged: {set(accepted)}")

    def test_a_trailing_slash_prefix_is_accepted(self):
        """SIBLING — the shape the `state` sugar itself produces."""
        prefix, error = self._prefix_or_error("zettelkasten/2_areas/")
        self.assertIsNone(error)
        self.assertIn(prefix, ("zettelkasten/2_areas", "zettelkasten/2_areas/"))

    def test_a_normalised_spelling_is_still_a_duplicate_of_the_plain_one(self):
        """Normalisation must happen BEFORE the duplicate check, or a role can
        declare the same zone twice and only one of them is enforced."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/2_areas", "zettelkasten/./2_areas"]')

    def test_a_traversal_that_normalises_back_inside_is_still_refused(self):
        """`..` is refused after normalisation, so a spelling that cancels out
        must not sneak through on the way."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='["zettelkasten/2_areas/../../etc"]')


class WritesDuplicateTests(unittest.TestCase):
    def test_rejects_duplicate_sugar_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes="[state, state]")

    def test_rejects_duplicate_after_expansion_of_sugar_and_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes=f'[state, "{STATE_SUGAR}"]')

    def test_rejects_the_state_sugar_spelled_out_without_a_trailing_slash(self):
        """§1.1 stores a prefix VERBATIM — nothing appends a trailing slash —
        so `state` and the slashless spelling of the same directory are the
        same zone and must collide. If they did not, a role could declare its
        state tree twice and get two prefixes that behave differently."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='[state, "zettelkasten/_system/roles/notion-sync/state"]')

    def test_rejects_the_inbox_sugar_spelled_out_without_a_trailing_slash(self):
        """The sharper half: an accepted duplicate here would be a SECOND,
        non-flat prefix over the inbox, and `inbox/roles/deep/nested.md` would
        pass the flat check by matching the other one — quietly undoing §3.5."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, writes='[inbox, "zettelkasten/_sources/inbox/roles"]')

    def test_the_inbox_sugar_alone_yields_exactly_one_flat_prefix(self):
        """SIBLING — the shape that must survive: one prefix, flat, so a
        nested inbox path has nothing else to match against."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            prefixes = _load(base, writes="[inbox]").write_prefixes
            self.assertEqual(len(prefixes), 1)
            self.assertTrue(prefixes[0].flat)

    def test_an_explicit_inbox_prefix_alone_is_accepted_and_not_flat(self):
        """SIBLING — declaring the inbox path explicitly, WITHOUT the sugar,
        is a legitimate (if unusual) way to ask for a non-flat inbox zone. It
        is only the combination that is a duplicate."""
        rel = "zettelkasten/_sources/inbox/roles"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            prefixes = _load(base, writes=f'["{rel}"]').write_prefixes
            self.assertEqual(len(prefixes), 1)
            self.assertFalse(prefixes[0].flat)

    def test_accepts_two_distinct_prefixes_that_share_a_parent(self):
        """SIBLING — overlapping parents are not duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(
                base,
                writes='["zettelkasten/2_areas/a/", "zettelkasten/2_areas/b/"]',
            )
            self.assertEqual(len(cfg.write_prefixes), 2)


# ==========================================================================
# secrets
# ==========================================================================

class SecretsTests(unittest.TestCase):
    def test_rejects_lowercase_secret_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, secrets="[notion_token]")

    def test_rejects_secret_name_starting_with_a_digit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, secrets="[1TOKEN]")

    def test_rejects_secret_name_starting_with_underscore(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, secrets="[_TOKEN]")

    def test_rejects_secret_name_with_a_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, secrets="[NOTION-TOKEN]")

    def test_accepts_secret_name_with_digits_and_underscores(self):
        """SIBLING — `[A-Z][A-Z0-9_]*` covers `NOTION_TOKEN_2`."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, secrets="[NOTION_TOKEN_2]").secrets,
                             ("NOTION_TOKEN_2",))

    def test_accepts_single_letter_secret_name(self):
        """SIBLING — the shortest legal env name is one capital."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(_load(base, secrets="[X]").secrets, ("X",))

    def test_accepts_several_secret_names(self):
        """SIBLING — a role may legitimately need more than one credential."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(
                _load(base, secrets="[NOTION_TOKEN, SLACK_TOKEN]").secrets,
                ("NOTION_TOKEN", "SLACK_TOKEN"),
            )

    def test_module_docstring_says_secrets_is_a_declaration_not_a_boundary(self):
        """§1 requires this verbatim in the module docstring, so no future
        reader mistakes `secrets:` for isolation."""
        doc = (rc.__doc__ or "").lower()
        self.assertIn("declaration", doc)
        self.assertIn("boundary", doc)


# ==========================================================================
# unknown frontmatter key — now normative (§1)
# ==========================================================================

class UnknownKeyTests(unittest.TestCase):
    def test_rejects_unknown_frontmatter_key_env_instead_of_secrets(self):
        """A typo'd or stale key must fail loudly at validate time, not produce
        a 401 at 07:00. `env:` is the stale spelling the design once used."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, extra="env: [NOTION_TOKEN]")

    def test_rejects_unknown_frontmatter_key_write_singular(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, extra="write: [state]")

    def test_unknown_key_error_names_the_offending_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError) as ctx:
                _load(base, extra="env: [NOTION_TOKEN]")
            self.assertIn("env", str(ctx.exception))

    def test_accepts_every_documented_key_present_at_once(self):
        """SIBLING — the full schema in one file must load cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(
                base,
                status="active",
                writes="[state, inbox]",
                secrets="[NOTION_TOKEN]",
                constitution="true",
                timeout_seconds="1800",
            )
            self.assertEqual(cfg.id, "notion-sync")
            self.assertEqual(set(_paths(cfg)), {STATE_SUGAR, INBOX_SUGAR})
            self.assertEqual(cfg.secrets, ("NOTION_TOKEN",))
            self.assertIs(cfg.constitution, True)
            self.assertEqual(cfg.timeout_seconds, 1800)


# ==========================================================================
# body — never parsed
# ==========================================================================

class BodyTests(unittest.TestCase):
    def test_rejects_empty_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, body="")

    def test_rejects_whitespace_only_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            with self.assertRaises(rc.RoleConfigError):
                _load(base, body="   \n\n\t\n")

    def test_accepts_single_line_body(self):
        """SIBLING — a one-sentence role is legitimate; only empty is a defect."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertIn("Посмотри почту.", _load(base, body="Посмотри почту.\n").body)

    def test_accepts_body_containing_horizontal_rules(self):
        """SIBLING — `---` inside the prose must not re-open the frontmatter."""
        body = "## Задача\n\nПервый шаг.\n\n---\n\nВторой шаг.\n"
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, body=body)
            self.assertIn("Второй шаг.", cfg.body)
            self.assertIn("---", cfg.body)
            self.assertEqual(cfg.cadence, "daily 07:00")

    def test_accepts_body_containing_a_yaml_looking_block(self):
        """SIBLING — a fenced YAML example in the prose is not frontmatter."""
        body = (
            "## Задача\n\n```yaml\nid: not-the-role-id\ncadence: hourly\n"
            "status: paused\nenv: [X]\n```\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, body=body)
            self.assertEqual(cfg.id, "notion-sync")
            self.assertEqual(cfg.cadence, "daily 07:00")
            self.assertEqual(cfg.status, "active")
            self.assertIn("not-the-role-id", cfg.body)

    def test_body_is_verbatim_and_no_sections_are_extracted(self):
        """The engine NEVER parses the prose body (§0)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, body=DEFAULT_BODY)
            self.assertIn("## Проверка", cfg.body)
            self.assertIn("## Задача", cfg.body)
            self.assertIn("## Завершение", cfg.body)
            for forbidden in ("sections", "check", "task", "finish", "gate_text"):
                self.assertFalse(
                    hasattr(cfg, forbidden),
                    f"RoleConfig must not expose parsed prose ({forbidden!r})",
                )

    def test_accepts_body_in_a_non_latin_script(self):
        """SIBLING — the body is the owner's own language, by design."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertIn("检查看板并同步。", _load(base, body="## 任务\n\n检查看板并同步。\n").body)


# ==========================================================================
# file-level shapes
# ==========================================================================

class FileShapeTests(unittest.TestCase):
    def test_rejects_malformed_yaml_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_text(
                rd / "role.md",
                "---\nid: notion-sync\nname: [unclosed\ncadence: hourly\n---\n\nтело\n",
            )
            with self.assertRaises(rc.RoleConfigError):
                rc.load_role(rd, base)

    def test_rejects_unterminated_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_text(rd / "role.md", "---\nid: notion-sync\nname: X\ncadence: hourly\n")
            with self.assertRaises(rc.RoleConfigError):
                rc.load_role(rd, base)

    def test_accepts_crlf_line_endings(self):
        """SIBLING — a Windows owner's editor writes CRLF; the values must come
        back clean, with no stray carriage return welded onto them."""
        text = role_md_text(writes="[state]", secrets="[NOTION_TOKEN]")
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_bytes(rd / "role.md", text.replace("\n", "\r\n").encode("utf-8"))
            cfg = rc.load_role(rd, base)
            self.assertEqual(cfg.id, "notion-sync")
            self.assertEqual(cfg.cadence, "daily 07:00")
            self.assertEqual(_paths(cfg), (STATE_SUGAR,))
            self.assertEqual(cfg.secrets, ("NOTION_TOKEN",))
            self.assertNotIn("\r", cfg.cadence)
            self.assertNotIn("\r", cfg.id)
            self.assertIn("Задача", cfg.body)

    def test_accepts_utf8_bom(self):
        """SIBLING — Notepad and PowerShell both emit a BOM; a role written
        there must not be dead on arrival."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_bytes(rd / "role.md", b"\xef\xbb\xbf" + role_md_text().encode("utf-8"))
            self.assertEqual(rc.load_role(rd, base).id, "notion-sync")

    def test_rejects_undecodable_role_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = _role_dir(base, "notion-sync")
            write_bytes(rd / "role.md", b"\xff\xfe\x00\x01binary")
            with self.assertRaises(rc.RoleConfigError):
                rc.load_role(rd, base)

    def test_cyrillic_body_survives_a_non_utf8_locale(self):
        """§0 — every read passes `encoding="utf-8"` explicitly. Under the
        locale default on a Western Windows install this body would come back
        as mojibake and the role would rewrite its own memory as garbage."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, body="## Задача\n\nСверь доску «Проекты».\n")
            self.assertIn("Сверь доску «Проекты».", cfg.body)

    def test_role_config_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base)
            self.assertTrue(dataclasses.is_dataclass(cfg))
            with self.assertRaises(dataclasses.FrozenInstanceError):
                cfg.status = "paused"  # type: ignore[misc]

    def test_load_role_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            rd = write_role(base, "notion-sync", writes="[state, inbox]")
            self.assertEqual(rc.load_role(rd, base), rc.load_role(rd, base))


# ==========================================================================
# path properties — the ONLY home for role-relative paths (§0 SoT)
# ==========================================================================

class PathPropertyTests(unittest.TestCase):
    def test_dir_is_the_role_directory_under_the_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base)
            self.assertEqual(cfg.dir, base / "_system" / "roles" / "notion-sync")

    def test_state_dir_log_path_and_role_file_resolve_under_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base)
            self.assertEqual(cfg.state_dir, cfg.dir / "state")
            self.assertEqual(cfg.log_path, cfg.dir / "log.jsonl")
            self.assertEqual(cfg.role_file, cfg.dir / "role.md")
            self.assertTrue(cfg.role_file.exists())

    def test_path_properties_are_pathlib_objects_not_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base)
            for value in (cfg.dir, cfg.state_dir, cfg.log_path, cfg.role_file):
                self.assertIsInstance(value, Path)

    def test_path_properties_hold_for_a_role_id_with_digits(self):
        """SIBLING — the path SoT must not assume a letters-only id."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            cfg = _load(base, "3ds-check-v2", role_id="3ds-check-v2")
            self.assertEqual(cfg.state_dir.parent.name, "3ds-check-v2")


# ==========================================================================
# discover_roles
# ==========================================================================

class DiscoverRolesTests(unittest.TestCase):
    def test_returns_role_dirs_sorted_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            for name in ("zeta", "alpha", "middle"):
                write_role(base, name, role_id=name)
            self.assertEqual([p.name for p in rc.discover_roles(base)],
                             ["alpha", "middle", "zeta"])

    def test_skips_names_starting_with_underscore(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            write_role(base, "notion-sync")
            write_text(roles_dir(base) / "_minder.md", "engine file\n")
            write_text(roles_dir(base) / "_run-frame.md", "frame\n")
            write_text(roles_dir(base) / "_shared" / "role.md", role_md_text())
            self.assertEqual([p.name for p in rc.discover_roles(base)], ["notion-sync"])

    def test_skips_directory_without_role_md_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            write_role(base, "notion-sync")
            (roles_dir(base) / "leftover" / "state").mkdir(parents=True)
            self.assertEqual([p.name for p in rc.discover_roles(base)], ["notion-sync"])

    def test_returns_directories_only_not_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            write_role(base, "notion-sync")
            write_text(roles_dir(base) / "stray.md", "not a role\n")
            found = rc.discover_roles(base)
            self.assertEqual([p.name for p in found], ["notion-sync"])
            self.assertTrue(all(p.is_dir() for p in found))

    def test_never_raises_on_a_malformed_role(self):
        """SIBLING of every load_role rejection — discovery must survive what
        loading refuses, or one bad role blinds the whole tick."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            write_role(base, "healthy", role_id="healthy")
            write_text(_role_dir(base, "broken") / "role.md", "---\nid: [unclosed\n---\n")
            self.assertEqual([p.name for p in rc.discover_roles(base)],
                             ["broken", "healthy"])

    def test_missing_roles_directory_returns_empty_list(self):
        """A base with no roles is normal, not an error (§1)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "zettelkasten"
            base.mkdir(parents=True)
            self.assertEqual(rc.discover_roles(base), [])

    def test_empty_roles_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            self.assertEqual(rc.discover_roles(base), [])

    def test_accepts_role_dir_name_with_digits_and_dashes(self):
        """SIBLING — discovery must not apply a narrower filter than the id rule."""
        with tempfile.TemporaryDirectory() as tmp:
            base = make_base(Path(tmp))
            write_role(base, "3ds-check-v2", role_id="3ds-check-v2")
            self.assertEqual([p.name for p in rc.discover_roles(base)], ["3ds-check-v2"])


class WritesCannotCoverRunGoverningSurfacesTests(unittest.TestCase):
    """§1.1 — a role may not write what decides how roles are run or judged.

    Every other refusal in `_validate_explicit_prefix` is about a path being
    outside the repository or owned by the tick. This one refuses paths that
    are squarely inside the base and would look perfectly ordinary — which is
    exactly why it needs tests in both directions.

    The case that motivated it: `writes: [<base>/_system/scripts]` was accepted,
    so a role rewrote `roles_guard.py` IN ZONE, the tick committed and pushed it
    as that role's own legitimate output, and the next night the role was judged
    by code it had written itself.
    """

    def _refused(self, entry):
        base = Path("/tmp/x/zettelkasten")
        with self.assertRaises(rc.RoleConfigError) as exc:
            rc._validate_explicit_prefix(base / "_system/roles/w/role.md", base, entry)
        return str(exc.exception)

    def _accepted(self, entry):
        base = Path("/tmp/x/zettelkasten")
        return rc._validate_explicit_prefix(base / "_system/roles/w/role.md", base, entry)

    def test_the_engine_scripts_directory_is_refused(self):
        self.assertIn("guard", self._refused("zettelkasten/_system/scripts"))

    def test_a_single_engine_script_is_refused(self):
        """Nesting counts — the rule is about the surface, not the granularity."""
        self._refused("zettelkasten/_system/scripts/roles_guard.py")

    def test_a_parent_that_would_swallow_a_governing_surface_is_refused(self):
        """The other direction: `zettelkasten` covers `_system/scripts`, so
        granting the whole base grants the guard."""
        self._refused("zettelkasten")

    def test_the_skills_and_agent_definition_are_refused(self):
        """`integrations/` holds the tick prompt; `.claude/` holds the subagent
        definition and the tool allowlist. Either one rewrites the rules the
        next run is executed under."""
        self._refused("integrations")
        self._refused(".claude")

    def test_ci_is_refused_but_the_rest_of_dot_github_is_not(self):
        """The surface is `.github/workflows`, which can run anything — not
        the whole of `.github`, which is ordinary repository furniture. A rule
        drawn one level too wide refuses a directory nobody had a reason to
        protect, and that is how a real protection gets weakened later."""
        self._refused(".github/workflows")
        self.assertTrue(self._accepted(".github/ISSUE_TEMPLATE"))

    def test_the_scheduler_helpers_are_refused(self):
        """`stage.sh` decides what gets committed; `finalize-tick.sh` decides
        what gets pushed."""
        self._refused("scripts/scheduler")

    def test_the_ignore_and_attribute_files_are_refused(self):
        """Both edit the guard's input rather than working within it."""
        self._refused(".gitignore")
        self._refused(".gitattributes")

    def test_ordinary_owner_paths_are_still_accepted(self):
        """SIBLING, and the one that matters most — a rule this broad is worth
        nothing if it also refuses the writes roles exist to make."""
        for entry in ("zettelkasten/2_areas",
                      "zettelkasten/1_projects/board.md",
                      "zettelkasten/_sources/inbox/roles",
                      "zettelkasten/_system/roles/w/state",
                      "zettelkasten/5_meta/mocs"):
            with self.subTest(entry=entry):
                self.assertTrue(self._accepted(entry))

    def test_a_name_that_merely_starts_the_same_is_not_a_match(self):
        """SIBLING — `_system/scripts-of-mine` is not `_system/scripts`.
        Segment boundaries, not string prefixes."""
        self.assertTrue(self._accepted("zettelkasten/_system/scripts-of-mine"))


class DuplicateFrontmatterKeysAreRefusedTests(unittest.TestCase):
    """PyYAML's default is silent last-wins, and `status` is why that matters.

    A role written `status: paused` with a stale `status: active` line below it
    parses as ACTIVE. The owner opens the file, reads `paused`, and the role
    runs anyway — reaching outward on a schedule they believe they stopped.
    Unknown keys were already a loud error; a REPEATED known key was the quiet
    one, and quiet is the whole problem.
    """

    def _load(self, tmp, frontmatter):
        base = Path(tmp) / "zettelkasten"
        (base / "_system/roles/w/state").mkdir(parents=True)
        (base / "_system/roles/w/role.md").write_text(
            f"---\n{frontmatter}---\n\n## Задача\nx\n", encoding="utf-8")
        return rc.load_role(base / "_system/roles/w", base)

    def test_a_repeated_status_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rc.RoleConfigError) as exc:
                self._load(tmp, "id: w\nname: W\ncadence: daily\n"
                                "status: paused\nstatus: active\nwrites: [state]\n")
            self.assertIn("duplicate", str(exc.exception).lower())

    def test_a_repeated_writes_is_refused(self):
        """SIBLING — the same hazard on the key that decides the boundary."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rc.RoleConfigError):
                self._load(tmp, "id: w\nname: W\ncadence: daily\n"
                                "writes: [state]\nwrites: [state, inbox]\n")

    def test_an_ordinary_role_still_loads(self):
        """SIBLING, and the one that matters — a stricter loader is worthless
        if it also refuses every well-formed role."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._load(tmp, "id: w\nname: W\ncadence: daily\n"
                                  "status: paused\nwrites: [state]\n")
            self.assertEqual(cfg.status, "paused")

    def test_a_repeated_key_inside_a_nested_value_is_also_refused(self):
        """SIBLING — the loader is installed on the mapping tag, so nesting
        does not slip past it."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(rc.RoleConfigError):
                self._load(tmp, "id: w\nname: W\ncadence: daily\n"
                                "id: other\nwrites: [state]\n")


class WritesCannotCoverTheOwnersKnowledgeTreeTests(unittest.TestCase):
    """§1.1 — a role may not be handed blanket rewrite over work it did not author.

    The case: `writes: [<base>/2_areas]` validated clean and covered 713 of the
    owner's own notes. A role then replaced a long reflection note with one
    line, IN ZONE, and every surface reported a clean run — because the guard
    asks «did it write where it said it would», not «was that its work to
    rewrite». Nothing downstream can catch this; the grant is the whole event.

    The design already answers it: a role drops a note in the inbox and the
    ordinary processing run folds it in. It does not edit records and notes
    directly. A role that maintains ONE living document names that document.
    """

    def _base(self, tmp):
        base = Path(tmp) / "zettelkasten"
        (base / "_system/roles/w").mkdir(parents=True)
        return base

    def _try(self, base, entry):
        return rc._validate_explicit_prefix(
            base / "_system/roles/w/role.md", base, entry)

    def test_a_directory_of_owner_notes_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            area = base / "2_areas"
            area.mkdir(parents=True)
            for i in range(3):
                (area / f"note-{i}.md").write_text("owner's\n", encoding="utf-8")
            with self.assertRaises(rc.RoleConfigError) as exc:
                self._try(base, "zettelkasten/2_areas")
            self.assertIn("3", str(exc.exception), "the owner is told the scale")

    def test_naming_the_one_document_is_accepted(self):
        """SIBLING — the shape the refusal is steering toward must work."""
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            area = base / "2_areas"
            area.mkdir(parents=True)
            for i in range(3):
                (area / f"note-{i}.md").write_text("owner's\n", encoding="utf-8")
            self.assertTrue(self._try(base, "zettelkasten/2_areas/note-1.md"))

    def test_a_directory_that_does_not_exist_yet_is_accepted(self):
        """SIBLING — a role's own new territory holds nothing of the owner's."""
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            self.assertTrue(self._try(base, "zettelkasten/2_areas/role-output"))

    def test_the_roles_inbox_is_accepted_however_full(self):
        """SIBLING — the inbox is the door the design tells a role to use, so a
        refusal that closed it would forbid the intended path."""
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            inbox = base / "_sources/inbox/roles"
            inbox.mkdir(parents=True)
            for i in range(5):
                (inbox / f"{i}.md").write_text("note\n", encoding="utf-8")
            self.assertTrue(self._try(base, "zettelkasten/_sources/inbox/roles"))

    def test_a_roles_own_state_is_accepted_however_full(self):
        """SIBLING — its own memory is exactly what it is supposed to rewrite."""
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            state = base / "_system/roles/w/state"
            state.mkdir(parents=True)
            for i in range(4):
                (state / f"{i}.md").write_text("mine\n", encoding="utf-8")
            self.assertTrue(self._try(base, "zettelkasten/_system/roles/w/state"))

    def test_a_directory_holding_one_document_is_accepted(self):
        """SIBLING — one file in a folder of its own is not a collection, and
        refusing it would push the owner into a worse shape for no gain."""
        with tempfile.TemporaryDirectory() as tmp:
            base = self._base(tmp)
            d = base / "2_areas/board"
            d.mkdir(parents=True)
            (d / "living.md").write_text("the one doc\n", encoding="utf-8")
            self.assertTrue(self._try(base, "zettelkasten/2_areas/board"))


if __name__ == "__main__":
    unittest.main()
