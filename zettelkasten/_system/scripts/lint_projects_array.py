#!/usr/bin/env python3
"""ZTN lint Scan A.8 — projects-array drift detection.

Enforces the primary-topic-only semantic for `projects:` frontmatter
arrays defined in `5_meta/PROCESSING_PRINCIPLES.md` §9.

Three checks per note (records + PARA knowledge):
  1. Length: 0 OK; 1 OK; 2 requires body boundary marker; 3+ overcount
  2. Hub-kind: each project must point to a hub with `hub_kind: project`
     (or absent — backward-compat default `project`); `trajectory` /
     `domain` are flagged
  3. Existence: project ID must resolve to a hub file under
     `5_meta/mocs/hub-{slug}.md`

Output: JSONL on stdout, one event per violation; exit 0 always.

Each event is suitable to materialise as a CLARIFICATION block per the
A.8 spec in the lint SKILL. The actual write into CLARIFICATIONS.md is
done by the lint orchestrator (it batches events from all scans).

Usage:
    python3 lint_projects_array.py [--root <path>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _common import read_frontmatter, repo_root


# Folders in scope — same as Scan A.7 trio backfill.
SCOPE_INCLUDE: tuple[str, ...] = (
    "_records/",
    "1_projects/",
    "2_areas/",
    "3_resources/",
    "4_archive/",
    # NOTE: hubs themselves are out of scope — they may legitimately
    # carry projects: as the hub's own primary; lint scans hub-frontmatter
    # only as a *target* for the kind check, not as a *subject*.
)

# Body-text markers accepted as boundary-case annotation when
# projects.length == 2.
BOUNDARY_MARKERS: tuple[str, ...] = (
    "boundary case",
    "boundary:",
    "cross-project",
    "joint review",
    "boundary record",
)


def _hub_path(root: Path, project_id: str) -> Path:
    return root / "5_meta" / "mocs" / f"hub-{project_id}.md"


def _hub_kind(root: Path, project_id: str) -> tuple[str | None, bool]:
    """Return (hub_kind, hub_exists). hub_kind defaults to 'project' if
    the field is absent on an existing hub (backward compat)."""
    path = _hub_path(root, project_id)
    if not path.exists():
        return None, False
    fm_body = read_frontmatter(path)
    if fm_body is None:
        return None, True  # malformed frontmatter — surface as unknown
    fm, _ = fm_body
    kind = fm.get("hub_kind")
    if kind is None:
        return "project", True
    return str(kind).strip().lower(), True


def _has_boundary_marker(fm: dict, body: str) -> bool:
    if fm.get("boundary") is True:
        return True
    body_lower = body.lower()
    return any(m in body_lower for m in BOUNDARY_MARKERS)


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")


def _scan_note(path: Path, root: Path) -> None:
    fm_body = read_frontmatter(path)
    if fm_body is None:
        return
    fm, body = fm_body

    projects = fm.get("projects") or []
    if not isinstance(projects, list):
        # invalid type — out of A.8 scope (handled by A.2 schema scan)
        return
    # filter empty/None entries
    projects = [str(p).strip() for p in projects if p]

    note_id = fm.get("id") or path.stem
    rel_path = str(path.relative_to(root))
    base_event = {
        "scan": "A.8",
        "note_id": note_id,
        "path": rel_path,
        "projects": projects,
    }

    n = len(projects)

    # Check 1: length
    if n == 2 and not _has_boundary_marker(fm, body):
        _emit({
            **base_event,
            "kind": "projects-array-2-without-boundary-marker",
            "severity": "weak",
            "reason": (
                "projects: has 2 entries but body lacks boundary annotation "
                "(boundary case / cross-project / joint review) and no "
                "`boundary: true` frontmatter field. Either pick the primary "
                "or annotate the boundary case explicitly."
            ),
            "to_resolve": (
                "Pick primary topic (drop one); OR add 'boundary case' "
                "annotation in body OR `boundary: true` in frontmatter."
            ),
        })
    elif n >= 3:
        _emit({
            **base_event,
            "kind": "projects-array-overcount",
            "severity": "weak",
            "reason": (
                f"projects: has {n} entries — primary-topic-only semantic "
                "allows max 2 (boundary). 3+ indicates umbrella/loose tagging "
                "drift (PROCESSING_PRINCIPLES §9)."
            ),
            "to_resolve": (
                "Pick the single primary; demote others to "
                "`tags: [project/{slug}]` (umbrella) or `concepts:` (topical)."
            ),
        })

    # Check 2 + 3: per-entry hub-kind / existence
    for project_id in projects:
        kind, exists = _hub_kind(root, project_id)
        if not exists:
            _emit({
                **base_event,
                "kind": "projects-array-unknown-id",
                "severity": "weak",
                "project_id": project_id,
                "reason": (
                    f"projects entry `{project_id}` does not resolve to a "
                    f"hub file at 5_meta/mocs/hub-{project_id}.md."
                ),
                "to_resolve": (
                    f"Verify project ID; either fix the slug, create "
                    f"hub-{project_id}.md, or drop the entry."
                ),
            })
            continue
        if kind in ("trajectory", "domain"):
            _emit({
                **base_event,
                "kind": "projects-array-non-project-hub",
                "severity": "weak",
                "project_id": project_id,
                "hub_kind": kind,
                "reason": (
                    f"projects entry `{project_id}` points to a "
                    f"hub_kind={kind} hub. Only hub_kind=project hubs are "
                    "eligible for the projects: axis (PROCESSING_PRINCIPLES §9)."
                ),
                "to_resolve": (
                    f"Drop `{project_id}` from projects: ; if the signal "
                    f"matters, add `tags: [{kind}/{project_id}]` "
                    f"({'or `domains:`' if kind == 'domain' else ''}) instead."
                ),
            })


def _iter_notes(root: Path):
    for prefix in SCOPE_INCLUDE:
        base = root / prefix
        if not base.exists():
            continue
        yield from base.rglob("*.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=None,
        help="ZTN base path (defaults to repo_root() / 'zettelkasten').",
    )
    args = parser.parse_args(argv)

    root = args.root or repo_root() / "zettelkasten"
    if not root.exists():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        return 1

    for path in _iter_notes(root):
        _scan_note(path, root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
