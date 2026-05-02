"""Shared utilities for constitution scripts.

Deterministic, no LLM. PyYAML is the single external dependency.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import yaml


# -----------------------------------------------------------------------------
# Schema definition (mirrors 0_constitution/CONSTITUTION.md §3)
# -----------------------------------------------------------------------------

REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "type",
    "domain",
    "statement",
    "priority_tier",
    "scope",
    "applies_to",
    "status",
)

ALLOWED_TYPES = {"axiom", "principle", "rule"}
ALLOWED_DOMAINS = {
    "identity", "ethics", "work", "tech",
    "relationships", "health", "money", "time",
    "learning", "ai-interaction", "meta",
}
ALLOWED_PRIORITY_TIERS = {1, 2, 3}
ALLOWED_FRAMINGS = {"positive", "negative"}
ALLOWED_BINDINGS = {"hard", "soft"}
ALLOWED_SCOPES = {"shared", "personal", "sensitive"}
ALLOWED_APPLIES_TO = {
    "claude-code", "ztn", "chatgpt", "claude-desktop",
    "life-advice", "work-code", "bootstrap", "minder",
}
ALLOWED_CONFIDENCES = {"proven", "working", "experimental"}
ALLOWED_STATUSES = {"active", "candidate", "archived", "placeholder"}


# -----------------------------------------------------------------------------
# Concept-name normalisation per `_system/registries/CONCEPT_NAMING.md`
# -----------------------------------------------------------------------------
#
# Autonomous-pipeline policy: ZTN engine resolves concept-name format
# issues with deterministic heuristics — never raises, never blocks owner,
# never surfaces a CLARIFICATION. `normalize_concept_name(raw)` returns
# either a valid snake_case ASCII identifier or `None` to signal "drop
# this entry" — the only fallback when normalisation cannot produce a
# valid name. Callers MUST handle `None` as "skip silently."

CONCEPT_NAME_MAX_LEN = 64
CONCEPT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_CONCEPT_SEP_RE = re.compile(
    r"[\s\-‐-―−/\\.,;:!?()\[\]{}\"'~%+@#&*=<>^|`]+"
)
_CONCEPT_RUN_US = re.compile(r"_+")

FORBIDDEN_TYPE_PREFIXES: tuple[str, ...] = (
    "theme_", "decision_", "person_", "project_", "tool_", "idea_",
    "event_", "goal_", "value_", "fact_", "organization_", "skill_",
    "location_", "emotion_", "preference_", "constraint_", "algorithm_",
    "other_",
)

# `type` enum emitted by ZTN (lowercase, excludes person/project per
# §"Concept scope" in `_system/docs/batch-format.md`).
EMITTED_CONCEPT_TYPES: frozenset[str] = frozenset({
    "theme", "tool", "decision", "idea", "event", "organization",
    "skill", "location", "emotion", "goal", "value", "preference",
    "constraint", "algorithm", "fact", "other",
})


def normalize_concept_name(raw: str | None) -> str | None:
    """Return a valid snake_case ASCII concept name or None to drop.

    Pure function; no side effects. Mirrors CONCEPT_NAMING.md normalisation
    algorithm with autonomous fallbacks:
    - non-ASCII residue after diacritic-fold → drop (None)
    - empty after type-prefix strip → drop (None)
    - over-length → truncate at last `_` boundary `≤ 64`; hard-cut otherwise

    The caller is responsible for emitting the returned value verbatim or
    skipping the entry on None — never substitute, never raise.
    """
    if raw is None:
        return None
    import unicodedata
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _CONCEPT_SEP_RE.sub("_", s)
    s = _CONCEPT_RUN_US.sub("_", s)
    s = s.strip("_")
    if not s:
        return None
    if not all(ord(c) < 128 for c in s):
        return None
    if not CONCEPT_NAME_RE.match(s):
        return None
    for prefix in FORBIDDEN_TYPE_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):].lstrip("_")
            break
    if not s:
        return None
    # Bare type-enum words (`theme`, `tool`, `decision`, …) collapse
    # via Rule 8 — broad classifiers belong in domains/tags, not as
    # concepts. Same drop rule covers inputs like `theme_` (which
    # trim to `theme`) and bare classifier inputs like `theme` or
    # `decision` directly.
    if s in EMITTED_CONCEPT_TYPES or s in {"person", "project"}:
        return None
    if len(s) > CONCEPT_NAME_MAX_LEN:
        truncated = s[:CONCEPT_NAME_MAX_LEN]
        last_us = truncated.rfind("_")
        s = truncated[:last_us] if last_us > 0 else truncated
    if not s:
        return None
    return s


def normalize_concept_list(raw_iter) -> list[str]:
    """Apply normalize_concept_name to each entry; drop Nones; dedup
    preserving first-seen order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in (raw_iter or []):
        n = normalize_concept_name(raw)
        if n is None or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


