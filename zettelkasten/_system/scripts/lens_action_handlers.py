"""Mechanical handlers for Action Hint application.

One handler per `ACTION_HINT_TYPES` value. Each handler is split in two
phases:

  - `validate_*(params, base)` — pure check; returns `(ok: bool, reason: str)`.
    Reason is empty string when ok. Validation is the «stale pre-check»:
    cited paths exist, target not already present, no duplicate, etc.
    Surfaced both in resolver Step 1 (before Step 2 curation) and again
    inside `apply_*` to defend against TOCTOU.

  - `apply_*(params, source_lens, base)` — execute when validation
    passes. Returns a `dict` describing the outcome:

      {
        "success": bool,
        "applied": bool,       # was a write performed?
        "reason": str,         # empty on success, populated otherwise
        "targets": list[str],  # paths touched (relative to base)
        "from_lens": str,      # `{lens-id}/{date}` provenance label
      }

    On validation failure inside apply, returns `success=False, applied=
    False` so the resolver can fall back to a clarification («attempted
    auto-apply, validation failed because X — owner review»). Never
    raises on routine validation failures; raises only on truly
    unexpected I/O errors.

Provenance: every additive edit carries an inline
`<!-- from_lens: {source_lens} -->` HTML comment at the inserted line.
New artefacts (hub stub) carry `from_lens:` directly in frontmatter.
The session log under `_system/state/resolve-sessions/` is the
human-readable audit; this module writes only to the target files.
"""

from __future__ import annotations

import re
import textwrap
from datetime import date as _date
from pathlib import Path

from _common import (
    ACTION_HINT_REQUIRED_PARAMS,
    ACTION_HINT_TYPES,
    repo_root,
)


# ---------------------------------------------------------------------------
# Common validation helpers
# ---------------------------------------------------------------------------

def _resolve(base: Path | None, rel: str) -> Path:
    base = base or repo_root()
    return (base / rel).resolve()


def _file_exists(base: Path | None, rel: str) -> bool:
    p = _resolve(base, rel)
    try:
        return p.is_file()
    except OSError:
        return False


def _read_text(base: Path | None, rel: str) -> str | None:
    try:
        return _resolve(base, rel).read_text(encoding="utf-8")
    except OSError:
        return None


_HUB_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


# Marker for the auto-managed wikilink section. Distinct from a manually
# curated `## Связи` so owner edits and auto edits don't collide.
_AUTO_LINK_SECTION_HEADER = "## Связи (auto)"


def _append_auto_link(path: Path, target_stem: str, source_lens: str) -> None:
    """Append `[[{target_stem}]]` to the auto-managed wikilink section.

    Creates the section at end of file if absent. The bullet carries an
    inline `<!-- from_lens: ... -->` comment for traceability without
    polluting frontmatter.
    """
    text = path.read_text(encoding="utf-8")
    bullet = f"- [[{target_stem}]] <!-- from_lens: {source_lens} -->\n"
    idx = text.find(_AUTO_LINK_SECTION_HEADER)
    if idx == -1:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{_AUTO_LINK_SECTION_HEADER}\n\n{bullet}"
        path.write_text(text, encoding="utf-8")
        return
    # Insert at the END of the auto section — before the next `## ` (any
    # non-`## Связи (auto)` heading) or EOF.
    section_body_start = text.find("\n", idx) + 1
    next_heading = re.search(r"\n##\s+(?!Связи \(auto\))", text[section_body_start:])
    insert_at = section_body_start + (next_heading.start() if next_heading else len(text) - section_body_start)
    # Ensure the new bullet sits on its own line.
    prefix = text[:insert_at]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    path.write_text(prefix + bullet + text[insert_at:], encoding="utf-8")


# ---------------------------------------------------------------------------
# wikilink_add
# ---------------------------------------------------------------------------

