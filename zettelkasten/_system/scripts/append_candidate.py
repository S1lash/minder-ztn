#!/usr/bin/env python3
"""Append a principle candidate to `_system/state/principle-candidates.jsonl`.

Invoked by the `/ztn:capture-candidate` skill from any session (personal,
work, external). Schema-validates inputs, enriches with origin + session
id + date, appends atomically. No LLM, no reasoning — just a clean buffer
write so the capture path is predictable regardless of session context.

Schema of each JSONL line:

    {
      "date": "YYYY-MM-DD",
      "situation": "...",
      "observation": "...",         # verbatim quote if available, else ""
      "hypothesis": "..." | null,   # inferred principle hypothesis or null
      "suggested_type": "axiom | principle | rule | unknown",
      "suggested_domain": "<domain> | unknown",
      "origin": "personal | work | external",
      "session_id": "...",
      "record_ref": "[[...]]" | null,
      "captured_by": "ztn:capture-candidate"
    }

Usage:
    python3 append_candidate.py \\
        --situation "..." \\
        [--observation "..."] \\
        [--hypothesis "..."] \\
        --suggested-type principle \\
        --suggested-domain tech \\
        [--origin personal|work|external] \\
        [--session-id ...] \\
        [--record-ref "[[...]]"] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from _common import (
    ALLOWED_DOMAINS,
    ALLOWED_TYPES,
    ConstitutionError,
    die,
    state_dir,
    today_iso,
)


BUFFER_FILENAME = "principle-candidates.jsonl"
ALLOWED_SUGGESTED_TYPES: frozenset[str] = frozenset(ALLOWED_TYPES | {"unknown"})
ALLOWED_SUGGESTED_DOMAINS: frozenset[str] = frozenset(ALLOWED_DOMAINS | {"unknown"})
ALLOWED_ORIGINS: frozenset[str] = frozenset({"personal", "work", "external"})

CONCEPT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
CONCEPT_NAME_MAX_LEN = 64
FORBIDDEN_TYPE_PREFIXES: tuple[str, ...] = (
    "theme_", "decision_", "person_", "project_", "tool_", "idea_",
    "event_", "goal_", "value_", "fact_", "organization_", "skill_",
    "location_", "emotion_", "preference_", "constraint_", "algorithm_",
    "other_",
)


def validate_concept_name(name: str) -> None:
    """Enforce CONCEPT_NAMING.md format on a single concept-name string.

    Raises ConstitutionError on any of: format mismatch (non-snake_case
    ASCII, runs of underscores, leading/trailing `_`), forbidden type
    prefix, or length > 64. Mirrors the rules in
    `_system/registries/CONCEPT_NAMING.md`.
    """
    if not name:
        raise ConstitutionError("concept name must not be empty")
    if len(name) > CONCEPT_NAME_MAX_LEN:
        raise ConstitutionError(
            f"concept name {name!r} exceeds {CONCEPT_NAME_MAX_LEN} chars "
            "(rule 7); shorten or extract the load-bearing noun"
        )
    if not CONCEPT_NAME_RE.match(name):
        raise ConstitutionError(
            f"concept name {name!r} violates snake_case ASCII (rules 1–4); "
            "expect ^[a-z0-9_]+$, no leading/trailing/consecutive '_'"
        )
    if "__" in name or name.startswith("_") or name.endswith("_"):
        raise ConstitutionError(
            f"concept name {name!r} violates rule 4 (no leading, trailing, "
            "or consecutive '_')"
        )
    for prefix in FORBIDDEN_TYPE_PREFIXES:
        if name.startswith(prefix):
            raise ConstitutionError(
                f"concept name {name!r} starts with forbidden type prefix "
                f"{prefix!r} (rule 5); type lives in metadata, not in name"
            )


def parse_applies_in_concepts(raw: str | None) -> list[str]:
    """Parse comma-separated concept names; validate each.

    Empty / None -> []. Whitespace around commas tolerated. On any
    invalid entry, raises ConstitutionError citing the bad name —
    helper does not silently sanitise per CONCEPT_NAMING §"On violation".
    """
    if not raw:
        return []
    names = [chunk.strip() for chunk in raw.split(",") if chunk.strip()]
    for name in names:
        validate_concept_name(name)
    return names


def resolve_origin(explicit: str | None) -> str:
    """Origin tag for the capture entry.

    In the single-context model there is no automatic environment-based
    tagging — the caller (skill, pipeline) may pass `--origin` explicitly
    to annotate the provenance. Default is `personal`, matching the
    default harness view.
    """
    if explicit:
        if explicit not in ALLOWED_ORIGINS:
            raise ConstitutionError(
                f"unknown origin {explicit!r}; "
                f"allowed: {sorted(ALLOWED_ORIGINS)}"
            )
        return explicit
    return "personal"


def default_session_id() -> str:
    return "session-" + datetime.utcnow().strftime("%Y-%m-%d-%H%M%S-UTC")


def build_entry(args: argparse.Namespace) -> dict:
    return {
        "date": today_iso(),
        "situation": args.situation.strip(),
        "observation": (args.observation or "").strip(),
        "hypothesis": args.hypothesis.strip() if args.hypothesis else None,
        "suggested_type": args.suggested_type,
        "suggested_domain": args.suggested_domain,
        "applies_in_concepts": parse_applies_in_concepts(
            args.applies_in_concepts
        ),
        "origin": resolve_origin(args.origin),
        "session_id": args.session_id or default_session_id(),
        "record_ref": args.record_ref,
        "captured_by": "ztn:capture-candidate",
    }


def append_atomic(entry: dict, buffer_path: Path) -> None:
    """Atomic single-line append with advisory file lock.

    POSIX O_APPEND gives atomicity for single writes up to PIPE_BUF
    (typically 4 KiB). Long candidate observations (with transcript
    fragments) can exceed that, and Windows / NFS do not guarantee
    O_APPEND atomicity at all. An exclusive advisory lock around the
    append closes that gap on every platform that supports fcntl.
    """
    buffer_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False)
    with buffer_path.open("a", encoding="utf-8") as fh:
        _acquire_exclusive_lock(fh)
        try:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            _release_lock(fh)


def _acquire_exclusive_lock(fh) -> None:
    """Advisory exclusive lock; blocks until available.

    Uses fcntl on POSIX. On Windows (no fcntl) we emit a warning and skip —
    append-only JSONL stays mostly safe for short lines via O_APPEND, and
    concurrent writers are a rare edge in Windows contexts for this tool.
    """
    try:
        import fcntl
    except ImportError:
        print(
            "warning: fcntl unavailable on this platform; proceeding without "
            "exclusive lock. Concurrent appenders on long lines may interleave.",
            file=sys.stderr,
        )
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _release_lock(fh) -> None:
    try:
        import fcntl
    except ImportError:
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--situation", required=True,
                        help="1-2 sentences — what was happening")
    parser.add_argument("--observation", default="",
                        help="verbatim quote / behaviour observed")
    parser.add_argument("--hypothesis", default=None,
                        help="inferred principle hypothesis (NULL if explicit)")
    parser.add_argument("--suggested-type", required=True,
                        help=f"one of {sorted(ALLOWED_SUGGESTED_TYPES)}")
    parser.add_argument("--suggested-domain", required=True,
                        help=f"one of {sorted(ALLOWED_SUGGESTED_DOMAINS)}")
    parser.add_argument("--origin", default=None,
                        help=f"one of {sorted(ALLOWED_ORIGINS)}; "
                             "default: 'personal'")
    parser.add_argument("--session-id", default=None,
                        help="session or source identifier; default: timestamp")
    parser.add_argument("--record-ref", default=None,
                        help="wiki-link to a record, e.g. [[_records/...]]")
    parser.add_argument("--applies-in-concepts", default=None,
                        help="comma-separated concept names per "
                             "_system/registries/CONCEPT_NAMING.md "
                             "(snake_case ASCII, English-only, ≤64 chars, "
                             "no forbidden type prefix). Empty / omitted "
                             "→ []. Each entry validated; non-conformant "
                             "name fails the append, never silently "
                             "rewritten.")
    parser.add_argument("--buffer", type=Path, default=None,
                        help=f"override buffer path (default: "
                             f"_system/state/{BUFFER_FILENAME})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the entry as JSON without writing")
    args = parser.parse_args(argv)

    if not args.situation.strip():
        die("--situation must not be empty")
    if args.suggested_type not in ALLOWED_SUGGESTED_TYPES:
        die(f"--suggested-type {args.suggested_type!r} not in "
            f"{sorted(ALLOWED_SUGGESTED_TYPES)}")
    if args.suggested_domain not in ALLOWED_SUGGESTED_DOMAINS:
        die(f"--suggested-domain {args.suggested_domain!r} not in "
            f"{sorted(ALLOWED_SUGGESTED_DOMAINS)}")

    try:
        entry = build_entry(args)
    except ConstitutionError as exc:
        die(str(exc))

    if args.dry_run:
        json.dump(entry, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    buffer_path = args.buffer or (state_dir() / BUFFER_FILENAME)
    append_atomic(entry, buffer_path)
    print(f"appended candidate to {buffer_path} (origin={entry['origin']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
