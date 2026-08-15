#!/usr/bin/env python3
"""Migration 024 — both retirement tables reach the declared schema.

The identity contract says a retirement declares three things: what kind of
change it was, which identifier survived it, and when it was decided. Neither
registry on a clone that predates the contract has columns for them.

  `1_projects/PROJECTS.md` — `## Consolidated / superseded`, columns
  `Old ID | Status | Now part of`, with the kind and the date crammed into one
  status string (`consolidated 2026-05-03`).

  `3_resources/people/PEOPLE.md` — `## Removed`, columns `ID | Reason`, with
  the kind, the successor and the date all dissolved in prose.

Both become `Old ID | Kind | Successor | Date | Reason`, and the project
section is renamed `## Retired Identifiers` so the live file and the shipped
template agree on what it is called.

**Parse, never guess.** The decomposition reuses the engine's own registry
parsers — the same code every consumer reads these tables with, including its
guard that a successor is accepted only when it names an identifier the
registry declares live. A row this migration cannot decompose confidently
keeps its original text, verbatim, in the `Reason` cell; its Kind, Successor
and Date cells are left EMPTY rather than filled with a plausible value, and
the row is surfaced as a CLARIFICATION for the owner. A wrong successor is not
a smaller error than a missing one — it silently repoints live references at
the wrong identity.

Nothing is lost either way: the `Reason` cell always carries the row's
original non-identifier text word for word, so the new table says everything
the old one said plus what it could decompose.

`## Stale People` is not touched. A tier drop is archival, not identity
retirement — the person is still exactly who they were.

Usage: python3 _024_retirement_schema.py --repo-root <path>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _identity_migration_lib import (  # noqa: E402
    append_clarifications,
    clarification_anchor,
    configure_std_streams,
    report_no_library,
    import_common,
    is_separator_row,
    read_text,
    render_row,
    resolve_base,
    table_cells,
    write_text,
)

MIGRATION = "migration-024"

TARGET_COLUMNS = ["Old ID", "Kind", "Successor", "Date", "Reason"]
SEPARATOR = ["---", "---", "---", "---", "---"]

# The declared vocabulary a project row's Status cell is written in. Only these
# tokens decompose; anything else is a row the owner has to read, because the
# difference between a merge and a rename is a difference in meaning that no
# amount of string handling recovers.
_STATUS_KIND = {
    "consolidated": "merge",
    "merged": "merge",
    "merge": "merge",
    "renamed": "rename",
    "rename": "rename",
    "void": "void",
}

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
_EMPTY_CELL_RE = re.compile(r"^[_*`\s]*\(?empty\)?[_*`\s]*$", re.IGNORECASE)

# A date, with the parentheses a prose reason usually wraps it in.
_DATE_WITH_PARENS_RE = re.compile(r"\s*\(?\s*\b\d{4}-\d{2}-\d{2}\b\s*\)?")
# The leading status token of a project row, which is that registry's way of
# saying the kind. Same vocabulary as `_STATUS_KIND`, matched at the front.
_STATUS_TOKEN_RE = re.compile(
    r"^\s*(" + "|".join(sorted(_STATUS_KIND, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_CONNECTIVE_CHARS = " \t—–-,;:.·|"


class Row:
    """One retirement row, before and after decomposition."""

    def __init__(self, entity_id: str, cells: list[str], raw: str):
        self.entity_id = entity_id
        self.cells = cells
        self.raw = raw
        self.kind: str | None = None
        self.successor: str | None = None
        self.successor_cell: str = ""
        self.date: str = ""
        self.problem: str | None = None
        # Default: the whole original text. That is right for a row nothing
        # was extracted from — there the original IS the residue. A row that
        # decomposes overwrites this in `_finish` with what is left after the
        # extraction, because restating an extracted part in the cell beside
        # it is the echo this whole contract exists to remove.
        self.reason: str = self.original_tail

    @property
    def original_tail(self) -> str:
        """Everything the row said apart from its identifier, verbatim."""
        tail = [c for c in self.cells[1:] if c and c not in {"-", "—", "–"}]
        return " — ".join(tail)

    def render(self) -> list[str]:
        return [
            self.entity_id,
            self.kind or "",
            self.successor_cell,
            self.date,
            self.reason,
        ]


def _find_date(cells: list[str]) -> str:
    for cell in cells:
        m = _ISO_DATE_RE.search(cell)
        if m:
            return m.group(1)
    return ""


def _successor_cell(row: Row, successor: str) -> str:
    """A wikilink to the surviving node — the original one when the row had it.

    The row's own link is preferred because it names the node the owner chose
    to point at (a hub, say), and the engine's parser reads either form back to
    the same identifier.
    """
    for cell in row.cells[1:]:
        m = _WIKILINK_RE.search(cell)
        if m:
            return m.group(0)
    return f"[[{successor}]]"


# -----------------------------------------------------------------------------
# Reason = residue
# -----------------------------------------------------------------------------
#
# What the original row said that the new columns do NOT. Kind, successor and
# date come out into columns of their own; what is left over is the reason, and
# only that goes in the Reason cell.
#
# Restating an extracted part beside the column that now holds it is the exact
# defect the identity contract exists to remove: four cells saying overlapping
# things, a reader made to check whether they agree, and nothing able to notice
# if someone later edits one and not the other.
#
# When stripping leaves nothing, the cell is EMPTY. A row that never recorded a
# reason honestly has none — the Archive Contract is forward-only and does not
# backfill pre-contract entities — and a synthesised sentence would put a guess
# where a reader expects a statement.


def _kind_marker_end(text: str, kind: str, common) -> int:
    """Index just past the phrase that announced the kind, or 0.

    The prose patterns come from `_common`, which owns how a retirement reason
    is worded — locating the marker here and detecting it there must never be
    two opinions. Only the FIRST match is consumed: in «Unknown — author
    couldn't identify», the second half is the reason, not a second marker.

    A `_common` that no longer exposes a pattern degrades to «marker not
    stripped», which leaves a slightly wordier reason — never a wrong one.
    """
    attr = {
        "merge": "_PROSE_MERGE_RE",
        "rename": "_PROSE_RENAME_RE",
        "void": "_PROSE_VOID_RE",
    }.get(kind)
    pattern = getattr(common, attr, None) if attr else None
    if pattern is not None:
        m = pattern.search(text)
        if m:
            return m.end()
    m = _STATUS_TOKEN_RE.match(text)
    return m.end() if m else 0


def _drop_successor_mention(text: str, successor: str) -> str:
    """Remove the one mention of the successor the parser read it from.

    The wikilink first, because that is what a project row carries; the bare
    token otherwise, which is what a prose reason carries. Only the first
    mention goes: `ai-twin`'s reason names `minder` a second time, inside
    «project ID `minder`», and that mention is the reason — the successor cell
    links the hub while the project identifier is the thing being clarified.
    """
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(0).strip("[]").split("|")[0].split("#")[0].strip()
        if target.startswith("hub-"):
            target = target[len("hub-"):]
        if target == successor:
            return text[:m.start()] + text[m.end():]
    m = re.search(r"(?<![\w-])" + re.escape(successor) + r"(?![\w-])", text)
    if m:
        return text[:m.start()] + text[m.end():]
    return text


def _unwrap_parens(text: str) -> str:
    """`(same person)` → `same person`, only when the parens wrap the whole."""
    if not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(text) - 1:
                return text  # the opener closes early — not a wrapper
    return text[1:-1].strip() if depth == 0 else text


def _residue(row: Row, kind: str, successor: str | None, common) -> str:
    text = row.original_tail
    text = text[_kind_marker_end(text, kind, common):]
    if successor:
        text = _drop_successor_mention(text, successor)
    text = _DATE_WITH_PARENS_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(_CONNECTIVE_CHARS).strip()
    text = _unwrap_parens(text)
    return text.strip(_CONNECTIVE_CHARS).strip()


def _finish(
    row: Row, kind: str | None, successor: str | None, live: set[str], common,
) -> None:
    """Apply the contract's successor rule, or mark the row unparseable."""
    if kind is None or kind == "unknown":
        row.problem = "the row does not say what kind of change this was"
        return
    if kind == "void":
        if successor:
            row.problem = (
                "the row reads as a void retirement but also names a "
                "successor, and a void identity never had one"
            )
            return
        row.kind = "void"
        row.date = _find_date(row.cells)
        row.reason = _residue(row, "void", None, common)
        return
    if not successor:
        row.problem = f"a {kind} requires a successor and the row names none"
        return
    if successor not in live:
        row.problem = (
            f"the successor `{successor}` is not an identifier this registry "
            f"declares live"
        )
        return
    row.kind = kind
    row.successor = successor
    row.successor_cell = _successor_cell(row, successor)
    row.date = _find_date(row.cells)
    row.reason = _residue(row, kind, successor, common)


