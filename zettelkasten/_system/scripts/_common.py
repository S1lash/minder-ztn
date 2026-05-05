"""Shared utilities for constitution scripts.

Deterministic, no LLM. PyYAML is the single external dependency.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
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
# Canonical thirteen — single source of truth for `domains:` / `domain:`.
# Mirrored in `_system/registries/DOMAINS.md`. Treat as immutable at runtime;
# changes require coordinated edits to DOMAINS.md and tests.
ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "work", "career", "personal",
    "identity", "ethics", "health",
    "relationships",
    "learning", "money", "time",
    "ai-interaction", "tech", "meta",
})

# Mirror of Minder's `ConceptDomain` enum
# (`minder/.../domain/value/ConceptDomain.java`). Per-concept-mention scope
# derived downstream from a note's `domains:` + `origin`. NOT used for
# ZTN-side validation — kept here as a documentation reference so future
# manifest/consumer work can spot drift between the two axes.
MINDER_CONCEPT_DOMAIN: frozenset[str] = frozenset({
    "work", "personal", "mixed", "unknown",
})
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

# Frozen mirror of Minder's `ConceptType` enum (18 values).
# Source of truth: minder/.../domain/graph/ConceptType.java.
# Mirrored in `_system/registries/CONCEPT_TYPES.md`. Drift detected by
# `test_common.py::TestConceptTypeMirror` (reads Java enum at test time).
# This is the documentation/audit set; emission gate is EMITTED_CONCEPT_TYPES.
CONCEPT_TYPES_ALL: frozenset[str] = frozenset({
    "person", "organization", "project", "idea", "tool", "skill", "location",
    "event", "emotion", "theme",
    "goal", "value", "preference", "constraint", "algorithm", "decision",
    "fact", "other",
})

# Per-type human-readable description, mirrored from Java enum constructor
# strings. Fed into the concept-matcher subagent prompt for disambiguation.
CONCEPT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "person": "People and contacts",
    "organization": "Companies, teams, communities",
    "project": "Projects and initiatives",
    "idea": "Ideas and concepts",
    "tool": "Technologies and instruments",
    "skill": "Skills and competencies",
    "location": "Places and locations",
    "event": "Events and meetings",
    "emotion": "Emotional states",
    "theme": "Topics and themes",
    "goal": "User goals and objectives",
    "value": "Personal values and principles",
    "preference": "User preferences",
    "constraint": "User constraints and rules",
    "algorithm": "Generalized decision patterns and reasoning sequences",
    "decision": "Explicit choices with reasoning and alternatives",
    "fact": "Individual facts and notes",
    "other": "Other concepts",
}

# `type` enum emitted by ZTN (lowercase, excludes person/project per
# §"Concept scope" in `_system/docs/batch-format.md`).
# Subset of CONCEPT_TYPES_ALL — gate at emit boundary.
EMITTED_CONCEPT_TYPES: frozenset[str] = CONCEPT_TYPES_ALL - frozenset({
    "person", "project",
})

# Bare type-enum words that collapse to drop per Rule 8 (broad
# classifiers belong in domains/tags, not as concepts). All 18 mirror
# values plus emit-set are reserved as concept-name surface — names
# matching any of these collapse via `normalize_concept_name`.
RESERVED_TYPE_WORDS: frozenset[str] = CONCEPT_TYPES_ALL


def validate_concept_type(value: str | None) -> bool:
    """Return True if value is a member of EMITTED_CONCEPT_TYPES.

    The validation gate at emit boundary: rejects unknown codes,
    rejects `person`/`project` (first-class entities, not concepts),
    rejects empty/null. Caller drops invalid entries silently.
    """
    if value is None or not isinstance(value, str):
        return False
    return value in EMITTED_CONCEPT_TYPES


def normalize_concept_type(raw: str | None) -> str | None:
    """Lowercase + strip + emit-set membership check; None on miss.

    Pure function. Strips surrounding whitespace, lowercases, then
    asserts membership in EMITTED_CONCEPT_TYPES. Returns the
    normalised code or None — caller drops on None.

    `person` and `project` map to None even though they're in the
    18-mirror — the emit boundary excludes them.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if not s:
        return None
    if s not in EMITTED_CONCEPT_TYPES:
        return None
    return s


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
    # Bare type-enum words (`theme`, `tool`, `decision`, `person`,
    # `project`, …) collapse via Rule 8 — broad classifiers belong in
    # domains/tags, not as concepts. Covers both `theme_` (which trims
    # to `theme`) and bare inputs like `theme` directly. People and
    # projects are first-class entities with their own slots, never
    # routed through the concept channel.
    if s in RESERVED_TYPE_WORDS:
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


