#!/usr/bin/env python3
"""Regenerate `_system/views/CONSTITUTION_INDEX.md` from 0_constitution/.

Deterministic, no LLM. Reads all principle notes, writes a registry table.

Usage:
    python3 gen_constitution_index.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _common import (
    ConstitutionError,
    constitution_root,
    die,
    iter_principles,
    now_iso_utc,
    views_dir,
)


HEADER = """# Constitution Index

> Auto-generated from `0_constitution/` by `_system/scripts/gen_constitution_index.py`.
> Do not edit manually — changes will be overwritten on next regeneration.
> Source of truth: the `.md` files under `0_constitution/`.
"""

LEGEND = """## Legend

- **T** = `priority_tier` (1 = non-negotiable, 2 = strong default, 3 = heuristic)
- **C** = `core` (★ = core: true; blank = core: false)
- **S** = `scope` (SH = shared, PE = personal, SN = sensitive)
- **ST** = `status` (A = active, C = candidate, AR = archived, PH = placeholder)
"""


def _scope_abbr(s: str) -> str:
    return {"shared": "SH", "personal": "PE", "sensitive": "SN"}.get(s, s)


def _status_abbr(s: str) -> str:
    return {"active": "A", "candidate": "C", "archived": "AR", "placeholder": "PH"}.get(s, s)


def render_index(principles: list) -> str:
    lines: list[str] = []
    lines.append(HEADER.rstrip())
    lines.append("")
    lines.append(f"_Generated: {now_iso_utc()}_")
    lines.append("")
    lines.append(LEGEND.rstrip())
    lines.append("")

    if not principles:
        lines.append("## Entries")
        lines.append("")
        lines.append("_No principles landed yet._")
        lines.append("")
        return "\n".join(lines) + "\n"

    # Group by type in fixed order.
    for type_name in ("axiom", "principle", "rule"):
        bucket = [p for p in principles if p.type == type_name]
        if not bucket:
            continue
        lines.append(f"## {type_name.capitalize()}s")
        lines.append("")
        lines.append("| ID | Title | Domain | T | C | S | ST | Last reviewed | Last applied | Path |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in bucket:
            fm = p.frontmatter
            lines.append(
                "| `{id}` | {title} | {domain} | {t} | {c} | {s} | {st} | {rev} | {app} | `{path}` |".format(
                    id=fm["id"],
                    title=str(fm["title"]).replace("|", "\\|"),
                    domain=fm["domain"],
                    t=fm["priority_tier"],
                    c="★" if p.is_core else "",
                    s=_scope_abbr(fm["scope"]),
                    st=_status_abbr(fm["status"]),
                    rev=fm.get("last_reviewed") or "—",
                    app=fm.get("last_applied") or "—",
                    path=p.path.relative_to(constitution_root().parent).as_posix(),
                )
            )
        lines.append("")

    # Stats block — at the bottom, for lint / human glance.
    stats = {
        "total": len(principles),
        "axiom": sum(1 for p in principles if p.type == "axiom"),
        "principle": sum(1 for p in principles if p.type == "principle"),
        "rule": sum(1 for p in principles if p.type == "rule"),
        "active": sum(1 for p in principles if p.status == "active"),
        "candidate": sum(1 for p in principles if p.status == "candidate"),
        "archived": sum(1 for p in principles if p.status == "archived"),
        "placeholder": sum(1 for p in principles if p.status == "placeholder"),
        "core": sum(1 for p in principles if p.is_core and p.status != "placeholder"),
    }
    lines.append("## Stats")
    lines.append("")
    for key in ("total", "axiom", "principle", "rule", "active", "candidate",
                "archived", "placeholder", "core"):
        lines.append(f"- **{key}:** {stats[key]}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print rendered index to stdout without writing")
    parser.add_argument("--output", type=Path, default=None,
                        help="override output path (default: _system/views/CONSTITUTION_INDEX.md)")
    args = parser.parse_args(argv)

    try:
        principles = iter_principles(constitution_root())
    except ConstitutionError as exc:
        die(str(exc))

    content = render_index(principles)

    if args.dry_run:
        sys.stdout.write(content)
        return 0

    out_path = args.output or (views_dir() / "CONSTITUTION_INDEX.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"wrote {out_path} ({len(principles)} principles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
