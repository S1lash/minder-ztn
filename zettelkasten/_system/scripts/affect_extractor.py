"""Lexicon-based per-day binary affect tag extraction.

Reads `affect_lexicon.yaml` (+ optional `.template.yaml` and `.local.yaml`
overlay), iterates `_records/observations/*.md` + `_records/meetings/*.md`
within a window, returns `dict[date, set[category]]`.

Categories whose entries are `_structural: true` are NOT detected by
this lexicon scan — handled externally by the worker (e.g.
`meeting_heavy_day` = ≥4 meetings on a date).

Match rules (per affect_lexicon spec):
  - case-insensitive
  - patterns ending `*` → stem match (`\\b{stem}\\w*`)
  - patterns without `*` → whole word match (`\\b{word}\\b`)
  - one match per category per day flips the day's binary tag to true
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Iterable

import yaml


def _load_lexicon(*paths: Path) -> dict[str, list[str]]:
    """Layered lexicon load: later paths override / extend earlier ones."""
    out: dict[str, list[str]] = {}
    for p in paths:
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cats = data.get("categories", {}) or {}
        for cat, entries in cats.items():
            if isinstance(entries, dict) and entries.get("_structural"):
                # structural-only category — keep marker so caller knows
                out.setdefault(cat, [])
                continue
            if not isinstance(entries, list):
                continue
            existing = out.setdefault(cat, [])
            for e in entries:
                if isinstance(e, str) and e not in existing:
                    existing.append(e)
    return out


def _compile_patterns(lexicon: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    """Compile regex per category. Skips empty (structural) categories."""
    compiled: dict[str, list[re.Pattern]] = {}
    for cat, entries in lexicon.items():
        if not entries:
            continue
        pats: list[re.Pattern] = []
        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            if entry.endswith("*"):
                stem = re.escape(entry[:-1])
                pat = re.compile(rf"(?i)\b{stem}\w*")
            else:
                # multi-word entry: convert whitespace to \s+
                escaped = re.escape(entry).replace(r"\ ", r"\s+")
                pat = re.compile(rf"(?i)\b{escaped}\b")
            pats.append(pat)
        compiled[cat] = pats
    return compiled


def _date_from_filename(stem: str) -> str | None:
    """Derive YYYY-MM-DD from filename stems used in records.

    Patterns supported (best-effort):
      `2024-01-01-<topic>` → `2024-01-01`
      `20240101-observation-…` → `2024-01-01`
      `YYYYMMDD-…`
    """
    if len(stem) >= 10 and stem[4] == "-" and stem[7] == "-":
        try:
            date_cls.fromisoformat(stem[:10])
            return stem[:10]
        except ValueError:
            pass
    if len(stem) >= 8 and stem[:8].isdigit():
        try:
            d = date_cls(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
            return d.isoformat()
        except ValueError:
            pass
    return None


def _frontmatter_date(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fm = yaml.safe_load(text[4:end]) or {}
    d = fm.get("date") or fm.get("created")
    if isinstance(d, date_cls):
        return d.isoformat()
    if isinstance(d, str):
        return d[:10]
    return None


def tag_records(
    records_dirs: list[Path],
    lexicon_yaml: Path,
    lexicon_local: Path | None = None,
    *,
    lexicon_template: Path | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, set[str]]:
    """Per-day binary affect tags over markdown records in `records_dirs`.

    Optional date window (inclusive) restricts which records to scan.
    """
    paths: list[Path] = []
    if lexicon_template and lexicon_template.exists():
        paths.append(lexicon_template)
    if lexicon_yaml.exists():
        paths.append(lexicon_yaml)
    if lexicon_local and lexicon_local.exists():
        paths.append(lexicon_local)
    lex = _load_lexicon(*paths)
    patterns = _compile_patterns(lex)
    if not patterns:
        return {}

    out: dict[str, set[str]] = {}
    for d in records_dirs:
        if not d.exists():
            continue
        for md in d.rglob("*.md"):
            if md.name.lower() == "readme.md":
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            date = _frontmatter_date(text) or _date_from_filename(md.stem)
            if not date:
                continue
            if window_start and date < window_start:
                continue
            if window_end and date > window_end:
                continue
            day = out.setdefault(date, set())
            # body excludes frontmatter to avoid matching fm fields
            body = text
            if text.startswith("---\n"):
                e = text.find("\n---\n", 4)
                if e > 0:
                    body = text[e + 5:]
            for cat, pats in patterns.items():
                if cat in day:
                    continue
                for p in pats:
                    if p.search(body):
                        day.add(cat)
                        break
    return out


def detect_meeting_heavy_days(
    meetings_dir: Path,
    *,
    threshold: int = 4,
    window_start: str | None = None,
    window_end: str | None = None,
) -> set[str]:
    """Per-day count of meeting-kind records → set of dates with ≥threshold."""
    counts: dict[str, int] = {}
    if not meetings_dir.exists():
        return set()
    for md in meetings_dir.rglob("*.md"):
        if md.name.lower() == "readme.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        date = _frontmatter_date(text) or _date_from_filename(md.stem)
        if not date:
            continue
        if window_start and date < window_start:
            continue
        if window_end and date > window_end:
            continue
        counts[date] = counts.get(date, 0) + 1
    return {d for d, c in counts.items() if c >= threshold}
