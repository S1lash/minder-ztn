#!/usr/bin/env python3
"""Ledger part-plugin — one part-kind behind the composite seam (BUILD-CONTRACT §2).

A "ledger" part tracks a set of keyed work items (workstreams, threads, bets)
across ticks: each item has a stable engine-minted `lk-NNNN` key, a lifecycle
status, an optional anchor onto a real Minder id, and an append-only provenance
trail of the records that justified it. The role's tick body only *proposes* a
structured delta payload; this plugin's `validate` gates it and `persist` is the
pure transform the sole writer (`roles_persist.py`) applies. The common layer
never names "ledger" — it loads this module dynamically by a part's `kind`
(`roles_common.import_archetype`), so a role composes one or more parts and this
plugin backs every part whose `kind` is `ledger`.

Exposes the per-part plugin interface (BUILD-CONTRACT §2):
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODEL, CONCIERGE_MANIFEST,
  fresh_state()                         -> dict  (empty part state + defaults)
  known_key_numbers(state)              -> Iterable[int]  (this part's key namespace)
  validate(prior_state, delta_payload)  -> ValidationResult
  persist(prior_state, approved_deltas, key_minter) -> new_state
  render(state)                         -> str   (state.md AUTO sub-zone body)
  identity(item, anchors)               -> IdentityResult
  gate_identity(role_id, part_id, prior_state, approved) -> (kept, signals)
  build_decisions(approved, minted, prior_state, role_id, part_id, hook, ts) -> list[dict]
  cold_materialize_decisions(adopted_state, role_id, part_id, ts) -> list[dict]
  delta_counts(persisted_deltas) -> (added, advanced)
  content_view(state)                   -> dict  (content frozen at cold-start)
  adopt_staging(prior_state, staging)   -> new_state  (adopt a frozen draft live)
  content_summary(state)                -> list[str]  (unit labels)
  consumed_records(state)               -> Iterable[str]  (record stems cited)

Items carry the enriched planning fields (owner / priority / due_date /
depends_on), settable at `add` time and via the `set-field` delta.

`GROUNDING_MODEL = "records"` declares that a citation grounds in a real in-remit
record (the shared frame delegates the grounding rule to this constant so a
non-records part plugs in without the frame fighting it). `known_key_numbers`
owns the ledger key-space scan — the common `KeyMinter.for_part` mints in THIS
part's namespace from it, so two ledger parts of one composite role never collide.

Grounding / append-not-replace / churn-guard / anchor-else-HITL are net-new to
this subsystem — the content pipeline has no persist stage, no HITL identity
path, and no grounding oracle to copy. All decision routing is deterministic;
anything requiring judgment (unanchored identity, wholesale churn) is surfaced as
a CLARIFICATION signal, never guessed.

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
    ValidationResult,
    decision_row,
    delta_ref,
    grow_provenance,
    is_valid_iso_date,
    nonempty_str,
    normalize_record_ref,
    parse_anchor,
    parse_key_number,
    part_subject,
    read_int_tunable,
    read_record_corpus,
    resolve_role_id,
    ungrounded_refs,
)


# -----------------------------------------------------------------------------
# Archetype identity + vocabulary
# -----------------------------------------------------------------------------

ARCHETYPE = "ledger"

# What a citation grounds in for this part-kind (BUILD-CONTRACT §2). The shared
# frame parameterises its honesty contract by this constant instead of hardcoding
# "cite a fresh record", so a future part-kind grounding in values / a numeric
# series plugs in without the frame fighting it. A ledger grounds in real in-remit
# records — every add's provenance and every mutating op's evidence must cite one.
GROUNDING_MODEL = "records"

# Ops the tick body may propose (BUILD-CONTRACT §3.1 / §4). Order is the natural
# lifecycle grouping; it does NOT dictate persist application order. `set-field`
# updates the enriched planning fields (owner / priority / due_date / depends_on)
# on a live item without changing its lifecycle status.
DELTAS: tuple[str, ...] = (
    "add", "advance", "supersede", "merge", "split", "rename", "set-field",
)

# Item lifecycle statuses (BUILD-CONTRACT §3.1 item_schema).
ITEM_STATUSES: frozenset[str] = frozenset(
    {"new", "active", "blocked", "done", "archived", "merged"}
)

# Enriched planning fields (BUILD-CONTRACT §3.1) — settable at `add` time and via
# `set-field`. `priority` is a closed vocabulary; `owner` / `due_date` are free
# (a person-id or free text / an ISO date); `depends_on` is a list of live keys.
SET_FIELDS: frozenset[str] = frozenset({"owner", "priority", "due_date", "depends_on"})
PRIORITIES: frozenset[str] = frozenset({"low", "med", "high"})


# `merged` is engine-managed — only supersede / merge / split retire an item into
# it (it always carries a `superseded_by` pointer). The body may never set it via
# add / advance; retirement goes through the dedicated ops so the pointer is
# never dropped.
BODY_STATUSES: frozenset[str] = ITEM_STATUSES - {"merged"}
# Retired items drop out of the "live" working set.
RETIRED_STATUSES: frozenset[str] = frozenset({"archived", "merged"})

# Render grouping order (present-state, not history).
STATUS_ORDER: tuple[str, ...] = (
    "new", "active", "blocked", "done", "merged", "archived",
)
_STATUS_LABELS: dict[str, str] = {
    "new": "New",
    "active": "Active",
    "blocked": "Blocked",
    "done": "Done",
    "merged": "Merged / superseded",
    "archived": "Archived",
}

# Deterministic status for engine-synthesised successor items. A merge
# consolidates already-tracked items and split fans a tracked item out — the
# successors carry the working (`active`) state forward rather than resetting to
# `new` (which would falsely present them as unconfirmed).
MERGE_RESULT_STATUS = "active"
SPLIT_CHILD_STATUS = "active"

# Default churn ceiling when the ledger omits it (BUILD-CONTRACT §3.1).
DEFAULT_CHURN_THRESHOLD = 5
# Default identity strictness when neither state nor caller supplies one
# (BUILD-CONTRACT §3.1 seeds "strict" — safest in cold-start / early life).
DEFAULT_IDENTITY_STRICTNESS = "strict"

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned ledger of keyed work items. Written ONLY by roles_persist.py "
        "through this plugin. Never hand-edited."
    ),
    "top_level": {
        "version": "int (schema version of the ledger file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'ledger'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": "str|null (high-water mark of consumed records)",
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "churn_threshold": f"int (new-adds ceiling per tick; default {DEFAULT_CHURN_THRESHOLD})",
        "identity_strictness": "str ('strict'|... ; governs unanchored-add HITL default)",
        "items": "list[item] (the ledger)",
    },
    "item": {
        "key": "str, engine-minted 'lk-NNNN' (stable, never reused)",
        "title": "str",
        "status": sorted(ITEM_STATUSES),
        "owner": "str|null  (who owns it — a person-id or free text)",
        "priority": "str|null  ('low'|'med'|'high')",
        "due_date": "str|null  (YYYY-MM-DD)",
        "depends_on": "list[str]  ('lk-NNNN' keys this item waits on; live keys only)",
        "anchor": "str|null  ('project:<id>'|'note:<id>'|'decision:<path>')",
        "provenance": "list[str]  ('[[record-basename]]', append-only, grows)",
        "superseded_by": "str|null  ('lk-NNNN' when retired via supersede/merge/split)",
        "archive_reason": "str, required iff status == 'archived'",
        "first_seen": "str  (YYYY-MM-DD)",
        "last_updated": "str  (YYYY-MM-DD)",
    },
}

# Ledger-file schema version (the only field a migration touches). Module-level
# and exported so the common writer / version-tolerant validator can read the
# current schema of THIS archetype. A ledger schema bump MUST update
# LEDGER_VERSION here AND add a matching MIGRATIONS entry (migrate-before-validate)
# so a stored ledger at `version < LEDGER_VERSION` upgrades in a degraded-mode
# path rather than being rejected.
LEDGER_VERSION = 1


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language WITHOUT ever exposing the word
# "archetype" / "part-kind" to the owner (FINAL-DESIGN §2 / BUILD-CONTRACT §2). It
# is the ONLY owner-facing voice of this plugin: `plain_purpose` + `triggers` let
# the concierge match a plain-language wish to this part; `produces_preview` shows
# what the board will look like; `determinism_note` DISCLOSES the honesty level
# (never claims a guarantee it does not hold — principle-ai-interaction-012).
# `built: True` marks this part-kind as installed and composable now (a
# ready-seam-only kind would carry `built: False` so the concierge never offers an
# unbuilt capability).
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Keep a living list of the concrete pieces of work an entity is made of — "
        "tasks, threads, bets, workstreams — each with a status, who owns it, and "
        "the history of how it got there."
    ),
    "triggers": [
        "веди задачи",
        "держи список дел",
        "следи за workstream'ами проекта",
        "кто за что отвечает",
        "что горит / что заблокировано",
        "track my tasks",
        "keep the project's workstreams",
        "who owns what",
        "what's blocked / what's next",
    ],
    "produces_preview": (
        "A board grouped by status (New / Active / Blocked / Done), each item a line "
        "like `lk-0007 · Migrate auth to OIDC · active · prio:high · owner:ivan · "
        "due:2026-08-01 · project:minder · [[2026-07-03-standup]]`, with priority, "
        "owner, due date and dependencies shown when set, and retired items as superseded."
    ),
    "determinism_note": (
        "TIGHT determinism: statuses come from a fixed set, keys are engine-minted "
        "and carried forward, and every change must cite a real in-remit record. "
        "The engine vouches for the bookkeeping; it does not judge whether an item "
        "matters — that is the tick body's reading."
    ),
    "built": True,
}


def fresh_state() -> dict:
    """Return a brand-new ledger's top-level fields with archetype defaults filled.

    This is the SINGLE HOME for the archetype-owned fresh-state defaults (§11.11)
    — most importantly `churn_threshold` and `identity_strictness`, whose sole
    owners are `DEFAULT_CHURN_THRESHOLD` / `DEFAULT_IDENTITY_STRICTNESS` here. The
    common writer (`roles_persist._fresh_part_state`) sources them from this plugin
    rather than re-declaring the literals, so the value + the shape live in one
    place behind the §4 seam.

    Fields the writer owns per instance are returned as neutral placeholders it
    overlays: `role_id` (runtime identity) and `description` (the writer's
    engine-written-only note). `archetype` is set to this plugin's `ARCHETYPE`.
    Field order follows the canonical §3.1 seed. Returns a fresh dict each call —
    no shared mutable state leaks between roles.
    """
    return {
        "version": LEDGER_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": DEFAULT_CHURN_THRESHOLD,
        "identity_strictness": DEFAULT_IDENTITY_STRICTNESS,
        "items": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Yield every `lk-NNNN` number this part's state holds (BUILD-CONTRACT §2).

    This is the ledger's OWN key-namespace scan — the single home for the state
    shape knowledge that lets the common `KeyMinter.for_part` mint the next free
    key without re-scanning any concrete shape. It scans live `items`, any frozen
    cold-start `staging.items`, and both the `key` AND `superseded_by` fields of
    each item — so a retired / superseded / staged key can never be re-minted even
    after its item is compacted away. Two ledger parts of one composite role each
    scan only their own `parts/{id}.json`, so their namespaces never collide.

    Owning this here (rather than in the common layer) closes the §11.11 archetype
    leak: the common key minter delegates the shape to this hook and never names a
    concrete part-kind. Yields nothing for a non-dict / empty state (a fresh part).
    """
    if not isinstance(state, dict):
        return
    buckets: list[Any] = [state.get("items")]
    staging = state.get("staging")
    if isinstance(staging, dict):
        buckets.append(staging.get("items"))
    for bucket in buckets:
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if not isinstance(item, dict):
                continue
            for field_name in ("key", "superseded_by"):
                n = parse_key_number(item.get(field_name))
                if n is not None:
                    yield n


