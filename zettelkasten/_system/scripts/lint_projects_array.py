#!/usr/bin/env python3
"""ZTN lint Scan A.8 — projects-array drift detection.

Enforces the primary-topic-only semantic for `projects:` frontmatter
arrays defined in `5_meta/PROCESSING_PRINCIPLES.md` §9.

Per note (records + PARA knowledge):
  1. Length: 0 OK; 1 OK; 2 requires body boundary marker; 3+ overcount.
  2. Identity resolution — PROJECTS.md is the single source of truth.
     Each `projects:` entry is resolved against the registry's categories:
       - registered project (Active/Completed/Archived) → OK
       - registered trajectory → `non-project` (wrong axis; use tags:)
       - consolidated / superseded ID → `consolidated` (migrate to successor)
       - absent from the registry → consult the hub only to refine:
           * hub_kind=project exists → `orphan-hub` (registry drift:
             a hub vouches for nothing; register it or remove the hub)
           * other-kind hub exists → `non-project-hub` (use tags:/domains:)
           * no hub → `unknown-id` (typo or unregistered)
     A hub is never an existence authority — a registered project needs no
     hub (hubs are created at a topic-volume threshold), and a hub without
     a registry row is drift, not proof of existence.

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


# A registry ID: lowercase slug, hyphen/underscore allowed, digit-or-alpha
# start. Filters header rows ("ID", "Old ID"), separator rows ("---"), and
# placeholders ("_(empty)_", "-").
_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Empty categorised registry — the safe-degradation value and the schema.
REGISTRY_CATEGORIES: tuple[str, ...] = ("project", "trajectory", "consolidated")


def _section_category(header: str) -> str | None:
    """Map a PROJECTS.md `#`-header to a registry category, or None to skip.

    `Template` sections are documentation (skip). `Trajectories` and
    `Consolidated / superseded` are their own categories. Everything else —
    Active / Completed / Archived projects, and the registry title — is a
    project section.
    """
    h = header.lower()
    if "template" in h:
        return None
    if "trajector" in h:
        return "trajectory"
    if "consolidat" in h or "supersed" in h:
        return "consolidated"
    return "project"


def _load_project_registry(root: Path) -> dict[str, set[str]]:
    """Parse PROJECTS.md into categorised ID sets — the single source of
    truth for project identity.

    Returns `{"project": {...}, "trajectory": {...}, "consolidated": {...}}`.
    A.8 resolves every `projects:` entry against these sets; a hub is never
    an existence authority, only consulted to refine the diagnostic for an
    ID absent from the registry entirely.

    Section → category via `_section_category` (Active/Completed/Archived →
    project; Trajectories → trajectory; Consolidated/superseded →
    consolidated; Template → skipped).

    Safe degradation: a missing or unreadable registry yields all-empty
    sets, which falls the resolution back to hub-only — the prior
    behaviour, no regression.
    """
    cats: dict[str, set[str]] = {c: set() for c in REGISTRY_CATEGORIES}
    path = root / "1_projects" / "PROJECTS.md"
    if not path.exists():
        return cats
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return cats

    category = "project"  # rows before the first section header default here
    skip = False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            cat = _section_category(line)
            skip = cat is None
            if cat is not None:
                category = cat
            continue
        if skip:
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        first_cell = stripped.strip("|").split("|", 1)[0].strip()
        # strip wrapping markdown emphasis from placeholder cells, e.g.
        # `_(empty)_` → `(empty)` — still rejected by the slug regex.
        candidate = first_cell.strip("*_`").strip()
        if _PROJECT_ID_RE.match(candidate):
            cats[category].add(candidate)
    return cats


def _has_boundary_marker(fm: dict, body: str) -> bool:
    if fm.get("boundary") is True:
        return True
    body_lower = body.lower()
    return any(m in body_lower for m in BOUNDARY_MARKERS)


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")


def _scan_note(path: Path, root: Path, registry: dict[str, set[str]]) -> None:
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

    # PROJECTS.md is the source of truth; if it is absent or empty we cannot
    # resolve identity at all. Skip resolution rather than flag every entry —
    # a friend mid-setup legitimately has notes before a populated registry.
    # (Length check above is registry-independent and still applies.)
    if not any(registry.values()):
        return

    # Check 2 + 3: per-entry resolution against the registry (single SoT).
    # PROJECTS.md is authoritative for both existence and classification of
    # every projects: entry. A hub never vouches for a project's existence —
    # it is consulted only to refine the diagnostic for an ID that is absent
    # from the registry entirely (orphan hub vs non-project hub vs typo).
    for project_id in projects:
        if project_id in registry["project"]:
            continue  # registered project — valid
        if project_id in registry["trajectory"]:
            _emit({
                **base_event,
                "kind": "projects-array-non-project",
                "severity": "weak",
                "project_id": project_id,
                "reason": (
                    f"projects entry `{project_id}` is a registered "
                    f"trajectory, not a project. The projects: axis is "
                    f"reserved for actual projects (PROCESSING_PRINCIPLES §9)."
                ),
                "to_resolve": (
                    f"Drop `{project_id}` from projects: ; use "
                    f"`tags: [trajectory/{project_id}]` instead."
                ),
            })
            continue
        if project_id in registry["consolidated"]:
            _emit({
                **base_event,
                "kind": "projects-array-consolidated",
                "severity": "weak",
                "project_id": project_id,
                "reason": (
                    f"projects entry `{project_id}` is a consolidated / "
                    f"superseded ID in PROJECTS.md. Records should point at "
                    f"its successor, not the retired ID."
                ),
                "to_resolve": (
                    f"Replace `{project_id}` with its successor project ID "
                    f"(see the Consolidated / superseded table in PROJECTS.md)."
                ),
            })
            continue
        # Absent from the registry — consult the hub only to refine.
        kind, hub_exists = _hub_kind(root, project_id)
        if hub_exists and kind == "project":
            _emit({
                **base_event,
                "kind": "projects-array-orphan-hub",
                "severity": "weak",
                "project_id": project_id,
                "hub_kind": kind,
                "reason": (
                    f"projects entry `{project_id}` has a hub_kind=project "
                    f"hub but no row in PROJECTS.md. PROJECTS.md is the source "
                    f"of truth for project existence; the orphan hub is "
                    f"registry drift."
                ),
                "to_resolve": (
                    f"Register `{project_id}` in PROJECTS.md, or — if it is "
                    f"not a real project — remove hub-{project_id}.md and drop "
                    f"the entry."
                ),
            })
        elif hub_exists:
            _emit({
                **base_event,
                "kind": "projects-array-non-project-hub",
                "severity": "weak",
                "project_id": project_id,
                "hub_kind": kind,
                "reason": (
                    f"projects entry `{project_id}` is unregistered and "
                    f"resolves to a hub_kind={kind} hub. Only registered "
                    f"projects are eligible for the projects: axis "
                    f"(PROCESSING_PRINCIPLES §9)."
                ),
                "to_resolve": (
                    f"Drop `{project_id}` from projects: ; if the signal "
                    f"matters, add `tags: [{kind}/{project_id}]`"
                    f"{' or `domains:`' if kind == 'domain' else ''} instead."
                ),
            })
        else:
            _emit({
                **base_event,
                "kind": "projects-array-unknown-id",
                "severity": "weak",
                "project_id": project_id,
                "reason": (
                    f"projects entry `{project_id}` resolves to neither a row "
                    f"in PROJECTS.md nor a hub file at "
                    f"5_meta/mocs/hub-{project_id}.md."
                ),
                "to_resolve": (
                    f"Verify project ID; fix the slug, register the project "
                    f"in PROJECTS.md, or drop the entry."
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

    registry = _load_project_registry(root)
    for path in _iter_notes(root):
        _scan_note(path, root, registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