# -----------------------------------------------------------------------------
# Audience-tag normalisation per `_system/registries/AUDIENCES.md`
# -----------------------------------------------------------------------------

AUDIENCE_CANONICAL: frozenset[str] = frozenset({
    "family", "friends", "work", "professional-network", "world",
})
AUDIENCE_TAG_RE = re.compile(r"^[a-z0-9-]+$")
AUDIENCE_TAG_MIN_LEN = 2
AUDIENCE_TAG_MAX_LEN = 32


def normalize_audience_tag(raw: str | None) -> str | None:
    """Normalise to kebab-case ASCII; return value if well-formed,
    else None. Caller checks against the canonical-five + Extensions
    whitelist to decide accept-vs-drop.

    Autonomous-pipeline policy: never raises; on any uncertainty, return
    None so caller drops the tag. Default empty `[]` audience is always
    safer than a guessed audience.
    """
    if raw is None:
        return None
    import unicodedata
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return None
    if not AUDIENCE_TAG_RE.match(s):
        return None
    if len(s) < AUDIENCE_TAG_MIN_LEN or len(s) > AUDIENCE_TAG_MAX_LEN:
        return None
    return s


# Single-context model: every consumer loads every scope.
#
# The `scope` field on principles (shared / personal / sensitive) stays as
# a data marker for future multi-user scenarios (sharing to wife / friends,
# MCP tokens). It does not currently drive any runtime filter — the whole
# tree is visible to every consumer on this machine. Filter logic is
# intentionally absent so the single-user dogfood stays simple; it is a
# one-file diff to re-add when scenarios require narrowing.
ALL_SCOPES_VISIBLE: frozenset[str] = frozenset({"shared", "personal", "sensitive"})


# -----------------------------------------------------------------------------
# Paths (resolved relative to repo root)
# -----------------------------------------------------------------------------

def repo_root() -> Path:
    """Return the zettelkasten repo root.

    Env var `ZTN_BASE` overrides; otherwise derive from this file's location.
    """
    env = os.environ.get("ZTN_BASE")
    if env:
        return Path(env).resolve()
    # scripts/_common.py → scripts → _system → zettelkasten
    return Path(__file__).resolve().parent.parent.parent


def constitution_root(base: Path | None = None) -> Path:
    return (base or repo_root()) / "0_constitution"


def system_dir(base: Path | None = None) -> Path:
    return (base or repo_root()) / "_system"


def views_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "views"


def state_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "state"


def registries_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "registries"


def docs_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "docs"


def scripts_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "scripts"


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------

class ConstitutionError(Exception):
    """Base error. Scripts catch and print to stderr, then sys.exit(1)."""


class SchemaError(ConstitutionError):
    """Frontmatter missing or invalid."""


class ParseError(ConstitutionError):
    """File cannot be parsed at the filesystem / YAML level."""


# -----------------------------------------------------------------------------
# Principle model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Principle:
    path: Path
    frontmatter: dict
    body: str

    @property
    def id(self) -> str:
        return self.frontmatter["id"]

    @property
    def type(self) -> str:
        return self.frontmatter["type"]

    @property
    def domain(self) -> str:
        return self.frontmatter["domain"]

    @property
    def priority_tier(self) -> int:
        return int(self.frontmatter["priority_tier"])

    @property
    def scope(self) -> str:
        return self.frontmatter["scope"]

    @property
    def applies_to(self) -> list[str]:
        val = self.frontmatter.get("applies_to", [])
        return list(val) if val else []

    @property
    def status(self) -> str:
        return self.frontmatter["status"]

    @property
    def is_core(self) -> bool:
        return bool(self.frontmatter.get("core", False))

    @property
    def is_placeholder(self) -> bool:
        return self.status == "placeholder"

    @property
    def title(self) -> str:
        return self.frontmatter["title"]

    @property
    def statement(self) -> str:
        return str(self.frontmatter["statement"]).strip()