# -----------------------------------------------------------------------------
# Item / state helpers
# -----------------------------------------------------------------------------

def _items(state: Any) -> list[dict]:
    if not isinstance(state, dict):
        return []
    items = state.get("items")
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def _index_by_key(items: Iterable[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items:
        key = it.get("key")
        if isinstance(key, str) and key:
            out[key] = it
    return out


def _is_live(item: dict) -> bool:
    return (
        item.get("status") not in RETIRED_STATUSES
        and not item.get("superseded_by")
    )


def _live_keys(items: Iterable[dict]) -> list[str]:
    return [it["key"] for it in items if isinstance(it.get("key"), str) and _is_live(it)]


def _min_date(values: Iterable[Any], fallback: str) -> str:
    dates = [v for v in values if isinstance(v, str) and v.strip()]
    return min(dates) if dates else fallback


# -----------------------------------------------------------------------------
# validate — structural + semantic gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed delta payload before it may be persisted.

    STRUCTURAL: the payload envelope and each delta parse; `op` is known; every
    per-op required field is present and correctly typed; statuses are in the
    lifecycle enum (`merged` is engine-only); `archive_reason` accompanies any
    archived target; `superseded_by` targets resolve; no key is consumed twice
    and no `provisional_key` collides; append-only fields (`first_seen`,
    `provenance` on a non-add op) may not be overwritten.

    SEMANTIC: grounding (every add's provenance and every mutating op's evidence
    cites a record present in `delta_payload.read_records` — uncited is rejected);
    append-not-replace (history / provenance only grow — enforced structurally by
    refusing replace-intent fields); churn-guard (on an established ledger, a tick
    that touches or retires every live item — via ANY mutating op, including a
    mass advance-to-archived or rename — or whose total mutations exceed
    `churn_threshold` is HELD as a `role-churn-guard` CLARIFICATION, never
    silently written).

    Contract of the return value:
      - ok=True  → persist `approved_deltas` (which MAY be empty — a legitimate
        no-op / empty tick). `rejections` lists per-delta drops (still applied:
        the good deltas persist, the bad ones do not).
      - ok=False → a BLOCKING condition (malformed envelope, corrupt prior state,
        or churn-guard hold) prevents persisting anything this tick;
        `approved_deltas` is empty and `clarifications` explains.

    Reject-counting for the 3-strike auto-pause is `roles_persist`'s call: a tick
    makes no forward progress when ok=False, or when ok=True with an empty
    `approved_deltas` and a non-empty `rejections`.
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

    prior_items = _items(prior_state)
    prior_index = _index_by_key(prior_items)
    # Corrupt prior state (duplicate keys) is a blocking integrity failure — a
    # tick over it could mint into a collision. Hold, do not guess a repair.
    live_key_list = [it.get("key") for it in prior_items if isinstance(it.get("key"), str)]
    if len(live_key_list) != len(set(live_key_list)):
        return ValidationResult.rejected(
            rejections=({"ref": "prior_state", "reason": "duplicate keys in prior ledger"},)
        )

    corpus = read_record_corpus(delta_payload)
    role_id = resolve_role_id(delta_payload, prior_state)

    approved: list[dict] = []
    rejections: list[dict] = []
    consumed: set[str] = set()  # existing keys already mutated this tick

    # Pass 1 — validate the adds. ONLY the provisional_keys of adds that pass
    # validation become resolvable same-tick targets. An add rejected here
    # (ungrounded, malformed, immutable-field, duplicate provisional_key) mints
    # no successor, so a paired supersede/merge/split cannot retire a live item
    # into a phantom that will never exist.
    approved_provisional: set[str] = set()
    seen_provisional: set[str] = set()
    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict) or delta.get("op") != "add":
            continue
        reason = _validate_add_op(delta, corpus, seen_provisional, prior_index)
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("provisional_key", "key")), "reason": reason})
            continue
        approved.append(delta)
        approved_provisional.add(delta["provisional_key"].strip())

    # A provisional target resolves only against an APPROVED add or a prior key.
    resolvable_targets = set(prior_index) | approved_provisional

    # Pass 2 — validate the mutating ops in body-proposed order.
    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": delta_ref(delta, idx, ("provisional_key", "key")), "reason": "delta is not a mapping"})
            continue
        op = delta.get("op")
        if op == "add":
            continue  # already handled in Pass 1
        if op not in DELTAS:
            rejections.append({"ref": delta_ref(delta, idx, ("provisional_key", "key")), "reason": f"unknown op {op!r}"})
            continue
        reason = _validate_delta(
            op, delta, prior_index, resolvable_targets, corpus, consumed
        )
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("provisional_key", "key")), "reason": reason})
            continue
        approved.append(delta)

    # Churn-guard — only on an ESTABLISHED ledger. An empty prior ledger with a
    # burst of adds is cold-start (owned by roles_persist staging), not churn.
    churn = _churn_guard(prior_items, approved, prior_state, role_id)
    if churn is not None:
        return ValidationResult(ok=False, clarifications=(churn,))

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
    )


