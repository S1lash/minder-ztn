"""Tests for migrate_legacy_frontmatter.py — legacy field rename + drop +
title backfill from H1 + entity-profile schema preservation."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import migrate_legacy_frontmatter as mig  # noqa: E402


def _write(path: Path, frontmatter: str, body: str = "# Body H1\n\nProse.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return path


def _run(root: Path, mode: str = "fix") -> list[dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        mig.main(["--mode", mode, "--root", str(root)])
    return [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]


class TestLegacyRename:
    def test_participants_to_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\nparticipants:\n- ilya\n- vanya\n",
            )
            events = _run(root, mode="fix")
            assert any(e.get("from") == "participants" and e.get("to") == "people" for e in events)
            text = f.read_text(encoding="utf-8")
            assert "participants:" not in text
            assert "people:" in text

    def test_date_to_created_string_cast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\ndate: 2026-04-28\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "date:" not in text or "created:" in text
            assert "created: '2026-04-28'" in text or "created: 2026-04-28" in text

    def test_project_refs_to_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\nproject_refs:\n- ai-twin\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "project_refs:" not in text
            assert "projects:" in text

    def test_canonical_wins_when_both_present(self):
        """If both legacy and canonical are set, drop legacy, keep canonical."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\nparticipants:\n- old\npeople:\n- new\n",
            )
            events = _run(root, mode="fix")
            assert any(e.get("fix_id") == "legacy-frontmatter-drop-shadowed" for e in events)
            text = f.read_text(encoding="utf-8")
            assert "participants:" not in text
            assert "- new" in text


class TestDropFields:
    def test_hub_refs_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\nhub_refs:\n- hub-foo\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "hub_refs:" not in text


class TestTypeSingularToPlural:
    def test_note_type_converted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\ntype: meeting\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "types:\n- meeting" in text

    def test_project_profile_type_preserved(self):
        """`type: project` on project profile is canonical, NOT migrated."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "1_projects" / "ai-twin.md",
                "id: ai-twin\ntype: project\nstatus: active\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "type: project" in text
            assert "types:" not in text


class TestTitleFromH1:
    def test_title_added_from_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\nlayer: record\n",
                body="# Встреча с Ваней по архитектуре\n\nДетали\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "title: Встреча с Ваней по архитектуре" in text

    def test_existing_title_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\ntitle: Existing\nlayer: record\n",
                body="# Different H1\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "title: Existing" in text
            assert "Different H1" not in text.split("---\n")[1]


class TestIdempotency:
    def test_already_migrated_no_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "_records" / "meetings" / "m.md",
                "id: m1\ntitle: T\nlayer: record\npeople:\n- ilya\ncreated: '2026-04-28'\n",
            )
            events1 = _run(root, mode="fix")
            non_summary = [e for e in events1 if "fix_id" in e]
            assert non_summary == []
            events2 = _run(root, mode="fix")
            assert [e for e in events2 if "fix_id" in e] == []


class TestScope:
    def test_excluded_dirs_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = _write(
                root / "_system" / "x.md",
                "id: x\nparticipants:\n- ilya\n",
            )
            _run(root, mode="fix")
            text = f.read_text(encoding="utf-8")
            assert "participants:" in text  # untouched
