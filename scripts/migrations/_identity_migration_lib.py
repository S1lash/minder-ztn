#!/usr/bin/env python3
"""Shared primitives for the identity migrations (023 / 024 / 025).

Three migrations land the identity contract on a clone that predates it, and
all three need the same four things: find the owner's base whatever they named
it, read and write files the same way on every platform, put a question in the
owner's queue without ever asking it twice, and keep a generated block
re-generatable without ever overwriting a hand edit.

Written once here rather than three times, because a migration that resolves
the base slightly differently from its neighbour is a migration that repairs a
different clone from the one its sibling repaired.

The leading underscore keeps the runner from globbing this as a migration of
its own — `pending()` globs `*.sh`, but the convention is what a reader relies
on.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402,F401

# The marker that brackets a generated block. `key` names the section; `hash`
# is the digest of the content this migration last wrote there, and is the
# whole mechanism behind "never overwrite a hand edit": on a re-run a block
# whose content still hashes to its marker is ours to refresh, and a block
# whose content does not is the owner's to keep.
_OPEN_RE_TMPL = r"<!-- ztn:{ns}:{key} hash=([0-9a-f]{{12}}) -->"
_CLOSE_TMPL = "<!-- /ztn:{ns}:{key} -->"


# -----------------------------------------------------------------------------
# Base + engine imports
# -----------------------------------------------------------------------------

def resolve_base(repo_root: Path) -> Path | None:
    """The owner's zettelkasten base, whatever they named the directory.

    The name is the owner's choice, so it is resolved by looking for the engine
    inside it rather than assumed. An ambiguous answer (two candidates) is
    reported as no answer: guessing which base to migrate is worse than saying
    the clone has a shape this migration does not understand.
    """
    found: list[Path] = []
    for child in sorted(repo_root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "_system" / "scripts" / "_common.py").is_file():
            found.append(child)
    if len(found) == 1:
        return found[0]
    fallback = repo_root / "zettelkasten"
    if fallback.is_dir():
        return fallback
    return None


def import_common(base: Path):
    """The engine's `_common` from inside the resolved base, or None.

    The engine ships its own parsers for both registries and for the owner's
    identifier. A migration that wrote a second parser would be a second
    opinion about what a registry says, and the two would diverge the first
    time either changed.

    **Absence is a condition, never an exception.** A clone can legitimately be
    mid-update with no shared library on disk yet — `sync_engine.sh` has a
    self-heal path for exactly that state. A migration that raised here would
    turn a recoverable state into a failing one, and as a structural migration
    it would abort the whole update: every friend, on the next update, bricked
    by a repair they did not need. So the caller gets None and says so.
    """
    library = base / "_system" / "scripts" / "_common.py"
    if not library.is_file():
        return None
    scripts = str(library.parent.resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import _common  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — a half-written library is absence too
        return None
    return _common


# The message every migration prints when the engine library is not on disk.
# It exits non-zero deliberately: under `run_migrations.py` a zero exit is
# recorded `applied` and the migration never runs again, which would silently
# skip the repair forever. A non-zero exit from a `heal` migration is recorded
# `partial`, the update continues, and the next update retries it — which is
# exactly "could not do its work, do not fake success, try again later".
NO_LIBRARY_RC = 1


def report_no_library(migration: str, base: Path) -> int:
    sys.stderr.write(
        f"{migration}: the engine library is not on disk yet at "
        f"{(base / '_system' / 'scripts' / '_common.py')} — this migration "
        f"reads the registries through it and will not guess without it.\n"
        f"{migration}: nothing was written. The update continues, and this "
        f"runs by itself on the next one, once the library is in place.\n"
    )
    return NO_LIBRARY_RC


# -----------------------------------------------------------------------------
# Shipped placeholders
# -----------------------------------------------------------------------------

# The two shapes the shipped templates use for a value the owner has not
# supplied yet: braces around the instruction to the reader
# (`{Your full name as you'd like agents to refer to you}`) and a
# `REPLACE_WITH_` sentinel. Matched by shape rather than by any one literal, so
# a reworded placeholder does not slip through and start meaning something.
_PLACEHOLDER_RE = re.compile(r"^(\{.*\}|REPLACE_WITH_[A-Z_]*)$", re.DOTALL)


def is_placeholder(value: str) -> bool:
    """True when a field still holds what the template shipped, not an answer.

    A migration that derives an identity from an unanswered field mints a
    person out of the instruction text. Every migration that reads an owner
    field reads it through this, so an un-bootstrapped clone is a condition to
    wait on rather than data to act on.
    """
    return bool(_PLACEHOLDER_RE.match((value or "").strip()))


# -----------------------------------------------------------------------------
# Portable file I/O
# -----------------------------------------------------------------------------

def read_text(path: Path, default: str | None = None) -> str:
    """UTF-8 read with universal newlines, so a CRLF checkout reads as LF."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if default is None:
            raise
        return default
    except (OSError, UnicodeDecodeError):
        if default is None:
            raise
        return default


