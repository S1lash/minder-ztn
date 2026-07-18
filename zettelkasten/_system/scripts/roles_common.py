#!/usr/bin/env python3
"""Shared foundation for the Roles subsystem.

Every other roles module (`minder_query`, `roles_persist`,
`roles_archetype_*`, `render_roles_registry`) imports from here. This module
owns the archetype-agnostic primitives — it NEVER names a concrete archetype.

Provides:
  - shared dataclasses: `ValidationResult`, `IdentityResult`,
    `ClarificationSignal`, `RemitSpec`, `PartSpec`, `RoleConfig`, `RunRecord`
  - composite config loader + validator: a role is an ordered list of `parts`,
    each `{id, kind}` (fail-closed on malformed operational schema; every
    `part.kind` must resolve to a plugin via `import_archetype`; remit
    fail-closes to empty). There is NO scalar-archetype path.
  - remit model (`parse_remit`) consumed by `minder_query`
  - per-part key minter (`KeyMinter`) — stable, monotonic `lk-NNNN` keys minted
    in each part's OWN namespace from the part plugin's `known_key_numbers`
    hook, so composite roles never collide and a retired key is never reused
  - delta-payload v2 envelope contract + the `delta_part` accessor (routing to
    each part's plugin lives in `roles_persist`)
  - conformant CLARIFICATION emitter (SYSTEM_CONFIG item-format contract)
  - runs index + human log writers (`roles-runs.jsonl` + `log_roles.md`)
  - `is_due` cadence semantics mirroring AGENT_LENSES
  - dynamic part-plugin loader (`import_archetype`) — loads a plugin by its
    `kind`; never hardcodes a concrete kind

Deterministic, no LLM. PyYAML is the single external dependency (via `_common`).
Cross-platform: `pathlib`, atomic writes (`.tmp` + `Path.replace`), reads via
universal-newline `read_text`, writes forced to LF.
"""

from __future__ import annotations

import importlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from _common import (
    now_iso_utc,
    state_dir,
    system_dir,
    today_iso,
)


# -----------------------------------------------------------------------------
# Enums / canonical vocabularies
# -----------------------------------------------------------------------------

ROLES_CADENCES: frozenset[str] = frozenset({"daily", "weekly", "biweekly", "monthly"})
ROLES_STATUSES: frozenset[str] = frozenset({"active", "paused"})
PERSONA_STANCES: frozenset[str] = frozenset({"inherit", "own", "counter"})
PERSONA_AXES: tuple[str, ...] = ("voice", "values", "worldview", "tempo")

# run-index schema (§3.5)
ROLES_RUN_STATUSES: frozenset[str] = frozenset(
    {"ok", "empty", "rejected", "error", "paused"}
)
# last_run for cadence = latest entry with a status in this set
ROLES_SUCCESS_STATUSES: frozenset[str] = frozenset({"ok", "empty"})
ROLES_HOOKS: frozenset[str] = frozenset({"tick", "ask"})

# CLARIFICATION types this subsystem is allowed to raise (§3.7). Canonical —
# registered append-only in SYSTEM_CONFIG. An emit with any other type is a
# programming error and is refused (surface, don't guess).
ROLE_CLARIFICATION_TYPES: frozenset[str] = frozenset({
    "role-cold-start",
    "role-new-key",
    "role-churn-guard",
    "role-identity-suggest",
    "role-auto-paused",
    "role-schema-version",
    "role-unroutable",
    "role-remit-changed",
    "role-nudge",
    "role-orphaned-part",
    "role-owner-confirm",
})

# A role's proactive voice (emission). A tick may surface a bounded, grounded nudge
# — the coach's push, the PM's «that workstream is what's blocking three others»,
# «что горит» — as an owner-facing `role-nudge` CLARIFICATION. It is ALWAYS HITL
# (origin role:{id} is non-personal; a nudge is never auto-applied — it only
# surfaces for the owner) and it never writes a canonical note. Anti-salami: a role
# may hold at most this many OPEN nudges at once — beyond it, new nudges defer
# rather than pile up an unread backlog (the cumulative budget).
ROLE_NUDGE_OPEN_BUDGET = 3

# anchor kinds — honest identity anchors onto real Minder ids (§3.1 / §4).
ANCHOR_KINDS: frozenset[str] = frozenset({"project", "note", "decision"})

# Grounding oracles a schema-bearing part may declare in config. Three are built:
#   - `records` — every op cites a real in-remit record (the engine-injected
#     `read_records` corpus). The default and the floor.
#   - `owner-confirm` — grounds a role-proposed fact in an owner HITL-confirm (the
#     engine-authored anchor): a record-cited op writes; an UNCITED op is never
#     auto-written — it surfaces a `role-owner-confirm` CLARIFICATION for the owner
#     to ratify.
#   - `values` — grounds an argued position in the owner's OWN constitution: a
#     position cites principle-ids, checked against an engine-VERIFIED oracle (the
#     runner computes it out-of-band via `/ztn:check-decision --dry_run` and verifies
#     each id against `0_constitution/`, then injects it as `payload["values_oracle"]`).
#     A body cannot forge a principle that is not in the tree. No oracle → fail-closed.
# `external` (a tool-pull) stays a designed Layer-2 seam. The config loader fail-closes
# on any other value so an unsupported mode never silently degrades to records.
PART_GROUNDING_MODES: frozenset[str] = frozenset({"records", "owner-confirm", "values"})

# Weekday name → Python `date.weekday()` index (Monday = 0).
WEEKDAY_NUM: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHLY_ANCHOR_MAX = 28  # values > 28 clamp to 28 (cadence semantics)

_KEY_RE = re.compile(r"^lk-(\d+)$")
_ROLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# A part id is the same slug shape as a role id (kebab, lowercase). Aliased so
# the intent is explicit without duplicating the pattern (one SoT for the shape).
_PART_ID_RE = _ROLE_ID_RE
_ARCHETYPE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESOLVED_WORD_RE = re.compile(r"\bresolved\b", re.IGNORECASE)

# Default hook paths (§2) — used when config omits them. Not a guess: the
# canonical per-instance layout is `hooks/{tick,ask}.md`.
DEFAULT_HOOKS: dict[str, str] = {"tick": "hooks/tick.md", "ask": "hooks/ask.md"}


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------

class RoleError(Exception):
    """Base error for the Roles subsystem. Callers catch and skip/log."""


class RoleConfigError(RoleError):
    """`config.yml` missing or structurally invalid (fail-closed → skip role)."""


class RoleArchetypeError(RoleError):
    """Archetype plugin cannot be loaded / named unsafely."""


class RoleClarificationError(RoleError):
    """A CLARIFICATION emit request violates the item-format contract."""


# -----------------------------------------------------------------------------
# Paths (resolved relative to repo root; ZTN_BASE honoured via _common)
# -----------------------------------------------------------------------------

def roles_dir(base: Path | None = None) -> Path:
    return system_dir(base) / "roles"


def role_dir(role_id: str, base: Path | None = None) -> Path:
    return roles_dir(base) / role_id


def role_config_path(role_id: str, base: Path | None = None) -> Path:
    return role_dir(role_id, base) / "config.yml"


def parts_dir(role_id: str, base: Path | None = None) -> Path:
    return role_dir(role_id, base) / "parts"


def part_state_path(role_id: str, part_id: str, base: Path | None = None) -> Path:
    """Per-part state file (§5) — each part owns its own file (SRP).

    e.g. `_system/roles/{role_id}/parts/{part_id}.json`. The composite role
    keeps one file per part rather than a single blob, so a per-part validator /
    render / hash operates on its own coherent unit.
    """
    return parts_dir(role_id, base) / f"{part_id}.json"


def role_brief_path(cfg: "RoleConfig", base: Path | None = None) -> Path | None:
    """Absolute path to the role's owner-plane brief, or None when unset (§5).

    `cfg.brief` is an optional owner-sovereign path relative to the role dir; the
    engine READS it as labelled STEER input into the tick and NEVER writes it.
    """
    if not cfg.brief:
        return None
    return role_dir(cfg.id, base) / cfg.brief


def clarifications_path(base: Path | None = None) -> Path:
    return state_dir(base) / "CLARIFICATIONS.md"


def roles_runs_path(base: Path | None = None) -> Path:
    return state_dir(base) / "roles-runs.jsonl"


def roles_log_path(base: Path | None = None) -> Path:
    return state_dir(base) / "log_roles.md"


