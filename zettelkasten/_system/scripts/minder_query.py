#!/usr/bin/env python3
"""Lens-style scoped read/search TOOL for the Roles subsystem.

Given a role's remit (`config.yml → remit`, all axes), this lets the role body
navigate its own zone agentically — the way a lens thinker reads its records —
instead of being handed one pre-dumped corpus. It is NOT a privacy gate, NOT a
hard filesystem deny, NOT the QMD MCP. Hard read-enforcement is deferred to a
later stage (build-contract §1.1); Stage-1 reading is honor-system. The tool's
SCOPE GUARANTEE, however, is real in every mode: the same `_matches_remit`
allow-list, fail-closed empty remit, `is_sensitive` handling, and symlink-skip
gate the corpus, so nothing outside the remit is ever returned — only the
granularity of what you ask for changes.

Modes (mutually exclusive; the default no-mode dump is the `ask` cold-path):
  - --list          : the zone INDEX — one lightweight entry per in-remit unit
                      ({path, type, trio, frontmatter_subset}, NO body) + counts.
                      The body's table-of-contents; the grounding oracle of stems.
  - --search "<q>"  : case-insensitive substring match over body + frontmatter,
                      restricted to in-remit units (remit FIRST, then search) →
                      {path, snippet}. Fail-closed: can never match out of remit.
  - --read <path>   : the FULL body (+ frontmatter_subset + trio) of the named
                      in-remit note(s) (comma-separated or repeated). An
                      out-of-remit path — including an out-of-remit `is_sensitive`
                      note — is REJECTED with an explicit marker, never returned.
  - (no mode)       : the full corpus dump (`resolve_corpus`) — kept for the
                      `ask` cold-path / fallback only; `--no-body` / `--no-stubs`
                      trim it.

Resolution (allow-list UNION across axes; fail-closed):
  - globs         : path glob (posix, base-relative; `**` spans dirs, `*` within)
  - tags          : note `tags` ∩ remit tags
  - project_ids   : `projects` ∩ remit  OR  the project's own note (id + type)
  - person_ids    : `people`   ∩ remit  OR  the person's own note (id + type)
  - hubs          : `hubs`     ∩ remit  OR  the hub's own note (id)
  - decision_notes: note resolved-type == "decision"
  - all           : whole owner note corpus (incl. `is_sensitive`)

An empty remit (no axis set, `all=false`) matches nothing — the fail-closed
default. A malformed remit degrades to empty via `roles_common.parse_remit`. A
structurally broken `config.yml` surfaces as a non-zero exit (surface, don't
guess); an empty resolution is a valid zero-exit result.

Honor-system privacy (§1.1): in-remit notes are returned as full units WITH
their privacy trio (`origin` / `audience_tags` / `is_sensitive`) so the frame
can judge — the resolver never drops an in-remit note. A FOREIGN entity
referenced from an in-remit note (a `projects` / `people` / `hubs` id whose own
note is out of remit) is returned as a lightweight `{id, name, type}` stub,
UNLESS that entity note is `is_sensitive` — then it is dropped with no stub.

Per-unit `type` uses the full `_common.CONCEPT_TYPES_ALL` vocabulary (which
already reserves `person` / `project`); an out-of-vocabulary declared type
(a record's `meeting`, a note-kind like `insight`) falls back to the
vocabulary's `other`. The raw `type` / `types` are preserved in
`frontmatter_subset`, so no information is lost.

Scope source — engine-owned (`--role`) vs dev/preview (`--remit-json` /
`--config`):
  `--role <id>` is the ENGINE-OWNED scope path: it resolves the remit from
  `_system/roles/<id>/config.yml → remit`, which is the ONLY scope source for
  a tick body. `--remit-json` and `--config` are DEV surfaces only — the
  concierge uses them to preview a drafted remit BEFORE a `config.yml` exists.
  They are NOT for the tick body and are GATED behind `ZTN_DEV=1` (refused
  otherwise), so `--remit-json '{"all":true}'` cannot defeat, through this very
  tool, the hard read-lock (INV-15). The tool-restricted subagent runtime reads
  via `--enforced --role <id>`, which REQUIRES `--role` and refuses both
  overrides UNCONDITIONALLY (even under `ZTN_DEV`) — so the body cannot read
  around its remit by construction. (`_load_remit_source` enforces this.)

Deterministic, no LLM. `pathlib`; base resolved via `_common.repo_root`
(honours `ZTN_BASE`); symlinked / out-of-tree files skipped (read-around
defence); reads via universal-newline `read_frontmatter`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from _common import (
    CONCEPT_TYPES_ALL,
    die,
    now_iso_utc,
    read_frontmatter,
    repo_root,
)
from roles_common import (
    RemitSpec,
    RoleConfig,
    RoleConfigError,
    as_str_list,
    load_role_config,
    load_role_config_file,
    parse_remit,
)


# -----------------------------------------------------------------------------
# Corpus scope + returned-frontmatter whitelist
# -----------------------------------------------------------------------------

# Owner note-bearing roots scanned for the corpus. Engine / system / source /
# constitution trees are NOT notes and stay out of scope; a remit glob that
# points outside these roots simply resolves nothing (fail-closed, not a
# guessed widening). Files without frontmatter (registries, READMEs) are
# skipped naturally by `read_frontmatter` returning None.
CORPUS_ROOTS: tuple[str, ...] = (
    "_records",
    "1_projects",
    "2_areas",
    "3_resources",
    "4_archive",
    "5_meta/mocs",
    "6_posts",
)

# Frontmatter keys surfaced in each unit's `frontmatter_subset`. A curated,
# classification-oriented slice — the privacy trio is carried separately in
# `trio` (one home, no duplication).
_SUBSET_KEYS: tuple[str, ...] = (
    "id",
    "title",
    "name",
    "type",
    "types",
    "layer",
    "kind",
    "status",
    "tags",
    "projects",
    "people",
    "hubs",
    "concepts",
    "domains",
    "aliases",
    "threads",
    "source",
    "created",
    "modified",
    "recorded_at",
)

# Frontmatter array axes that reference foreign entities (drive stub emission).
_ENTITY_REF_KEYS: tuple[str, ...] = ("projects", "people", "hubs")

# Layer values that identify a first-class entity note when `type` is absent
# (person notes carry `layer: person`, not `type: person`).
_LAYER_TO_TYPE: dict[str, str] = {"person": "person", "project": "project"}


# -----------------------------------------------------------------------------
# Small frontmatter helpers (tolerant coercion)
# -----------------------------------------------------------------------------

def resolve_type(fm: dict) -> str:
    """Canonical entity type within `_common.CONCEPT_TYPES_ALL`.

    Prefers a valid single `type`, then the first valid member of `types`,
    then the `layer` discriminator (person / project first-class notes), and
    finally the vocabulary's own `other` catch-all — never a guessed mapping
    of an out-of-vocabulary declared kind.
    """
    t = fm.get("type")
    if isinstance(t, str) and t in CONCEPT_TYPES_ALL:
        return t
    for member in as_str_list(fm.get("types")):
        if member in CONCEPT_TYPES_ALL:
            return member
    layer = fm.get("layer")
    if isinstance(layer, str):
        mapped = _LAYER_TO_TYPE.get(layer.strip().lower())
        if mapped is not None:
            return mapped
    return "other"


def _json_default(value: Any) -> str:
    """JSON fallback for values PyYAML materialises but `json` cannot serialise.

    `YYYY-MM-DD` frontmatter (`created` / `modified` / `recorded_at` / …)
    becomes a `date`; render it (and any `datetime`) as an ISO string.
    """
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _entity_name(fm: dict, entity_id: str) -> str:
    """Human name for a stub: `name`, else `title`, else the id itself."""
    for key in ("name", "title"):
        val = fm.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return entity_id


def _trio(fm: dict) -> dict:
    """The privacy trio (§3.8) with canonical defaults: personal / [] / false."""
    origin = fm.get("origin")
    return {
        "origin": origin if isinstance(origin, str) and origin.strip() else "personal",
        "audience_tags": as_str_list(fm.get("audience_tags")),
        "is_sensitive": bool(fm.get("is_sensitive", False)),
    }


def _frontmatter_subset(fm: dict) -> dict:
    """Curated classification slice of a note's frontmatter (present keys only)."""
    return {key: fm[key] for key in _SUBSET_KEYS if key in fm}