# -----------------------------------------------------------------------------
# Parsing & validation
# -----------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.DOTALL)


def read_frontmatter(path: Path) -> tuple[dict, str] | None:
    """Generic frontmatter reader used by lint helpers.

    Returns (frontmatter_dict, body_text) or None when the file has no
    frontmatter block, the YAML cannot be parsed, or the YAML root is
    not a mapping. Tolerant of read errors (returns None) — the caller
    decides whether to skip silently or propagate. Distinct from
    `parse_file()` which is principle-schema-aware.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return fm, m.group(2)


def write_frontmatter(path: Path, fm: dict, body: str) -> None:
    """Round-trip frontmatter back to disk preserving body verbatim.

    YAML serialised with sort_keys=False, default_flow_style=False,
    allow_unicode=True. Width 10000 prevents PyYAML wrapping long
    lists. Insertion order on `fm` is preserved.
    """
    yaml_text = yaml.safe_dump(
        fm, sort_keys=False, default_flow_style=False,
        allow_unicode=True, width=10000,
    ).rstrip("\n")
    path.write_text(f"---\n{yaml_text}\n---\n{body}", encoding="utf-8")


def parse_file(path: Path) -> Principle:
    """Read markdown file, split frontmatter / body, validate schema.

    Raises SchemaError / ParseError with a `{path}: {reason}` message.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParseError(f"{path}: cannot read file ({exc})") from exc

    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ParseError(f"{path}: no YAML frontmatter found")

    yaml_text, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ParseError(f"{path}: YAML parse error — {exc}") from exc
    if not isinstance(fm, dict):
        raise SchemaError(f"{path}: frontmatter must be a mapping, got {type(fm).__name__}")

    validate_frontmatter(path, fm)
    return Principle(path=path, frontmatter=fm, body=body)


def validate_frontmatter(path: Path, fm: dict) -> None:
    """Raise SchemaError on any violation. Called by parse_file."""
    missing = [f for f in REQUIRED_FIELDS if f not in fm]
    if missing:
        raise SchemaError(f"{path}: missing required fields: {missing}")

    def check_enum(field_name: str, value, allowed: Iterable) -> None:
        if value not in allowed:
            raise SchemaError(
                f"{path}: field '{field_name}' has invalid value {value!r}; "
                f"allowed: {sorted(allowed)}"
            )

    check_enum("type", fm["type"], ALLOWED_TYPES)
    check_enum("domain", fm["domain"], ALLOWED_DOMAINS)
    check_enum("priority_tier", fm["priority_tier"], ALLOWED_PRIORITY_TIERS)
    check_enum("scope", fm["scope"], ALLOWED_SCOPES)
    check_enum("status", fm["status"], ALLOWED_STATUSES)

    if "framing" in fm:
        check_enum("framing", fm["framing"], ALLOWED_FRAMINGS)
    if "binding" in fm:
        check_enum("binding", fm["binding"], ALLOWED_BINDINGS)
    if "confidence" in fm:
        check_enum("confidence", fm["confidence"], ALLOWED_CONFIDENCES)

    applies_to = fm.get("applies_to", [])
    if not isinstance(applies_to, list):
        raise SchemaError(f"{path}: applies_to must be a list, got {type(applies_to).__name__}")
    for item in applies_to:
        if item not in ALLOWED_APPLIES_TO:
            # Consumer-side rule: unknown values are ignored but not a fatal
            # schema error — new enum values may land in CONSTITUTION.md before
            # scripts are updated. Log to stderr.
            print(
                f"warning: {path}: unknown applies_to value {item!r} — ignored",
                file=sys.stderr,
            )

    if "core" in fm and not isinstance(fm["core"], bool):
        raise SchemaError(f"{path}: field 'core' must be boolean")

    # ID shape: {type}-{domain}-{NNN}
    expected_prefix = f"{fm['type']}-{fm['domain']}-"
    if not str(fm["id"]).startswith(expected_prefix):
        raise SchemaError(
            f"{path}: id {fm['id']!r} does not match expected prefix "
            f"{expected_prefix!r} (type-domain-NNN)"
        )