def _validate_add_op(
    delta: dict, corpus: set[str], seen_provisional: set[str],
    prior_index: dict[str, dict],
) -> str | None:
    """Validate an `add` delta in isolation (Pass 1).

    Enforces first_seen immutability, the structural + grounding contract of
    `_validate_add`, and same-tick provisional_key uniqueness. On success the
    normalised provisional_key is recorded in `seen_provisional` so a later add
    reusing it is rejected as a collision (and never silently doubles a key)."""
    if "first_seen" in delta:
        return "append-not-replace: 'first_seen' is immutable"
    reason = _validate_add(delta, corpus, prior_index)
    if reason is not None:
        return reason
    pk = delta["provisional_key"].strip()  # _validate_add guaranteed non-empty
    if pk in seen_provisional:
        return f"duplicate provisional_key {pk!r}"
    seen_provisional.add(pk)
    return None


def _validate_delta(
    op: str,
    delta: dict,
    prior_index: dict[str, dict],
    resolvable_targets: set[str],
    corpus: set[str],
    consumed: set[str],
) -> str | None:
    """Return a rejection reason string, or None when the delta is valid.

    Mutates `consumed` with any existing key this delta retires / mutates, so a
    later delta touching the same key is rejected as a conflict."""
    # Append-not-replace: the body may never overwrite an immutable field.
    if "first_seen" in delta:
        return "append-not-replace: 'first_seen' is immutable"
    if op != "add" and "provenance" in delta:
        return "append-not-replace: provenance grows via 'evidence', not replacement"

    if op == "add":
        return _validate_add(delta, corpus, prior_index)
    if op == "advance":
        return _validate_advance(delta, prior_index, corpus, consumed)
    if op == "supersede":
        return _validate_supersede(delta, prior_index, resolvable_targets, corpus, consumed)
    if op == "merge":
        return _validate_merge(delta, prior_index, corpus, consumed)
    if op == "split":
        return _validate_split(delta, prior_index, corpus, consumed)
    if op == "rename":
        return _validate_rename(delta, prior_index, consumed)
    if op == "set-field":
        return _validate_set_field(delta, prior_index, corpus, consumed)
    return f"unhandled op {op!r}"  # unreachable — op membership checked upstream


def _validate_add(delta: dict, corpus: set[str], prior_index: dict[str, dict]) -> str | None:
    if not nonempty_str(delta.get("provisional_key")):
        return "add missing non-empty 'provisional_key'"
    if not nonempty_str(delta.get("title")):
        return "add missing non-empty 'title'"
    status = delta.get("status", "new")
    if status not in BODY_STATUSES:
        return f"add 'status' must be one of {sorted(BODY_STATUSES)}, got {status!r}"
    if status == "archived" and not nonempty_str(delta.get("archive_reason")):
        return "add with status 'archived' requires a non-empty 'archive_reason'"
    anchor = delta.get("anchor")
    # Honor-system anchor (§11.10): only the anchor's SHAPE is checked here. A
    # well-formed-but-nonexistent anchor (e.g. `project:does-not-exist`) is
    # accepted without a `role-new-key` HITL — consistent with the lens-style
    # read. Cross-checking the anchor value against the resolved corpus is a
    # hardening item gated to act / friend-deploy, deliberately not done now.
    if anchor is not None and parse_anchor(anchor) is None:
        return f"add 'anchor' is malformed: {anchor!r}"
    # Enriched planning fields — optional at add time; when present each must be
    # well-formed (surface, don't silently drop a body's malformed value). A new
    # item may only depend on an already-tracked live key (same-tick provisional
    # deps are set next tick once the target has a real key).
    field_err = _validate_planning_fields(delta, prior_index, self_key=None)
    if field_err is not None:
        return f"add {field_err}"
    missing = ungrounded_refs(delta.get("provenance"), corpus)
    if not isinstance(delta.get("provenance"), (list, tuple)) or not delta.get("provenance"):
        return "add 'provenance' must cite at least one read record"
    if missing:
        return f"ungrounded: provenance not in read_records: {missing}"
    return None