# -----------------------------------------------------------------------------
# Table surgery
# -----------------------------------------------------------------------------

def _section_bounds(lines: list[str], match) -> tuple[int, int] | None:
    """`(heading_index, end_index)` of the first section whose heading matches."""
    start = None
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            continue
        if start is None:
            if match(line):
                start = i
            continue
        return start, i
    return (start, len(lines)) if start is not None else None


def _already_migrated(headers: list[str]) -> bool:
    lowered = {h.strip().lower() for h in headers}
    return "kind" in lowered and "date" in lowered and "successor" in lowered


def plan_section(
    path: Path,
    match_heading,
    new_heading: str | None,
    decompose,
) -> dict:
    """Work out one registry's new retirement table, WITHOUT writing it.

    Planning and applying are separate on purpose. The rows this migration
    cannot decompose become questions in the owner's queue, and if the table
    were rewritten first, a failure before the queue was written would leave a
    migrated table with no record that anything needed asking — and the next
    run would see `already-migrated` and never ask. So the caller queues first
    and applies second.

    Returns `status`, the parsed / unparsed rows, and on a rewrite the exact
    text to write.
    """
    if not path.is_file():
        return {"status": "no-registry"}
    text = read_text(path)
    lines = text.split("\n")
    bounds = _section_bounds(lines, match_heading)
    if bounds is None:
        return {"status": "no-section"}
    start, end = bounds

    table_start = None
    table_end = None
    headers: list[str] | None = None
    for i in range(start + 1, end):
        cells = table_cells(lines[i])
        if cells is None:
            if table_start is not None:
                break
            continue
        if table_start is None:
            table_start = i
            headers = cells
        table_end = i
    if table_start is None or headers is None or table_end is None:
        return {"status": "no-table"}

    if _already_migrated(headers):
        return {"status": "already-migrated"}

    rows: list[Row] = []
    passthrough: list[str] = []
    for i in range(table_start + 1, table_end + 1):
        cells = table_cells(lines[i])
        if cells is None or is_separator_row(cells):
            continue
        entity_id = cells[0].strip("*_` ").strip()
        if not entity_id or _EMPTY_CELL_RE.match(cells[0]):
            passthrough.append(cells[0])
            continue
        rows.append(Row(entity_id, cells, lines[i]))

    for row in rows:
        decompose(row)

    rendered = [render_row(TARGET_COLUMNS), render_row(SEPARATOR)]
    rendered.extend(render_row(row.render()) for row in rows)
    for cell in passthrough:
        rendered.append(render_row([cell, "", "", "", ""]))

    if new_heading is not None:
        lines[start] = new_heading
    lines[table_start:table_end + 1] = rendered

    return {
        "status": "rewritten",
        "path": path,
        "text": "\n".join(lines),
        "parsed": [r for r in rows if r.problem is None],
        "unparsed": [r for r in rows if r.problem is not None],
    }