def discover_role_ids(base: Path | None = None) -> list[str]:
    """Return sorted role ids — instance dirs holding a `config.yml`.

    `_`-prefixed entries (e.g. `_frame.md`) are engine files, not roles, and
    are skipped.
    """
    rdir = roles_dir(base)
    if not rdir.is_dir():
        return []
    out: list[str] = []
    for child in sorted(rdir.iterdir()):
        if child.name.startswith("_"):
            continue
        if child.is_dir() and (child / "config.yml").is_file():
            out.append(child.name)
    return out


# -----------------------------------------------------------------------------
# Anchor helpers (shared schema — §3.1 `anchor`)
# -----------------------------------------------------------------------------

def parse_anchor(anchor: Any) -> tuple[str, str] | None:
    """Split `kind:value` into `(kind, value)` when kind is a valid anchor
    kind and value is non-empty; else None. `null`/None/empty → None.
    """
    if not isinstance(anchor, str):
        return None
    s = anchor.strip()
    if not s or ":" not in s:
        return None
    kind, value = s.split(":", 1)
    kind = kind.strip()
    value = value.strip()
    if kind not in ANCHOR_KINDS or not value:
        return None
    return kind, value


def is_valid_anchor(anchor: Any) -> bool:
    """True when `anchor` is a well-formed `kind:value` for a known kind."""
    return parse_anchor(anchor) is not None


# -----------------------------------------------------------------------------
# Record-ref normalisation (single home — §11.11)
# -----------------------------------------------------------------------------

def normalize_record_ref(raw: str) -> str:
    """Normalise a record reference to its bare basename. The ONE home.

    A record ref surfaces across the subsystem in three forms — a
    `[[wikilink]]`, a bare `name`, or a `name.md` filename — mixed freely in
    provenance lists, evidence refs and read-record grounding. This is the
    single canonical normaliser so every caller compares refs on the same
    footing (persist watermark dedup and the ledger grounding check MUST agree):

      1. strip a surrounding `[[ … ]]` wrapper (both brackets required),
      2. strip a trailing `.md`,
      3. return the stripped stem.

    A degenerate ref — ``""``, ``"[[]]"``, ``"[[   ]]"``, ``".md"`` —
    normalises to the empty string consistently: an empty wrapper carries no
    basename. Callers treat ``""`` as "no usable ref" and drop it.
    """
    s = str(raw).strip()
    if s.startswith("[[") and s.endswith("]]"):
        s = s[2:-2].strip()
    if s.endswith(".md"):
        s = s[:-3]
    return s.strip()


def read_record_corpus(delta_payload: Any) -> set[str]:
    """The set of in-remit record basenames the body may cite this tick.

    The single home for the grounding oracle shared by every `GROUNDING_MODEL =
    "records"` part plugin (ledger, narrative): the normalised `read_records`
    stems the runner injected. Every citation is checked against this set.

    A ref that NORMALISES to the empty string (e.g. `"[[]]"`, `".md"`) names no
    real record and NEVER enters the corpus — the filter is on the normalised
    result, not the raw truthiness, so a degenerate stem cannot become a citation a
    degenerate evidence ref would then match (the grounding oracle must never let a
    ref that resolves to no basename count as present)."""
    raw = delta_payload.get("read_records") if isinstance(delta_payload, dict) else None
    if not isinstance(raw, (list, tuple)):
        return set()
    out: set[str] = set()
    for r in raw:
        if not isinstance(r, str):
            continue
        norm = normalize_record_ref(r)
        if norm:
            out.add(norm)
    return out


def ungrounded_refs(refs: Any, corpus: set[str]) -> list[str]:
    """Return the citations in `refs` absent from `corpus` (grounding failures).

    A non-list `refs` yields a sentinel so the caller rejects it; a blank / non-str
    entry is reported verbatim. A ref that NORMALISES to the empty string (a
    degenerate `"[[]]"` / `".md"` that carries no basename) is reported as missing
    even though its raw form is non-blank — it names no record, so it can never be
    grounded regardless of what the corpus contains. Shared by every records-grounded
    plugin so the grounding check and the persist watermark compare on one footing."""
    if not isinstance(refs, (list, tuple)):
        return ["<not-a-list>"]
    missing: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            missing.append(str(ref))
            continue
        norm = normalize_record_ref(ref)
        if not norm or norm not in corpus:
            missing.append(ref)
    return missing


def grow_provenance(existing: Any, additions: Iterable[str]) -> list[str]:
    """Append-only merge of record refs: keep every existing entry in order, then
    append any addition whose normalised basename is not already present. Never
    shrinks (grows-only).

    The single home for the provenance-merge every records-grounded part plugin
    performs. Refs compare on their `normalize_record_ref` basename, so a
    `[[wikilink]]` and a bare `name.md` for the same record dedup as one and the
    grounding check and the persist watermark agree on one footing (§11.11).
    """
    out: list[str] = []
    seen: set[str] = set()
    for ref in existing if isinstance(existing, list) else []:
        if not isinstance(ref, str):
            continue
        out.append(ref)
        seen.add(normalize_record_ref(ref))
    for ref in additions:
        if not isinstance(ref, str) or not ref.strip():
            continue
        base = normalize_record_ref(ref)
        if base in seen:
            continue
        seen.add(base)
        out.append(ref)
    return out


# -----------------------------------------------------------------------------
# Archetype-agnostic value + state utilities (shared by every part plugin)
# -----------------------------------------------------------------------------
# Small, shape-free helpers the part plugins share — a non-empty-string guard, a
# real-calendar-date check, an evidence-list cleaner, a label truncator, and a
# typed-tunable reader off part state. Homed here (not copied per plugin) so ONE
# definition serves ledger / narrative / registry; none names a concrete kind.

def nonempty_str(value: Any) -> bool:
    """True when `value` is a string with non-whitespace content."""
    return isinstance(value, str) and bool(value.strip())


def is_valid_iso_date(value: Any) -> bool:
    """True when `value` is a REAL calendar date in strict YYYY-MM-DD form.

    A shape-only regex would accept an impossible date like `2026-13-99`; `strptime`
    rejects impossible months/days, so a garbage date never persists or renders. A
    non-string value raises inside `strptime` and is reported False.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def clean_evidence(evidence: Any) -> list[str]:
    """Keep the non-empty string refs of an evidence list, in order."""
    if not isinstance(evidence, (list, tuple)):
        return []
    return [r for r in evidence if isinstance(r, str) and r.strip()]


def truncate(text: str, limit: int = 80) -> str:
    """Trim `text` to `limit` chars, appending a single ellipsis when it overflows."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def read_int_tunable(state: Any, field: str, default: int) -> int:
    """Read an int tunable off `state[field]`, falling back to `default`.

    A part carries per-kind int knobs (e.g. a churn ceiling) in its own state; the
    reading logic — coerce to int, fall back to the caller's default on a missing or
    non-numeric value — is archetype-agnostic and homed here. Each plugin supplies
    its own field name + DEFAULT constant, so per-kind config stays in the plugin.
    """
    if isinstance(state, dict):
        try:
            return int(state.get(field, default))
        except (TypeError, ValueError):
            return default
    return default


