#!/usr/bin/env python3
"""Registry part-plugin — the universal keyed-entry part-kind behind the seam.

A "registry" part holds a set of OWNER-SHAPED entries: things with attributes the
owner described in plain words (captured by the concierge into a schema), not a
plugin written per shape. Where a `ledger` part tracks discrete work with a moving
status and a `narrative` part holds evolving prose, a `registry` part is the
universal floor — "things with attributes" (a keeper / catalog) or "an event
stream" (a log) — that covers the vast majority of structured role-state without a
new plugin per wish.

Shape is DATA, not code. The entry schema lives in `state["schema"]` (overlaid by
the sole writer from the part's config — config is the source of truth):

    {"key": "<natural-key field name>",
     "fields": [{"name": ..., "type": "text|number|date|bool|..."}, ...],
     "append_only": bool,          # false = catalog, true = log
     "grounding": "records",       # the grounding oracle (records this slice)
     "grounding_check": bool}      # Stage 2.5 flag (read by the frame, not here)

Every hook READS the schema from state and drives its behaviour off it. The plugin
NAMES no concrete shape — it operates generically against whatever the owner
declared.

Two modes, one kind, chosen by `schema.append_only`:
  - CATALOG (`append_only: false`) — entries UPSERT by their natural key. Changing a
    tracked attribute (say an entry's location) updates that entry; `set-field` sets
    one declared field; `retire` flags an entry gone (never deletes). Serves any keyed
    collection you keep current — things with named attributes, a preferences set, a
    plain link between entries.
  - LOG (`append_only: true`) — every `append` mints a FRESH entry; existing entries
    NEVER mutate (no upsert-of-existing, no set-field). `retire` is still allowed.
    Serves a stream you only add to — dated entries you never edit later.

Identity is the NATURAL KEY, not an engine-minted `lk-NNNN`. Exact-key match is the
deterministic identity floor (a catalog upsert hits the same key or creates a new
one); near-duplicate detection (two near-identical names for one thing) is a Stage-1/2 SEMANTIC
concern, accepted non-det, NOT a HITL here. Registry therefore does NOT inherit the
ledger's minted-key + anchor-onto-Minder-id identity — `known_key_numbers` yields
nothing (registry mints no `lk` key) and `gate_identity` is a pure pass-through that
never fabricates an anchor.

`GROUNDING_MODEL = "records"` (this build): every op cites ≥1 in-remit record, checked
against the injected corpus exactly like ledger/narrative (`roles_common`). Provenance
grows append-only; a catalog update PRESERVES the prior value in the entry's own
grow-only history trail, so a mutation never silently erases the old fact.

Exposes the per-part plugin interface (the SAME hooks ledger/narrative expose):
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODEL, CONCIERGE_MANIFEST, REGISTRY_VERSION,
  REQUIRES_SCHEMA (the config loader reads this to require a schema, then delegates
    its shape validation to `validate_schema` below — the loader inspects no shape),
  validate_schema(raw)                  -> dict  (canonical schema; raises on malformed)
  fresh_state()                         -> dict  (generic skeleton; schema placeholder)
  known_key_numbers(state)              -> Iterable[int]  (registry mints no keys)
  validate(prior_state, delta_payload)  -> ValidationResult
  persist(prior_state, approved_deltas, key_minter) -> new_state
  render(state)                         -> str   (state.md AUTO sub-zone body)
  identity(item, anchors)               -> IdentityResult  (n/a — natural keys)
  gate_identity(role_id, part_id, prior_state, approved) -> (kept, [])
  build_decisions(approved, minted, prior_state, role_id, part_id, hook, ts) -> list[dict]
  cold_materialize_decisions(adopted_state, role_id, part_id, ts) -> list[dict]
  delta_counts(persisted_deltas) -> (added, advanced)
  content_view(state)                   -> dict  (content frozen at cold-start)
  adopt_staging(prior_state, staging)   -> new_state
  content_summary(state)                -> list[str]
  consumed_records(state)               -> Iterable[str]
  registry_summary(state)               -> dict

Deterministic, no LLM. Cross-platform: pure in-memory transforms; the caller owns
all I/O (atomic writes, hashing) via `roles_common` / `roles_persist`.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from _common import today_iso

from roles_common import (
    ClarificationSignal,
    IdentityResult,
    PART_GROUNDING_MODES,
    RoleConfigError,
    ValidationResult,
    clean_evidence,
    decision_row,
    delta_ref,
    grow_provenance,
    is_valid_iso_date,
    nonempty_str,
    normalize_record_ref,
    read_int_tunable,
    read_record_corpus,
    resolve_role_id,
    truncate,
    ungrounded_refs,
)


# -----------------------------------------------------------------------------
# Archetype identity + vocabulary
# -----------------------------------------------------------------------------

ARCHETYPE = "registry"

# The default/documentary grounding for this kind. The REAL grounding is per-part:
# `validate()` branches on the part's `schema.grounding` (records | owner-confirm). A
# record-cited op writes in EITHER mode; an uncited op is rejected under `records` and
# surfaces a `role-owner-confirm` proposal (never auto-written) under `owner-confirm`.
# `external` (a tool-pull) stays a designed Layer-2 seam, not accepted here.
GROUNDING_MODEL = "records"

# Signals the composite config loader (`roles_common._parse_parts`) that a registry
# part MUST carry a well-formed `schema:` block (a natural key + typed fields) and
# lets the loader validate it fail-closed. A kind without this flag (ledger /
# narrative) needs no schema — the loader leaves its PartSpec schema empty.
REQUIRES_SCHEMA = True

# Ops the tick body may propose. `append` is LOG-only (mints a fresh entry every
# time); `upsert` / `set-field` are CATALOG-only (add-or-update / set one field);
# `retire` flags an entry gone (never deletes) in EITHER mode. Order does not dictate
# persist application order.
DELTAS: tuple[str, ...] = ("upsert", "append", "set-field", "retire")

# The catalog ops (add-or-update by natural key). A log rejects these.
_CATALOG_OPS: frozenset[str] = frozenset({"upsert", "set-field"})
# The single log op. A catalog rejects it.
_LOG_OPS: frozenset[str] = frozenset({"append"})

# Fields the body may NEVER set directly on a delta — engine-owned (stamped on
# persist). A delta carrying any of them is rejected (append-not-replace).
_BODY_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {"history", "provenance", "retired", "retire_reason", "first_seen", "last_updated"}
)

# Loosely-checked declared field types (schema §3.5 "types loosely valid"). An
# unrecognised type accepts any non-null value (forward-compatible — a future type
# lands without a validator change); a `null` value always passes (clears / omits).
_TYPE_VALIDATORS: dict[str, Any] = {
    "text": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "date": lambda v: isinstance(v, str) and is_valid_iso_date(v.strip()),
}

# Registry schema version — bumped only on an incompatible shape change (with a
# matching migration). Additive-optional changes keep it stable.
REGISTRY_VERSION = 1

# Default churn ceiling: catalog mutations (update / set-field / retire / create) per
# tick over an ESTABLISHED registry. A garbled tick exceeding it is HELD. Fresh LOG
# appends are EXEMPT (§1) — a busy logging day never trips it.
DEFAULT_CHURN_THRESHOLD = 5

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned keyed-entry registry. Written ONLY by roles_persist.py through "
        "this plugin. Never hand-edited. Its `schema` is overlaid from config.yml on "
        "every load — config is the source of truth for the shape."
    ),
    "top_level": {
        "version": "int (schema version of the registry file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'registry'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": "str|null (high-water mark of consumed records)",
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "churn_threshold": f"int (catalog mutations ceiling per tick; default {DEFAULT_CHURN_THRESHOLD})",
        "schema": (
            "object {key, fields:[{name,type}], append_only, grounding, grounding_check} "
            "— overlaid from config; drives all behaviour"
        ),
        "entries": "list[entry] (append-only set; entries flag-retired, never deleted)",
    },
    "entry": {
        "key": "str (the owner-declared natural key value — the identity)",
        "fields": "object {field_name: value} — only the SET declared fields",
        "history": "list[{field, from, to, at}] (grow-only field version trail)",
        "provenance": "list[str]  ('[[record-basename]]', append-only, grows)",
        "retired": "bool (flag-gone; never deleted)",
        "retire_reason": "str (present iff retired — the Archive-Contract reason)",
        "first_seen": "str  (YYYY-MM-DD)",
        "last_updated": "str  (YYYY-MM-DD)",
    },
}


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language WITHOUT ever exposing the word
# "archetype" / "schema" / "kind" to the owner. `plain_purpose` + `triggers` match a
# plain wish to this part; `produces_preview` shows the shape; `determinism_note`
# DISCLOSES the honesty level. `built: True` marks it installed + composable now.
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Keep track of a set of things you describe — a catalog you keep up to date "
        "(items each with a name, a location, a category — updated as they change) OR "
        "a running log you keep adding to over time (dated entries you never edit "
        "later). You name what each entry is and what to remember about it; the engine "
        "keeps the list honest."
    ),
    "triggers": [
        "помни что и где",
        "веди каталог / список вещей",
        "держи мои предпочтения",
        "веди журнал, только дополняя",
        "добавляй новую запись каждый раз",
        "keep track of what and where",
        "keep a catalog of things",
        "hold my preferences",
        "keep a running log I only add to",
        "add an entry each time, never edit the past",
    ],
    "produces_preview": (
        "A present-state list of your entries — a catalog updates an entry in place "
        "when something changes (keeping the old value in a history trail), a log adds "
        "a fresh entry each time. Each entry shows only the attributes you've set, with "
        "retired entries flagged, and every change cites the record that prompted it."
    ),
    "determinism_note": (
        "MEDIUM determinism: the engine guarantees each entry keeps its natural key, "
        "that a catalog update never erases the prior value (it keeps a history trail), "
        "that nothing is ever deleted (retire only flags), that every change cites a "
        "real in-remit record, and that a garbled flood is held. It does NOT judge "
        "whether two similarly-named entries are the same thing — that reading is the "
        "tick body's, shown as such."
    ),
    "built": True,
}


# -----------------------------------------------------------------------------
# Config-time schema hook — the plugin owns its own schema shape (the seam)
# -----------------------------------------------------------------------------

def validate_schema(raw: Any) -> dict:
    """Validate the raw `schema:` block from a registry part's config; return the
    canonical schema dict, or raise `RoleConfigError` on any malformed input.

    This is the plugin side of the composite loader seam: because `REQUIRES_SCHEMA`
    is set, `roles_common._parse_part_schema` dispatches the raw `schema:` block here
    and never inspects its shape itself. THIS plugin owns the registry schema
    contract — a natural `key` field name, a non-empty list of `{name, type}` fields
    (unique names, string types), a `grounding` in `PART_GROUNDING_MODES`, plus the
    boolean `append_only` / `grounding_check` defaults. A future schema-bearing kind
    ships its own `validate_schema` with a different shape and the loader is unchanged.

    Error messages carry the shape-specific detail only (they name no config path or
    part id); the loader locates them to `{path}: part {pid!r}` when it catches. The
    returned dict `{key, fields, append_only, grounding, grounding_check}` is the
    canonical schema the plugin's runtime hooks read (shape lives in DATA, not code),
    and the loader lifts `grounding` / `append_only` / `grounding_check` off it as the
    PartSpec convenience mirrors.
    """
    if not isinstance(raw, dict):
        raise RoleConfigError(
            "needs a 'schema:' block (a natural key + typed fields), got "
            f"{type(raw).__name__}"
        )
    key = raw.get("key")
    if not isinstance(key, str) or not key.strip():
        raise RoleConfigError(
            f"schema 'key' must be a non-empty field name, got {key!r}"
        )
    key = key.strip()

    raw_fields = raw.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise RoleConfigError(
            "schema 'fields' must be a non-empty list of {name, type} entries"
        )
    fields: list[dict] = []
    seen_names: set[str] = set()
    for fidx, f in enumerate(raw_fields):
        if not isinstance(f, dict):
            raise RoleConfigError(
                f"schema fields[{fidx}] must be a mapping with 'name' and 'type'"
            )
        fname = f.get("name")
        if not isinstance(fname, str) or not fname.strip():
            raise RoleConfigError(
                f"schema fields[{fidx}].name must be a non-empty string, got {fname!r}"
            )
        fname = fname.strip()
        if fname in seen_names:
            raise RoleConfigError(
                f"schema has a duplicate field name {fname!r}"
            )
        ftype = f.get("type")
        if not isinstance(ftype, str) or not ftype.strip():
            raise RoleConfigError(
                f"schema field {fname!r} must declare a string 'type', got {ftype!r}"
            )
        seen_names.add(fname)
        fields.append({"name": fname, "type": ftype.strip()})

    grounding = raw.get("grounding", "records")
    if not isinstance(grounding, str) or grounding.strip() not in PART_GROUNDING_MODES:
        raise RoleConfigError(
            "schema 'grounding' must be one of "
            f"{sorted(PART_GROUNDING_MODES)}, got {grounding!r}"
        )
    grounding = grounding.strip()
    append_only = bool(raw.get("append_only", False))
    grounding_check = bool(raw.get("grounding_check", False))
    return {
        "key": key,
        "fields": fields,
        "append_only": append_only,
        "grounding": grounding,
        "grounding_check": grounding_check,
    }


def fresh_state() -> dict:
    """A brand-new registry's top-level fields with archetype defaults filled.

    NULLARY — the SINGLE HOME for the registry-owned fresh-state defaults (most
    importantly `churn_threshold`). `schema` is a `{}` PLACEHOLDER: the sole writer
    overlays the real config-declared schema onto both a fresh seed and a loaded
    state (config is the source of truth for the shape), so this stays generic. The
    common writer overlays the per-instance fields it owns (`role_id`, `part_id`,
    `archetype`, `description`). Returns a fresh dict each call.
    """
    return {
        "version": REGISTRY_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": DEFAULT_CHURN_THRESHOLD,
        "schema": {},
        "entries": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Registry mints no `lk-NNNN` keys — its identity is the owner's natural key.

    Yields nothing. The common `KeyMinter.for_part` therefore starts at 1, but
    `persist` never calls the minter (registry keys are the owner's own values), so
    no `lk` key is ever minted for a registry part. Present so the writer can call it
    uniformly across every part-kind (the seam never special-cases registry)."""
    return ()