def validate_wikilink_add(params: dict, base: Path | None = None) -> tuple[bool, str]:
    """Both notes exist; bidirectional wikilink not yet present."""
    note_a = params.get("note_a")
    note_b = params.get("note_b")
    if not isinstance(note_a, str) or not isinstance(note_b, str):
        return False, "params.note_a and params.note_b must be strings"
    if note_a == note_b:
        return False, "note_a and note_b are the same path"
    if not _file_exists(base, note_a):
        return False, f"note_a does not exist: {note_a}"
    if not _file_exists(base, note_b):
        return False, f"note_b does not exist: {note_b}"

    # Bidirectional already present? Detect by basename appearing as a
    # wikilink target inside the other note. Coarse but safe — false
    # positives (an unrelated `[[X]]` inside a quoted block) only mean
    # we drop the hint, never that we mis-apply.
    a_text = _read_text(base, note_a) or ""
    b_text = _read_text(base, note_b) or ""
    a_basename = Path(note_a).stem
    b_basename = Path(note_b).stem
    a_links_b = f"[[{b_basename}" in a_text
    b_links_a = f"[[{a_basename}" in b_text
    if a_links_b and b_links_a:
        return False, "wikilink already bidirectional"
    return True, ""


def apply_wikilink_add(params: dict, source_lens: str, base: Path | None = None) -> dict:
    """Add a bidirectional wikilink between two notes.

    Re-validates inside apply (TOCTOU defence). On success appends
    `[[{other-stem}]]` to a `## Связи (auto)` section in each note —
    creating the section when absent. Trace inline via
    `<!-- from_lens: ... -->`. Returns `targets` with both relative
    paths.
    """
    ok, reason = validate_wikilink_add(params, base)
    if not ok:
        return {"success": False, "applied": False, "reason": reason, "targets": [], "from_lens": source_lens}
    a_rel = params["note_a"]
    b_rel = params["note_b"]
    a_path = _resolve(base, a_rel)
    b_path = _resolve(base, b_rel)
    _append_auto_link(a_path, b_path.stem, source_lens)
    _append_auto_link(b_path, a_path.stem, source_lens)
    return {
        "success": True,
        "applied": True,
        "reason": "",
        "targets": [a_rel, b_rel],
        "from_lens": source_lens,
    }


# ---------------------------------------------------------------------------
# hub_stub_create
# ---------------------------------------------------------------------------

def validate_hub_stub_create(params: dict, base: Path | None = None) -> tuple[bool, str]:
    """Slug well-formed; hub doesn't exist yet; all cited notes exist."""
    slug = params.get("suggested_slug")
    cited = params.get("cited_notes")
    if not isinstance(slug, str) or not slug:
        return False, "params.suggested_slug must be a non-empty string"
    # Tolerate optional `hub-` prefix — strip for slug-format check.
    bare = slug[4:] if slug.startswith("hub-") else slug
    if not _HUB_SLUG_RE.match(bare):
        return False, f"slug not in lowercase-kebab format: {slug}"
    if not isinstance(cited, list) or not cited:
        return False, "params.cited_notes must be a non-empty list"
    for entry in cited:
        if not isinstance(entry, str):
            return False, "params.cited_notes entries must be strings"
        if not _file_exists(base, entry):
            return False, f"cited note does not exist: {entry}"
    hub_rel = f"5_meta/mocs/hub-{bare}.md"
    if _file_exists(base, hub_rel):
        return False, f"hub already exists: {hub_rel}"
    return True, ""