HUB_TRIO_FIELDS: tuple[str, ...] = ("origin", "audience_tags", "is_sensitive")

_HUB_FIX_IDS: dict[str, str] = {
    "origin": "hub-origin-derive-autofix",
    "audience_tags": "hub-audience-derive-autofix",
    "is_sensitive": "hub-sensitivity-derive-autofix",
}


def recompute_hub_trio(
    hub_fm: dict, member_trios: list[dict]
) -> tuple[dict, list[dict]]:
    """Derive hub privacy trio from member-note trios.

    Single source of truth for `/ztn:process` hub C/D, `/ztn:maintain`
    Step 4 hub linkage, and `lint_concept_audit.py` hub-pass logic.

    Derivation rules:
    - `origin` ← dominant origin across members (tie → `personal`)
    - `audience_tags` ← intersection of member audience_tags (only
      audiences ALL members agree on widen the hub)
    - `is_sensitive` ← any-member contagion (`true` if any member is
      sensitive, else `false`)

    **Owner-vs-engine ownership contract via `_engine_derived`.** Hub
    frontmatter carries an `_engine_derived: [field, ...]` list that
    enumerates which trio fields the engine currently owns. Behaviour:

    - Field missing from frontmatter → engine derives, writes value,
      ADDS field name to `_engine_derived`. (First touch on a fresh
      hub leaves all three engine-owned, continuously re-derived.)
    - Field present AND its name in `_engine_derived` → engine
      RE-DERIVES on every call, overwriting prior engine value.
      Membership changed → trio updates automatically.
    - Field present AND name NOT in `_engine_derived` → owner edit;
      engine NEVER touches it. To re-engage the engine, owner removes
      the value AND adds the field name back to `_engine_derived` (or
      simply removes the value — engine re-adds the marker on next
      derive).

    Backward compatibility: if `_engine_derived` is absent and a trio
    field IS present, the engine treats it as owner-set (preserves
    it). This matches the legacy "set once, owner takes over"
    semantics for hubs created before the marker existed; new hubs
    get the marker on first derivation.

    Returns (modified_fm, events). Events list captures every
    re-derivation (not just first-touch) so audit logs reflect
    continuous engine activity.
    """
    events: list[dict] = []
    new_fm = dict(hub_fm)

    if member_trios:
        from collections import Counter
        origins = [m.get("origin", "personal") for m in member_trios
                   if isinstance(m, dict)]
        if origins:
            counter = Counter(origins)
            ranked = counter.most_common()
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                derived_origin = ranked[0][0]
            else:
                derived_origin = "personal"
        else:
            derived_origin = "personal"

        audience_sets: list[set[str]] = []
        for m in member_trios:
            if not isinstance(m, dict):
                continue
            tags = m.get("audience_tags") or []
            if isinstance(tags, list):
                audience_sets.append(set(t for t in tags if isinstance(t, str)))
        if audience_sets:
            derived_audience = sorted(set.intersection(*audience_sets))
        else:
            derived_audience = []

        derived_sens = any(
            bool(m.get("is_sensitive"))
            for m in member_trios
            if isinstance(m, dict)
        )
    else:
        derived_origin = "personal"
        derived_audience = []
        derived_sens = False

    derived_values = {
        "origin": derived_origin,
        "audience_tags": derived_audience,
        "is_sensitive": derived_sens,
    }

    raw_marker = new_fm.get("_engine_derived")
    if isinstance(raw_marker, list):
        engine_owned = {x for x in raw_marker if isinstance(x, str)}
        marker_present = True
    else:
        engine_owned = set()
        marker_present = False

    for field in HUB_TRIO_FIELDS:
        present = field in new_fm
        if not present:
            # Missing → engine derives, takes ownership.
            new_fm[field] = derived_values[field]
            engine_owned.add(field)
            events.append({
                "fix_id": _HUB_FIX_IDS[field],
                "result": derived_values[field],
                "reason": "missing-field",
            })
        elif marker_present and field in engine_owned:
            # Engine-owned and value differs → re-derive.
            if new_fm[field] != derived_values[field]:
                events.append({
                    "fix_id": _HUB_FIX_IDS[field],
                    "result": derived_values[field],
                    "reason": "rederived",
                    "before": new_fm[field],
                })
                new_fm[field] = derived_values[field]
        # else: owner-set (no marker, or marker without this field).
        # Engine does not touch.

    if engine_owned:
        new_fm["_engine_derived"] = sorted(engine_owned)
    elif "_engine_derived" in new_fm and not engine_owned:
        # All fields owner-claimed; clean empty marker.
        del new_fm["_engine_derived"]

    return new_fm, events


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


