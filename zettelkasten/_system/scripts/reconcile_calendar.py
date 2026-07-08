#!/usr/bin/env python3
"""Deterministic calendar-aggregation reconciler for CALENDAR.md.

The calendar aggregate has the same silent-drop failure mode as TASKS.md (a
"regenerate from all notes" step the autonomous tick downgrades at scale), but
it cannot be reconciled the same way: the CALENDAR.md aggregate carries no stable
``^meeting-id`` (unlike ``^task-id`` in TASKS.md), source events frequently lack
an anchor, and dates are often fuzzy (``~середина 2026-07``, ranges). Keying by
(date, text) would be brittle and produce false positives.

So the check is deliberately COARSE: a note that carries at least one FUTURE
``📅`` line in its BODY but whose ``[[note-id]]`` appears in NO forward-facing
CALENDAR section (Recurring / Upcoming / Deadlines — everything except Past) has
had its events dropped wholesale. Per-event precision is not attempted; a note
with several future events, one of them aggregated, is considered covered.

**Coverage is partial and this is BEST-EFFORT, not a deterministic gate** (unlike
the task reconciler, which works because ``^task-id`` anchors are genuinely
authored). Many calendar events are synthesized from meeting PROSE and never
appear as a ``- 📅`` body line — those have no anchor a script can diff, so a drop
of a prose-only event is invisible here. This catches drops of ``📅``-anchored
events only. The durable protection is the nightly lint scan surfacing what it
CAN see; the in-process check is a best-effort assist, not a guarantee.

Read-only: never writes. ``/ztn:process`` Step 4.2 and the weekly lint scan both
call ``--report``; the update migration detects + nudges.

CLI:
  --report [--json] [--today YYYY-MM-DD]

``--today`` overrides the date used to decide "future" (for deterministic tests);
it defaults to the real current date.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOTS = ("_records", "1_projects", "2_areas", "3_resources")

# `- 📅 **{date-string}** …` event line in a note body.
_EVENT_RE = re.compile(r"^\s*- 📅 \*\*(.+?)\*\*")
# First YYYY-MM-DD or YYYY-MM anywhere in the (possibly fuzzy) date string.
_DATE_RE = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")
# A `[[note-id]]` or `[[note-id|alias]]` wikilink (alias stripped on use).
_WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")
_HEADING_RE = re.compile(r"^## (.+?)\s*$")
# Everything before Past is forward-facing.
_PAST_HEADING_RE = re.compile(r"^## Past\b")
# Fenced code block delimiter — `- 📅` inside a ``` example is not a real event.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _first_future_date(date_str: str, today: _dt.date) -> bool:
    """True if the date string's first parseable YYYY-MM(-DD) is >= today.

    Fuzzy / unparseable strings return False — they are never flagged (no
    false positives from `~середина июля` and friends).
    """
    m = _DATE_RE.search(date_str)
    if not m:
        return False
    year, month = int(m.group(1)), int(m.group(2))
    day = int(m.group(3)) if m.group(3) else 1
    try:
        d = _dt.date(year, month, day)
    except ValueError:
        return False
    # A year-month with no day is future only when its month is STRICTLY after
    # the current month — a day-less date in the current month is ambiguous
    # (could be mid-month past), so it is not flagged (conservative, coarse).
    if m.group(3) is None:
        return (year, month) > (today.year, today.month)
    return d >= today


def scan_note_future_event_notes(base: Path, today: _dt.date, roots=DEFAULT_ROOTS) -> set[str]:
    """Note-ids that carry at least one parseable FUTURE ``📅`` event."""
    notes: set[str] = set()
    for root in roots:
        root_dir = base / root
        if not root_dir.is_dir():
            continue
        for path in sorted(root_dir.rglob("*.md")):
            if path.name == "README.md":
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            in_fence = False
            for line in lines:
                if _FENCE_RE.match(line):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                m = _EVENT_RE.match(line)
                if m and _first_future_date(m.group(1), today):
                    notes.add(path.stem)
                    break
    return notes


def calendar_forward_notes(path: Path) -> set[str]:
    """Note-ids wikilinked from any forward-facing CALENDAR section."""
    linked: set[str] = set()
    in_past = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return linked
    for line in lines:
        if _HEADING_RE.match(line):
            in_past = bool(_PAST_HEADING_RE.match(line))
            continue
        if in_past:
            continue
        for m in _WIKILINK_RE.finditer(line):
            linked.add(m.group(1).split("|")[0].strip())  # drop |alias
    return linked


def reconcile(base: Path, calendar_path: Path, today: _dt.date, roots=DEFAULT_ROOTS) -> dict:
    future_notes = scan_note_future_event_notes(base, today, roots)
    forward_notes = calendar_forward_notes(calendar_path)
    orphans = sorted(future_notes - forward_notes)
    return {
        "future_event_note_count": len(future_notes),
        "calendar_forward_note_count": len(forward_notes),
        "orphan_note_count": len(orphans),
        "orphan_notes": orphans,
        "consistent": len(orphans) == 0,
    }


def _default_calendar_path(base: Path) -> Path:
    return base / "_system" / "CALENDAR.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="zettelkasten base dir")
    parser.add_argument("--calendar", type=Path, default=None, help="CALENDAR.md path")
    parser.add_argument("--report", action="store_true", required=True,
                        help="print reconciliation status (read-only)")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument("--today", default=None, help="override today (YYYY-MM-DD, for tests)")
    args = parser.parse_args(argv)

    base = args.base
    calendar_path = args.calendar or _default_calendar_path(base)
    if not calendar_path.is_file():
        print(f"error: CALENDAR.md not found at {calendar_path}", file=sys.stderr)
        return 2

    if args.today:
        today = _dt.date.fromisoformat(args.today)
    else:
        today = _dt.date.today()

    result = reconcile(base, calendar_path, today)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"future-event notes: {result['future_event_note_count']} "
              f"| in calendar: {result['calendar_forward_note_count']} "
              f"| orphan notes: {result['orphan_note_count']} "
              f"| consistent: {result['consistent']}")
        for nid in result["orphan_notes"]:
            print(f"  orphan-note [[{nid}]] — has a future 📅 event, absent from CALENDAR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
