#!/usr/bin/env python3
"""Recover an inbox item whose name a slash split into nested folders.

The problem. Producer tools name an export after the recording's title, and a
title can contain `/` — «07-09 Встреча - A/B-тест», «вкладки Top/New». No
filesystem accepts that in a name, so the sync or the unzip turns the one
segment into two directories:

    _sources/inbox/plaud/07-09 Встреча - A/
        B-тест …/
            transcript_with_summary.md

`normalize_portable_name` cannot help here. It maps `/` → `-` on a NAME, and by
the time the engine sees this there is no illegal character left to find: both
segments are perfectly legal names. The information is not lost, though — it is
sitting in the directory structure, and joining the segments back with `-` is
exactly what `normalize_portable_name` would have produced had it seen the
original string.

What counts as a split name. A directory directly under an inbox source that
carries **no item marker of its own** and **contains subdirectories**. That
shape does not otherwise occur in a folder-per-item layout: the markers live in
the item folder.

Scope comes from the registry, never from guesswork. `SOURCES.md` already
declares each source's `Layout` and its `Skip Subdirs`, and both bind here:

- **`Skip Subdirs` is never entered.** A source declares those folders out of
  the processing queue (`garmin/raw/` holds minute-level JSON payloads). A
  repair that reaches past a declared boundary and MOVES owner data is the
  exact failure this engine defends against, so the boundary is honoured
  before anything is inspected.
- **`dir-per-item` / `dir-with-summary`** — the layouts that legitimately have
  item folders. These are where a join can be autonomous.
- **`flat-md`, or a source not in the registry** — an item is a FILE, so the
  layout defines no folders at all. A directory there is surfaced and never
  joined: it may equally be a folder the owner made on purpose, and destroying
  someone's own organisation is not a repair.

When it is repaired autonomously. Only in a folder layout, and only when the
parent holds EXACTLY ONE child that is itself a well-formed item. Then the join
is the single correct reading and the owner has nothing to decide — the
autonomous-resolution exception of `ENGINE_DOCTRINE §3.1` (deterministic,
conservative-safe, no actionable choice to surface). Anything else — several
children, mixed content, a child that is not an item, a flat-md source — is
reported for a `source-layout-split-name` CLARIFICATION and left untouched.

CLI:
  --report [--json]   list candidates and their verdicts (read-only)
  --apply             perform the unambiguous joins only

Exit status: 0 on success; 2 when the inbox path is unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import normalize_portable_name  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from lib.portable import configure_stdout  # noqa: E402

# Files whose presence marks a directory as one complete item. Mirrors the
# layouts in `_system/registries/SOURCES.md`: `dir-with-summary` writes the
# first, `dir-per-item` the second, and any `.md` covers a hand-assembled item.
ITEM_MARKERS = ("transcript_with_summary.md", "transcript.md")

# The character `normalize_portable_name` substitutes for `/`. Joining with the
# same one keeps a recovered name identical to what the normaliser would have
# produced from the original string.
JOIN = "-"


def _is_item_dir(path: Path) -> bool:
    """True when the directory is one complete inbox item."""
    if not path.is_dir():
        return False
    for marker in ITEM_MARKERS:
        if (path / marker).is_file():
            return True
    return any(child.suffix == ".md" for child in path.iterdir() if child.is_file())


def _children(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if not p.name.startswith("."))


# Layouts whose items are FOLDERS. Only these can carry a split item folder,
# and only these are eligible for an autonomous join.
FOLDER_LAYOUTS = frozenset({"dir-per-item", "dir-with-summary"})


def read_source_registry(sources_md: Path) -> dict[str, dict]:
    """`source-id -> {"layout": str, "skip": set[str]}` from `SOURCES.md`.

    Parsed straight from the registry rather than restated here: `Layout` and
    `Skip Subdirs` are facts the registry owns, and a second copy of them would
    be a second thing to keep true.

    An unreadable or absent registry yields `{}`, which makes every source
    unknown — and an unknown source is surfaced, never joined. Failing towards
    "ask the owner" is the correct direction for a tool that moves files.
    """
    out: dict[str, dict] = {}
    try:
        lines = sources_md.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return out
    headers: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == "ID":
            headers = cells
            continue
        if not headers or set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(headers, cells))
        source_id = row.get("ID", "").strip("`")
        if not source_id or source_id.startswith("_"):
            continue
        skip_raw = row.get("Skip Subdirs", "")
        skip = {
            s.strip().strip("`/")
            for s in skip_raw.replace(",", " ").split()
            if s.strip() and s.strip() != "—"
        }
        out[source_id] = {"layout": row.get("Layout", ""), "skip": skip}
    return out


def find_candidates(inbox_root: Path, registry: dict[str, dict] | None = None) -> list[dict]:
    """Split-name candidates across every source folder under the inbox.

    Each entry carries a `verdict`: `join` when the repair is unambiguous,
    `surface` when it is not, with `reason` naming why.
    """
    out: list[dict] = []
    if not inbox_root.is_dir():
        return out
    if registry is None:
        registry = read_source_registry(
            inbox_root.parent.parent / "_system" / "registries" / "SOURCES.md"
        )
    for source_dir in sorted(p for p in inbox_root.iterdir() if p.is_dir()):
        declared = registry.get(source_dir.name, {})
        layout = declared.get("layout", "")
        skip = declared.get("skip", set())
        for parent in sorted(p for p in source_dir.iterdir() if p.is_dir()):
            if parent.name in skip:
                continue  # declared out of the processing queue — never entered
            if layout not in FOLDER_LAYOUTS:
                # `flat-md`, or a source the registry does not know. Its items
                # are files, so it defines no folders — this one may be the
                # owner's own, and a repair must not reorganise it.
                out.append({
                    "source": source_dir.name,
                    "parent": parent.relative_to(inbox_root).as_posix(),
                    "children": [c.name for c in _children(parent)],
                    "verdict": "surface",
                    "reason": (
                        f"source layout is {layout or 'unknown'}, whose items are files — "
                        "a folder here is undefined by the layout and is never rejoined"
                    ),
                })
                continue
            if _is_item_dir(parent):
                continue
            children = _children(parent)
            subdirs = [c for c in children if c.is_dir()]
            if not subdirs:
                continue  # an empty folder is not a split name

            entry = {
                "source": source_dir.name,
                "parent": parent.relative_to(inbox_root).as_posix(),
                "children": [c.name for c in children],
            }

            if len(children) != 1:
                entry["verdict"] = "surface"
                entry["reason"] = (
                    f"{len(children)} children — a split name leaves exactly one, "
                    "so this is a real folder or a partial move"
                )
                out.append(entry)
                continue

            child = children[0]
            if not _is_item_dir(child):
                entry["verdict"] = "surface"
                entry["reason"] = (
                    f"the single child {child.name!r} is not a complete item "
                    f"(no {' / '.join(ITEM_MARKERS)} and no .md)"
                )
                out.append(entry)
                continue

            joined = normalize_portable_name(f"{parent.name}{JOIN}{child.name}")
            if not joined:
                entry["verdict"] = "surface"
                entry["reason"] = "the joined name normalises to nothing"
                out.append(entry)
                continue

            target = source_dir / joined
            if target.exists():
                entry["verdict"] = "surface"
                entry["reason"] = f"target {joined!r} already exists — never guess a suffix"
                out.append(entry)
                continue

            entry["verdict"] = "join"
            entry["target"] = target.relative_to(inbox_root).as_posix()
            entry["child"] = child.name
            out.append(entry)
    return out


def apply_joins(inbox_root: Path, candidates: list[dict]) -> list[dict]:
    """Perform the `join` verdicts. Returns what was actually moved.

    Move-then-remove, never copy: the item keeps its identity, and the emptied
    parent leaves nothing behind for the next run to re-detect.
    """
    done: list[dict] = []
    for entry in candidates:
        if entry.get("verdict") != "join":
            continue
        parent = inbox_root / entry["parent"]
        child = parent / entry["child"]
        target = inbox_root / entry["target"]
        if not child.is_dir() or target.exists():
            continue  # re-validated at apply time; drift means skip, never force
        child.rename(target)
        try:
            parent.rmdir()
        except OSError:
            # Something appeared in the parent between detection and now. The
            # item is already safe at its new name; leave the remainder for the
            # next run to look at rather than removing something unseen.
            pass
        done.append({"from": entry["parent"], "to": entry["target"]})
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recover slash-split inbox item names")
    ap.add_argument("--inbox", type=Path, required=True, help="_sources/inbox directory")
    ap.add_argument("--sources", type=Path, default=None,
                    help="SOURCES.md path (defaults to the base's registry)")
    ap.add_argument("--report", action="store_true", help="list candidates (read-only)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--apply", action="store_true", help="perform unambiguous joins")
    args = ap.parse_args(argv)

    # Every line below can carry an owner filename, which is why this script
    # exists at all — printing one through the platform default raises on
    # Windows and turns a repair into a crash.
    configure_stdout()

    if not args.inbox.is_dir():
        print(f"error: inbox not found at {args.inbox}", file=sys.stderr)
        return 2

    registry = read_source_registry(
        args.sources
        or (args.inbox.parent.parent / "_system" / "registries" / "SOURCES.md")
    )
    candidates = find_candidates(args.inbox, registry)
    applied = apply_joins(args.inbox, candidates) if args.apply else []

    if args.json:
        print(json.dumps({"candidates": candidates, "applied": applied}, ensure_ascii=False))
        return 0

    if not candidates:
        print("split-names: none found")
        return 0
    for entry in candidates:
        if entry["verdict"] == "join":
            verb = "joined" if args.apply else "would join"
            print(f"  {verb}: {entry['parent']}/{entry['child']} → {entry['target']}")
        else:
            print(f"  surface: {entry['parent']} — {entry['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