def iter_principles(root: Path) -> list[Principle]:
    """Walk `root` (expected: 0_constitution/), return all parsed principles.

    Skips CONSTITUTION.md (the protocol doc itself) and any README-like files
    at the top level. Sub-folders {axiom,principle,rule}/* are scanned. Also
    validates that all ids are unique — duplicates raise SchemaError.
    Symbolic-link files are skipped (security defence for export paths).
    """
    if not root.exists():
        return []
    results: list[Principle] = []
    for type_name in sorted(ALLOWED_TYPES):
        type_dir = root / type_name
        if not type_dir.is_dir():
            continue
        for md_file in sorted(type_dir.rglob("*.md")):
            if md_file.is_symlink():
                # Symlinks are never followed — they could point outside the
                # repo (e.g. into $HOME) and leak content via export.
                print(
                    f"warning: {md_file}: symbolic link skipped",
                    file=sys.stderr,
                )
                continue
            results.append(parse_file(md_file))
    # Sort by id for deterministic output across platforms.
    results.sort(key=lambda p: p.id)
    _check_unique_ids(results)
    return results


def _check_unique_ids(principles: list[Principle]) -> None:
    seen: dict[str, Path] = {}
    for p in principles:
        prior = seen.get(p.id)
        if prior is not None:
            raise SchemaError(
                f"duplicate id {p.id!r}: "
                f"first seen in {prior}, also in {p.path}"
            )
        seen[p.id] = p.path


# -----------------------------------------------------------------------------
# Filters
# -----------------------------------------------------------------------------

_HIDDEN_STATUSES_DEFAULT: frozenset[str] = frozenset({"archived", "placeholder"})


def is_visible(
    p: Principle,
    *,
    consumer: str | None = None,
    allow_statuses: frozenset[str] | set[str] | None = None,
) -> bool:
    """True if principle is visible to a consumer.

    `allow_statuses`: set of status values that override the default
    exclusion list (`archived`, `placeholder`). Use for test fixtures or
    for lint health views that need to see the full tree.

    Scope-based context narrowing is not currently applied — every scope
    is visible to every consumer. The `scope` field exists as a data
    marker for future multi-user scenarios.
    """
    hidden = _HIDDEN_STATUSES_DEFAULT - (frozenset(allow_statuses) if allow_statuses else frozenset())
    if p.status in hidden:
        return False
    if consumer and p.applies_to:
        if consumer not in p.applies_to:
            return False
    return True


# -----------------------------------------------------------------------------
# Body helpers (for Evidence Trail & SOUL markers)
# -----------------------------------------------------------------------------

EVIDENCE_TRAIL_HEADING = "## Evidence Trail"


def find_evidence_trail_bounds(body: str) -> tuple[int, int] | None:
    """Return (start, end) char offsets in body for the Evidence Trail section.

    `start` points to the first char of the first entry (line after heading).
    `end` points to the first char of the next `## ` heading, or len(body).
    Returns None if section not found.
    """
    pattern = re.compile(r"^## Evidence Trail\s*$", re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return None
    start = m.end()
    # Skip leading newlines after heading
    while start < len(body) and body[start] in "\r\n":
        start += 1
    next_h = re.search(r"^## ", body[start:], re.MULTILINE)
    end = start + next_h.start() if next_h else len(body)
    return start, end


SOUL_MARKER_START = "<!-- AUTO-GENERATED FROM CONSTITUTION — DO NOT EDIT MANUALLY -->"
SOUL_MARKER_END = "<!-- END AUTO-GENERATED -->"


def find_soul_auto_zone(text: str) -> tuple[int, int] | None:
    """Return (content_start, content_end) between SOUL auto-markers.

    content_start = position right after the start marker line (including
    trailing newline). content_end = position right before the end marker line.
    Returns None if either marker is missing.
    """
    i_start = text.find(SOUL_MARKER_START)
    if i_start < 0:
        return None
    # Advance past the marker line including its newline
    line_end = text.find("\n", i_start)
    if line_end < 0:
        return None
    content_start = line_end + 1

    i_end = text.find(SOUL_MARKER_END, content_start)
    if i_end < 0:
        return None
    # content_end: include preceding newline so replacement is clean
    content_end = i_end
    return content_start, content_end


# -----------------------------------------------------------------------------
# Misc
# -----------------------------------------------------------------------------

def today_iso() -> str:
    return date.today().isoformat()


def now_iso_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)
