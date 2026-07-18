"""Tests for role_state_hash.py — the per-part state.md sub-zone owner-edit guard.

Verifies the hash covers ONLY one named part's inner sub-zone (the owner portrait
above the zones AND every other part's sub-zone are invisible to it), that an edit
inside the zone changes the hash (tamper detection), that volatile HTML-comment
metadata inside the zone is stripped before hashing, and that a missing/mismatched
sub-zone surfaces rather than being guessed around. Also confirms CRLF and LF
checkouts hash identically, and that two parts' sub-zones are hashed independently.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import role_state_hash as x  # noqa: E402


def _zone(part_id: str, inner: str) -> str:
    begin = (
        f"<!-- AUTO: role-state/{part_id} — maintained by roles_persist.py; "
        "do not hand-edit -->"
    )
    end = f"<!-- END AUTO: role-state/{part_id} -->"
    return f"{begin}\n{inner}\n{end}\n"


def _state_file(role_id: str, portrait: str, zones: str) -> str:
    return (
        f"---\nrole: {role_id}\ntype: role-state\n---\n\n"
        f"# {role_id} — role state\n\n"
        f"{portrait}\n\n"
        f"{zones}"
    )


class RoleStateHashTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, role_id: str, text: str) -> Path:
        p = self.base / "_system" / "roles" / role_id / "state.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    INNER = "### Active\n\n- `lk-0001` Foo · active · — · —"
    INNER_B = "**Purpose:** ship the thing."

    def _two_part_file(self, role_id: str, portrait: str,
                       a: str, b: str) -> str:
        return _state_file(role_id, portrait,
                           _zone("workstreams", a) + _zone("purpose", b))

    # -- inner-zone-only / owner-zone invisibility ------------------------

    def test_owner_portrait_edit_invisible_to_hash(self) -> None:
        p = self._write("r1", _state_file("r1", "Portrait ONE.", _zone("ws", self.INNER)))
        h1 = x.hash_state(p, "ws")
        # Same inner zone, entirely different owner prose above the markers.
        p.write_text(
            _state_file("r1", "Completely different portrait TWO.", _zone("ws", self.INNER)),
            encoding="utf-8",
        )
        h2 = x.hash_state(p, "ws")
        self.assertEqual(h1, h2)

    def test_auto_zone_edit_changes_hash(self) -> None:
        p = self._write("r1", _state_file("r1", "Portrait.", _zone("ws", self.INNER)))
        h1 = x.hash_state(p, "ws")
        edited = self.INNER + "\n- `lk-0002` Bar · new · — · —"
        p.write_text(_state_file("r1", "Portrait.", _zone("ws", edited)), encoding="utf-8")
        h2 = x.hash_state(p, "ws")
        self.assertNotEqual(h1, h2)  # tamper of the auto zone is detected

    def test_volatile_html_comment_stripped(self) -> None:
        # A render-timestamp comment line inside the zone must not affect the hash.
        with_ts = "<!-- rendered 2026-07-11T06:00:00Z -->\n" + self.INNER
        self.assertEqual(x.hash_inner(with_ts), x.hash_inner(self.INNER))

    def test_extract_part_zone_returns_inner(self) -> None:
        text = _state_file("r1", "Portrait.", _zone("ws", self.INNER))
        self.assertEqual(x.extract_part_zone(text, "ws"), self.INNER)
        self.assertIsNone(x.extract_part_zone(text, "other"))

    def test_hash_inner_matches_hash_state(self) -> None:
        p = self._write("r1", _state_file("r1", "Portrait.", _zone("ws", self.INNER)))
        self.assertEqual(x.hash_state(p, "ws"), x.hash_inner(self.INNER))

    # -- multi-zone independence ------------------------------------------

    def test_two_parts_hash_independently(self) -> None:
        p = self._write("r1", self._two_part_file("r1", "P.", self.INNER, self.INNER_B))
        h_ws = x.hash_state(p, "workstreams")
        h_pu = x.hash_state(p, "purpose")
        self.assertNotEqual(h_ws, h_pu)
        # Each part's hash equals the inner-only hash of its own zone.
        self.assertEqual(h_ws, x.hash_inner(self.INNER))
        self.assertEqual(h_pu, x.hash_inner(self.INNER_B))

    def test_edit_of_one_part_leaves_other_hash_stable(self) -> None:
        p = self._write("r1", self._two_part_file("r1", "P.", self.INNER, self.INNER_B))
        h_pu_before = x.hash_state(p, "purpose")
        # Edit only the workstreams zone.
        edited = self.INNER + "\n- `lk-0009` New · new · — · —"
        p.write_text(self._two_part_file("r1", "P.", edited, self.INNER_B), encoding="utf-8")
        self.assertNotEqual(x.hash_state(p, "workstreams"), x.hash_inner(self.INNER))
        self.assertEqual(x.hash_state(p, "purpose"), h_pu_before)  # untouched

    def test_prefix_part_id_not_confused(self) -> None:
        # A part id that is a prefix of another must not match the wrong zone.
        p = self._write(
            "r1", _state_file("r1", "P.", _zone("work", self.INNER) + _zone("workstreams", self.INNER_B))
        )
        self.assertEqual(x.hash_state(p, "work"), x.hash_inner(self.INNER))
        self.assertEqual(x.hash_state(p, "workstreams"), x.hash_inner(self.INNER_B))

    # -- surface, don't guess ---------------------------------------------

    def test_markers_missing_raises(self) -> None:
        p = self.base / "_system" / "roles" / "r1" / "state.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\nrole: r1\n---\n\nNo markers here.\n", encoding="utf-8")
        with self.assertRaises(x.RoleStateHashError):
            x.hash_state(p, "ws")

    def test_part_id_mismatch_raises(self) -> None:
        p = self._write("r1", _state_file("r1", "Portrait.", _zone("ws", self.INNER)))
        # markers are for part `ws`; asking for `other` must not silently succeed.
        with self.assertRaises(x.RoleStateHashError):
            x.hash_state(p, "other")

    # -- cross-platform ---------------------------------------------------

    def test_crlf_and_lf_hash_identically(self) -> None:
        lf = _state_file("r1", "Portrait.", _zone("ws", self.INNER))
        p_lf = self._write("r1", lf)
        h_lf = x.hash_state(p_lf, "ws")

        p_crlf = self.base / "_system" / "roles" / "r2" / "state.md"
        p_crlf.parent.mkdir(parents=True, exist_ok=True)
        crlf = _state_file("r2", "Portrait.", _zone("ws", self.INNER)).replace("\n", "\r\n")
        p_crlf.write_bytes(crlf.encode("utf-8"))
        h_crlf = x.hash_state(p_crlf, "ws")
        self.assertEqual(h_lf, h_crlf)


if __name__ == "__main__":
    unittest.main()
