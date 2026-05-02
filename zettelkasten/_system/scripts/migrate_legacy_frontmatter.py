"""Migrate legacy frontmatter field names to current schema.

One-time owner-data migration for notes produced by older /ztn:process
versions that used the pre-canonical field names. Invoked manually by
the owner; not run automatically by any skill.

Migrations applied:
- `participants:` → `people:`
- `date:` → `created:` (string-cast)
- `project_refs:` → `projects:`
- `hub_refs:` → drop (hubs derived separately, no fixed frontmatter slot)
- `type:` (singular string) → `types: [<value>]`
- Add `title:` from body H1 header when missing

Idempotent: re-running on already-migrated files yields zero writes.

Scope: `_records/`, `1_projects/`, `2_areas/`, `3_resources/`, `5_meta/mocs/`.
Skipped: `_system/`, `_sources/`, `0_constitution/`, `4_archive/`, `5_meta/templates/`,
`5_meta/CONCEPT.md`, `5_meta/PROCESSING_PRINCIPLES.md`, README files.

Modes:
  --mode scan  — print files needing migration, no writes
  --mode fix   — apply migration, write back

Output: one JSON event per change to stdout (jsonl).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

LEGACY_FIELDS = {
    "participants": "people",
    "date": "created",
    "project_refs": "projects",
}
DROP_FIELDS = {"hub_refs"}

SCOPE_DIRS = ["_records", "1_projects", "2_areas", "3_resources", "5_meta/mocs"]
EXCLUDE_DIRS = {"_system", "_sources", "0_constitution", "4_archive"}
EXCLUDE_FILES = {"CONCEPT.md", "PROCESSING_PRINCIPLES.md"}


def _walk(base: Path):
    for sub in SCOPE_DIRS:
        root = base / sub
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            if p.name.upper() == "README.MD" or p.name in EXCLUDE_FILES:
                continue
            if any(part in EXCLUDE_DIRS for part in p.relative_to(base).parts):
                continue
            yield p


def _parse(text: str):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    return text[4:end], text[end + 5:]


def _extract_h1_title(body: str) -> str | None:
    m = re.search(r"^#\s+(.+?)$", body, re.MULTILINE)
    return m.group(1).strip() if m else None


def migrate_one(path: Path, mode: str) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    parsed = _parse(text)
    if parsed is None:
        return []
    fm_text, body = parsed
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return []
    if not isinstance(fm, dict):
        return []

    events: list[dict] = []
    new_fm = dict(fm)

    # rename legacy → canonical (only if canonical not already set)
    for old, new in LEGACY_FIELDS.items():
        if old in new_fm and new not in new_fm:
            value = new_fm.pop(old)
            if old == "date":
                value = str(value)
            new_fm[new] = value
            events.append({
                "fix_id": "legacy-frontmatter-rename",
                "from": old, "to": new,
                "path": path.as_posix(),
            })
        elif old in new_fm:
            # both present — drop legacy (canonical wins)
            new_fm.pop(old)
            events.append({
                "fix_id": "legacy-frontmatter-drop-shadowed",
                "field": old,
                "path": path.as_posix(),
            })

    # drop fields with no current home
    for f in DROP_FIELDS:
        if f in new_fm:
            new_fm.pop(f)
            events.append({
                "fix_id": "legacy-frontmatter-drop",
                "field": f,
                "path": path.as_posix(),
            })

    # singular `type:` (string) → `types: [value]` if no `types:` present.
    # Skip canonical singular-type values reserved for entity profiles
    # (project / person / hub) — those are NOT note types and stay singular.
    PROFILE_TYPES = {"project", "person", "hub"}
    if "type" in new_fm and isinstance(new_fm["type"], str):
        type_value = new_fm["type"]
        if type_value in PROFILE_TYPES:
            pass  # canonical entity-profile schema; leave as-is
        else:
            if "types" not in new_fm:
                new_fm["types"] = [type_value]
                events.append({
                    "fix_id": "legacy-frontmatter-type-singular-to-plural",
                    "value": type_value,
                    "path": path.as_posix(),
                })
            new_fm.pop("type")

    # add title from H1 if missing
    if not new_fm.get("title"):
        title = _extract_h1_title(body)
        if title:
            # insert title after id (or at top if no id)
            ordered = {}
            inserted = False
            for k, v in new_fm.items():
                ordered[k] = v
                if k == "id" and not inserted:
                    ordered["title"] = title
                    inserted = True
            if not inserted:
                ordered = {"title": title, **new_fm}
            new_fm = ordered
            events.append({
                "fix_id": "legacy-frontmatter-title-from-h1",
                "title": title,
                "path": path.as_posix(),
            })

    if events and mode == "fix":
        new_text = yaml.safe_dump(
            new_fm, sort_keys=False, allow_unicode=True,
            default_flow_style=False, width=10000,
        ).rstrip("\n")
        path.write_text(f"---\n{new_text}\n---\n{body}", encoding="utf-8")

    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scan", "fix"], default="scan")
    parser.add_argument("--root", type=Path, default=None,
                        help="ZTN base (defaults to env ZTN_BASE or detected from script location)")
    args = parser.parse_args(argv)

    base = args.root
    if base is None:
        # script lives at <base>/_system/scripts/migrate_legacy_frontmatter.py
        base = Path(__file__).resolve().parent.parent.parent

    total_events = 0
    files_touched = set()
    for p in _walk(base):
        events = migrate_one(p, args.mode)
        for ev in events:
            print(json.dumps(ev, ensure_ascii=False))
            total_events += 1
            files_touched.add(ev["path"])

    print(json.dumps({
        "summary": {
            "mode": args.mode,
            "events": total_events,
            "files_touched": len(files_touched),
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