def _validate_planning_fields(
    delta: dict, prior_index: dict[str, dict], self_key: str | None
) -> str | None:
    """Validate any present enriched planning fields on an add / set-field delta.

    Only fields PRESENT in `delta` are checked (all are optional). `priority` must
    be in the enum or null; `due_date` must be a REAL YYYY-MM-DD calendar date or
    null; `owner` must be a string or null; `depends_on` must be null (clears) or a
    list of `lk-NNNN` keys each resolving to a LIVE prior item and never the item
    itself (no self-dependency). Every field accepts `null` to clear it — a uniform
    body API across the four. Returns a reason string (without an op prefix) or None.

    `depends_on` resolution is checked against `prior_index` — the state BEFORE this
    tick. It is a SET-TIME contract: a dep that is live now may be retired by a
    later (or same-tick) op, leaving a stale reference. `depends_on` is a planning
    hint, not enforced logic; present-state consumers filter retired deps, so the
    writer does not maintain referential integrity of the hint here.
    """
    if "priority" in delta:
        pr = delta.get("priority")
        if pr is not None and pr not in PRIORITIES:
            return f"'priority' must be one of {sorted(PRIORITIES)} or null, got {pr!r}"
    if "due_date" in delta:
        dd = delta.get("due_date")
        if dd is not None and not (isinstance(dd, str) and is_valid_iso_date(dd.strip())):
            return f"'due_date' must be a valid YYYY-MM-DD date or null, got {dd!r}"
    if "owner" in delta:
        ow = delta.get("owner")
        if ow is not None and not isinstance(ow, str):
            return f"'owner' must be a string or null, got {type(ow).__name__}"
    if "depends_on" in delta:
        dep = delta.get("depends_on")
        if dep is not None:  # null clears to [] (uniform with the other fields)
            if not isinstance(dep, list):
                return f"'depends_on' must be a list of keys or null, got {type(dep).__name__}"
            for k in dep:
                if parse_key_number(k) is None:
                    return f"'depends_on' entry {k!r} is not a well-formed 'lk-NNNN' key"
                if self_key is not None and k == self_key:
                    return "'depends_on' cannot list the item's own key (self-dependency)"
                target = prior_index.get(k)
                if target is None:
                    return f"'depends_on' key {k!r} does not exist in the ledger"
                if not _is_live(target):
                    return f"'depends_on' key {k!r} is retired (depend on live items only)"
    return None


def _validate_set_field(
    delta: dict, prior_index: dict[str, dict], corpus: set[str], consumed: set[str]
) -> str | None:
    """Validate a `set-field` delta: update one planning field on a live item.

    The target key must be live and un-touched this tick; `field` must be a
    settable planning field; `value` must be well-formed for that field; the change
    must cite a grounded record. `set-field` never touches lifecycle status,
    provenance history, or immutable fields — only owner / priority / due_date /
    depends_on."""
    key = delta.get("key")
    err = _require_live_target(key, prior_index, consumed, "set-field")
    if err:
        return err
    field = delta.get("field")
    if field not in SET_FIELDS:
        return f"set-field 'field' must be one of {sorted(SET_FIELDS)}, got {field!r}"
    # Reuse the shared field validator by projecting {field: value} onto a probe.
    probe = {field: delta.get("value")}
    field_err = _validate_planning_fields(probe, prior_index, self_key=key)
    if field_err is not None:
        return f"set-field {field_err}"
    err = _require_grounded_evidence(delta, corpus, "set-field")
    if err:
        return err
    consumed.add(key)
    return None


def _validate_advance(
    delta: dict, prior_index: dict[str, dict], corpus: set[str], consumed: set[str]
) -> str | None:
    key = delta.get("key")
    err = _require_live_target(key, prior_index, consumed, "advance")
    if err:
        return err
    to_status = delta.get("to_status")
    if to_status not in BODY_STATUSES:
        return f"advance 'to_status' must be one of {sorted(BODY_STATUSES)}, got {to_status!r}"
    if to_status == "archived" and not nonempty_str(delta.get("archive_reason")):
        return "advance to 'archived' requires a non-empty 'archive_reason'"
    err = _require_grounded_evidence(delta, corpus, "advance")
    if err:
        return err
    consumed.add(key)
    return None


def _validate_supersede(
    delta: dict,
    prior_index: dict[str, dict],
    resolvable_targets: set[str],
    corpus: set[str],
    consumed: set[str],
) -> str | None:
    key = delta.get("key")
    err = _require_live_target(key, prior_index, consumed, "supersede")
    if err:
        return err
    by = delta.get("by")
    if not nonempty_str(by):
        return "supersede missing non-empty 'by'"
    if by == key:
        return "supersede 'by' cannot equal 'key'"
    if by not in resolvable_targets:
        return f"supersede 'by' does not resolve to an existing or same-tick key: {by!r}"
    err = _require_grounded_evidence(delta, corpus, "supersede")
    if err:
        return err
    consumed.add(key)
    return None


def _validate_merge(
    delta: dict, prior_index: dict[str, dict], corpus: set[str], consumed: set[str]
) -> str | None:
    keys = delta.get("keys")
    if not isinstance(keys, list) or len(keys) < 2:
        return "merge 'keys' must list at least two existing keys"
    if len(keys) != len(set(keys)):
        return "merge 'keys' contains duplicates"
    for key in keys:
        err = _require_live_target(key, prior_index, consumed, "merge")
        if err:
            return err
    if not nonempty_str(delta.get("into_title")):
        return "merge missing non-empty 'into_title'"
    err = _require_grounded_evidence(delta, corpus, "merge")
    if err:
        return err
    consumed.update(keys)
    return None


def _validate_split(
    delta: dict, prior_index: dict[str, dict], corpus: set[str], consumed: set[str]
) -> str | None:
    key = delta.get("key")
    err = _require_live_target(key, prior_index, consumed, "split")
    if err:
        return err
    into = delta.get("into")
    if not isinstance(into, list) or len(into) < 2:
        return "split 'into' must list at least two child items"
    for child in into:
        if not isinstance(child, dict) or not nonempty_str(child.get("title")):
            return "split 'into' children each need a non-empty 'title'"
    err = _require_grounded_evidence(delta, corpus, "split")
    if err:
        return err
    consumed.add(key)
    return None


def _validate_rename(
    delta: dict, prior_index: dict[str, dict], consumed: set[str]
) -> str | None:
    # KNOWN BOUNDED EXEMPTION (C4): `rename` carries no grounding-evidence
    # requirement — unlike add/advance/supersede/merge/split it does NOT call
    # `_require_grounded_evidence`. This is a deliberate, spec-consistent
    # exemption, not an oversight: a rename changes only an item's `title`, adds
    # no new tracked fact and cites no record, so there is nothing to ground.
    # The safety envelope still holds — the churn-guard COUNTS every rename (a
    # wholesale title rewrite of the live set trips the all-keys-changed / volume
    # hold in `_churn_guard`), so a garbled mass-rename cannot slip through
    # ungated. Any future rename variant that carries new grounded content MUST
    # add the evidence check here.
    key = delta.get("key")
    err = _require_live_target(key, prior_index, consumed, "rename")
    if err:
        return err
    if not nonempty_str(delta.get("title")):
        return "rename missing non-empty 'title'"
    consumed.add(key)
    return None