def apply_section(result: dict) -> None:
    if result["status"] == "rewritten":
        write_text(result["path"], result["text"])


# -----------------------------------------------------------------------------
# Per-registry decomposition
# -----------------------------------------------------------------------------

def project_decomposer(common, base: Path):
    registry = common.parse_project_registry(base)
    live = {
        e.entity_id for e in registry.values()
        if e.category in ("project", "trajectory")
    }

    def decompose(row: Row) -> None:
        entry = registry.get(row.entity_id)
        status = (row.cells[1] if len(row.cells) > 1 else "").strip().lower()
        token = status.split()[0].strip(":,") if status else ""
        kind = entry.kind if entry and entry.kind else _STATUS_KIND.get(token)
        successor = entry.successor if entry else None
        _finish(row, kind, successor, live, common)

    return decompose


def people_decomposer(common, base: Path):
    registry = common.parse_people_registry(base)
    live = {e.entity_id for e in registry.values() if e.category == "person"}

    def decompose(row: Row) -> None:
        entry = registry.get(row.entity_id)
        # The people parser already reads the kind and the successor out of the
        # reason prose, and already refuses a successor that is not a live
        # registered identifier. Reusing it is what makes this migration agree
        # with every other consumer of the same table.
        kind = entry.kind if entry else None
        successor = entry.successor if entry else None
        _finish(row, kind, successor, live, common)

    return decompose


