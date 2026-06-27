"""Tests for render_content_map.py — CONTENT_MAP.md derived view.

Coverage:
- hub membership from note body [[hub-*]] links
- multi-hub note appears under each hub
- hub-orphan note → Unclustered section
- only content_potential notes included
- ripeness formula (convergence × note_count × avg_potential)
- posts-on-theme from POSTS.md source_notes
- multi-angle cell formatting
- frontmatter counts; determinism
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import render_content_map as rcm  # type: ignore


def _scaffold(root: Path) -> None:
    for sub in ("1_projects", "2_areas", "3_resources", "4_archive",
                "5_meta/mocs", "_system"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _note(root: Path, rel: str, *, potential="high", ctype="insight",
          angle="An angle", hubs=None, nid=None, title=None, domains=None) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    nid = nid or p.stem
    fm = [f"id: {nid}", "layer: knowledge"]
    if title:
        fm.append(f"title: '{title}'")
    if potential:
        fm.append(f"content_potential: {potential}")
    if ctype:
        fm.append(f"content_type: {ctype}")
    if angle is not None:
        if isinstance(angle, list):
            fm.append("content_angle:")
            for a in angle:
                fm.append(f"  - {a}")
        else:
            fm.append(f"content_angle: {angle}")
    if domains:
        fm.append("domains:")
        for d in domains:
            fm.append(f"  - {d}")
    body = "Body.\n\n## Связи\n\n"
    for h in (hubs or []):
        body += f"- [[{h}]] — hub link\n"
    p.write_text("---\n" + "\n".join(fm) + "\n---\n" + body, encoding="utf-8")


def _hub(root: Path, hub_id: str, title="Hub Title", related=None) -> None:
    p = root / "5_meta" / "mocs" / f"{hub_id}.md"
    body = "Body.\n\n## Связи\n\n"
    for r in (related or []):
        body += f"- [[{r}]]\n"
    p.write_text(
        f"---\nid: {hub_id}\nlayer: hub\ntitle: '{title}'\n---\n{body}",
        encoding="utf-8")


def _posts(root: Path, rows: list[str]) -> None:
    table = ("# Published Posts\n\n## Published\n\n"
             "| Date | Title | Platform | Link | Source Notes |\n"
             "|------|-------|----------|------|--------------|\n")
    for r in rows:
        table += r + "\n"
    table += "\n## Content Strategy\n\nnothing\n"
    (root / "_system" / "POSTS.md").write_text(table, encoding="utf-8")


def _render(root: Path) -> str:
    return rcm.render_content_map(root)


def test_hub_membership_from_body_link():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-alpha", title="Alpha")
        _note(root, "1_projects/n1.md", hubs=["hub-alpha"], nid="n1")
        out = _render(root)
        assert "### [[hub-alpha]] — Alpha" in out
        assert "[[n1]]" in out
        # n1 sits under the theme, not unclustered
        theme_part, unclustered = out.split("## Unclustered")
        assert "[[n1]]" in theme_part
        assert "[[n1]]" not in unclustered


def test_multi_hub_note_appears_in_each():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-a"); _hub(root, "hub-b")
        _note(root, "1_projects/n.md", hubs=["hub-a", "hub-b"], nid="n")
        out = _render(root)
        assert out.count("[[n]]") == 2


def test_orphan_note_unclustered():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _note(root, "3_resources/orphan.md", hubs=[], nid="orph", domains=["tech"])
        out = _render(root)
        _, unclustered = out.split("## Unclustered")
        assert "[[orph]]" in unclustered
        assert "domains:[tech]" in unclustered


def test_unclustered_note_carries_ripeness():
    # a standalone (theme_id note:{id}) must be parseable for ripeness like a hub
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _note(root, "3_resources/s.md", potential="high", hubs=[], nid="s")
        out = _render(root)
        _, unclustered = out.split("## Unclustered")
        m = re.search(r"\[\[s\]\].*ripeness ([\d.]+)", unclustered)
        assert m, unclustered
        assert float(m.group(1)) == 2.0  # 1 high note: (1+1)*1*1.0


def test_only_content_potential_included():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _note(root, "1_projects/y.md", potential="high", nid="y")
        _note(root, "1_projects/n.md", potential=None, nid="n")
        out = _render(root)
        assert "[[y]]" in out
        assert "[[n]]" not in out
        assert "content_notes: 1" in out


def test_ripeness_formula():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-x", title="X")
        # 3 notes: 2 high, 1 medium → avg=(1+1+0.5)/3=0.8333, conv=1+2=3,
        # count=3 → 3*3*0.8333 = 7.5
        _note(root, "1_projects/a.md", potential="high", hubs=["hub-x"], nid="a")
        _note(root, "1_projects/b.md", potential="high", hubs=["hub-x"], nid="b")
        _note(root, "1_projects/c.md", potential="medium", hubs=["hub-x"], nid="c")
        out = _render(root)
        m = re.search(r"hub-x\]\] — X · ripeness ([\d.]+)", out)
        assert m, out
        assert abs(float(m.group(1)) - 7.5) < 0.05, m.group(1)


def test_ripeness_never_zero_medium_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-m")
        _note(root, "1_projects/m.md", potential="medium", hubs=["hub-m"], nid="m")
        out = _render(root)
        m = re.search(r"hub-m\]\].*ripeness ([\d.]+)", out)
        assert float(m.group(1)) > 0


def test_posts_on_theme():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-p", title="P")
        _note(root, "1_projects/src.md", hubs=["hub-p"], nid="src")
        _posts(root, ["| 2026-01-01 | T | LinkedIn | [x] | [[src]] |"])
        out = _render(root)
        assert "post(s) published on this theme" in out
        assert re.search(r"hub-p\]\].*1 post", out)


def test_posts_on_theme_multi_hub_counts_both():
    # a note in 2 hubs, sourced by a published post → the post counts for BOTH
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-a", title="A"); _hub(root, "hub-b", title="B")
        _note(root, "1_projects/src.md", hubs=["hub-a", "hub-b"], nid="src")
        _posts(root, ["| 2026-01-01 | T | LinkedIn | [x] | [[src]] |"])
        out = _render(root)
        assert re.search(r"hub-a\]\].*1 post", out)
        assert re.search(r"hub-b\]\].*1 post", out)


def test_post_unmatched_note_no_count():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-p", title="P")
        _note(root, "1_projects/src.md", hubs=["hub-p"], nid="src")
        _posts(root, ["| 2026-01-01 | T | LinkedIn | [x] | [[other-note]] |"])
        out = _render(root)
        assert "post(s) published" not in out


def test_multi_angle_cell():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _note(root, "1_projects/n.md", angle=["First angle", "Second", "Third"],
              hubs=[], nid="n")
        out = _render(root)
        assert '"First angle" (+2)' in out


def test_related_hubs_rendered():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-a", related=["hub-b"]); _hub(root, "hub-b")
        _note(root, "1_projects/n.md", hubs=["hub-a"], nid="n")
        out = _render(root)
        assert "related hubs: [[hub-b]]" in out


def test_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); _scaffold(root)
        _hub(root, "hub-a")
        _note(root, "1_projects/n2.md", hubs=["hub-a"], nid="n2")
        _note(root, "1_projects/n1.md", hubs=["hub-a"], nid="n1")
        a = _render(root)
        b = _render(root)
        # identical modulo the generated timestamp line
        strip = lambda s: re.sub(r"generated: .*", "", s)
        assert strip(a) == strip(b)