def _require_live_target(
    key: Any, prior_index: dict[str, dict], consumed: set[str], op: str
) -> str | None:
    if not nonempty_str(key):
        return f"{op} missing non-empty 'key'"
    if key not in prior_index:
        return f"{op} 'key' {key!r} does not exist in the ledger"
    if key in consumed:
        return f"{op} 'key' {key!r} is already mutated by another delta this tick"
    if not _is_live(prior_index[key]):
        return f"{op} 'key' {key!r} is already retired"
    return None


def _require_grounded_evidence(delta: dict, corpus: set[str], op: str) -> str | None:
    evidence = delta.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return f"{op} 'evidence' must cite at least one read record"
    missing = ungrounded_refs(evidence, corpus)
    if missing:
        return f"ungrounded: {op} evidence not in read_records: {missing}"
    return None


def _churn_guard(
    prior_items: list[dict],
    approved: list[dict],
    prior_state: Any,
    role_id: str,
) -> ClarificationSignal | None:
    live_before = _live_keys(prior_items)
    if not live_before:
        return None  # empty / freshly-drafted ledger → cold-start owns this

    threshold = read_int_tunable(prior_state, "churn_threshold", DEFAULT_CHURN_THRESHOLD)

    # Two independent triggers, closing the advance/rename evasion (§11.8):
    #
    #   changed_keys — keys a RETIRING or REWRITING op touches: supersede / split
    #   / every merge source, advance-to-a-RETIRED-status (the evasion: advancing
    #   every live item to `archived` empties the set with no merge/split), and
    #   rename (a wholesale title rewrite). A benign advance to a LIVE status
    #   (e.g. new→active) is normal progress and is deliberately NOT counted here
    #   — otherwise a single-item ledger advancing its one item would trip on
    #   every tick. The volume path below still counts it. `set-field` is treated
    #   the SAME as a benign advance: changing an item's owner / priority / due /
    #   deps ANNOTATES the work, it does not replace it (unlike rename/retire which
    #   ARE counted), so it is NOT a changed_key but IS counted in the volume path.
    #
    #   total_mutations — every mutating delta (any advance, rename, supersede,
    #   merge, split) plus new adds. This is the scale backstop: a mass advance
    #   or rename with zero adds still trips the threshold even when it is not a
    #   full sweep of the live set.
    changed_keys: set[str] = set()
    new_adds = 0
    mutating_deltas = 0
    for d in approved:
        op = d.get("op")
        if op == "add":
            new_adds += 1
            continue
        mutating_deltas += 1
        if op == "merge" and isinstance(d.get("keys"), list):
            changed_keys.update(k for k in d["keys"] if nonempty_str(k))
        elif op in ("supersede", "split", "rename") and nonempty_str(d.get("key")):
            changed_keys.add(d["key"])
        elif (
            op == "advance"
            and d.get("to_status") in RETIRED_STATUSES
            and nonempty_str(d.get("key"))
        ):
            changed_keys.add(d["key"])

    total_mutations = mutating_deltas + new_adds

    all_keys_changed = set(live_before).issubset(changed_keys)
    if not (all_keys_changed or total_mutations > threshold):
        return None

    reasons: list[str] = []
    if all_keys_changed:
        reasons.append(
            f"every one of {len(live_before)} live item(s) would be touched or "
            "retired this tick"
        )
    if total_mutations > threshold:
        reasons.append(
            f"{total_mutations} mutation(s) exceed the churn threshold of {threshold}"
        )
    detail = "; ".join(reasons)
    return ClarificationSignal(
        ctype="role-churn-guard",
        subject=role_id,
        context=(
            f"The tick proposed a wholesale rewrite of the ledger ({detail}). "
            "This is held rather than written so a garbled or over-eager tick "
            "cannot silently replace the tracked work. Review the proposed "
            "deltas and confirm before any are applied."
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
    """Apply already-validated deltas to a copy of `prior_state` and return the
    new ledger state. Pure: does no I/O and never mutates its inputs.

    - `add`   → mint a stable `lk-NNNN` via `key_minter`, seed the item.
    - `advance` → set status + last_updated; grow provenance with the evidence.
    - `supersede` → retire the source (status 'merged', `superseded_by` = target).
    - `merge` → mint a consolidated item; retire every source into it.
    - `split` → mint a child per `into` entry; retire the parent into the first.
    - `rename` → update title + last_updated only.

    History never blanks: `first_seen` is preserved (min of sources on merge,
    parent's on split children), provenance only grows, and every retirement
    keeps its trail. Adds are applied first so a same-tick supersede/merge/split
    may resolve a `provisional_key` target.
    """
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    items = new_state.get("items")
    if not isinstance(items, list):
        items = []
    new_state["items"] = items
    index = _index_by_key(it for it in items if isinstance(it, dict))
    today = today_iso()
    provisional_map: dict[str, str] = {}

    deltas = [d for d in approved_deltas if isinstance(d, dict)]

    # Phase A — adds first, so provisional keys resolve for later ops.
    for delta in deltas:
        if delta.get("op") != "add":
            continue
        key = key_minter.mint()
        item = _new_item(delta, key, today)
        items.append(item)
        index[key] = item
        pk = delta.get("provisional_key")
        if nonempty_str(pk):
            provisional_map[pk] = key

    # Phase B — mutating ops in body-proposed order.
    for delta in deltas:
        op = delta.get("op")
        if op == "add":
            continue
        if op == "advance":
            _apply_advance(index, delta, today)
        elif op == "supersede":
            _apply_supersede(index, delta, provisional_map, today)
        elif op == "merge":
            _apply_merge(index, items, delta, key_minter, today)
        elif op == "split":
            _apply_split(index, items, delta, key_minter, today)
        elif op == "rename":
            _apply_rename(index, delta, today)
        elif op == "set-field":
            _apply_set_field(index, delta, today)

    return new_state


def _new_item(delta: dict, key: str, today: str) -> dict:
    anchor = delta.get("anchor")
    anchor = anchor if parse_anchor(anchor) is not None else None
    status = delta.get("status", "new")
    provenance = grow_provenance([], delta.get("provenance") or [])
    item = {
        "key": key,
        "title": str(delta.get("title", "")).strip(),
        "status": status,
        "owner": _clean_owner(delta.get("owner")),
        "priority": delta.get("priority") if delta.get("priority") in PRIORITIES else None,
        "due_date": _clean_due_date(delta.get("due_date")),
        "depends_on": _clean_depends_on(delta.get("depends_on")),
        "anchor": anchor,
        "provenance": provenance,
        "superseded_by": None,
        "first_seen": today,
        "last_updated": today,
    }
    if status == "archived":
        item["archive_reason"] = str(delta.get("archive_reason", "")).strip()
    return item


def _clean_owner(value: Any) -> str | None:
    """Coerce an `owner` field to a non-empty stripped string, else None."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clean_due_date(value: Any) -> str | None:
    """Coerce a `due_date` to a valid YYYY-MM-DD calendar date, else None."""
    if isinstance(value, str) and is_valid_iso_date(value.strip()):
        return value.strip()
    return None


def _clean_depends_on(value: Any) -> list[str]:
    """Coerce `depends_on` to a de-duplicated list of `lk-NNNN` keys (order kept)."""
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for k in value:
        if parse_key_number(k) is not None and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _apply_advance(index: dict[str, dict], delta: dict, today: str) -> None:
    item = index.get(delta.get("key"))
    if item is None:
        return
    item["status"] = delta.get("to_status")
    item["provenance"] = grow_provenance(item.get("provenance"), delta.get("evidence") or [])
    item["last_updated"] = today
    if item["status"] == "archived":
        item["archive_reason"] = str(delta.get("archive_reason", "")).strip()
    else:
        item.pop("archive_reason", None)


def _apply_supersede(
    index: dict[str, dict], delta: dict, provisional_map: dict[str, str], today: str
) -> None:
    item = index.get(delta.get("key"))
    if item is None:
        return
    by = delta.get("by")
    resolved = provisional_map.get(by)
    if resolved is None and by not in index:
        # Defense-in-depth: `by` is neither a minted successor nor an existing
        # key. Never write an unresolved provisional string as `superseded_by`
        # (a phantom pointer) — leave the source item live and untouched.
        return
    item["superseded_by"] = resolved if resolved is not None else by
    item["status"] = "merged"
    item["provenance"] = grow_provenance(item.get("provenance"), delta.get("evidence") or [])
    item["last_updated"] = today


def _apply_merge(
    index: dict[str, dict],
    items: list[dict],
    delta: dict,
    key_minter,
    today: str,
) -> None:
    sources = [index[k] for k in delta.get("keys", []) if k in index]
    if not sources:
        return
    evidence = delta.get("evidence") or []
    merged_provenance: list[str] = []
    for src in sources:
        merged_provenance = grow_provenance(merged_provenance, src.get("provenance") or [])
    merged_provenance = grow_provenance(merged_provenance, evidence)

    new_key = key_minter.mint()
    new_item = {
        "key": new_key,
        "title": str(delta.get("into_title", "")).strip(),
        "status": MERGE_RESULT_STATUS,
        "anchor": None,
        "provenance": merged_provenance,
        "superseded_by": None,
        "first_seen": _min_date((s.get("first_seen") for s in sources), today),
        "last_updated": today,
    }
    items.append(new_item)
    index[new_key] = new_item

    for src in sources:
        src["status"] = "merged"
        src["superseded_by"] = new_key
        src["provenance"] = grow_provenance(src.get("provenance"), evidence)
        src["last_updated"] = today


def _apply_split(
    index: dict[str, dict],
    items: list[dict],
    delta: dict,
    key_minter,
    today: str,
) -> None:
    parent = index.get(delta.get("key"))
    if parent is None:
        return
    evidence = delta.get("evidence") or []
    child_provenance = grow_provenance(list(parent.get("provenance") or []), evidence)
    first_seen = parent.get("first_seen") if nonempty_str(parent.get("first_seen")) else today

    first_child_key: str | None = None
    for child in delta.get("into", []):
        if not isinstance(child, dict):
            continue
        child_key = key_minter.mint()
        if first_child_key is None:
            first_child_key = child_key
        child_item = {
            "key": child_key,
            "title": str(child.get("title", "")).strip(),
            "status": SPLIT_CHILD_STATUS,
            "anchor": None,
            "provenance": list(child_provenance),
            "superseded_by": None,
            "first_seen": first_seen,
            "last_updated": today,
        }
        items.append(child_item)
        index[child_key] = child_item

    parent["status"] = "merged"
    # Single-valued `superseded_by` can only point at one successor — the first
    # child is the canonical pointer; decisions.jsonl records the full fan-out.
    parent["superseded_by"] = first_child_key
    parent["provenance"] = grow_provenance(parent.get("provenance"), evidence)
    parent["last_updated"] = today


def _apply_rename(index: dict[str, dict], delta: dict, today: str) -> None:
    # Title-only mutation — no provenance/evidence is grown (the grounding gate
    # is deliberately exempt for rename; see `_validate_rename`'s C4 note). The
    # rename is still counted by the churn-guard, so this exemption is bounded.
    item = index.get(delta.get("key"))
    if item is None:
        return
    item["title"] = str(delta.get("title", "")).strip()
    item["last_updated"] = today


def _apply_set_field(index: dict[str, dict], delta: dict, today: str) -> None:
    """Set one enriched planning field (owner / priority / due_date / depends_on)
    on a live item; grow its provenance with the change's evidence. Lifecycle
    status, title, first_seen and the retirement fields are untouched."""
    item = index.get(delta.get("key"))
    if item is None:
        return
    field = delta.get("field")
    value = delta.get("value")
    if field == "owner":
        item["owner"] = _clean_owner(value)
    elif field == "priority":
        item["priority"] = value if value in PRIORITIES else None
    elif field == "due_date":
        item["due_date"] = _clean_due_date(value)
    elif field == "depends_on":
        item["depends_on"] = _clean_depends_on(value)
    else:
        return  # unreachable — field membership checked in validate
    item["provenance"] = grow_provenance(item.get("provenance"), delta.get("evidence") or [])
    item["last_updated"] = today


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

def render(state: Any) -> str:
    """Render the ledger as the state.md AUTO-zone markdown body.

    Items are grouped by status (fixed present-state order); within a group they
    are sorted by key number. Each item renders as
    `- {title} · {status} · {anchor} · {provenance}` with a `→ superseded by …`
    suffix on retired items. The caller wraps this in the role-state markers.
    """
    items = _items(state)
    if not items:
        return "_No items yet._"

    # Present-state board: `needs:` shows only LIVE blockers. `depends_on` is
    # set-time-validated against live keys, but a later op can retire a dep,
    # leaving a stale reference the render must not surface (§4 planning-hint
    # contract). `_live_keys` is the one SoT for "live" — the same predicate the
    # set-field validator uses to reject a retired dep at set time.
    live = set(_live_keys(items))

    by_status: dict[str, list[dict]] = {}
    for it in items:
        by_status.setdefault(it.get("status"), []).append(it)

    lines: list[str] = []
    rendered_statuses = list(STATUS_ORDER) + [
        s for s in sorted(by_status) if s not in STATUS_ORDER
    ]
    for status in rendered_statuses:
        group = by_status.get(status)
        if not group:
            continue
        group.sort(key=lambda it: (parse_key_number(it.get("key")) or 0, str(it.get("key"))))
        label = _STATUS_LABELS.get(status, str(status or "unknown"))
        lines.append(f"### {label}")
        lines.append("")
        for it in group:
            lines.append(_render_item(it, live))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_item(item: dict, live_keys: set[str]) -> str:
    title = str(item.get("title") or "").strip() or "(untitled)"
    status = str(item.get("status") or "unknown")
    anchor = item.get("anchor")
    anchor_disp = anchor if nonempty_str(anchor) else "—"
    provenance = item.get("provenance")
    prov_disp = ", ".join(provenance) if isinstance(provenance, list) and provenance else "—"
    key = str(item.get("key") or "").strip()
    key_disp = f"`{key}` " if key else ""
    line = f"- {key_disp}{title} · {status}{_render_planning(item, live_keys)} · {anchor_disp} · {prov_disp}"
    superseded_by = item.get("superseded_by")
    if nonempty_str(superseded_by):
        line += f" → superseded by `{superseded_by}`"
    if status == "archived" and nonempty_str(item.get("archive_reason")):
        line += f" (archived: {str(item['archive_reason']).strip()})"
    return line


def _render_planning(item: dict, live_keys: set[str]) -> str:
    """Render the enriched planning fields inline, only those actually set.

    A present-state view: an item with no owner / priority / due / deps renders
    exactly as before (no empty scaffolding). Order: priority, owner, due, deps.
    `needs:` lists only LIVE dependencies — a dep retired after it was set is
    filtered against `live_keys` so the board never shows a stale blocker."""
    bits: list[str] = []
    priority = item.get("priority")
    if priority in PRIORITIES:
        bits.append(f"prio:{priority}")
    owner = item.get("owner")
    if nonempty_str(owner):
        bits.append(f"owner:{owner.strip()}")
    due = item.get("due_date")
    if nonempty_str(due):
        bits.append(f"due:{due.strip()}")
    deps = item.get("depends_on")
    if isinstance(deps, list) and deps:
        live_deps = [str(d) for d in deps if str(d) in live_keys]
        if live_deps:
            bits.append("needs:" + ",".join(live_deps))
    return f" · {' · '.join(bits)}" if bits else ""


# -----------------------------------------------------------------------------
# identity — anchor onto a real Minder id, else surface HITL (never guess)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Decide a stable external anchor for an item, or signal that it needs HITL.

    When the item already carries a well-formed anchor (`project:<id>` /
    `note:<id>` / `decision:<path>`) it is honoured directly. Otherwise the
    anchor is an LLM judgment the engine must NOT guess: the result is flagged
    `needs_hitl=True` (feeds a `role-new-key` CLARIFICATION). The conservative
    default carried in `reason` depends on identity strictness — `strict` holds
    the item pending owner review; a looser strictness defaults to "attach to the
    nearest existing key" but still surfaces the decision.

    `anchors` supplies context without ever forcing a guess. It may be:
      - an iterable of available anchor strings, or
      - a mapping `{"available": [...], "strictness": "strict"|...}`.
    """
    anchor = item.get("anchor") if isinstance(item, dict) else None
    if parse_anchor(anchor) is not None:
        return IdentityResult(anchored=True, anchor=anchor)

    strictness, available = _read_anchor_context(anchors)
    title = str(item.get("title") or "").strip() if isinstance(item, dict) else ""
    subject = f"item {title!r}" if title else "a new item"
    if strictness == "strict":
        reason = (
            f"{subject} has no anchor onto a real Minder id; strict identity holds "
            "it for owner review rather than attaching it automatically."
        )
    else:
        near = f" (nearest existing anchors: {', '.join(available)})" if available else ""
        reason = (
            f"{subject} has no anchor; conservative default is to attach it to the "
            f"nearest existing key{near}, surfaced for owner confirmation."
        )
    return IdentityResult(anchored=False, anchor=None, needs_hitl=True, reason=reason)


def _read_anchor_context(anchors: Any) -> tuple[str, list[str]]:
    strictness = DEFAULT_IDENTITY_STRICTNESS
    available: list[str] = []
    if isinstance(anchors, dict):
        raw_strict = anchors.get("strictness")
        if nonempty_str(raw_strict):
            strictness = raw_strict.strip()
        raw_avail = anchors.get("available")
        if isinstance(raw_avail, (list, tuple)):
            available = [a for a in raw_avail if nonempty_str(a)]
    elif isinstance(anchors, (list, tuple)):
        available = [a for a in anchors if nonempty_str(a)]
    return strictness, available


# -----------------------------------------------------------------------------
# Composite-seam hooks — the archetype-specific mechanics the sole writer
# (roles_persist) dispatches through, so it never names the Ledger state shape:
#   gate_identity            — anchor-else-HITL routing (Ledger-only concept)
#   build_decisions          — one decisions.jsonl row per persisted delta
#   cold_materialize_decisions — rows for adopting a frozen cold-start draft
#   content_view / adopt_staging — freeze / adopt the content behind cold-start
#   content_summary / consumed_records — labels + record stems of the content
# Each is pure; the writer owns all I/O + the generic envelope fields.
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Route unanchored new items through the identity decision (§1.4 / §3.7).

    An anchored add passes untouched. An unanchored add is an LLM judgment the
    engine must NOT guess: under `strict` identity the item is HELD (dropped, with
    any same-tick supersede that targeted its provisional key); under a looser
    strictness it persists unanchored and a `role-new-key` CLARIFICATION invites
    the owner to attach it. Subjects are part-scoped. Returns `(kept, signals)`.

    `identity_strictness` is a LEDGER-owned tunable — sourced from `prior_state`
    here, not passed by the writer (which never reaches into a plugin-owned field).
    Ledger-specific by nature — anchoring onto a real Minder id is a ledger-item
    concept. A part-kind with no anchor op (e.g. narrative) returns `(approved,
    [])` from its own trivial `gate_identity`, so the writer stays generic.
    """
    strictness = str(prior_state.get("identity_strictness") or DEFAULT_IDENTITY_STRICTNESS) \
        if isinstance(prior_state, dict) else DEFAULT_IDENTITY_STRICTNESS
    unanchored = [
        d for d in approved
        if d.get("op") == "add" and parse_anchor(d.get("anchor")) is None
    ]
    if not unanchored:
        return list(approved), []

    prior_items = _items(prior_state)
    available = _available_anchors(prior_items, approved)
    hold = strictness == "strict"
    signals: list[ClarificationSignal] = []
    held_pk: set[str] = set()

    for d in unanchored:
        title = str(d.get("title") or "").strip() or "(untitled)"
        pk = d.get("provisional_key")
        result = identity(
            {"title": title, "anchor": None},
            {"strictness": strictness, "available": available},
        )
        reason = getattr(result, "reason", "") or ""
        if hold:
            action_taken = "Held — not persisted this tick pending an anchor."
            if isinstance(pk, str) and pk.strip():
                held_pk.add(pk.strip())
        else:
            action_taken = "Persisted unanchored; attach on confirmation."
        signals.append(ClarificationSignal(
            ctype="role-new-key",
            subject=f"{part_subject(role_id, part_id)} · {title}",
            context=(
                f"The tick added a new item '{title}' to part '{part_id}' with no "
                "anchor onto a real Minder id (project:/note:/decision:). "
                f"{reason} Confirm the correct anchor or approve the conservative "
                "default."
            ),
            source=f"roles tick for {role_id} (part {part_id})",
            suggested_action=(
                "Set the item's anchor to the real project / note / decision id, "
                "or confirm attaching it to the nearest existing key."
            ),
            action_taken=action_taken,
            confidence_tier="surfaced",
        ))

    if not held_pk:
        return list(approved), signals

    kept: list[dict] = []
    for d in approved:
        op = d.get("op")
        if op == "add" and d.get("provisional_key") in held_pk:
            continue
        if op == "supersede" and d.get("by") in held_pk:
            continue  # its successor add was held — the supersede cannot resolve
        kept.append(d)
    return kept, signals


def _available_anchors(prior_items: list[dict], approved: list[dict]) -> list[str]:
    seen: set[str] = set()
    for it in prior_items:
        anchor = it.get("anchor")
        if _is_live(it) and parse_anchor(anchor) is not None:
            seen.add(anchor)
    for d in approved:
        if d.get("op") == "add" and parse_anchor(d.get("anchor")) is not None:
            seen.add(d.get("anchor"))
    return sorted(seen)


def build_decisions(
    approved_deltas: list[dict],
    minted: list[str],
    prior_state: Any,
    role_id: str,
    part_id: str,
    hook: str,
    ts: str,
) -> list[dict]:
    """One decision row per persisted delta, resolving minted keys, stamped `part`.

    Ledger `kind` vocabulary: item-create / status-advance / supersede / merge /
    split / rename / field-set (cold-materialize is emitted by the approval path).
    `minted` is the mint order recorded by the writer's recording minter, so a
    minted-key delta (add / merge / split) attributes to its real `lk-NNNN`.
    """
    prior_index = _index_by_key(_items(prior_state))
    rows: list[dict] = []
    idx = 0

    def _take() -> Any:
        nonlocal idx
        key = minted[idx] if idx < len(minted) else None
        idx += 1
        return key

    provisional_map: dict[str, str] = {}
    for d in approved_deltas:
        if d.get("op") != "add":
            continue
        key = _take()
        pk = d.get("provisional_key")
        if isinstance(pk, str) and key is not None:
            provisional_map[pk] = key
        rows.append(decision_row(
            "item-create", key, hook, role_id, part_id, ts,
            to=d.get("status", "new"), evidence=list(d.get("provenance") or []),
        ))

    for d in approved_deltas:
        op = d.get("op")
        if op == "add":
            continue
        key = d.get("key")
        evidence = list(d.get("evidence") or [])
        if op == "advance":
            frm = prior_index.get(key, {}).get("status")
            rows.append(decision_row(
                "status-advance", key, hook, role_id, part_id, ts,
                **{"from": frm, "to": d.get("to_status"), "evidence": evidence},
            ))
        elif op == "supersede":
            by = provisional_map.get(d.get("by"), d.get("by"))
            rows.append(decision_row(
                "supersede", key, hook, role_id, part_id, ts,
                **{"from": prior_index.get(key, {}).get("status"),
                   "to": "merged", "by": by, "evidence": evidence},
            ))
        elif op == "merge":
            new_key = _take()
            rows.append(decision_row(
                "merge", new_key, hook, role_id, part_id, ts,
                from_keys=list(d.get("keys") or []), to="active", evidence=evidence,
            ))
        elif op == "split":
            n = len(d.get("into") or [])
            child_keys = [_take() for _ in range(n)]
            rows.append(decision_row(
                "split", key, hook, role_id, part_id, ts,
                into_keys=child_keys, to="merged", evidence=evidence,
            ))
        elif op == "rename":
            rows.append(decision_row(
                "rename", key, hook, role_id, part_id, ts, to=d.get("title"),
            ))
        elif op == "set-field":
            rows.append(decision_row(
                "field-set", key, hook, role_id, part_id, ts,
                field=d.get("field"), to=d.get("value"), evidence=evidence,
            ))
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts — the ledger's op vocabulary.

    A ledger `add` creates a new tracked item (added); every other op changes an
    existing one (advanced). The writer dispatches through this so it never names a
    concrete op — a narrative returns (0, N) since it creates no keyed items."""
    added = sum(1 for d in persisted_deltas if isinstance(d, dict) and d.get("op") == "add")
    advanced = sum(1 for d in persisted_deltas if isinstance(d, dict) and d.get("op") != "add")
    return added, advanced


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per adopted item when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", it.get("key"), "tick", role_id, part_id, ts,
            to=it.get("status"), evidence=list(it.get("provenance") or []),
        )
        for it in _items(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start (§1.6).

    Ledger content is its `items` list. The writer spreads this into the staging
    dict (so `staging['items']` holds the frozen draft) and adopts it later via
    `adopt_staging`; the generic envelope fields never enter the draft."""
    return {"items": list(_items(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state (§11.7).

    Returns a deep copy of `prior_state` with its content replaced by the draft's
    (the staged `items`). The writer then clears `staging`, resets the reject
    counter and advances the watermark over `consumed_records`."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    src = staging.get("items") if isinstance(staging, dict) else None
    ns["items"] = [it for it in src if isinstance(it, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification).

    Works on both a live state and a staging dict (both carry `items`). Ledger
    labels are item titles; an empty list means the part carries no content."""
    return [str(it.get("title") or "").strip() for it in _items(state)]


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites (watermark advance on adopt).

    Works on both a live state and a staging dict. Ledger content grounds in each
    item's provenance trail; non-record refs normalise to empty and are dropped."""
    for it in _items(state):
        for ref in (it.get("provenance") or []):
            stem = normalize_record_ref(ref)
            if stem:
                yield stem


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[label,count],...], staged}`. The render layer (registry
    view) reads only this dict, never the ledger's internal item / status shape, so
    the projection dispatches through the seam like the writer. Item counts by
    status (STATUS_ORDER first, unknown statuses after, never dropped) + the frozen
    cold-start staging count. Tolerant of a partially-written / corrupt state."""
    raw = state.get("items") if isinstance(state, dict) else None
    items = raw if isinstance(raw, list) else []
    counts: dict[str, int] = {}
    total = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        total += 1
        st = it.get("status")
        if isinstance(st, str) and st:
            counts[st] = counts.get(st, 0) + 1
    breakdown: list[list] = [[st, counts[st]] for st in STATUS_ORDER if counts.get(st)]
    breakdown += [[st, counts[st]] for st in sorted(counts) if st not in STATUS_ORDER]
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("items"), list):
        staged = sum(1 for x in staging["items"] if isinstance(x, dict))
    return {"total": total, "breakdown": breakdown, "staged": staged}