def apply_hub_stub_create(params: dict, source_lens: str, base: Path | None = None) -> dict:
    """Create a new hub stub and add back-wikilinks from each cited note.

    Hub frontmatter uses safe defaults (`hub_kind: domain`,
    `chronological_map_mode: curated`) so the new file passes
    `lint_hub_integrity`. Body has `## Что объединяет` placeholder and
    `## Заметки` wikilink list. Provenance: `from_lens:` field in
    frontmatter + a trailing HTML comment.
    """
    ok, reason = validate_hub_stub_create(params, base)
    if not ok:
        return {"success": False, "applied": False, "reason": reason, "targets": [], "from_lens": source_lens}
    raw_slug = params["suggested_slug"]
    bare = raw_slug[4:] if raw_slug.startswith("hub-") else raw_slug
    slug = f"hub-{bare}"
    cited = list(params["cited_notes"])
    today = _date.today().isoformat()
    hub_rel = f"5_meta/mocs/{slug}.md"
    hub_path = _resolve(base, hub_rel)
    title_human = bare.replace("-", " ").strip().capitalize()
    fm = textwrap.dedent(f"""\
        ---
        id: {slug}
        title: 'Hub: {title_human}'
        layer: hub
        hub_kind: domain
        chronological_map_mode: curated
        excluded_from_map: []
        excluded_from_map_reasons: []
        domains: []
        created: {today}
        modified: '{today}'
        hub_created: {today}
        from_lens: {source_lens}
        origin: personal
        audience_tags: []
        is_sensitive: false
        ---
        """)
    body_lines: list[str] = [
        f"# Hub: {title_human}",
        "",
        "## Что объединяет",
        "",
        "_(placeholder — owner fills with the substrate this hub names)_",
        "",
        "## Заметки",
        "",
    ]
    body_lines.extend(f"- [[{Path(c).stem}]]" for c in cited)
    body_lines += [
        "",
        f"<!-- auto-created from_lens: {source_lens} on {today} -->",
        "",
    ]
    hub_path.parent.mkdir(parents=True, exist_ok=True)
    hub_path.write_text(fm + "\n".join(body_lines), encoding="utf-8")
    for c in cited:
        _append_auto_link(_resolve(base, c), slug, source_lens)
    return {
        "success": True,
        "applied": True,
        "reason": "",
        "targets": [hub_rel] + cited,
        "from_lens": source_lens,
    }


# ---------------------------------------------------------------------------
# open_thread_add
# ---------------------------------------------------------------------------

def validate_open_thread_add(params: dict, base: Path | None = None) -> tuple[bool, str]:
    """Title not duplicate of a row already in OPEN_THREADS.md (heuristic)."""
    title = params.get("thread_title")
    cited = params.get("cited_records")
    if not isinstance(title, str) or not title.strip():
        return False, "params.thread_title must be a non-empty string"
    if not isinstance(cited, list) or not cited:
        return False, "params.cited_records must be a non-empty list"
    for entry in cited:
        if not isinstance(entry, str):
            return False, "params.cited_records entries must be strings"
        if not _file_exists(base, entry):
            return False, f"cited record does not exist: {entry}"
    open_threads = _read_text(base, "_system/state/OPEN_THREADS.md") or ""
    # Heuristic: case-folded substring match on the trimmed title.
    needle = title.strip().casefold()
    if needle and needle in open_threads.casefold():
        return False, "thread with substantively-similar title already in OPEN_THREADS"
    return True, ""


def apply_open_thread_add(params: dict, source_lens: str, base: Path | None = None) -> dict:
    """Append a row to the `## Active` section of OPEN_THREADS.md.

    If the section is empty (`_(empty)_` placeholder), replaces the
    placeholder. Otherwise appends a bullet at section end. Provenance
    inline.
    """
    ok, reason = validate_open_thread_add(params, base)
    if not ok:
        return {"success": False, "applied": False, "reason": reason, "targets": [], "from_lens": source_lens}
    rel = "_system/state/OPEN_THREADS.md"
    p = _resolve(base, rel)
    text = p.read_text(encoding="utf-8")
    today = _date.today().isoformat()
    title = params["thread_title"].strip()
    cited = ", ".join(f"[[{Path(c).stem}]]" for c in params["cited_records"])
    priority = params.get("priority", "medium")
    bullet = (
        f"- {title} — opened {today}, priority {priority}; "
        f"cited: {cited} <!-- from_lens: {source_lens} -->\n"
    )
    marker = "## Active"
    idx = text.find(marker)
    if idx == -1:
        if text and not text.endswith("\n"):
            text += "\n"
        new_text = text + f"\n## Active\n\n{bullet}"
    else:
        section_start = text.find("\n", idx) + 1
        next_h = text.find("\n## ", section_start)
        section_end = next_h + 1 if next_h != -1 else len(text)
        section_body = text[section_start:section_end]
        if "_(empty)_" in section_body:
            new_section_body = section_body.replace("_(empty)_\n", bullet, 1)
            if new_section_body == section_body:
                # placeholder lacked trailing newline
                new_section_body = section_body.replace("_(empty)_", bullet.rstrip("\n"), 1) + "\n"
            new_text = text[:section_start] + new_section_body + text[section_end:]
        else:
            # Trim trailing blank lines, then append bullet, then restore separator.
            trimmed = section_body.rstrip("\n")
            sep_lost = section_body[len(trimmed):]
            new_section_body = trimmed + ("\n" if trimmed else "") + bullet + sep_lost
            new_text = text[:section_start] + new_section_body + text[section_end:]
    p.write_text(new_text, encoding="utf-8")
    return {
        "success": True,
        "applied": True,
        "reason": "",
        "targets": [rel],
        "from_lens": source_lens,
    }