# -----------------------------------------------------------------------------
# Shared dataclasses
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class IdentityResult:
    """Outcome of `archetype.identity(item, anchors)`.

    Either the item anchors onto a real Minder id (`anchored=True`,
    `anchor="project:minder"|"note:{id}"|"decision:{path}"`), or the anchor is
    ambiguous and the decision must go to the owner (`needs_hitl=True`) — never
    guessed. `reason` carries a short human explanation for the HITL path.
    """
    anchored: bool
    anchor: str | None = None
    needs_hitl: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ClarificationSignal:
    """A validator/persist request for one CLARIFICATION block.

    `ctype` MUST be a member of `ROLE_CLARIFICATION_TYPES`. Bundled inside a
    `ValidationResult` and emitted by the caller via `emit_clarification_signal`.
    """
    ctype: str
    subject: str
    context: str
    source: str
    suggested_action: str
    action_taken: str
    title_hint: str = ""
    confidence_tier: str = "surfaced"
    quote: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of `archetype.validate(prior_state, delta_payload)`.

    Neutral container filled by the archetype plugin; consumed by
    `roles_persist`. `ok` is the go/no-go for persisting `approved_deltas`.
    `rejections` are `{"ref": <provisional_key|key|op>, "reason": str}` records
    (feed reject counting + the auto-pause counter). `clarifications` are the
    HITL signals the persist stage emits before/instead of writing.
    """
    ok: bool
    approved_deltas: tuple[dict, ...] = ()
    rejections: tuple[dict, ...] = ()
    clarifications: tuple[ClarificationSignal, ...] = ()

    @staticmethod
    def accepted(
        approved_deltas: Iterable[dict] = (),
        clarifications: Iterable[ClarificationSignal] = (),
    ) -> "ValidationResult":
        return ValidationResult(
            ok=True,
            approved_deltas=tuple(approved_deltas),
            clarifications=tuple(clarifications),
        )

    @staticmethod
    def rejected(
        rejections: Iterable[dict] = (),
        clarifications: Iterable[ClarificationSignal] = (),
    ) -> "ValidationResult":
        return ValidationResult(
            ok=False,
            rejections=tuple(rejections),
            clarifications=tuple(clarifications),
        )


@dataclass(frozen=True)
class RemitSpec:
    """Resolved remit (§3.3 `remit`) — the allow-list `minder_query` reads.

    All list axes are tuples of strings. `all=True` widens the corpus to the
    whole base (incl. sensitive) — an explicit owner choice. `decision_notes`
    folds `type:decision` notes into the corpus. A remit that resolves empty
    matches nothing (fail-closed default).
    """
    globs: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()
    person_ids: tuple[str, ...] = ()
    hubs: tuple[str, ...] = ()
    decision_notes: bool = False
    all: bool = False

    @property
    def is_empty(self) -> bool:
        return not (
            self.globs
            or self.tags
            or self.project_ids
            or self.person_ids
            or self.hubs
            or self.decision_notes
            or self.all
        )


@dataclass(frozen=True)
class PartSpec:
    """One entry in a role's ordered `parts` list (BUILD-CONTRACT §1).

    `id` is unique within the role and names both the part's state file
    (`parts/{id}.json`) and its state.md AUTO sub-zone. `kind` is the archetype
    plugin backing the part, loaded via `import_archetype(kind)`; the loader
    fail-closes when a kind does not resolve to an installed plugin.

    A schema-bearing kind (a registry — one that exports `REQUIRES_SCHEMA = True`)
    additionally carries the owner-declared shape: `schema` is the canonical
    `{key, fields, append_only, grounding, grounding_check}` dict the plugin reads
    to drive all behaviour (shape lives in DATA, not code), and `grounding` /
    `append_only` / `grounding_check` are lifted out as convenience mirrors of the
    same schema values for the writer's grounding-mode routing. A kind that needs no
    schema (ledger / narrative) carries an empty `schema` and the plain defaults, so
    its PartSpec — and its behaviour — is unchanged. `field(default_factory=dict)` is
    a frozen-safe default (the mutable dict is built per instance, never shared).
    """
    id: str
    kind: str
    schema: dict = field(default_factory=dict)
    grounding: str = "records"
    append_only: bool = False
    grounding_check: bool = False


@dataclass
class RoleConfig:
    """Parsed, validated `config.yml` (§3.3). Owner-sovereign — treated as
    read-only by convention (the engine never self-edits identity).

    A role's state is a COMPOSITE of `parts` (ordered `PartSpec` list) — the
    scalar-archetype model is gone. `brief` is an optional owner-plane path the
    engine reads as STEER and never writes.

    Not frozen: `persona`, `hooks`, `activation` are plain dicts and a frozen
    dataclass carrying unhashable fields is a latent footgun; immutability here
    is a discipline, not a lock.
    """
    id: str
    parts: tuple[PartSpec, ...]
    remit: RemitSpec
    hooks: dict
    persona: dict
    cadence: str
    cadence_anchor: Any
    activation: dict
    status: str
    schema_version: int
    name: str = ""
    brief: str | None = None
    path: Path | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def part_ids(self) -> tuple[str, ...]:
        """The part ids in declared order — the state.md sub-zone order."""
        return tuple(p.id for p in self.parts)


@dataclass(frozen=True)
class RunRecord:
    """One `roles-runs.jsonl` entry (§3.5)."""
    role_id: str
    run_at: str
    status: str
    hook: str
    counts: dict

    def to_dict(self) -> dict:
        return {
            "role_id": self.role_id,
            "run_at": self.run_at,
            "status": self.status,
            "hook": self.hook,
            "counts": normalise_run_counts(self.counts),
        }


def make_run_counts(
    added: int = 0,
    advanced: int = 0,
    clarifications: int = 0,
    rejected: int = 0,
) -> dict:
    """Build the `counts` sub-object with the fixed §3.5 key set."""
    return {
        "added": int(added),
        "advanced": int(advanced),
        "clarifications": int(clarifications),
        "rejected": int(rejected),
    }


def normalise_run_counts(counts: Any) -> dict:
    """Coerce arbitrary input into the fixed `counts` shape (missing → 0)."""
    src = counts if isinstance(counts, dict) else {}
    return make_run_counts(
        added=_as_int(src.get("added")),
        advanced=_as_int(src.get("advanced")),
        clarifications=_as_int(src.get("clarifications")),
        rejected=_as_int(src.get("rejected")),
    )


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# -----------------------------------------------------------------------------
# Remit model
# -----------------------------------------------------------------------------

def parse_remit(raw: Any) -> RemitSpec:
    """Parse the `remit` block into a `RemitSpec`. Fail-closed.

    Anything malformed (not a mapping, wrong types) degrades to an EMPTY remit
    that matches nothing — never a broad or guessed scope. `all` and
    `decision_notes` coerce to bool; list axes keep only non-empty strings,
    de-duplicated in first-seen order.
    """
    if not isinstance(raw, dict):
        return RemitSpec()
    return RemitSpec(
        globs=_str_tuple(raw.get("globs")),
        tags=_str_tuple(raw.get("tags")),
        project_ids=_str_tuple(raw.get("project_ids")),
        person_ids=_str_tuple(raw.get("person_ids")),
        hubs=_str_tuple(raw.get("hubs")),
        decision_notes=bool(raw.get("decision_notes", False)),
        all=bool(raw.get("all", False)),
    )


def as_str_list(raw: Any) -> list[str]:
    """Coerce input into a list of non-empty stripped strings, de-duplicated in
    first-seen order. Non-list/tuple input → empty list. Single home for
    string-list coercion — `parse_remit` / `_str_tuple` (and `minder_query`)
    all route through here rather than re-implementing the strip/dedup logic.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(as_str_list(value))


# -----------------------------------------------------------------------------
# Config loader + validator
# -----------------------------------------------------------------------------

def load_role_config(role_id: str, base: Path | None = None) -> RoleConfig:
    """Load + validate `_system/roles/{role_id}/config.yml`.

    Raises `RoleConfigError` on any operational-schema violation (fail-closed —
    the tick orchestrator skips the role and logs an `error` run). The config's
    own `id` field must match `role_id`.
    """
    path = role_config_path(role_id, base)
    cfg = load_role_config_file(path)
    if cfg.id != role_id:
        raise RoleConfigError(
            f"{path}: config id {cfg.id!r} does not match directory {role_id!r}"
        )
    return cfg