def write_text(path: Path, text: str) -> None:
    """UTF-8 write with explicit LF, on every platform.

    `newline=""` is what stops python's text layer from translating `\\n` to
    `\\r\\n` on Windows — a migration that silently rewrote a whole registry in
    CRLF would show every line as changed in the owner's next diff.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# -----------------------------------------------------------------------------
# Generated blocks — idempotent per section
# -----------------------------------------------------------------------------

def upsert_block(
    document: str, ns: str, key: str, content: str,
) -> tuple[str, str]:
    """Insert or refresh one generated block. Returns `(document, outcome)`.

    Outcomes:
      `added`    the block was not there and now is
      `refreshed` the block was there, untouched since we wrote it, and the
                 sources have since said something new
      `unchanged` the block was there and the sources still say the same thing
      `kept`     the block was there and does NOT hash to its marker — the
                 owner edited it, so it is left exactly as they left it

    `kept` is the whole point. A migration that re-runs and rewrites is a
    migration that eats the owner's corrections, and the owner never finds out
    which run did it.
    """
    open_re = re.compile(_OPEN_RE_TMPL.format(ns=re.escape(ns), key=re.escape(key)))
    close = _CLOSE_TMPL.format(ns=ns, key=key)
    new_hash = digest(content)
    block = f"<!-- ztn:{ns}:{key} hash={new_hash} -->\n{content}\n{close}"

    m = open_re.search(document)
    if m is None:
        joiner = "" if document.endswith("\n\n") else (
            "\n" if document.endswith("\n") else "\n\n"
        )
        return document + joiner + block + "\n", "added"

    close_at = document.find(close, m.end())
    if close_at == -1:
        # An opening marker with no closing one: the block's extent is unknown,
        # so its content cannot be compared and must not be replaced.
        return document, "kept"

    existing = document[m.end():close_at].strip("\n")
    if digest(existing) != m.group(1):
        return document, "kept"
    if existing == content:
        return document, "unchanged"
    return (
        document[:m.start()] + block + document[close_at + len(close):],
        "refreshed",
    )


# -----------------------------------------------------------------------------
# The owner's question queue
# -----------------------------------------------------------------------------

_OPEN_ITEMS_RE = re.compile(r"^##\s+Open Items\s*$", re.MULTILINE)


def clarification_anchor(migration: str, key: str) -> str:
    return f"<!-- {migration}: {key} -->"


def append_clarifications(
    base: Path, migration: str, heading: str, items: list[tuple[str, str]],
) -> tuple[int, int]:
    """Append clarification blocks under `## Open Items`. `(written, skipped)`.

    Each item is `(anchor, block)`. An anchor already present in either the
    open queue or the resolved archive is skipped: the owner has already been
    asked, and asking again — after they answered — is worse than not asking,
    because it teaches them the queue repeats itself.
    """
    path = base / "_system" / "state" / "CLARIFICATIONS.md"
    if not path.is_file():
        return 0, len(items)
    text = read_text(path)
    archive = read_text(
        base / "_system" / "state" / "CLARIFICATIONS_ARCHIVE.md", default="",
    )

    fresh = [
        (anchor, block) for anchor, block in items
        if anchor not in text and anchor not in archive
    ]
    if not fresh:
        return 0, len(items)

    body = "\n".join(f"{block.rstrip()}\n{anchor}\n" for anchor, block in fresh)
    section = f"## {heading}\n\n{body}"

    m = _OPEN_ITEMS_RE.search(text)
    if m is None:
        text = text.rstrip("\n") + "\n\n## Open Items\n\n" + section
    else:
        insert_at = m.end()
        text = text[:insert_at] + "\n\n" + section.rstrip("\n") + "\n" + text[insert_at:]
    write_text(path, text)
    return len(fresh), len(items) - len(fresh)


# -----------------------------------------------------------------------------
# Markdown tables
# -----------------------------------------------------------------------------

_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


def table_cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [c.strip() for c in stripped.strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(
        _SEPARATOR_RE.match(c) for c in cells if c
    )


def render_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"