# -----------------------------------------------------------------------------
# Domain normalisation per `_system/registries/DOMAINS.md`
# -----------------------------------------------------------------------------
#
# Same shape as audience normalisation: kebab-case ASCII, length 2..32, caller
# decides accept-vs-drop against canonical 13 ∪ active Extensions.
#
# Slash-syntax handling. Real corpus contains values like `work/process`,
# `personal/psychology` — owner's compact notation for "this entity belongs
# to MULTIPLE domains: work AND process". The ZTN axis is flat (no hierarchy)
# but it IS multi-valued, so slash entries split into independent values.
# Each part is normalised + filtered against the accept set independently.
# Real-corpus consequence: `work/process` keeps `work` (canonical) and drops
# `process` (not in whitelist) — same outcome as before — but `work/learning`
# keeps BOTH (both canonical), which the previous "prefix-only" policy lost.

DOMAIN_RE = re.compile(r"^[a-z0-9-]+$")
DOMAIN_MIN_LEN = 2
DOMAIN_MAX_LEN = 32


def normalize_domain(raw: str | None) -> str | None:
    """Strict single-value normalisation to kebab-case ASCII; return value if
    well-formed, else None.

    No slash handling — slash is treated as an irrecoverable separator that
    indicates multi-valued input. Callers that need to expand slash entries
    use `expand_domain_entry()` instead, which splits before normalising.
    Direct `normalize_domain("work/process")` returns None because the
    slash makes the string non-well-formed for a single-value slot.

    Autonomous-pipeline policy: never raises. On any irrecoverable shape,
    return None so the caller drops the value silently.
    """
    if raw is None:
        return None
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return None
    if not DOMAIN_RE.match(s):
        return None
    if len(s) < DOMAIN_MIN_LEN or len(s) > DOMAIN_MAX_LEN:
        return None
    return s


def expand_domain_entry(raw: str | None) -> list[str]:
    """Expand a single raw entry into zero, one, or many normalised values.

    Slash-syntax splits: `work/process` → `[work, process]` (each part runs
    through `normalize_domain` independently). Non-slash input collapses to
    a single-element list (`[work]`) or empty (`[]`) on irrecoverable shape.

    Returns deduplicated list preserving first-seen order. Caller filters
    against the accept set; this function only handles the format substrate.
    """
    if raw is None:
        return []
    if not isinstance(raw, str):
        return []
    parts = [p.strip() for p in raw.split("/")] if "/" in raw else [raw]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        n = normalize_domain(part)
        if n is None or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def normalize_domain_list(raw_iter, accept_set: Iterable[str] | None = None) -> list[str]:
    """Expand each entry via `expand_domain_entry` (slash-split aware), then
    filter against the accept set; dedup preserving first-seen order.

    `accept_set` defaults to ALLOWED_DOMAINS — pass `ALLOWED_DOMAINS | extensions`
    when extension-aware filtering is needed.
    """
    accept = frozenset(accept_set) if accept_set is not None else ALLOWED_DOMAINS
    seen: set[str] = set()
    out: list[str] = []
    for raw in (raw_iter or []):
        for n in expand_domain_entry(raw):
            if n in accept and n not in seen:
                seen.add(n)
                out.append(n)
    return out