# -----------------------------------------------------------------------------
# Schema + state accessors (shape lives in DATA; every hook reads it here)
# -----------------------------------------------------------------------------

def _schema(state: Any) -> dict:
    if not isinstance(state, dict):
        return {}
    schema = state.get("schema")
    return schema if isinstance(schema, dict) else {}


def _key_field(state: Any) -> str:
    """The name of the natural-key field the owner declared, or '' when absent."""
    key = _schema(state).get("key")
    return key.strip() if isinstance(key, str) else ""


def _append_only(state: Any) -> bool:
    return bool(_schema(state).get("append_only"))


def _field_order(schema: dict) -> list[str]:
    """Declared field names in schema order (drives render / content order)."""
    out: list[str] = []
    for f in schema.get("fields", []) if isinstance(schema, dict) else []:
        if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"].strip():
            out.append(f["name"].strip())
    return out


def _fields_by_name(schema: dict) -> dict[str, Any]:
    """`{field_name: declared_type}` for the declared fields."""
    out: dict[str, Any] = {}
    for f in schema.get("fields", []) if isinstance(schema, dict) else []:
        if isinstance(f, dict) and isinstance(f.get("name"), str) and f["name"].strip():
            out[f["name"].strip()] = f.get("type")
    return out


def _entries(state: Any) -> list[dict]:
    """The entry list of a live state OR a staging dict (both carry `entries`)."""
    if not isinstance(state, dict):
        return []
    entries = state.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _entry_key(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    key = entry.get("key")
    return key.strip() if isinstance(key, str) else ""


def _is_live(entry: dict) -> bool:
    return not bool(entry.get("retired"))


def _live_entries(entries: Iterable[dict]) -> list[dict]:
    return [e for e in entries if isinstance(e, dict) and _is_live(e)]


def _live_index(entries: Iterable[dict]) -> dict[str, dict]:
    """Live entries indexed by natural key. In a CATALOG a key is unique among live
    entries (the validator blocks a duplicate); in a LOG this is not built for
    identity (a log addresses nothing by key except an unambiguous retire)."""
    out: dict[str, dict] = {}
    for e in entries:
        k = _entry_key(e)
        if k and _is_live(e):
            out[k] = e
    return out


def _clean_fields(raw: Any, declared: list[str]) -> dict:
    """Keep only the DECLARED fields with a non-null value, in schema order."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for name in declared:
        if name in raw and raw[name] is not None:
            out[name] = raw[name]
    return out


# -----------------------------------------------------------------------------
# validate — structural + semantic gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed registry delta payload before it may be persisted.

    STRUCTURAL: the payload envelope parses; `op` is known AND allowed in the part's
    mode (a catalog rejects `append`; a log rejects `upsert` / `set-field`); no
    engine-owned field is body-set; the natural `key` is present; a catalog does not
    already hold a duplicate LIVE key (a blocking integrity failure); fields conform
    to the declared schema (declared names only, loosely-typed); a `set-field` /
    `retire` resolves to an existing live entry; a key is not touched twice this tick.

    SEMANTIC: grounding (every op cites ≥1 record present in `read_records` — uncited
    is rejected); append-only + grow-only (structural — a catalog update preserves the
    prior value in history, retire flags rather than deletes, a log never mutates an
    existing entry); churn-guard (on an ESTABLISHED registry, a catalog mutation /
    retire burst over the threshold — or a wholesale rewrite of the live set — is HELD;
    fresh LOG appends are exempt).

    Same contract shape as ledger/narrative: ok=True persists `approved_deltas`
    (possibly empty), ok=False blocks the whole tick (malformed envelope, corrupt prior
    state, missing schema, or churn hold).
    """
    if not isinstance(delta_payload, dict):
        return ValidationResult.rejected(
            rejections=({"ref": "payload", "reason": "delta payload is not a mapping"},)
        )
    raw_deltas = delta_payload.get("deltas")
    if not isinstance(raw_deltas, list):
        return ValidationResult.rejected(
            rejections=({"ref": "payload", "reason": "'deltas' must be a list"},)
        )

    schema = _schema(prior_state)
    if not nonempty_str(schema.get("key")):
        # Defensive — the config loader requires a valid schema before a registry
        # part loads, but a corrupt state with no schema cannot be validated. Hold.
        return ValidationResult.rejected(
            rejections=({"ref": "schema", "reason": "registry schema has no natural 'key' field"},)
        )

    append_only = bool(schema.get("append_only"))
    declared = _fields_by_name(schema)
    prior_entries = _entries(prior_state)
    prior_live = _live_entries(prior_entries)

    # Corrupt catalog (duplicate LIVE keys) is a blocking integrity failure — an
    # upsert over it could resolve ambiguously. Hold, do not guess a repair. A LOG
    # legitimately holds duplicate keys (two appends), so this applies to catalogs.
    if not append_only:
        live_keys = [_entry_key(e) for e in prior_live if _entry_key(e)]
        if len(live_keys) != len(set(live_keys)):
            return ValidationResult.rejected(
                rejections=({"ref": "prior_state",
                             "reason": "duplicate live keys in catalog registry"},)
            )

    live_index = _live_index(prior_live)
    corpus = read_record_corpus(delta_payload)
    role_id = resolve_role_id(delta_payload, prior_state)
    grounding = str(schema.get("grounding") or "records").strip()

    approved: list[dict] = []
    rejections: list[dict] = []
    proposed: list[dict] = []  # uncited owner-confirm proposals — surfaced, never written
    touched: set[str] = set()  # natural keys mutated/created this tick (non-append)

    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": "delta is not a mapping"})
            continue
        reason = _validate_delta(
            delta, schema, declared, append_only, prior_live, live_index, touched
        )
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": reason})
            continue
        # Grounding, routed per the part's mode. A record-cited op writes in EITHER mode.
        g_reason = _grounding_reason(delta, corpus)
        if g_reason is None:
            approved.append(delta)
        elif grounding == "owner-confirm":
            # A role-proposed owner-fact with no note to cite is NEVER auto-written — it
            # surfaces for the owner to ratify. Not a rejection (no auto-pause pressure).
            proposed.append(delta)
        else:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": g_reason})

    churn = _churn_guard(prior_live, approved, prior_state, role_id)
    if churn is not None:
        return ValidationResult(ok=False, clarifications=(churn,))

    clarifications: tuple = ()
    if proposed:
        clarifications = (_owner_confirm_signal(role_id, proposed, schema),)

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
        clarifications=clarifications,
    )