# ---------------------------------------------------------------------------
# decision_update_section
# ---------------------------------------------------------------------------

_DATE_HEADING_RE = re.compile(r"^##\s+Update\s+(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def validate_decision_update_section(params: dict, base: Path | None = None) -> tuple[bool, str]:
    """Decision note exists; no `## Update {today}` already present."""
    from datetime import date as _date  # local import keeps module load lean

    path = params.get("decision_note_path")
    reason_text = params.get("update_reason")
    if not isinstance(path, str) or not path:
        return False, "params.decision_note_path must be a non-empty string"
    if not isinstance(reason_text, str) or not reason_text.strip():
        return False, "params.update_reason must be a non-empty string"
    if not _file_exists(base, path):
        return False, f"decision note does not exist: {path}"
    text = _read_text(base, path) or ""
    today = _date.today().isoformat()
    for m in _DATE_HEADING_RE.finditer(text):
        if m.group(1) == today:
            return False, f"`## Update {today}` already present"
    return True, ""


def apply_decision_update_section(params: dict, source_lens: str, base: Path | None = None) -> dict:
    """Append a scaffolded `## Update {today}` section to a decision note.

    The section carries the lens-supplied `update_reason` plus a
    placeholder line for the owner to fill. Provenance inline.
    """
    ok, reason = validate_decision_update_section(params, base)
    if not ok:
        return {"success": False, "applied": False, "reason": reason, "targets": [], "from_lens": source_lens}
    rel = params["decision_note_path"]
    p = _resolve(base, rel)
    text = p.read_text(encoding="utf-8")
    today = _date.today().isoformat()
    section = (
        f"\n## Update {today}\n\n"
        f"_Auto-scaffolded from {source_lens}_  \n"
        f"**Reason:** {params['update_reason']}\n\n"
        f"_(placeholder — owner fills with the actual update)_\n"
        f"<!-- from_lens: {source_lens} -->\n"
    )
    if text and not text.endswith("\n"):
        text += "\n"
    p.write_text(text + section, encoding="utf-8")
    return {
        "success": True,
        "applied": True,
        "reason": "",
        "targets": [rel],
        "from_lens": source_lens,
    }


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

VALIDATORS = {
    "wikilink_add": validate_wikilink_add,
    "hub_stub_create": validate_hub_stub_create,
    "open_thread_add": validate_open_thread_add,
    "decision_update_section": validate_decision_update_section,
}

APPLIERS = {
    "wikilink_add": apply_wikilink_add,
    "hub_stub_create": apply_hub_stub_create,
    "open_thread_add": apply_open_thread_add,
    "decision_update_section": apply_decision_update_section,
}

# Cross-check: every whitelisted type has both a validator and an applier.
assert set(VALIDATORS) == ACTION_HINT_TYPES, "validator set drifted from ACTION_HINT_TYPES"
assert set(APPLIERS) == ACTION_HINT_TYPES, "applier set drifted from ACTION_HINT_TYPES"
# Cross-check: every required-params entry has a validator (catches typos in
# `_common.ACTION_HINT_REQUIRED_PARAMS`).
assert set(ACTION_HINT_REQUIRED_PARAMS) == ACTION_HINT_TYPES, "required-params set drifted"