def load_role_config_file(path: Path) -> RoleConfig:
    """Load + validate a `config.yml` from an explicit path."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RoleConfigError(f"{path}: cannot read config ({exc})") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RoleConfigError(f"{path}: YAML parse error — {exc}") from exc
    if not isinstance(raw, dict):
        raise RoleConfigError(
            f"{path}: config root must be a mapping, got "
            f"{type(raw).__name__}"
        )
    return _build_role_config(raw, path)


def _build_role_config(raw: dict, path: Path) -> RoleConfig:
    role_id = raw.get("id")
    if not isinstance(role_id, str) or not _ROLE_ID_RE.match(role_id):
        raise RoleConfigError(
            f"{path}: 'id' must be a lowercase slug (a-z, 0-9, '-'), "
            f"got {role_id!r}"
        )

    parts = _parse_parts(raw.get("parts"), raw.get("archetype"), path)

    cadence = raw.get("cadence")
    if cadence not in ROLES_CADENCES:
        raise RoleConfigError(
            f"{path}: 'cadence' must be one of {sorted(ROLES_CADENCES)}, "
            f"got {cadence!r}"
        )

    cadence_anchor = _validate_anchor_for_cadence(
        path, cadence, raw.get("cadence_anchor")
    )

    status = raw.get("status", "active")
    if status not in ROLES_STATUSES:
        raise RoleConfigError(
            f"{path}: 'status' must be one of {sorted(ROLES_STATUSES)}, "
            f"got {status!r}"
        )

    schema_version = raw.get("schema_version", 2)
    try:
        schema_version = int(schema_version)
    except (TypeError, ValueError):
        raise RoleConfigError(
            f"{path}: 'schema_version' must be an integer, "
            f"got {schema_version!r}"
        )

    hooks = _coerce_hooks(raw.get("hooks"))
    persona = _coerce_persona(raw.get("persona"))
    activation = _coerce_activation(raw.get("activation"))
    remit = parse_remit(raw.get("remit"))

    name = raw.get("name")
    name = name.strip() if isinstance(name, str) else ""

    raw_brief = raw.get("brief")
    brief = raw_brief.strip() if isinstance(raw_brief, str) and raw_brief.strip() else None

    return RoleConfig(
        id=role_id,
        parts=parts,
        remit=remit,
        hooks=hooks,
        persona=persona,
        cadence=cadence,
        cadence_anchor=cadence_anchor,
        activation=activation,
        status=status,
        schema_version=schema_version,
        name=name,
        brief=brief,
        path=path,
    )


def _parse_parts(
    raw_parts: Any, raw_archetype: Any, path: Path
) -> tuple[PartSpec, ...]:
    """Parse the ordered `parts` list into validated `PartSpec`s. Fail-closed.

    A role's state is a composite of parts, each `{id, kind}`. `id` is unique
    within the role; `kind` must resolve to an installed plugin via
    `import_archetype` (fail-closed — an unknown kind is a config error, never a
    silently-skipped part). Declared order is preserved (it drives the state.md
    sub-zone order and cold-start staging order).

    There is NO scalar-archetype fallback: a v1 `archetype:` config is invalid.
    When `parts` is absent but a scalar `archetype` is present, the error names
    the removed field and shows the composite replacement (a clear rebuild
    pointer, not a silent coercion).
    """
    if not isinstance(raw_parts, list) or not raw_parts:
        if raw_archetype is not None:
            raise RoleConfigError(
                f"{path}: the scalar 'archetype' field is removed — roles are "
                "composite now. Declare 'parts' as an ordered list of "
                "{id, kind}, e.g. "
                f"'parts: [{{id: workstreams, kind: {raw_archetype!r}}}]'."
            )
        raise RoleConfigError(
            f"{path}: 'parts' must be a non-empty list of {{id, kind}} entries"
        )

    specs: list[PartSpec] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_parts):
        if not isinstance(entry, dict):
            raise RoleConfigError(
                f"{path}: parts[{idx}] must be a mapping with 'id' and 'kind', "
                f"got {type(entry).__name__}"
            )
        pid = entry.get("id")
        if not isinstance(pid, str) or not _PART_ID_RE.match(pid):
            raise RoleConfigError(
                f"{path}: parts[{idx}].id must be a lowercase slug "
                f"(a-z, 0-9, '-'), got {pid!r}"
            )
        if pid in seen_ids:
            raise RoleConfigError(
                f"{path}: duplicate part id {pid!r} — part ids must be unique "
                "within a role"
            )
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise RoleConfigError(
                f"{path}: parts[{idx}].kind must be a non-empty string, "
                f"got {kind!r}"
            )
        kind = kind.strip()
        # Fail-closed: the kind must resolve to a real plugin now, not at first
        # tick. import_archetype validates the name shape AND the module's
        # presence, so an unsafe or missing kind is caught at load.
        try:
            plugin = import_archetype(kind)
        except RoleArchetypeError as exc:
            raise RoleConfigError(
                f"{path}: part {pid!r} kind {kind!r} does not resolve to a "
                f"plugin ({exc})"
            ) from exc
        schema, grounding, append_only, grounding_check = _parse_part_schema(
            entry.get("schema"), plugin, pid, path
        )
        seen_ids.add(pid)
        specs.append(PartSpec(
            id=pid, kind=kind, schema=schema, grounding=grounding,
            append_only=append_only, grounding_check=grounding_check,
        ))

    # Cross-part validation — a schema-bearing kind whose schema REFERENCES another
    # part (e.g. an assessment's `over: <sibling>`) can only be checked once EVERY part
    # id is known, so it runs as a second pass here. A plugin that needs it exports
    # `validate_cross_part(schema, sibling_part_ids) -> None`; the loader calls it only
    # when present (default-absent on the other kinds), passes the part's SIBLING ids
    # (every other part in the role, self excluded — a part cannot reference itself),
    # and locates any `RoleConfigError` to `{path}: part {pid!r}` — the SAME
    # archetype-agnostic dispatch pattern as `_parse_part_schema`'s `validate_schema`
    # (the 17th interface concern; the loader names no kind, the plugin owns the check).
    all_part_ids = {s.id for s in specs}
    for spec in specs:
        cross = getattr(import_archetype(spec.kind), "validate_cross_part", None)
        if not callable(cross):
            continue
        try:
            cross(spec.schema, all_part_ids - {spec.id})
        except RoleConfigError as exc:
            raise RoleConfigError(f"{path}: part {spec.id!r} {exc}") from exc
    return tuple(specs)


def _parse_part_schema(
    raw: Any, plugin: Any, pid: str, path: Path
) -> tuple[dict, str, bool, bool]:
    """Dispatch a parts[] entry's optional `schema:` block to its plugin. Fail-closed.

    Archetype-agnostic — this loader names no concrete kind and inspects no schema
    shape. A schema-bearing kind (one whose plugin exports `REQUIRES_SCHEMA = True`)
    OWNS its schema contract behind the `validate_schema(raw) -> dict` hook, which
    returns the canonical schema dict or raises `RoleConfigError` on malformed input.
    The loader only DISPATCHES to that hook and locates any error to
    `{path}: part {pid!r}` (the hook's message carries the shape detail, no path/id),
    so a future kind with a different schema shape (`{metrics: [...]}`,
    `{over: ..., verdicts: [...]}`, …) needs no change here.

    A kind that needs no schema (ledger / narrative — no `REQUIRES_SCHEMA`) ignores any
    schema block and gets the defaults `({}, "records", False, False)`, leaving its
    PartSpec — and behaviour — unchanged.

    Returns `(schema, grounding, append_only, grounding_check)`: `schema` is the
    plugin's canonical dict; the trailing three are the PartSpec convenience mirrors
    lifted off that dict (each defaulting when the kind's schema does not declare it)
    for the writer's grounding-mode routing.

    Sibling: a schema that references ANOTHER part (an assessment's `over: <sibling>`)
    cannot be checked here — this hook sees one part's block, not the sibling ids. That
    CROSS-part existence check runs as a second pass in `_parse_parts` once every part
    is parsed, via the optional `plugin.validate_cross_part(schema, sibling_part_ids)`
    hook (the 17th interface concern), dispatched the same archetype-agnostic way.
    """
    if not bool(getattr(plugin, "REQUIRES_SCHEMA", False)):
        return {}, "records", False, False
    try:
        schema = plugin.validate_schema(raw)
    except RoleConfigError as exc:
        raise RoleConfigError(f"{path}: part {pid!r} {exc}") from exc
    grounding = schema.get("grounding", "records")
    append_only = bool(schema.get("append_only", False))
    grounding_check = bool(schema.get("grounding_check", False))
    return schema, grounding, append_only, grounding_check


def _validate_anchor_for_cadence(path: Path, cadence: str, raw_anchor: Any) -> Any:
    """Validate `cadence_anchor` against `cadence`; return the normalised anchor.

    - daily → anchor ignored (normalised to "daily")
    - weekly / biweekly → a weekday name (lowercased)
    - monthly → int in 1..28 (values > 28 clamp to 28; digit-strings coerced)
    Raises `RoleConfigError` on a clearly-invalid anchor (surface, don't guess).
    """
    if cadence == "daily":
        return "daily"
    if cadence in ("weekly", "biweekly"):
        if not isinstance(raw_anchor, str):
            raise RoleConfigError(
                f"{path}: '{cadence}' cadence needs a weekday 'cadence_anchor', "
                f"got {raw_anchor!r}"
            )
        anchor = raw_anchor.strip().lower()
        if anchor not in WEEKDAY_NUM:
            raise RoleConfigError(
                f"{path}: 'cadence_anchor' must be a weekday "
                f"({sorted(WEEKDAY_NUM)}), got {raw_anchor!r}"
            )
        return anchor
    # monthly
    try:
        day = int(raw_anchor)
    except (TypeError, ValueError):
        raise RoleConfigError(
            f"{path}: 'monthly' cadence needs an integer day-of-month "
            f"'cadence_anchor', got {raw_anchor!r}"
        )
    if day < 1:
        raise RoleConfigError(
            f"{path}: 'cadence_anchor' day-of-month must be >= 1, got {day}"
        )
    return min(day, MONTHLY_ANCHOR_MAX)


def _coerce_hooks(raw: Any) -> dict:
    """Return `{tick, ask}` hook paths, defaulting to the canonical layout."""
    hooks = dict(DEFAULT_HOOKS)
    if isinstance(raw, dict):
        for key in ("tick", "ask"):
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                hooks[key] = val.strip()
    return hooks


def _coerce_persona(raw: Any) -> dict:
    """Coerce persona axes to {inherit|own|counter}; unknown → inherit.

    Persona is identity (owner-sovereign); the loader keeps it structurally
    sound without vetoing owner intent. Semantic checks (a `counter` axis
    requiring a `mandate`) belong to the concierge/tick body, not the loader.
    """
    persona: dict = {}
    src = raw if isinstance(raw, dict) else {}
    for axis in PERSONA_AXES:
        val = src.get(axis)
        persona[axis] = val if val in PERSONA_STANCES else "inherit"
    mandate = src.get("mandate")
    if isinstance(mandate, dict):
        persona["mandate"] = mandate
    return persona


def _coerce_activation(raw: Any) -> dict:
    """Return the activation gate with §3.3 defaults filled."""
    src = raw if isinstance(raw, dict) else {}
    by_elapsed_raw = src.get("by_elapsed_time")
    by_elapsed = by_elapsed_raw if isinstance(by_elapsed_raw, dict) else {}
    return {
        "by_change": bool(src.get("by_change", True)),
        "by_elapsed_time": {
            "enabled": bool(by_elapsed.get("enabled", False)),
            "threshold_weeks": by_elapsed.get("threshold_weeks", None),
        },
    }


# -----------------------------------------------------------------------------
# Role reference resolution — STT-tolerant, deterministic, NEVER guesses
# -----------------------------------------------------------------------------
# The owner addresses a role in free speech ("спроси у Руди", "ask my PM role",
# "узнай у роли в зтн") — often via STT, so the reference is a display name, a
# transliteration, or a slightly-garbled token, not the machine id. This resolver
# maps that free text to CANDIDATE roles and ranks them by match quality; it never
# picks one silently. The consuming skill (`ztn:role:ask` / `edit` / `list`)
# surfaces on ambiguity and confirms on a fuzzy match — the resolver only proposes.

# Minimal Cyrillic→Latin transliteration so a Cyrillic display name and its Latin
# id/spelling resolve to each other ("Руди" ↔ "rudi", "Миндер" ↔ "minder"). Not a
# transliteration STANDARD — just the common letters; anything unmapped passes
# through unchanged. Deterministic and ASCII-safe (cross-platform).
_CYRILLIC_TRANSLIT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


@dataclass(frozen=True)
class RoleRef:
    """One candidate a free-text reference resolved to.

    `match` grades the quality: `id-exact` / `name-exact` are certain; `fuzzy` is a
    normalised-substring or single-edit-distance match the caller must CONFIRM
    (never act on a fuzzy match without owner confirmation)."""
    role_id: str
    name: str
    match: str  # "id-exact" | "name-exact" | "fuzzy"

    @property
    def is_exact(self) -> bool:
        return self.match in ("id-exact", "name-exact")


def _translit_cyrillic(text: str) -> str:
    return "".join(_CYRILLIC_TRANSLIT.get(ch, ch) for ch in text)


def normalize_role_ref(text: Any) -> str:
    """Normalise a role reference token for matching: transliterate Cyrillic,
    NFKD-fold diacritics, lowercase, keep only alphanumerics.

    So `"Minder-PM"`, `"minder pm"`, and `"Миндер ПМ"` all normalise to
    `"minderpm"`, and `"Руди"` / `"rudi"` both to `"rudi"`. Dropping dashes /
    spaces / punctuation makes the match robust to how the owner spoke the name.

    A non-string reference is NOT coerced — it returns `""` so the resolver yields
    no candidate (the caller enumerates), never a phantom `str(None)`→`"none"` match.
    Transliteration runs BEFORE NFKD: a precomposed Cyrillic letter (`"й"` = и +
    combining breve) must hit its `_CYRILLIC_TRANSLIT` mapping ("y") rather than
    decompose to a bare `и`→"i" — so the common `-й`/`-y` Russian names
    (Nikolay / Sergey) resolve name-exact across scripts, not fuzzy."""
    if not isinstance(text, str):
        return ""
    s = _translit_cyrillic(text.lower())
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum())


def _edit_distance_within(a: str, b: str, limit: int) -> bool:
    """True when Levenshtein(a, b) <= limit. Deterministic, small-string DP —
    tolerates a single-char STT slip (`"rudy"` ↔ `"rudi"`) without matching
    genuinely different names."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = cur
    return prev[-1] <= limit


def _fuzzy_ref_match(norm_q: str, norm_target: str) -> bool:
    """A fuzzy (confirm-me) match between two normalised tokens.

    Short tokens (< 3 chars) must match exactly (else "a" matches everything);
    otherwise a substring either direction, or a length-scaled edit distance (1 per
    ~4 chars, min 1) — enough for an STT slip, not enough to conflate two roles."""
    if len(norm_q) < 3 or len(norm_target) < 3:
        return norm_q == norm_target
    if norm_q in norm_target or norm_target in norm_q:
        return True
    limit = max(1, min(len(norm_q), len(norm_target)) // 4)
    return _edit_distance_within(norm_q, norm_target, limit)


def resolve_role_reference(text: Any, base: Path | None = None) -> list[RoleRef]:
    """Resolve a free-text role reference to ranked candidate roles.

    Deterministic and STT-tolerant; NEVER guesses — it returns every plausible
    candidate ordered best-first (`id-exact` → `name-exact` → `fuzzy`, then by id),
    and the caller decides: proceed on a lone exact match, CONFIRM on a fuzzy one,
    surface a pick-list on ambiguity, enumerate all roles on an empty / generic
    reference (`"узнай у роли"` normalises to a non-name and yields no match, so the
    caller lists roles). An unreadable role config is skipped, not fatal."""
    norm_q = normalize_role_ref(text)
    if not norm_q:
        return []
    out: list[RoleRef] = []
    for rid in discover_role_ids(base):
        try:
            cfg = load_role_config(rid, base)
        except RoleError:
            continue
        name = cfg.name or rid
        norm_id = normalize_role_ref(rid)
        norm_name = normalize_role_ref(name)
        if norm_q == norm_id:
            out.append(RoleRef(rid, name, "id-exact"))
        elif norm_q == norm_name:
            out.append(RoleRef(rid, name, "name-exact"))
        elif _fuzzy_ref_match(norm_q, norm_id) or _fuzzy_ref_match(norm_q, norm_name):
            out.append(RoleRef(rid, name, "fuzzy"))
    rank = {"id-exact": 0, "name-exact": 1, "fuzzy": 2}
    out.sort(key=lambda r: (rank[r.match], r.role_id))
    return out


# -----------------------------------------------------------------------------
# Key minter — stable, monotonic `lk-NNNN`, never reuses a retired key
# -----------------------------------------------------------------------------

def parse_key_number(key: Any) -> int | None:
    """Return the integer N of an `lk-NNNN` key, else None."""
    m = _KEY_RE.match(str(key)) if key is not None else None
    return int(m.group(1)) if m else None


def format_key(number: int) -> str:
    """Render an `lk-NNNN` key (zero-padded to at least 4 digits)."""
    if number < 1:
        raise ValueError(f"key number must be >= 1, got {number}")
    return f"lk-{number:04d}"


def next_key_number(known_numbers: Iterable[int]) -> int:
    """The next free key number = max known number + 1 (1 when none).

    Archetype-agnostic: takes the numbers a part already holds (the part
    plugin's `known_key_numbers(state)` yields them) rather than scanning any
    concrete state shape. Non-int entries are ignored defensively.
    """
    highest = 0
    for n in known_numbers:
        if isinstance(n, int) and n > highest:
            highest = n
    return highest + 1


class KeyMinter:
    """Mints monotonic `lk-NNNN` keys for one part's persist pass.

    Built once per tick from a PART's prior state via `for_part`, so a batch of
    add-style deltas gets sequential, never-reused keys without re-scanning
    between mints. Keys are minted in the part's OWN namespace — the minter only
    ever sees one part's known numbers — so two parts of the same composite role
    never collide (each part's state file is addressed by `part_id`).
    """

    def __init__(self, start: int) -> None:
        if start < 1:
            raise ValueError(f"minter start must be >= 1, got {start}")
        self._next = start

    @classmethod
    def for_part(cls, plugin, part_state: Any) -> "KeyMinter":
        """Build a minter for `part_state`, seeded past every key the part holds.

        Delegates the state-shape knowledge to the part plugin's
        `known_key_numbers` hook (the common layer never names a concrete
        part-kind), so a retired/superseded key the plugin still reports is
        never re-minted.
        """
        return cls(next_key_number(plugin.known_key_numbers(part_state)))

    def peek(self) -> str:
        """The key the next `mint()` will return, without consuming it."""
        return format_key(self._next)

    def mint(self) -> str:
        key = format_key(self._next)
        self._next += 1
        return key


# -----------------------------------------------------------------------------
# Delta payload v2 — the body → writer contract (BUILD-CONTRACT §4)
# -----------------------------------------------------------------------------
# The tick body emits ONE payload per run; the writer (`roles_persist`) routes
# each delta to its addressed part's plugin. Envelope:
#
#   { "role_id": str,
#     "hook": "tick" | "cold-start",
#     "run_at": "<ISO>",
#     "read_records": ["<record-stem>", ...],   # ENGINE-INJECTED by the runner
#     "deltas": [ { "part": "<part_id>", "op": "<plugin op>", ... }, ... ] }
#
# Every delta carries `part` — the id of the part it addresses. The writer groups
# deltas by part and hands each group to that part's `plugin.validate` /
# `plugin.persist`; grounding is checked per the part plugin's GROUNDING_MODEL.
# `read_records` is a SHARED grounding corpus across a role's parts (one remit).
# ENGINE-INJECTED lanes the runner overwrites onto the payload before the writer sees
# it (the body never authors them):
#   - `read_records: [...]`               — the records-grounding oracle (one remit).
#   - `readings: {source: reading}`       — the metric-readings lane (`REQUIRES_READINGS`
#                                            parts read it; SHARED across parts).
#   - `values_oracles: {part_id: [pid]}`  — the values-grounding oracle, PER PART: the
#                                            engine-verified constitution principle-ids a
#                                            values-grounded part (a stance) may cite. The
#                                            SKILL computes it via `/ztn:check-decision
#                                            --dry_run` + verifies each id against
#                                            `0_constitution/`; absent → the part fail-closes.
# An OPTIONAL `nudges: [{text, evidence[]}]` field carries the role's proactive
# voice — bounded, grounded, always-HITL `role-nudge` CLARIFICATIONs the writer
# surfaces for the owner (never a canonical write). See `roles_persist._process_nudges`.
# This layer owns the envelope contract + the `delta_part` accessor; the routing
# itself lives in `roles_persist` (core-b). v1's part-less, single-archetype
# payload is removed — a delta without a resolvable `part` is unroutable.
PAYLOAD_SCHEMA_VERSION = 2


def delta_part(delta: Any) -> str | None:
    """Return the part id a delta addresses, or None when absent/invalid.

    The single home for reading the `part` field off a v2 delta — the writer
    routes with this rather than re-implementing the field parse. A delta whose
    `part` is missing, non-string, or blank is unroutable (None); the caller
    rejects it (surface, don't guess a target part).
    """
    if not isinstance(delta, dict):
        return None
    part = delta.get("part")
    if isinstance(part, str) and part.strip():
        return part.strip()
    return None


def resolve_role_id(delta_payload: Any, prior_state: Any) -> str:
    """Resolve the owning role id from the delta payload, else the prior state, else
    the neutral fallback `"role"`.

    Shared by every part plugin's validate pass (the churn-guard / clarification
    subjects need the role id). The payload wins over prior state so a freshly-set
    id is honoured before a stale one; a non-dict source is skipped.
    """
    for src in (delta_payload, prior_state):
        if isinstance(src, dict):
            rid = src.get("role_id")
            if isinstance(rid, str) and rid:
                return rid
    return "role"


def delta_ref(delta: Any, idx: int, key_fields: Iterable[str] = ()) -> str:
    """A human-readable reference to a delta, for a rejection record.

    Returns the first non-empty value among `key_fields` the delta carries — each
    plugin passes its own key-field preference (the ledger `("provisional_key",
    "key")`, the registry `("key",)`, a narrative none) — else `"{op}#{idx}"`, else
    `"delta#{idx}"`. One home so every plugin labels a rejected delta identically.
    """
    if isinstance(delta, dict):
        for key_field in key_fields:
            val = delta.get(key_field)
            if isinstance(val, str) and val:
                return val
        op = delta.get("op")
        if isinstance(op, str) and op:
            return f"{op}#{idx}"
    return f"delta#{idx}"


# -----------------------------------------------------------------------------
# Shared part-scoped helpers (SoT for the decision-row shape + subject format)
# -----------------------------------------------------------------------------
# Both the writer (`roles_persist`) and every part plugin build decision rows and
# part-scoped CLARIFICATION subjects. Keeping the shape here (rather than in the
# writer) is the single home the composite seam needs: a plugin owns its op → kind
# mapping but never re-invents the row envelope, and per-part holds dedup on an
# identical subject regardless of which module emitted them.

def part_subject(role_id: str, part_id: str) -> str:
    """Part-scoped CLARIFICATION subject so per-part holds dedup independently.

    One home for the `{role} · {part}` format — the writer's auto-pause /
    schema-version signals and a plugin's identity-hold signals must produce the
    SAME subject for a given part, else two open blocks would pile up for one hold.
    """
    return f"{role_id} · {part_id}"


def decision_row(
    kind: str, key: Any, hook: str, role_id: str, part: str, ts: str, **extra: Any
) -> dict:
    """One `decisions.jsonl` row (§3.4) — the shared audit-row envelope.

    Every part plugin builds its own rows (its op vocabulary → `kind`), but the
    envelope (`ts`, `role_id`, `part`, `kind`, `key`, `hook` + op-specific extras)
    is uniform so a reader parses one shape across archetypes. `part` stamps which
    part the decision belongs to (composite roles interleave rows from many parts).
    """
    row = {
        "ts": ts, "role_id": role_id, "part": part,
        "kind": kind, "key": key, "hook": hook,
    }
    row.update(extra)
    return row


# -----------------------------------------------------------------------------
# Cadence — is_due
# -----------------------------------------------------------------------------

def _coerce_date(value: Any) -> date | None:
    """Coerce a date / datetime / ISO string / run-dict into a `date`, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, dict):
        value = value.get("run_at")
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def is_due(
    role_config: RoleConfig,
    last_run: Any,
    today: Any = None,
) -> bool:
    """True when the role's cadence window is open today.

    Mirrors AGENT_LENSES cadence semantics — daily / weekly / biweekly /
    monthly with `cadence_anchor`; first-run fires when `today == anchor`; no
    catch-up (a missed window is gone, not replayed). A `paused` role is never
    due. `last_run` accepts a `date` / datetime / ISO string / run-dict / None;
    `today` defaults to the system date.

    Cadence-only: the `activation` gate (`by_change` / `by_elapsed_time`) is an
    additional filter the tick skill applies on top of this.
    """
    if not role_config.is_active:
        return False
    today_d = _coerce_date(today) or date.today()
    last_d = _coerce_date(last_run)
    cadence = role_config.cadence
    anchor = role_config.cadence_anchor

    if cadence == "daily":
        return last_d is None or last_d < today_d

    if cadence in ("weekly", "biweekly"):
        anchor_wd = WEEKDAY_NUM.get(str(anchor).strip().lower())
        if anchor_wd is None or today_d.weekday() != anchor_wd:
            return False
        if last_d is None:
            return True  # first run — today matches anchor
        gap = 6 if cadence == "weekly" else 14
        return (today_d - last_d).days >= gap

    if cadence == "monthly":
        try:
            dom = min(int(anchor), MONTHLY_ANCHOR_MAX)
        except (TypeError, ValueError):
            return False
        if today_d.day != dom:
            return False
        if last_d is None:
            return True
        return (today_d.year, today_d.month) != (last_d.year, last_d.month)

    return False


# -----------------------------------------------------------------------------
# Dynamic part-plugin loader — the seam (common layer never hardcodes a kind)
# -----------------------------------------------------------------------------

def import_archetype(name: str):
    """Import the part-plugin module `roles_archetype_{name}` by its kind.

    `name` is a `part.kind` (e.g. `ledger`, `narrative`); validated as a safe
    lowercase identifier before import (defends against path/name injection).
    Raises `RoleArchetypeError` when the name is unsafe or the module is absent.
    """
    if not isinstance(name, str) or not _ARCHETYPE_NAME_RE.match(name):
        raise RoleArchetypeError(f"unsafe archetype name: {name!r}")
    module_name = f"roles_archetype_{name}"
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise RoleArchetypeError(
            f"archetype plugin {module_name!r} not found ({exc})"
        ) from exc


# -----------------------------------------------------------------------------
# Low-level write helpers (atomic; LF-forced for cross-platform determinism)
# -----------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    tmp.replace(path)


def _append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# -----------------------------------------------------------------------------
# Runs index + human log
# -----------------------------------------------------------------------------

def append_run(
    record: RunRecord | dict,
    base: Path | None = None,
    runs_path: Path | None = None,
) -> dict:
    """Append one entry to `roles-runs.jsonl` (§3.5). Returns the written dict.

    Accepts a `RunRecord` or a raw dict. Validates `status` / `hook` and
    normalises `counts` to the fixed key set (surface, don't guess — an unknown
    status is a bug, not silently coerced).
    """
    entry = record.to_dict() if isinstance(record, RunRecord) else _run_from_dict(record)
    path = runs_path or roles_runs_path(base)
    _append_text(path, json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _run_from_dict(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise RoleError(f"run record must be a mapping, got {type(raw).__name__}")
    role_id = raw.get("role_id")
    run_at = raw.get("run_at") or now_iso_utc()
    status = raw.get("status")
    hook = raw.get("hook")
    if not isinstance(role_id, str) or not role_id:
        raise RoleError("run record missing 'role_id'")
    if status not in ROLES_RUN_STATUSES:
        raise RoleError(
            f"run record 'status' must be one of {sorted(ROLES_RUN_STATUSES)}, "
            f"got {status!r}"
        )
    if hook not in ROLES_HOOKS:
        raise RoleError(
            f"run record 'hook' must be one of {sorted(ROLES_HOOKS)}, "
            f"got {hook!r}"
        )
    return {
        "role_id": role_id,
        "run_at": run_at,
        "status": status,
        "hook": hook,
        "counts": normalise_run_counts(raw.get("counts")),
    }


def read_runs(
    role_id: str | None = None,
    base: Path | None = None,
    runs_path: Path | None = None,
) -> list[dict]:
    """Return parsed run entries (chronological), optionally filtered by role.

    Malformed lines are skipped tolerantly (best-effort — a corrupt line must
    not crash cadence resolution).
    """
    path = runs_path or roles_runs_path(base)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            entry = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if role_id is not None and entry.get("role_id") != role_id:
            continue
        out.append(entry)
    return out


def last_successful_run(
    role_id: str,
    base: Path | None = None,
    runs_path: Path | None = None,
) -> dict | None:
    """Latest run entry for `role_id` with status in {ok, empty} (§3.5), or None.

    This is the `last_run` cadence reads: `rejected` / `error` / `paused` runs
    do not advance the window, so the role retries on the next due day.
    """
    latest: dict | None = None
    for entry in read_runs(role_id, base, runs_path):
        if entry.get("status") in ROLES_SUCCESS_STATUSES:
            latest = entry
    return latest


def format_run_log_section(
    run_at: str,
    lines: Iterable[str],
) -> str:
    """Compose a `log_roles.md` section mirroring `log_agent_lens.md` shape."""
    body = "\n".join(str(line) for line in lines)
    return f"\n## {run_at} — roles run\n\n{body}\n"


def append_roles_log(
    block: str,
    base: Path | None = None,
    log_path: Path | None = None,
) -> None:
    """Append a human-readable block to `log_roles.md` (append-only §3.5)."""
    path = log_path or roles_log_path(base)
    if not path.exists():
        _atomic_write(path, "# Roles Run Log\n")
    _append_text(path, block if block.endswith("\n") else block + "\n")


# -----------------------------------------------------------------------------
# Conformant CLARIFICATION emitter (SYSTEM_CONFIG item-format contract)
# -----------------------------------------------------------------------------

_CLARIFICATIONS_SKELETON = (
    "# Clarifications Needed\n\n## Open Items\n\n## Resolved Items\n"
)
_OPEN_ITEMS_RE = re.compile(r"^## Open Items[ \t]*$", re.MULTILINE)
_RESOLVED_ITEMS_RE = re.compile(r"^## Resolved Items\b", re.MULTILINE)
# A conformant item header: `### {YYYY-MM-DD} — {title}` — group 1 is the title
# (`{ctype}: {subject}` optionally suffixed ` — {hint}`). The em dash (U+2014)
# matches `build_clarification_block`'s `### {date} — {title}` exactly.
_CLARIF_HEADER_RE = re.compile(r"^### \d{4}-\d{2}-\d{2} — (.+?)\s*$")


def _dedup_marker(ctype: str, subject: str) -> str:
    return f"<!-- role-clarif: {ctype}/{subject} -->"


def _open_items_span(text: str) -> tuple[int, int] | None:
    """(start, end) char offsets of the `## Open Items` section body, or None.

    The end is bounded by `## Resolved Items` (or EOF), NOT the first following
    `## ` heading — producers (process / lint) interleave their own sub-group
    H2 headers inside Open Items, so a role's dedup marker can sit below one of
    them and must still be inside the scanned span.
    """
    m = _OPEN_ITEMS_RE.search(text)
    if not m:
        return None
    start = text.find("\n", m.end())
    start = m.end() if start < 0 else start + 1
    nxt = _RESOLVED_ITEMS_RE.search(text, start)
    return start, (nxt.start() if nxt else len(text))


def build_clarification_block(
    *,
    ctype: str,
    subject: str,
    context: str,
    source: str,
    suggested_action: str,
    action_taken: str,
    title_hint: str = "",
    confidence_tier: str = "surfaced",
    quote: str = "",
    date_str: str | None = None,
) -> str:
    """Render one conformant CLARIFICATION block (no I/O).

    Follows the SYSTEM_CONFIG item-format contract: `### {date} — {title}` header,
    mandatory `**Context:**`, plus Type / Subject / Source / Suggested action /
    Action taken / Confidence tier and an optional `**Quote:**`. Refuses an
    off-contract type, a blank mandatory field, or a title carrying the literal
    word RESOLVED (which `/ztn:resolve-clarifications` treats as auto-archive).
    """
    if ctype not in ROLE_CLARIFICATION_TYPES:
        raise RoleClarificationError(
            f"unknown role CLARIFICATION type {ctype!r}; "
            f"expected one of {sorted(ROLE_CLARIFICATION_TYPES)}"
        )
    subject = (subject or "").strip()
    context = (context or "").strip()
    source = (source or "").strip()
    if not subject:
        raise RoleClarificationError("CLARIFICATION 'subject' is mandatory")
    if not context:
        raise RoleClarificationError("CLARIFICATION 'context' is mandatory")
    if not source:
        raise RoleClarificationError("CLARIFICATION 'source' is mandatory")

    date_str = date_str or today_iso()
    hint = (title_hint or "").strip()
    # The word RESOLVED must not leak into a title (resolve auto-archives it),
    # but only the ENGINE-controlled portion (ctype + title_hint) is guarded —
    # the owner-derived subject is theirs (a legit «Resolved billing disputes»
    # subject must not make emission raise and silently drop the item).
    if _RESOLVED_WORD_RE.search(f"{ctype} {hint}"):
        raise RoleClarificationError(
            "CLARIFICATION type/title_hint must not contain the word RESOLVED: "
            f"{ctype!r} / {hint!r}"
        )
    title = f"{ctype}: {subject}"
    if hint:
        title = f"{title} — {hint}"

    parts = [
        f"### {date_str} — {title}",
        "",
        f"**Type:** {ctype}",
        f"**Subject:** {subject}",
        f"**Source:** {source}",
        f"**Confidence tier:** {confidence_tier}",
        f"**Context:** {context}",
        f"**Action taken:** {(action_taken or '').strip()}",
        f"**Suggested action:** {(suggested_action or '').strip()}",
    ]
    q = (quote or "").strip()
    if q:
        parts.append(f"**Quote:** > «{q}»")
    parts.append(_dedup_marker(ctype, subject))
    return "\n".join(parts) + "\n"


def emit_clarification(
    *,
    ctype: str,
    subject: str,
    context: str,
    source: str,
    suggested_action: str,
    action_taken: str,
    title_hint: str = "",
    confidence_tier: str = "surfaced",
    quote: str = "",
    date_str: str | None = None,
    base: Path | None = None,
    path: Path | None = None,
    dedup: bool = True,
) -> bool:
    """Append a conformant CLARIFICATION block to `## Open Items`. Atomic.

    Returns True when a block was written, False when `dedup` is on and an OPEN
    item for this `(ctype, subject)` already exists (keeps cold-start / churn
    re-surfacing idempotent — the same frozen question does not pile up each
    tick). Newest-first: inserted right under the `## Open Items` header.
    """
    block = build_clarification_block(
        ctype=ctype,
        subject=subject,
        context=context,
        source=source,
        suggested_action=suggested_action,
        action_taken=action_taken,
        title_hint=title_hint,
        confidence_tier=confidence_tier,
        quote=quote,
        date_str=date_str,
    )
    target = path or clarifications_path(base)

    if target.exists():
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # An existing queue that cannot be read is NOT a blank slate —
            # falling back to the skeleton would atomically overwrite every
            # open item. Surface, don't guess (never destroy owner state).
            raise RoleClarificationError(
                f"{target}: cannot read CLARIFICATIONS queue ({exc})"
            ) from exc
    else:
        text = _CLARIFICATIONS_SKELETON

    if _OPEN_ITEMS_RE.search(text) is None:
        # No Open Items section — append one so the block has a home.
        if not text.endswith("\n"):
            text += "\n"
        text += "\n## Open Items\n"

    if dedup:
        span = _open_items_span(text)
        if span is not None:
            start, end = span
            if _dedup_marker(ctype, subject) in text[start:end]:
                return False

    m = _OPEN_ITEMS_RE.search(text)
    line_end = text.find("\n", m.end())
    insert_at = len(text) if line_end < 0 else line_end + 1
    new_text = text[:insert_at] + "\n" + block + text[insert_at:]
    _atomic_write(target, new_text)
    return True


def count_open_role_nudges(
    role_id: str, base: Path | None = None, path: Path | None = None
) -> int:
    """Count a role's OPEN `role-nudge` CLARIFICATIONs — the cumulative anti-salami
    budget check. A nudge's subject is `{role_id} · {summary}`, so its hidden dedup
    marker is `role-nudge/{role_id} · …`; this counts those in the `## Open Items`
    span only (resolved nudges no longer count against the budget). Returns 0 when
    there is no queue / no open section. Tolerant of read failure (returns 0)."""
    target = path or clarifications_path(base)
    if not target.exists():
        return 0
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    span = _open_items_span(text)
    if span is None:
        return 0
    start, end = span
    # `role_id` followed by the ` · ` subject separator — unambiguous even when one
    # role id is a prefix of another (the separator, not just the id, must match).
    marker_prefix = f"<!-- role-clarif: role-nudge/{role_id} ·"
    return text[start:end].count(marker_prefix)


def clarification_seen_resolved(
    ctype: str, subject: str, base: Path | None = None, path: Path | None = None
) -> bool:
    """True when a CLARIFICATION for `(ctype, subject)` sits in `## Resolved Items`
    — the owner already saw and closed it. The anti-flip-flop guard: a dismissed
    `role-nudge` is not re-surfaced next tick (open-span dedup alone would let a
    resolved nudge re-nag). A genuinely NEW concern gets a different subject (its
    text hash differs) and still surfaces. Tolerant: False on no queue / read error."""
    target = path or clarifications_path(base)
    if not target.exists():
        return False
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    m = _RESOLVED_ITEMS_RE.search(text)
    if m is None:
        return False
    return _dedup_marker(ctype, subject) in text[m.start():]


def emit_clarification_signal(
    signal: ClarificationSignal,
    base: Path | None = None,
    path: Path | None = None,
    date_str: str | None = None,
    dedup: bool = True,
) -> bool:
    """Emit a `ClarificationSignal` bundled inside a `ValidationResult`."""
    return emit_clarification(
        ctype=signal.ctype,
        subject=signal.subject,
        context=signal.context,
        source=signal.source,
        suggested_action=signal.suggested_action,
        action_taken=signal.action_taken,
        title_hint=signal.title_hint,
        confidence_tier=signal.confidence_tier,
        quote=signal.quote,
        date_str=date_str,
        base=base,
        path=path,
        dedup=dedup,
    )


# -----------------------------------------------------------------------------
# CLARIFICATION resolution — move an open item to Resolved Items
# -----------------------------------------------------------------------------

def _find_role_block(
    lines: list[str], lo: int, hi: int, ctype: str, subject: str
) -> tuple[int, int] | None:
    """Line indices `[start, end)` of the item block matching `(ctype, subject)`.

    Anchors on the hidden dedup marker first (`<!-- role-clarif: {ctype}/{subject}
    -->`), falling back to the `### {date} — {ctype}: {subject}` header when the
    marker was stripped. Block start is the enclosing `### ` header; the block
    ends at the next `### ` / `## ` heading (a producer sub-group H2 or the next
    item) or `hi`, so the trailing blank between blocks is folded into the removed
    span. Search is confined to `[lo, hi)` — the `## Open Items` body. None when
    no block matches.
    """
    marker = _dedup_marker(ctype, subject)
    anchor: int | None = None
    for i in range(lo, hi):
        if lines[i].strip() == marker:
            anchor = i
            break
    if anchor is None:
        want = f"{ctype}: {subject}"
        for i in range(lo, hi):
            if not lines[i].startswith("### "):
                continue
            m = _CLARIF_HEADER_RE.match(lines[i])
            if m and (m.group(1) == want or m.group(1).startswith(want + " — ")):
                anchor = i
                break
    if anchor is None:
        return None

    start = anchor
    while start >= lo and not lines[start].startswith("### "):
        start -= 1
    if start < lo or not lines[start].startswith("### "):
        return None
    end = start + 1
    while end < hi:
        if lines[end].startswith("### ") or lines[end].startswith("## "):
            break
        end += 1
    return start, end


def _build_resolved_block(block_lines: list[str], resolution: str) -> list[str]:
    """Append the Archive-Contract `**Resolved:** {resolution}` line to a block.

    Trailing blank lines are dropped; the reason line is inserted just above the
    dedup marker when present (keeping the marker last), else appended.
    """
    body = list(block_lines)
    while body and body[-1].strip() == "":
        body.pop()
    resolved_line = f"**Resolved:** {str(resolution).strip()}"
    if body and body[-1].lstrip().startswith("<!-- role-clarif:"):
        body.insert(len(body) - 1, resolved_line)
    else:
        body.append(resolved_line)
    return body


def _insert_resolved_block(lines: list[str], entry_lines: list[str]) -> list[str]:
    """Insert `entry_lines` newest-first under `## Resolved Items` (create if absent).

    Produces `header / blank / entry / blank / rest` with single blank separators
    (leading blanks of the prior body are collapsed) so the section stays clean.
    """
    r_idx: int | None = None
    for i, ln in enumerate(lines):
        if ln.startswith("## Resolved Items"):
            r_idx = i
            break
    if r_idx is None:
        out = list(lines)
        while out and out[-1].strip() == "":
            out.pop()
        out.append("")
        out.append("## Resolved Items")
        r_idx = len(out) - 1
        lines = out
    insert_at = r_idx + 1
    rest = lines[insert_at:]
    while rest and rest[0].strip() == "":
        rest.pop(0)
    return lines[:insert_at] + [""] + entry_lines + [""] + rest


def resolve_clarification(
    ctype: str,
    subject: str,
    resolution: str,
    base: Path | None = None,
    path: Path | None = None,
) -> bool:
    """Move an OPEN CLARIFICATION for `(ctype, subject)` to Resolved Items. Atomic.

    Finds the matching block under `## Open Items` (by the hidden dedup marker,
    or the `### {date} — {ctype}: {subject}` header when the marker was stripped),
    removes it, appends a `**Resolved:** {resolution}` line (the Archive-Contract
    reason), and re-inserts it newest-first under `## Resolved Items`. Returns
    False when there is no queue, no `## Open Items` section, or no matching open
    block (so the caller can close a stale item idempotently — a second call is a
    no-op False). An existing queue that cannot be read raises rather than being
    overwritten (surface, don't guess — never destroy owner state).
    """
    ctype = (ctype or "").strip()
    subject = (subject or "").strip()
    if not ctype or not subject:
        return False
    target = path or clarifications_path(base)
    if not target.exists():
        return False
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RoleClarificationError(
            f"{target}: cannot read CLARIFICATIONS queue ({exc})"
        ) from exc

    lines = text.split("\n")
    open_idx: int | None = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## Open Items":
            open_idx = i
            break
    if open_idx is None:
        return False
    hi = len(lines)
    for i in range(open_idx + 1, len(lines)):
        if lines[i].startswith("## Resolved Items"):
            hi = i
            break

    bounds = _find_role_block(lines, open_idx + 1, hi, ctype, subject)
    if bounds is None:
        return False
    b_start, b_end = bounds

    entry_lines = _build_resolved_block(lines[b_start:b_end], resolution)
    remaining = lines[:b_start] + lines[b_end:]
    new_lines = _insert_resolved_block(remaining, entry_lines)
    _atomic_write(target, "\n".join(new_lines))
    return True
