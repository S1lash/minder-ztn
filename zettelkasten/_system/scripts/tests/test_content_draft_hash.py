"""Tests for content_draft_hash.py — the owner-edit guard hash."""

from __future__ import annotations

import content_draft_hash as cdh  # type: ignore


FM = "---\ndraft_for: \"X\"\nstatus: draft\n---\n"


def test_body_extracted_below_frontmatter():
    assert cdh.draft_body(FM + "Hello body.\n") == "Hello body.\n"


def test_frontmatter_change_does_not_change_hash():
    # owner-edit guard hashes the BODY only — frontmatter status flips etc.
    # must not look like a body edit.
    a = cdh.content_hash("---\nstatus: draft\n---\nSame body.\n")
    b = cdh.content_hash("---\nstatus: owner-editing\n---\nSame body.\n")
    assert a == b


def test_trailing_whitespace_normalized():
    a = cdh.content_hash(FM + "Line one.\nLine two.\n")
    b = cdh.content_hash(FM + "Line one.   \nLine two.\n\n\n")
    assert a == b


def test_real_body_edit_changes_hash():
    a = cdh.content_hash(FM + "Original sentence.\n")
    b = cdh.content_hash(FM + "Original sentence. Owner added this.\n")
    assert a != b


def test_deterministic():
    t = FM + "Body with unicode — тест.\n"
    assert cdh.content_hash(t) == cdh.content_hash(t)


def test_no_frontmatter_hashes_whole_text():
    assert cdh.draft_body("Just text.\n") == "Just text.\n"