# -----------------------------------------------------------------------------
# Glob matching (base-relative, posix; `**` spans dirs, `*` stays in a segment)
# -----------------------------------------------------------------------------

def _glob_to_regex(pattern: str) -> str:
    """Translate a path glob to an anchored regex.

    `**/` matches zero or more directory segments, a trailing `**` matches the
    rest of the path, `*` matches within one segment (no `/`), `?` matches one
    non-slash character. All other characters are escaped literally. Portable
    across Python versions (no reliance on `Path.match`'s `**` support).
    """
    parts: list[str] = ["^"]
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            j = i + 1
            if j < n and pattern[j] == "*":
                j += 1
                if j < n and pattern[j] == "/":
                    parts.append("(?:.*/)?")  # `**/` → zero or more dirs
                    i = j + 1
                else:
                    parts.append(".*")  # trailing `**` → rest of path
                    i = j
            else:
                parts.append("[^/]*")  # `*` → within a segment
                i += 1
        elif ch == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(ch))
            i += 1
    parts.append("$")
    return "".join(parts)


class _GlobSet:
    """Compiled remit globs; `matches(rel)` is True on the first hit."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self._res: list[re.Pattern[str]] = []
        for pat in patterns:
            if not isinstance(pat, str) or not pat.strip():
                continue
            self._res.append(re.compile(_glob_to_regex(pat.strip())))

    def matches(self, rel: str) -> bool:
        return any(rx.match(rel) for rx in self._res)


# -----------------------------------------------------------------------------
# Corpus unit + index
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class _Unit:
    rel: str
    fm: dict
    body: str
    rtype: str
    projects: tuple[str, ...]
    people: tuple[str, ...]
    hubs: tuple[str, ...]
    tags: tuple[str, ...]

    @property
    def entity_id(self) -> str | None:
        eid = self.fm.get("id")
        return eid if isinstance(eid, str) and eid.strip() else None


def _scan_corpus(base: Path) -> list[_Unit]:
    """Read every frontmatter-bearing note under the corpus roots.

    Skips symlinked files and any file that resolves outside `base`
    (read-around defence), and files without a parseable frontmatter block.
    Returns units sorted by relative path for deterministic output.

    Read-around invariant (wikilinks): each unit's `body` is captured VERBATIM
    and `[[wikilinks]]` inside it are NEVER dereferenced or inlined. Every
    corpus fetch re-enters `_matches_remit`, so an out-of-remit link target is
    unreachable — the remit boundary holds because the tool follows no link.
    Any future link-inlining MUST route the link target through
    `_matches_remit` FIRST, or the boundary is silently defeated.
    """
    base_resolved = base.resolve()
    units: list[_Unit] = []
    for root_name in CORPUS_ROOTS:
        root = base / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                path.resolve().relative_to(base_resolved)
            except ValueError:
                continue  # symlink / traversal pointing outside the base tree
            parsed = read_frontmatter(path)
            if parsed is None:
                continue
            fm, body = parsed
            rel = path.relative_to(base).as_posix()
            units.append(
                _Unit(
                    rel=rel,
                    fm=fm,
                    body=body,
                    rtype=resolve_type(fm),
                    projects=tuple(as_str_list(fm.get("projects"))),
                    people=tuple(as_str_list(fm.get("people"))),
                    hubs=tuple(as_str_list(fm.get("hubs"))),
                    tags=tuple(as_str_list(fm.get("tags"))),
                )
            )
    units.sort(key=lambda u: u.rel)
    return units


# -----------------------------------------------------------------------------
# Remit matching
# -----------------------------------------------------------------------------

def _matches_remit(unit: _Unit, remit: RemitSpec, globs: _GlobSet) -> bool:
    """True when the unit falls within the remit (allow-list union)."""
    if remit.all:
        return True
    if globs.matches(unit.rel):
        return True
    eid = unit.entity_id
    if remit.tags and any(t in remit.tags for t in unit.tags):
        return True
    if remit.project_ids and (
        any(p in remit.project_ids for p in unit.projects)
        or (eid in remit.project_ids and unit.rtype == "project")
    ):
        return True
    if remit.person_ids and (
        any(p in remit.person_ids for p in unit.people)
        or (eid in remit.person_ids and unit.rtype == "person")
    ):
        return True
    if remit.hubs and (
        any(h in remit.hubs for h in unit.hubs) or eid in remit.hubs
    ):
        return True
    if remit.decision_notes and unit.rtype == "decision":
        return True
    return False


def _unit_to_dict(unit: _Unit, include_body: bool) -> dict:
    out: dict = {
        "path": unit.rel,
        "type": unit.rtype,
        "trio": _trio(unit.fm),
        "frontmatter_subset": _frontmatter_subset(unit.fm),
    }
    if include_body:
        out["body"] = unit.body
    return out


# -----------------------------------------------------------------------------
# Resolution
# -----------------------------------------------------------------------------

def remit_to_dict(remit: RemitSpec) -> dict:
    return {
        "globs": list(remit.globs),
        "tags": list(remit.tags),
        "project_ids": list(remit.project_ids),
        "person_ids": list(remit.person_ids),
        "hubs": list(remit.hubs),
        "decision_notes": remit.decision_notes,
        "all": remit.all,
    }


def _resolve_units(remit: RemitSpec, base: Path) -> tuple[list[_Unit], list[_Unit]]:
    """Scan the corpus once and split into `(all_units, in_remit_units)`.

    The single scope-bearing primitive every mode shares — the in-remit split
    is computed by the SAME `_matches_remit` allow-list, so `--list`,
    `--search`, and `--read` all inherit an identical fail-closed boundary. An
    empty (or `all=false` with no axis) remit resolves to `([], [])` with no
    filesystem scan. `base` must already be resolved.
    """
    if remit.is_empty:
        return [], []
    all_units = _scan_corpus(base)
    globs = _GlobSet(remit.globs)
    in_remit = [u for u in all_units if _matches_remit(u, remit, globs)]
    return all_units, in_remit


def resolve_corpus(
    remit: RemitSpec,
    base: Path | None = None,
    include_body: bool = True,
    include_stubs: bool = True,
) -> dict:
    """Resolve a remit into the in-scope note corpus + foreign-entity stubs.

    Returns a JSON-ready dict: `remit` echo, `counts`, `units`, `entity_stubs`.
    An empty (or `all=false` with no axis) remit short-circuits to an empty
    corpus with no filesystem scan.
    """
    base = (base or repo_root())
    base = Path(base).resolve()

    counts = {
        "scanned": 0,
        "units": 0,
        "entity_stubs": 0,
        "sensitive_in_remit": 0,
        "dropped_sensitive_stubs": 0,
    }
    empty = {
        "remit": remit_to_dict(remit),
        "counts": counts,
        "units": [],
        "entity_stubs": [],
    }
    if remit.is_empty:
        return empty

    all_units, in_remit = _resolve_units(remit, base)
    counts["scanned"] = len(all_units)

    # Index by entity id for stub resolution + to know which ids are already
    # returned as full in-remit units (never stubbed).
    id_index: dict[str, _Unit] = {}
    for unit in all_units:
        eid = unit.entity_id
        if eid is not None and eid not in id_index:
            id_index[eid] = unit
    in_remit_ids = {u.entity_id for u in in_remit if u.entity_id is not None}

    unit_dicts: list[dict] = []
    for unit in in_remit:
        if unit.fm.get("is_sensitive"):
            counts["sensitive_in_remit"] += 1
        unit_dicts.append(_unit_to_dict(unit, include_body))

    entity_stubs: list[dict] = []
    if include_stubs and not remit.all:
        referenced: set[str] = set()
        for unit in in_remit:
            for key in _ENTITY_REF_KEYS:
                referenced.update(as_str_list(unit.fm.get(key)))
        foreign = sorted(referenced - in_remit_ids)
        for entity_id in foreign:
            target = id_index.get(entity_id)
            if target is None:
                continue  # no resolvable note — cannot honestly stub it
            if target.fm.get("is_sensitive"):
                counts["dropped_sensitive_stubs"] += 1
                continue  # honor-system: out-of-remit sensitive entity, no stub
            entity_stubs.append(
                {
                    "id": entity_id,
                    "name": _entity_name(target.fm, entity_id),
                    "type": target.rtype,
                }
            )

    counts["units"] = len(unit_dicts)
    counts["entity_stubs"] = len(entity_stubs)

    return {
        "remit": remit_to_dict(remit),
        "counts": counts,
        "units": unit_dicts,
        "entity_stubs": entity_stubs,
    }


# -----------------------------------------------------------------------------
# Scoped modes: --list (index) / --search (grep-my-zone) / --read (full note)
# -----------------------------------------------------------------------------

_SNIPPET_WIDTH = 160  # total chars of match context returned by --search


def list_index(
    remit: RemitSpec,
    base: Path | None = None,
    include_stubs: bool = True,
) -> dict:
    """`--list`: the zone INDEX — every in-remit unit without its body + counts.

    Identical in-remit set to `resolve_corpus`, only the bodies are dropped.
    This is the navigation entrypoint: the stems here are the grounding oracle
    a role body may cite, `--read`-ing selectively for depth.
    """
    return resolve_corpus(
        remit, base=base, include_body=False, include_stubs=include_stubs
    )


def _stringify(value: Any) -> str:
    """Flatten a frontmatter value into searchable text (lists/dicts/scalars)."""
    if isinstance(value, (list, tuple)):
        return " ".join(_stringify(v) for v in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {_stringify(v)}" for k, v in value.items())
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _frontmatter_text(fm: dict) -> str:
    """One searchable `key: value` line per frontmatter entry."""
    return "\n".join(f"{key}: {_stringify(val)}" for key, val in fm.items())


def _snippet(text: str, needle_lower: str, width: int = _SNIPPET_WIDTH) -> str | None:
    """Single-line match context around the first case-insensitive hit, or None."""
    idx = text.lower().find(needle_lower)
    if idx < 0:
        return None
    half = max(0, (width - len(needle_lower)) // 2)
    start = max(0, idx - half)
    end = min(len(text), idx + len(needle_lower) + half)
    core = " ".join(text[start:end].split())  # collapse newlines / runs of ws
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{core}{suffix}"


def search_corpus(
    remit: RemitSpec,
    query: str,
    base: Path | None = None,
) -> dict:
    """`--search`: case-insensitive substring match over body + frontmatter,
    RESTRICTED to in-remit units.

    Fail-closed by construction: only the in-remit split is iterated, so a hit
    on the same keyword in an out-of-remit note is never returned. Body is
    searched first (its context is the more useful snippet), then the
    frontmatter text. Returns `{query, remit, counts, matches:[{path, snippet}]}`.
    """
    base = Path(base or repo_root()).resolve()
    _, in_remit = _resolve_units(remit, base)

    needle = (query or "").lower()
    matches: list[dict] = []
    if needle:
        for unit in in_remit:
            snippet = _snippet(unit.body, needle)
            if snippet is None:
                snippet = _snippet(_frontmatter_text(unit.fm), needle)
            if snippet is not None:
                matches.append({"path": unit.rel, "snippet": snippet})

    return {
        "query": query,
        "remit": remit_to_dict(remit),
        "counts": {
            "in_remit": len(in_remit),
            "matched": len(matches),
        },
        "matches": matches,
    }


def _split_read_paths(values: Iterable[str]) -> list[str]:
    """Flatten repeated + comma-separated `--read` values into clean rel paths."""
    out: list[str] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _read_rel(raw: str, base: Path) -> str:
    """Normalise a requested `--read` path to a base-relative posix string.

    An absolute path inside the base is relativised; anything else is returned
    as-is (and will simply not match any in-remit unit → refused).
    """
    p = Path(raw)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(base).as_posix()
        except ValueError:
            return p.as_posix()
    return Path(raw).as_posix()


def read_notes(
    remit: RemitSpec,
    raw_paths: Iterable[str],
    base: Path | None = None,
) -> dict:
    """`--read`: full body (+ subset + trio) of named IN-REMIT notes.

    The scoped-read boundary, fail-closed: a requested path that is not in the
    remit — whether it exists-but-is-out-of-remit (incl. `is_sensitive`) or does
    not exist at all — is REJECTED with an explicit `{path, refused, reason}`
    marker and its body is never returned. Returns
    `{remit, counts, notes:[…full unit…], refused:[…]}`.
    """
    base = Path(base or repo_root()).resolve()
    all_units, in_remit = _resolve_units(remit, base)
    in_remit_by_rel = {u.rel: u for u in in_remit}
    all_by_rel = {u.rel: u for u in all_units}

    notes: list[dict] = []
    refused: list[dict] = []
    for rel in _split_read_paths(raw_paths):
        norm = _read_rel(rel, base)
        unit = in_remit_by_rel.get(norm)
        if unit is not None:
            notes.append(_unit_to_dict(unit, include_body=True))
            continue
        reason = "out-of-remit" if norm in all_by_rel else "not-found"
        refused.append({"path": norm, "refused": True, "reason": reason})

    return {
        "remit": remit_to_dict(remit),
        "counts": {
            "returned": len(notes),
            "refused": len(refused),
        },
        "notes": notes,
        "refused": refused,
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _load_remit_source(args: argparse.Namespace) -> tuple[RemitSpec, RoleConfig | None]:
    """Resolve the remit from exactly one source (--role / --config / --remit-json).

    `--role` is the engine-owned scope path (config.yml → remit, the only scope
    source for a tick body); `--config` / `--remit-json` are dev/preview
    surfaces, not for the tick body (see module docstring 'Scope source' — and
    the enforced-read gating an enforced mode must add).

    Config errors surface via `die` (surface, don't guess). A malformed
    `--remit-json` degrades to an empty remit (fail-closed).

    HARD READ-LOCK (INV-15 / CONTRACT §6.1). `--config` / `--remit-json` are
    dev/preview scope OVERRIDES the tick body must never reach: they are gated
    behind `ZTN_DEV=1` (the explicit dev flag). An `--enforced` (role-bound)
    invocation — how the tool-restricted subagent runtime reads — refuses BOTH
    overrides UNCONDITIONALLY (even under `ZTN_DEV`) and REQUIRES `--role`, so the
    body cannot read around its remit by construction, not by honour.
    """
    base = Path(args.base).resolve() if args.base else None
    enforced = bool(getattr(args, "enforced", False))
    using_dev_scope = bool(args.config) or (args.remit_json is not None)
    if enforced:
        if using_dev_scope:
            die(
                "--config/--remit-json are refused in --enforced mode: the tick body "
                "reads role-bound only (--role). This is the hard read-lock (INV-15)."
            )
        if not args.role:
            die("--enforced requires --role (the body's only scope source)")
    elif using_dev_scope and os.environ.get("ZTN_DEV") != "1":
        die(
            "--config/--remit-json are dev-only scope overrides — set ZTN_DEV=1 to "
            "use them. The tick body must scope via --role (hard read-lock, INV-15)."
        )
    sources = [bool(args.role), bool(args.config), args.remit_json is not None]
    if sum(sources) != 1:
        die(
            "exactly one remit source required: "
            "--role <id> | --config <path> | --remit-json <json>"
        )

    if args.role:
        try:
            cfg = load_role_config(args.role, base)
        except RoleConfigError as exc:
            die(str(exc))
        return cfg.remit, cfg

    if args.config:
        try:
            cfg = load_role_config_file(Path(args.config))
        except RoleConfigError as exc:
            die(str(exc))
        return cfg.remit, cfg

    try:
        raw = json.loads(args.remit_json)
    except json.JSONDecodeError:
        raw = None  # fail-closed → empty remit
    return parse_remit(raw), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", default=None,
        help="ENGINE-OWNED scope: role id under _system/roles/<id>/ — resolve "
             "its config.yml remit. The ONLY scope source for a tick body",
    )
    parser.add_argument(
        "--config", default=None,
        help="DEV surface, GATED behind ZTN_DEV=1 (refused otherwise, and always in "
             "--enforced mode): explicit path to a role config.yml. NOT for the tick "
             "body — see module docstring 'Scope source' + the hard read-lock",
    )
    parser.add_argument(
        "--remit-json", default=None,
        help="DEV surface, GATED behind ZTN_DEV=1 (refused otherwise, and always in "
             "--enforced mode): inline remit JSON, fail-closed to empty. NOT for the "
             "tick body — see 'Scope source' + the hard read-lock",
    )
    parser.add_argument(
        "--enforced", action="store_true",
        help="ROLE-BOUND read (the tool-restricted subagent runtime, INV-15): require "
             "--role and refuse --config/--remit-json unconditionally, so the body "
             "cannot read around its remit by construction",
    )
    parser.add_argument(
        "--base", default=None,
        help="zettelkasten base override (else ZTN_BASE / derived)",
    )
    parser.add_argument(
        "--no-body", action="store_true",
        help="(default dump only) omit note bodies (metadata-only listing)",
    )
    parser.add_argument(
        "--no-stubs", action="store_true",
        help="(default dump / --list) omit foreign-entity stubs",
    )
    parser.add_argument(
        "--compact", action="store_true",
        help="emit compact JSON (no indent)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list", dest="list_mode", action="store_true",
        help="zone INDEX: in-remit units without bodies (+ counts) — the "
             "navigation entrypoint",
    )
    mode.add_argument(
        "--search", default=None, metavar="Q",
        help="case-insensitive substring match over body + frontmatter, "
             "restricted to in-remit units → path + snippet",
    )
    mode.add_argument(
        "--read", action="append", default=None, metavar="PATH",
        help="full body of the named in-remit note(s) — comma-separated or "
             "repeated; out-of-remit paths are rejected (fail-closed)",
    )
    args = parser.parse_args(argv)

    remit, cfg = _load_remit_source(args)
    base = Path(args.base).resolve() if args.base else None

    if args.list_mode:
        mode_name = "list"
        result = list_index(remit, base=base, include_stubs=not args.no_stubs)
    elif args.search is not None:
        mode_name = "search"
        result = search_corpus(remit, args.search, base=base)
    elif args.read:
        mode_name = "read"
        result = read_notes(remit, args.read, base=base)
    else:
        mode_name = "resolve"
        result = resolve_corpus(
            remit,
            base=base,
            include_body=not args.no_body,
            include_stubs=not args.no_stubs,
        )
    result = {
        "role_id": cfg.id if cfg is not None else None,
        "parts": [{"id": p.id, "kind": p.kind} for p in cfg.parts] if cfg is not None else None,
        "generated_at": now_iso_utc(),
        "mode": mode_name,
        **result,
    }

    indent = None if args.compact else 2
    json.dump(
        result, sys.stdout, ensure_ascii=False, indent=indent, default=_json_default
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
