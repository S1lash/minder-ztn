#!/usr/bin/env python3
"""Deterministic hash of ONE named part's `state.md` sub-zone — the per-part
owner-edit guard for the composite Roles engine.

A composite role's `state.md` has an owner prose "portrait" followed by N
contiguous AUTO sub-zones, one per part, in `config.parts[]` order
(BUILD-CONTRACT §6):

    <owner prose "portrait" — owner-owned, ABOVE the first START marker>
    <!-- AUTO: role-state/{part_id} — maintained by roles_persist.py; do not hand-edit -->
    … this part's render …
    <!-- END AUTO: role-state/{part_id} -->
    <!-- AUTO: role-state/{other_part} … -->
    … the next part's render …
    <!-- END AUTO: role-state/{other_part} -->

`roles_persist.py` (the sole writer) stores each part's sub-zone hash in that
part's own state file (`parts/{part_id}.json → state_auto_hash`) after every
render. On the next run it recomputes this hash for the CURRENT sub-zone; if it
differs, that one sub-zone was hand-edited → the engine flags it and preserves
it, never overwriting. Because the guard is scoped to a single named part, an
owner edit to part A's sub-zone does not block the engine from rewriting part B.

Only the content BETWEEN one part's markers is hashed — the owner portrait above
the zones, and every OTHER part's sub-zone, are invisible to this part's hash (by
design). The marker lines themselves are excluded.

Normalization: single-line HTML-comment lines inside the zone (volatile engine
metadata such as a render timestamp) are dropped first, then the remainder is
passed through `content_draft_hash.normalize` (rstrip each line, join with "\\n",
strip) and hashed with sha256. Reusing that normalizer keeps one owner-edit-hash
normalization in the codebase (SoT/DRY).

Usage:
    python3 role_state_hash.py <state.md-path> <part-id>   # prints the hex digest
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from content_draft_hash import normalize

# A full-line HTML comment inside the auto-zone carries engine metadata (e.g. a
# render timestamp) — volatile, so it is stripped before hashing. The rendered
# part body itself is table rows / bullets / prose, never HTML comments, so this
# never removes owner-meaningful content.
_HTML_COMMENT_LINE_RE = re.compile(r"^\s*<!--.*-->\s*$")


class RoleStateHashError(Exception):
    """A part's state.md sub-zone could not be located (markers missing,
    mismatched part id, or malformed). Surfaced, never guessed around."""


def _part_zone_re(part_id: str) -> re.Pattern[str]:
    """Regex capturing the INNER content of the `role-state/{part_id}` sub-zone.

    The BEGIN marker's stable prefix (`<!-- AUTO: role-state/{part_id} `, up to
    and including the space after the part id) is anchored, then the rest of the
    marker line is consumed up to its `-->`; the END marker is matched exactly.
    Requiring a space immediately after the part id makes the token boundary
    exact — `role-state/work ` never matches a `role-state/workstreams` marker.
    Group 1 is the inner content, exclusive of both marker lines.
    """
    begin = re.escape(f"<!-- AUTO: role-state/{part_id} ")
    end = re.escape(f"<!-- END AUTO: role-state/{part_id} -->")
    return re.compile(begin + r"[^\n]*?-->\n(.*?)\n?" + end, re.DOTALL)


def extract_part_zone(text: str, part_id: str) -> str | None:
    """Return the inner sub-zone content for `part_id`, or None if not present."""
    m = _part_zone_re(part_id).search(text)
    return m.group(1) if m else None


def strip_volatile(inner: str) -> str:
    """Drop single-line HTML-comment lines (volatile engine metadata) from the
    inner zone before hashing."""
    return "\n".join(
        line for line in inner.splitlines()
        if not _HTML_COMMENT_LINE_RE.match(line)
    )


def hash_inner(inner: str) -> str:
    """sha256 of the normalized, volatile-stripped inner sub-zone."""
    return hashlib.sha256(
        normalize(strip_volatile(inner)).encode("utf-8")
    ).hexdigest()


def hash_part_zone(text: str, part_id: str) -> str:
    """Hash the `role-state/{part_id}` sub-zone found in `text` (in-memory).

    Raises RoleStateHashError when the named sub-zone cannot be located, so the
    writer's owner-edit guard can distinguish "this part's markers are gone" from
    "the zone is present but drifted".
    """
    inner = extract_part_zone(text, part_id)
    if inner is None:
        raise RoleStateHashError(
            f"role-state sub-zone for part {part_id!r} not found "
            "(markers missing, malformed, or part id mismatch)"
        )
    return hash_inner(inner)


def hash_state(path: Path, part_id: str) -> str:
    """Hash the `role-state/{part_id}` sub-zone of a role state.md file.

    `read_text` decodes in text mode (universal newlines → CRLF checkouts hash
    identically to LF). Raises RoleStateHashError if the sub-zone cannot be
    located.
    """
    return hash_part_zone(path.read_text(encoding="utf-8"), part_id)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        sys.stderr.write("usage: role_state_hash.py <state.md-path> <part-id>\n")
        return 2
    path = Path(args[0])
    part_id = args[1]
    try:
        digest = hash_state(path, part_id)
    except FileNotFoundError:
        sys.stderr.write(f"role_state_hash: file not found: {path}\n")
        return 1
    except RoleStateHashError as exc:
        sys.stderr.write(f"role_state_hash: {exc}\n")
        return 1
    sys.stdout.write(digest + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
