#!/usr/bin/env python3
"""Seed `_system/state/identity-orphan-baseline.txt` from the base as it stands.

Companion to `030-seed-orphan-baseline.sh`; the reasoning lives there. This
half does three things and nothing else: refuse when the engine library is not
on disk yet, refuse when a baseline already exists, and otherwise write one row
per orphan the audit finds.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402

HEADER = """# Known orphan namespaced tags of THIS base — a CLOSED baseline.
#
# An orphan is a tag naming an identity that its registry never declared,
# neither live nor retired. Nothing else examines these: every other check
# reasons outward from a declared identity, so an identifier that was never
# declared has nothing to reason from.
#
# Each row is drift that predates the check. The list only SHRINKS: an orphan is
# resolved by registering the identity, retagging the note, or dropping the tag
# — the owner decides which, through /ztn:resolve-clarifications, and the row
# goes with it. A NEW orphan is not added here; it is residue, which is the
# whole point of writing this check down.
#
# When the last row goes, delete the file: an orphan then simply is residue.
#
# Format:  <tag> | <path relative to the ZTN base>

"""


def main() -> int:
    # The rows carry the owner's own tag names, which are not ASCII on every
    # base; a Windows console would end the run in a traceback without this.
    configure_std_streams()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", required=True)
    args = ap.parse_args()

    repo = Path(args.repo_root)
    base = repo / "zettelkasten"
    scripts = base / "_system" / "scripts"
    if not (scripts / "identity_audit.py").is_file():
        print("030: no engine library on disk yet — nothing seeded, will retry")
        return 1

    sys.path.insert(0, str(scripts))
    try:
        import identity_audit as ia  # noqa: E402
    except Exception as exc:  # pragma: no cover - defensive
        print(f"030: could not load the identity audit ({exc}) — will retry")
        return 1

    target = base / ia.ORPHAN_BASELINE_REL
    if target.exists():
        print("030: a baseline is already present — left untouched")
        return 0

    try:
        result = ia.audit(base)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"030: the scan could not complete ({exc}) — will retry")
        return 1

    rows = sorted({(o["tag"], o["path"]) for o in result.get("orphans", [])})
    if not rows:
        print("030: no orphan tags — no baseline needed")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        HEADER + "".join(f"{tag} | {path}\n" for tag, path in rows),
        encoding="utf-8", newline="\n",
    )
    print(f"030: seeded {len(rows)} orphan row(s) into {ia.ORPHAN_BASELINE_REL}")
    print("     Each is a clarification, not a repair — resolve them at your pace.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