def _grounding_reason(delta: dict, corpus: set[str]) -> str | None:
    """None when the op cites ≥1 real in-remit record; else a reason. Records is the
    deterministic oracle (`corpus` is the engine-injected `read_records`, which the
    body cannot forge). The caller routes this per the part's grounding mode: `records`
    rejects an uncited op; `owner-confirm` surfaces it as a proposal instead."""
    op = delta.get("op")
    evidence = delta.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return f"{op} 'evidence' must cite at least one read record"
    missing = ungrounded_refs(evidence, corpus)
    if missing:
        return f"ungrounded: {op} evidence not in read_records: {missing}"
    return None


def _owner_confirm_signal(
    role_id: str, proposed: list[dict], schema: dict
) -> ClarificationSignal:
    """A `role-owner-confirm` proposal: in an `owner-confirm` registry the role wants to
    record owner-facts it has no note to cite. These are NEVER auto-written — a role
    never asserts a fact on the owner's behalf. The owner ratifies the true ones."""
    key_field = str(schema.get("key") or "key")
    lines = []
    for d in proposed[:12]:
        k = str(d.get("key") or "").strip()
        fields = d.get("fields") if isinstance(d.get("fields"), dict) else {}
        desc = ", ".join(f"{n}={v}" for n, v in fields.items()) if fields else ""
        lines.append(f"  - {d.get('op')} {key_field}={k}" + (f" ({desc})" if desc else ""))
    # Subject is the role id, so the CLARIFICATION dedup surfaces ONE open proposal
    # batch per role at a time: the owner ratifies (or dismisses) it and the next
    # tick's still-uncited facts surface as the next batch — batch-at-a-time, never a
    # per-tick pile-up of overlapping proposals.
    return ClarificationSignal(
        ctype="role-owner-confirm",
        subject=role_id,
        context=(
            f"Role `{role_id}` proposes recording {len(proposed)} owner-fact(s) it has "
            f"no in-zone note to cite (an `owner-confirm` registry). Nothing was written "
            f"— a role never asserts a fact on your behalf. Confirm any that are true:\n"
            + "\n".join(lines)
        ),
        source=f"roles tick for {role_id} (owner-confirm proposal)",
        suggested_action=(
            "Add the true ones via `/ztn:role:edit`, or let them become notes and the "
            "next tick cites them; ignore the rest."
        ),
        action_taken="Surfaced as a proposal; nothing written (owner ratifies).",
    )