# -----------------------------------------------------------------------------
# Generic Extensions-table parser (shared by AUDIENCES.md / DOMAINS.md / future)
# -----------------------------------------------------------------------------

_EXTENSIONS_BLOCK_RE = re.compile(
    r"<!-- BEGIN extensions -->(.*?)<!-- END extensions -->", re.DOTALL,
)


def parse_extensions_table(
    path: Path,
    canonical_blacklist: Iterable[str] | None = None,
) -> set[str]:
    """Parse the `<!-- BEGIN extensions --> ... <!-- END extensions -->` block
    from a registry markdown file (AUDIENCES.md, DOMAINS.md, ...).

    Table shape: `| Name | Added | Status | Purpose | Notes |`. Returns the
    set of NAME values whose Status does not start with `deprecated`. Tolerant
    of missing file or malformed table — returns empty set on any failure.

    `canonical_blacklist` (lower-cased internally) silently rejects any
    extension whose case-folded name equals a canonical-set member —
    enforces the «Extensions cannot be equal to a canonical word
    (case-folded)» rule documented in AUDIENCES.md and DOMAINS.md. The
    canonical row wins; the conflicting extension is dropped at parse
    time without surfacing — owner notices missing acceptance and
    renames to a non-conflicting form.

    Single source of truth — older lint / emit helpers carry their own
    near-identical implementations and may migrate to this when their
    callers are next touched.
    """
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    m = _EXTENSIONS_BLOCK_RE.search(text)
    if not m:
        return set()
    blacklist = {c.lower() for c in (canonical_blacklist or ())}
    out: set[str] = set()
    for line in m.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        if "---" in line:  # table separator row
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        name, _added, status = cells[0], cells[1], cells[2]
        if not name or name.lower() in {"tag", "domain", "name"}:
            continue
        if name.startswith("_(") or name in {"—", "-"}:
            continue
        if status.lower().startswith("deprecated"):
            continue
        if name.lower() in blacklist:
            # Reserved-keyword conflict: extension matches canonical
            # case-folded. Doc contract is silent-drop; canonical wins.
            continue
        out.add(name)
    return out


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
    # Normalise domain before enum check so `ai_interaction` (snake) and
    # `AI-Interaction` (mixed case) are accepted as their canonical
    # `ai-interaction`. The normalised value is written back to the
    # frontmatter dict so downstream consumers (Principle.domain, id-prefix
    # check below, manifest emit) see the canonical form. None on
    # irrecoverable shape falls through to check_enum which raises with the
    # raw value — keeps error messages truthful about what owner wrote.
    norm_domain = normalize_domain(fm["domain"])
    if norm_domain is not None and norm_domain in ALLOWED_DOMAINS:
        fm["domain"] = norm_domain
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
# Reprocess-corpus selection (deterministic substrate for /ztn:process §2.1)
# -----------------------------------------------------------------------------

# Roots walked by `/ztn:process --reprocess-corpus`. Keep aligned with the
# SKILL spec's §2.1 reprocess-corpus branch: records cover transcript-grounded
# logs, knowledge covers PARA layers (4_archive intentionally excluded — history
# is not rewritten).
REPROCESS_CORPUS_ROOTS: dict[str, tuple[str, ...]] = {
    "records": ("_records/meetings", "_records/observations"),
    "knowledge": ("1_projects", "2_areas", "3_resources"),
}

REPROCESS_CORPUS_LAYERS: frozenset[str] = frozenset({"record", "knowledge"})