# -----------------------------------------------------------------------------
# Reporting
# -----------------------------------------------------------------------------

CLARIFICATION_BLOCK = """\
### {today} — retirement row could not be decomposed: `{entity_id}`

**Type:** identity-retirement-unparsed
**Subject:** {entity_id}
**Registry:** {registry}
**Source:** engine migration 024 (retirement schema)
**Action taken:** the row was moved to the new `Old ID | Kind | Successor | \
Date | Reason` schema with its original text preserved word for word in \
`Reason`. `Kind`, `Successor` and `Date` were left EMPTY — nothing was guessed.
**Original row:** `{raw}`
**Uncertainty:** {problem}.
**To resolve:** Run `/ztn:resolve-clarifications` and answer with the kind — \
`merge` (it became part of another identity), `rename` (same identity, new \
identifier) or `void` (it never existed) — plus the surviving identifier for a \
merge or a rename. The skill fills the row through `entity-retire`, which also \
migrates every live surface still naming `{entity_id}`.
"""


def report(label: str, result: dict) -> None:
    status = result["status"]
    if status != "rewritten":
        print(f"024: {label} — {status.replace('-', ' ')}")
        return
    parsed = result["parsed"]
    unparsed = result["unparsed"]
    print(
        f"024: {label} — {len(parsed)} row(s) decomposed, "
        f"{len(unparsed)} surfaced"
    )
    for row in parsed:
        successor = row.successor or "—"
        date = row.date or "no date in the row"
        print(f"024:   parsed  `{row.entity_id}` → {row.kind} / {successor} / {date}")
    for row in unparsed:
        print(f"024:   surfaced `{row.entity_id}` — {row.problem}")


def main(argv: list[str] | None = None) -> int:
    # Owner text is not ASCII; std streams must not use the platform default.
    configure_std_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args(argv)

    base = resolve_base(args.repo_root)
    if base is None:
        print("024: no zettelkasten base on this clone — nothing to do")
        return 0

    common = import_common(base)
    if common is None:
        return report_no_library("024", base)
    today = common.today_iso()

    project_result = plan_section(
        base / "1_projects" / "PROJECTS.md",
        lambda line: common.registry_section_category(line) == "consolidated",
        "## Retired Identifiers",
        project_decomposer(common, base),
    )
    report("1_projects/PROJECTS.md", project_result)

    people_result = plan_section(
        base / "3_resources" / "people" / "PEOPLE.md",
        lambda line: (
            common.people_registry_section_category(line) == "consolidated"
        ),
        None,  # the people registry's section keeps its own name
        people_decomposer(common, base),
    )
    report("3_resources/people/PEOPLE.md", people_result)

    items: list[tuple[str, str]] = []
    for registry, result in (
        ("1_projects/PROJECTS.md", project_result),
        ("3_resources/people/PEOPLE.md", people_result),
    ):
        for row in result.get("unparsed", []):
            items.append((
                clarification_anchor(MIGRATION, f"{registry}#{row.entity_id}"),
                CLARIFICATION_BLOCK.format(
                    today=today, entity_id=row.entity_id, registry=registry,
                    raw=row.raw.strip(), problem=row.problem,
                ),
            ))
    if items:
        written, skipped = append_clarifications(
            base, MIGRATION, f"migration 024 — retirement schema ({today})",
            items,
        )
        print(f"024: {written} clarification(s) queued, {skipped} already known")

    # Queue first, tables second — see `plan_section`.
    apply_section(project_result)
    apply_section(people_result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