def _validate_delta(
    delta: dict,
    schema: dict,
    declared: dict[str, Any],
    append_only: bool,
    prior_live: list[dict],
    live_index: dict[str, dict],
    touched: set[str],
) -> str | None:
    """Return a STRUCTURAL rejection reason, or None when the delta is well-formed.

    Grounding is checked separately (`_grounding_reason`) so it can be routed per the
    part's grounding mode. Mutates `touched` with any natural key a non-append op
    creates / mutates, so a later delta touching the same key this tick is a conflict."""
    op = delta.get("op")
    if op not in DELTAS:
        return f"unknown op {op!r}"
    # Mode gating — a data flag, not a second plugin (§1).
    if append_only and op in _CATALOG_OPS:
        return f"append-only registry (a log): use 'append', not {op!r} — existing entries never mutate"
    if not append_only and op in _LOG_OPS:
        return "catalog registry: use 'upsert', not 'append' ('append' is for append-only logs)"

    for forbidden in _BODY_FORBIDDEN_FIELDS:
        if forbidden in delta:
            return f"append-not-replace: '{forbidden}' is engine-owned, not body-set"

    key = delta.get("key")
    if not nonempty_str(key):
        return f"{op} missing non-empty natural 'key'"
    key = key.strip()

    if op == "append":
        # A fresh log entry — no same-tick key conflict (duplicate keys are the norm).
        return _validate_field_map(delta.get("fields"), declared)

    # Catalog ops + retire address a single entry — one touch per key per tick.
    if key in touched:
        return f"{op} 'key' {key!r} is already created/mutated by another delta this tick"

    if op == "upsert":
        field_err = _validate_field_map(delta.get("fields"), declared)
        if field_err is not None:
            return field_err
        touched.add(key)
        return None

    if op == "set-field":
        if key not in live_index:
            return f"set-field 'key' {key!r} does not exist as a live entry"
        field = delta.get("field")
        if field not in declared:
            return f"set-field 'field' must be a declared field {sorted(declared)}, got {field!r}"
        val_err = _validate_field_value(field, delta.get("value"), declared[field])
        if val_err is not None:
            return f"set-field {val_err}"
        touched.add(key)
        return None

    if op == "retire":
        if not nonempty_str(delta.get("reason")):
            return "retire requires a non-empty 'reason' (the Archive-Contract reason)"
        matches = [e for e in prior_live if _entry_key(e) == key]
        if not matches:
            return f"retire 'key' {key!r} does not exist as a live entry"
        if len(matches) > 1:
            return f"retire 'key' {key!r} is ambiguous — matches {len(matches)} live entries"
        touched.add(key)
        return None

    return f"unhandled op {op!r}"  # unreachable — op membership checked above