# -----------------------------------------------------------------------------
# Action Hints — lens emission contract (consumed by /ztn:resolve-clarifications)
# -----------------------------------------------------------------------------
#
# Lenses MAY append an `## Action Hints` trailer to their output file,
# proposing structural changes (wikilink_add, hub_stub_create, ...). The
# resolver ingests these hints, judges with full owner context, and either
# auto-applies (when precedent + constitution + safety align) or queues
# for owner review. See `integrations/claude-code/skills/
# ztn-resolve-clarifications/SKILL.md` for the consumer side.
#
# Whitelist enforcement happens at resolver Step 2, not at lens emission.
# Lenses propose freely; non-whitelisted types are routed to clarifications
# with «type X is not currently auto-applicable; owner review required».

ACTION_HINT_TYPES: frozenset[str] = frozenset({
    "wikilink_add",
    "hub_stub_create",
    "open_thread_add",
    "decision_update_section",
})

ACTION_HINT_CONFIDENCES: frozenset[str] = frozenset({"low", "medium", "high"})

# Per-type required `params` fields. Resolver's stale pre-check + handlers
# rely on these. Missing fields → hint is dropped at parse with a reason.
ACTION_HINT_REQUIRED_PARAMS: dict[str, frozenset[str]] = {
    "wikilink_add": frozenset({"note_a", "note_b"}),
    "hub_stub_create": frozenset({"suggested_slug", "cited_notes"}),
    "open_thread_add": frozenset({"thread_title", "cited_records"}),
    "decision_update_section": frozenset({"decision_note_path", "update_reason"}),
}


_ACTION_HINTS_HEADER_RE = re.compile(
    r"^##\s+Action\s+Hints\s*$", re.MULTILINE | re.IGNORECASE
)


def extract_action_hints_block(body: str) -> str | None:
    """Return the YAML body inside an `## Action Hints` section, or None.

    The block runs from the line after the header to either the next
    `## ` heading at column 0 or EOF. Returns the YAML text trimmed of
    leading/trailing blank lines. None when no `## Action Hints` header
    is present.
    """
    if not body:
        return None
    m = _ACTION_HINTS_HEADER_RE.search(body)
    if m is None:
        return None
    start = m.end()
    rest = body[start:]
    # Find next top-level `## ` heading (NOT `### ` or deeper).
    next_heading = re.search(r"\n##\s+(?!#)", rest)
    block = rest[: next_heading.start()] if next_heading else rest
    return block.strip("\n")


@dataclass(frozen=True)
class ActionHint:
    """One parsed Action Hint emitted by a lens.

    `raw_index` is the 0-based position inside the lens file's `## Action
    Hints` list — used for traceability when a hint is dropped or queued.
    """
    type: str
    params: dict
    confidence: str
    brief_reasoning: str
    raw_index: int


def parse_action_hints(body: str) -> tuple[list[ActionHint], list[dict]]:
    """Parse `## Action Hints` trailer into structured hints.

    Returns `(hints, drops)`:
      - `hints`: well-formed `ActionHint` instances (type whitelisted,
        confidence valid, required params present)
      - `drops`: list of `{raw_index, reason, raw}` for malformed entries

    Deterministic — no LLM. PyYAML strict load. Tolerant of missing
    section (returns `([], [])`). Caller logs drops.
    """
    block = extract_action_hints_block(body)
    if block is None or not block.strip():
        return ([], [])

    try:
        parsed = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        return ([], [{"raw_index": -1, "reason": f"yaml-parse-error: {exc}", "raw": block}])

    if not isinstance(parsed, list):
        return ([], [{"raw_index": -1, "reason": "expected-yaml-list", "raw": block}])

    hints: list[ActionHint] = []
    drops: list[dict] = []
    for idx, raw in enumerate(parsed):
        if not isinstance(raw, dict):
            drops.append({"raw_index": idx, "reason": "entry-not-mapping", "raw": raw})
            continue
        hint_type = raw.get("type")
        params = raw.get("params")
        confidence = raw.get("confidence")
        brief = raw.get("brief_reasoning")
        if not isinstance(hint_type, str) or not hint_type:
            drops.append({"raw_index": idx, "reason": "missing-type", "raw": raw})
            continue
        if hint_type not in ACTION_HINT_TYPES:
            drops.append({"raw_index": idx, "reason": f"type-not-whitelisted:{hint_type}", "raw": raw})
            continue
        if not isinstance(params, dict):
            drops.append({"raw_index": idx, "reason": "missing-params-mapping", "raw": raw})
            continue
        required = ACTION_HINT_REQUIRED_PARAMS[hint_type]
        missing = [k for k in required if k not in params]
        if missing:
            drops.append({"raw_index": idx, "reason": f"missing-params:{','.join(missing)}", "raw": raw})
            continue
        if confidence not in ACTION_HINT_CONFIDENCES:
            drops.append({"raw_index": idx, "reason": f"bad-confidence:{confidence}", "raw": raw})
            continue
        if not isinstance(brief, str) or not brief.strip():
            drops.append({"raw_index": idx, "reason": "missing-brief-reasoning", "raw": raw})
            continue
        hints.append(ActionHint(
            type=hint_type,
            params=params,
            confidence=confidence,
            brief_reasoning=brief.strip(),
            raw_index=idx,
        ))
    return (hints, drops)

