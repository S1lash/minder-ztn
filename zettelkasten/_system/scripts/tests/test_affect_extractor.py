"""Tests for affect_extractor."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import affect_extractor as ax  # noqa: E402


_LEX = """
categories:
  anxious:
    - тревож*
    - anxious
  flow:
    - in flow
    - "deep work"
"""


def _write_lex(tmp: Path) -> Path:
    p = tmp / "affect_lexicon.yaml"
    p.write_text(_LEX, encoding="utf-8")
    return p


def _write_record(tmp: Path, name: str, date: str, body: str) -> None:
    p = tmp / "_records" / "observations" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ndate: '{date}'\nlayer: record\nkind: observation\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_stem_match_russian(tmp_path):
    lex = _write_lex(tmp_path)
    _write_record(tmp_path, "20240101-anxious.md", "2024-01-01", "сегодня было тревожно с утра")
    tags = ax.tag_records([tmp_path / "_records" / "observations"], lex)
    assert tags["2024-01-01"] == {"anxious"}


def test_whole_word_english(tmp_path):
    lex = _write_lex(tmp_path)
    _write_record(tmp_path, "20240102-anxiousnot.md", "2024-01-02", "anxiousness levels growing")
    tags = ax.tag_records([tmp_path / "_records" / "observations"], lex)
    # "anxious" without `*` must NOT match "anxiousness"
    assert "anxious" not in tags.get("2024-01-02", set())


def test_multiword_phrase(tmp_path):
    lex = _write_lex(tmp_path)
    _write_record(tmp_path, "20240103-flow.md", "2024-01-03", "had a bit of deep work today")
    tags = ax.tag_records([tmp_path / "_records" / "observations"], lex)
    assert tags["2024-01-03"] == {"flow"}


def test_case_insensitive(tmp_path):
    lex = _write_lex(tmp_path)
    _write_record(tmp_path, "20240104-up.md", "2024-01-04", "TOTALLY ANXIOUS today")
    tags = ax.tag_records([tmp_path / "_records" / "observations"], lex)
    assert tags["2024-01-04"] == {"anxious"}


def test_lexicon_overlay_extends(tmp_path):
    base_lex = _write_lex(tmp_path)
    local = tmp_path / "affect_lexicon.local.yaml"
    local.write_text("categories:\n  flow:\n    - zone\n", encoding="utf-8")
    _write_record(tmp_path, "20240105-zone.md", "2024-01-05", "in the zone all morning")
    tags = ax.tag_records([tmp_path / "_records" / "observations"], base_lex, local)
    assert tags["2024-01-05"] == {"flow"}


def test_window_filter(tmp_path):
    lex = _write_lex(tmp_path)
    _write_record(tmp_path, "20240101-a.md", "2024-01-01", "anxious")
    _write_record(tmp_path, "20240120-b.md", "2024-01-20", "anxious")
    tags = ax.tag_records(
        [tmp_path / "_records" / "observations"], lex,
        window_start="2024-01-15", window_end="2024-01-31",
    )
    assert "2024-01-01" not in tags
    assert "2024-01-20" in tags


def test_meeting_heavy_day(tmp_path):
    md = tmp_path / "_records" / "meetings"
    md.mkdir(parents=True)
    for i in range(5):
        (md / f"20240110-meeting-{i}.md").write_text(
            f"---\ndate: '2024-01-10'\nlayer: record\nkind: meeting\n---\n\nbody {i}\n",
            encoding="utf-8",
        )
    heavy = ax.detect_meeting_heavy_days(md, threshold=4)
    assert "2024-01-10" in heavy
