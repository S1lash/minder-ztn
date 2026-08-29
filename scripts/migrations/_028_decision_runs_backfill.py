"""Add `format_version` to decision-run lines written before it was emitted.

Additive and value-preserving by construction: the field is inserted directly
after `kind`, every other key keeps its value and its position, and a line that
already has one is passed through untouched. Nothing here interprets or
recomputes a run — it states which format the line is in, which is the one
thing the line could not say about itself.

The file is rewritten only when at least one line changed, and only after the
whole file has been parsed successfully. A substrate that cannot be parsed is
left exactly as found and reported: a half-rewritten audit log would be worse
than an unversioned one, and this migration has no way to know why the parse
failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402

from _identity_migration_lib import resolve_base  # noqa: E402

MIGRATION = "028-decision-runs-format-version"
FORMAT_VERSION = "1.0"
SUBSTRATE = ("_system", "state", "check-decision-runs.jsonl")


def backfill(path: Path) -> tuple[int, int]:
    """`(changed, total)`. Raises ValueError if any line fails to parse."""
    raw = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    changed = 0
    for number, line in enumerate(raw, start=1):
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"line {number} is not valid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"line {number} is not an object")
        if "format_version" in entry:
            rows.append(line)
            continue
        rebuilt: dict = {}
        for key, value in entry.items():
            rebuilt[key] = value
            if key == "kind":
                rebuilt["format_version"] = FORMAT_VERSION
        if "format_version" not in rebuilt:
            # No `kind` to anchor after — still version it, at the front.
            rebuilt = {"format_version": FORMAT_VERSION, **entry}
        rows.append(json.dumps(rebuilt, ensure_ascii=False))
        changed += 1
    if changed:
        path.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="")
    return changed, len(raw)


def main() -> int:
    configure_std_streams()
    base = resolve_base(Path(__file__).resolve().parents[2])
    if base is None:
        print(f"{MIGRATION}: no zettelkasten base resolved — nothing to backfill")
        return 0

    path = base.joinpath(*SUBSTRATE)
    if not path.is_file():
        print(f"{MIGRATION}: no decision-run substrate yet — nothing to backfill")
        return 0

    try:
        changed, total = backfill(path)
    except (OSError, ValueError) as exc:
        print(f"{MIGRATION}: left unchanged — {exc}", file=sys.stderr)
        return 1

    print(f"{MIGRATION}: versioned {changed} of {total} decision-run line(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