_FILENAME_DATE_PREFIX_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-")


def _reprocess_created_key(fm: dict, filename: str) -> str:
    """Sort key for reprocess-corpus selection.

    Prefer YAML `created:` (string or date object); fall back to filename
    `YYYYMMDD-` prefix; last resort `9999-99-99` so files without any
    extractable date sort to the end without crashing.
    """
    raw = fm.get("created")
    if isinstance(raw, (date, datetime)):
        return raw.isoformat()[:10]
    if isinstance(raw, str) and raw:
        return raw[:10]
    m = _FILENAME_DATE_PREFIX_RE.match(filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "9999-99-99"


def select_reprocess_corpus_files(
    base: Path | str,
    scope: str = "all",
    limit: int | None = None,
) -> list[Path]:
    """Return chronologically-sorted corpus files for `--reprocess-corpus`.

    Walks the roots determined by `scope`, keeps files whose YAML
    frontmatter declares `layer:` ∈ {`record`, `knowledge`}, sorts by
    `created:` (filename `YYYYMMDD-` prefix as fallback), then truncates
    to the first `limit` entries when `limit` is non-negative.

    scope:
        ``records``   — `_records/meetings/`, `_records/observations/`
        ``knowledge`` — `1_projects/`, `2_areas/`, `3_resources/`
        ``all``       — both (default)

    limit:
        ``None`` or negative → no truncation (full list)
        ``0``                → empty list (explicit no-op)
        ``N >= len(files)``  → full list

    `base` is the zettelkasten root (typically `repo_root()`).

    Implementation notes: deterministic, no LLM. Matches §2.1 reprocess-
    corpus branch of `/ztn:process` SKILL spec. Exposed so that the
    orchestrator can shell out for a single source-of-truth file list
    instead of reimplementing the walk per invocation.
    """
    if scope not in REPROCESS_CORPUS_ROOTS and scope != "all":
        raise ValueError(
            f"unknown scope {scope!r}; expected 'records', 'knowledge', or 'all'"
        )
    base = Path(base)
    if scope == "all":
        roots = REPROCESS_CORPUS_ROOTS["records"] + REPROCESS_CORPUS_ROOTS["knowledge"]
    else:
        roots = REPROCESS_CORPUS_ROOTS[scope]

    entries: list[tuple[str, str, Path]] = []
    for rel in roots:
        root = base / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if not path.is_file():
                continue
            parsed = read_frontmatter(path)
            if parsed is None:
                continue
            fm, _body = parsed
            if fm.get("layer") not in REPROCESS_CORPUS_LAYERS:
                continue
            entries.append((_reprocess_created_key(fm, path.name), path.name, path))

    entries.sort(key=lambda e: (e[0], e[1]))
    files = [e[2] for e in entries]

    if limit is not None and limit >= 0:
        files = files[:limit]
    return files


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