def _validate_field_map(raw: Any, declared: dict[str, Any]) -> str | None:
    """Validate an `upsert` / `append` `fields` map: declared names only, each value
    loosely-typed. A missing / null `fields` is allowed (an entry with just its key)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return "'fields' must be a mapping of declared field → value"
    for name, value in raw.items():
        if name not in declared:
            return f"unknown field {name!r} — not in the declared schema {sorted(declared)}"
        val_err = _validate_field_value(name, value, declared[name])
        if val_err is not None:
            return val_err
    return None


def _validate_field_value(name: str, value: Any, declared_type: Any) -> str | None:
    """Loosely validate one field value against its declared type. `null` always
    passes (clears / omits). An unrecognised type accepts any non-null value."""
    if value is None:
        return None
    validator = _TYPE_VALIDATORS.get(declared_type) if isinstance(declared_type, str) else None
    if validator is not None and not validator(value):
        return f"field {name!r} value {value!r} is not a valid {declared_type}"
    return None


def _churn_guard(
    prior_live: list[dict],
    approved: list[dict],
    prior_state: Any,
    role_id: str,
) -> ClarificationSignal | None:
    """Hold a tick that floods an ESTABLISHED registry with mutations / retires.

    A fresh registry (no live entries) is cold-start territory (owned by the writer's
    staging), never churn. Otherwise two independent triggers fire a hold:

      - all_keys_sweep — every entry of a NON-TRIVIAL live set (≥2 entries) would be
        RETIRED this tick, emptying the present set. Retire is the only "sweep" op:
        an update / set-field annotates an entry in place (the primary catalog use —
        say an entry's location changed), so it never counts toward this trigger; a
        single-entry registry cannot be swept (one mutation is not a burst).
      - volume — total non-append operations this tick (create + update + set-field +
        retire) exceed `churn_threshold`. This is the scale backstop that DOES catch
        a mass update. LOG appends are EXEMPT entirely (§1): a busy logging day is
        normal, so only a log's retires count toward the volume.
    """
    live_keys = {_entry_key(e) for e in prior_live if _entry_key(e)}
    if not live_keys:
        return None  # empty / freshly-drafted registry → cold-start owns this

    threshold = read_int_tunable(prior_state, "churn_threshold", DEFAULT_CHURN_THRESHOLD)
    retired_keys: set[str] = set()
    volume = 0
    for d in approved:
        op = d.get("op")
        if op == "append":
            continue  # fresh log append — exempt entirely (§1)
        key = d.get("key")
        key = key.strip() if nonempty_str(key) else ""
        volume += 1
        if op == "retire":
            retired_keys.add(key)  # the only op that empties the live set

    all_keys_sweep = len(live_keys) >= 2 and live_keys.issubset(retired_keys)
    if not (all_keys_sweep or volume > threshold):
        return None

    reasons: list[str] = []
    if all_keys_sweep:
        reasons.append(
            f"every one of {len(live_keys)} live entry(ies) would be retired this tick"
        )
    if volume > threshold:
        reasons.append(
            f"{volume} catalog mutation(s) exceed the churn threshold of {threshold}"
        )
    detail = "; ".join(reasons)
    return ClarificationSignal(
        ctype="role-churn-guard",
        subject=role_id,
        context=(
            f"The tick proposed a wholesale rewrite of the registry ({detail}). "
            "This is held rather than written so a garbled or over-eager tick cannot "
            "silently replace the tracked entries. Review the proposed deltas and "
            "confirm before any are applied."
        ),
        source=f"roles tick for {role_id}",
        suggested_action=(
            "Review the held deltas; if the rewrite is intended, re-run the tick "
            "after raising churn_threshold, or approve the deltas manually."
        ),
        action_taken="Held — nothing was persisted this tick.",
        confidence_tier="surfaced",
    )


# -----------------------------------------------------------------------------
# persist — pure transform (roles_persist is the sole caller / writer)
# -----------------------------------------------------------------------------

def persist(prior_state: Any, approved_deltas: Iterable[dict], key_minter) -> dict:
    """Apply already-validated deltas to a copy of `prior_state`; return new state.

    Pure: no I/O, never mutates inputs, never calls `key_minter` (registry keys are
    the owner's natural values, not minted). Per op:
      - `append`  → mint a fresh entry (log; existing entries untouched).
      - `upsert`  → update the live entry with that natural key (prior values preserved
                    in the grow-only history trail), or create it when new.
      - `set-field` → set one declared field on the live entry; history grows.
      - `retire`  → flag the live entry gone (never deletes); provenance grows.

    History never blanks: a catalog update records `{field, from, to, at}` before
    overwriting, `first_seen` is preserved, provenance only grows, and a retirement
    keeps the entry and its trail intact.
    """
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    entries = new_state.get("entries")
    if not isinstance(entries, list):
        entries = []
    new_state["entries"] = entries
    schema = _schema(new_state)
    declared = _field_order(schema)
    today = today_iso()
    live_index = _live_index(it for it in entries if isinstance(it, dict))

    for delta in approved_deltas:
        if not isinstance(delta, dict):
            continue
        op = delta.get("op")
        key = delta.get("key")
        key = key.strip() if nonempty_str(key) else ""
        if not key:
            continue
        if op == "append":
            entries.append(_new_entry(key, delta, declared, today))
        elif op == "upsert":
            existing = live_index.get(key)
            if existing is None:
                item = _new_entry(key, delta, declared, today)
                entries.append(item)
                live_index[key] = item
            else:
                _apply_field_updates(existing, _clean_fields(delta.get("fields"), declared),
                                     delta.get("evidence"), today)
        elif op == "set-field":
            existing = live_index.get(key)
            if existing is not None:
                _apply_field_updates(existing, {delta.get("field"): delta.get("value")},
                                     delta.get("evidence"), today)
        elif op == "retire":
            _apply_retire(entries, key, delta.get("reason"), delta.get("evidence"), today)

    return new_state


def _new_entry(key: str, delta: dict, declared: list[str], today: str) -> dict:
    return {
        "key": key,
        "fields": _clean_fields(delta.get("fields"), declared),
        "history": [],
        "provenance": grow_provenance([], delta.get("evidence") or []),
        "retired": False,
        "first_seen": today,
        "last_updated": today,
    }


def _apply_field_updates(
    entry: dict, updates: dict, evidence: Any, today: str
) -> None:
    """Set the given fields on a live entry, recording each real change in the
    grow-only history trail (prior value preserved), then grow provenance. A `null`
    value clears the field (recorded as a change when it was previously set)."""
    fields = entry.get("fields")
    if not isinstance(fields, dict):
        fields = {}
        entry["fields"] = fields
    history = entry.get("history")
    if not isinstance(history, list):
        history = []
        entry["history"] = history
    changed = False
    for name, value in updates.items():
        if not isinstance(name, str) or not name:
            continue
        old = fields.get(name)
        if value == old:
            continue  # no real change — do not grow history on a no-op
        history.append({"field": name, "from": old, "to": value, "at": today})
        if value is None:
            fields.pop(name, None)
        else:
            fields[name] = value
        changed = True
    entry["provenance"] = grow_provenance(entry.get("provenance"), evidence or [])
    if changed or evidence:
        entry["last_updated"] = today


def _apply_retire(
    entries: list[dict], key: str, reason: Any, evidence: Any, today: str
) -> None:
    """Flag the single live entry with `key` as retired (never deletes). Validate
    guaranteed exactly one live match, so the first live match is unambiguous."""
    for entry in entries:
        if _entry_key(entry) == key and _is_live(entry):
            entry["retired"] = True
            entry["retire_reason"] = str(reason or "").strip()
            entry["provenance"] = grow_provenance(entry.get("provenance"), evidence or [])
            entry["last_updated"] = today
            return


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

def render(state: Any) -> str:
    """Render the registry as the state.md AUTO-zone markdown body (present-state).

    Entries are grouped by a `category` field when the schema declares one (else a
    flat list); within a group they sort by natural key. Each entry renders as
    `- {key} · {field}:{value} …` showing ONLY the set fields, with a `· retired
    (reason)` suffix on retired entries. The caller wraps this in the role-state
    markers."""
    entries = _entries(state)
    if not entries:
        return "_No entries yet._"
    schema = _schema(state)
    field_order = _field_order(schema)
    group_field = "category" if "category" in field_order else None

    lines: list[str] = []
    if group_field is not None:
        groups: dict[str, list[dict]] = {}
        for e in entries:
            cat = e.get("fields", {}).get(group_field) if isinstance(e.get("fields"), dict) else None
            groups.setdefault(str(cat).strip() if nonempty_str(cat) else "—", []).append(e)
        for cat in sorted(groups):
            lines.append(f"### {cat}")
            lines.append("")
            for e in sorted(groups[cat], key=_entry_key):
                lines.append(_render_entry(e, field_order, group_field))
            lines.append("")
    else:
        for e in sorted(entries, key=_entry_key):
            lines.append(_render_entry(e, field_order, None))

    return "\n".join(lines).rstrip() + "\n"


def _render_entry(entry: dict, field_order: list[str], skip_field: str | None) -> str:
    key = _entry_key(entry) or "(no key)"
    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
    bits: list[str] = []
    for name in field_order:
        if name == skip_field:
            continue  # shown as the group header
        if name in fields:
            bits.append(f"{name}:{fields[name]}")
    # Any set field not in the declared order (defensive — never drop a set value).
    for name in fields:
        if name not in field_order and name != skip_field:
            bits.append(f"{name}:{fields[name]}")
    line = f"- {key}"
    if bits:
        line += " · " + " · ".join(bits)
    if entry.get("retired"):
        reason = str(entry.get("retire_reason") or "").strip()
        line += " · retired" + (f" ({reason})" if reason else "")
    return line


# -----------------------------------------------------------------------------
# identity — natural keys; no external anchor concept (never guesses)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Registry entries are identified by the owner's NATURAL KEY, not an external
    Minder id — exact-key match is the deterministic identity floor. There is nothing
    to anchor and nothing to guess, so this returns `anchored=True` and never
    fabricates an anchor. The writer never calls this for a registry part (no anchor
    op reaches the identity gate); present for interface uniformity."""
    return IdentityResult(anchored=True, anchor=None)


# -----------------------------------------------------------------------------
# Composite-seam hooks (mirror ledger/narrative; registry-shaped)
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Registry has no anchor-identity concept — every approved delta passes.

    Returns `(approved, [])`. The anchor-else-HITL gate is a ledger-item mechanic; a
    registry entry is identified by its exact natural key (deterministic), and
    near-duplicate keys are a Stage-1/2 SEMANTIC concern, not a HITL here. This never
    fabricates an anchor."""
    return list(approved), []


def build_decisions(
    approved_deltas: list[dict],
    minted: list[str],
    prior_state: Any,
    role_id: str,
    part_id: str,
    hook: str,
    ts: str,
) -> list[dict]:
    """One decision row per persisted registry delta, stamped `part`.

    Registry `kind` vocabulary: entry-create / entry-update (an upsert that hit an
    existing live key) / entry-append / entry-field-set / entry-retire. No `lk` keys
    are minted, so `minted` is ignored and the row `key` is the entry's natural key
    (a reader joins a row to its entry by that key)."""
    prior_live = _live_index(_entries(prior_state))
    rows: list[dict] = []
    for d in approved_deltas:
        op = d.get("op")
        key = d.get("key")
        evidence = clean_evidence(d.get("evidence"))
        if op == "append":
            rows.append(decision_row("entry-append", key, hook, role_id, part_id, ts,
                                     evidence=evidence))
        elif op == "upsert":
            kind = "entry-update" if key in prior_live else "entry-create"
            rows.append(decision_row(kind, key, hook, role_id, part_id, ts,
                                     evidence=evidence))
        elif op == "set-field":
            rows.append(decision_row("entry-field-set", key, hook, role_id, part_id, ts,
                                     field=d.get("field"), to=d.get("value"), evidence=evidence))
        elif op == "retire":
            rows.append(decision_row("entry-retire", key, hook, role_id, part_id, ts,
                                     reason=d.get("reason"), evidence=evidence))
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts — the registry's op vocabulary.

    `append` and `upsert` put an entry (add-or-update) → counted as ADDED; `set-field`
    and `retire` change an existing one → ADVANCED. (An `upsert` that only updated a
    live entry is counted as added too — the pure delta list carries no prior state to
    tell create from update; the imprecision is cosmetic run-count only.)"""
    added = sum(
        1 for d in persisted_deltas
        if isinstance(d, dict) and d.get("op") in ("append", "upsert")
    )
    advanced = sum(
        1 for d in persisted_deltas
        if isinstance(d, dict) and d.get("op") in ("set-field", "retire")
    )
    return added, advanced


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per entry when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", e.get("key"), "tick", role_id, part_id, ts,
            evidence=clean_evidence(e.get("provenance")), retired=bool(e.get("retired")),
        )
        for e in _entries(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start.

    Registry content is its `entries` list. The writer spreads this into the staging
    dict and adopts it later via `adopt_staging`; the schema is NOT frozen (the writer
    re-overlays it from config on every load — config is the source of truth)."""
    return {"entries": list(_entries(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state.

    Returns a deep copy of `prior_state` (which already carries the config-overlaid
    schema) with its `entries` replaced by the staged draft's. The writer clears
    `staging`, resets the reject counter and advances the watermark over
    `consumed_records`."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    src = staging.get("entries") if isinstance(staging, dict) else None
    ns["entries"] = [e for e in src if isinstance(e, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification + count).

    ONE label per entry — its natural key plus its set fields (and `(retired)` when
    flagged). Works on both a live state and a staging dict; an empty list means the
    part carries no content."""
    return [_entry_label(e) for e in _entries(state)]


def _entry_label(entry: dict) -> str:
    key = _entry_key(entry) or "(no key)"
    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
    body = ", ".join(f"{n}={fields[n]}" for n in fields)
    label = f"{key}: {body}" if body else key
    if entry.get("retired"):
        label += " (retired)"
    return truncate(label)


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites (watermark advance on adopt).

    Works on both a live state and a staging dict. Registry content grounds in each
    entry's provenance trail; non-record refs normalise to empty and are dropped."""
    for e in _entries(state):
        for ref in e.get("provenance") or []:
            stem = normalize_record_ref(ref)
            if stem:
                yield stem


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[label,count],...], staged}`. Total = all entries; breakdown =
    live vs retired present-state counts (non-zero only); staged = a frozen cold-start
    draft's entries. The render layer reads only this dict, never the registry's
    internal entry shape. Tolerant of a partially-written / corrupt state."""
    raw = state.get("entries") if isinstance(state, dict) else None
    entries = raw if isinstance(raw, list) else []
    total = 0
    live = 0
    retired = 0
    for e in entries:
        if not isinstance(e, dict):
            continue
        total += 1
        if e.get("retired"):
            retired += 1
        else:
            live += 1
    breakdown: list[list] = []
    if live:
        breakdown.append(["live", live])
    if retired:
        breakdown.append(["retired", retired])
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("entries"), list):
        staged = sum(1 for x in staging["entries"] if isinstance(x, dict))
    return {"total": total, "breakdown": breakdown, "staged": staged}
