#!/usr/bin/env python3
"""Stance part-plugin — the reference kind for "an argued position, held and pushed back".

A `stance` part HOLDS a position and ARGUES it against the owner's drift. It is the one
"hold a position, push back on drift" primitive. Where a `registry` part is the universal
floor for "things with attributes", a `metrics` part tracks "a number toward a target",
and an `assessment` part keeps "a keyed on/off-track verdict", a `stance` part is a
REFERENCE — a plugin tuned for one common shape: a keyed set of positions, each with an
argument the role advances over time.

DUAL GROUNDING — per instance, chosen once in config. A position must REST ON something
the owner can verify; a stance can rest on either of two grounds, declared in the part's
`schema.grounding`:

  - `records` (the DEFAULT for a push-back role) — an argued position grounded in the
    owner's OWN NOTES. Each position cites in-remit record stems, checked ⊆ the
    engine-injected `read_records` corpus, EXACTLY as ledger / narrative / registry /
    metrics / assessment ground. A push-back voice that argues from the owner's own
    expertise composes THIS mode: it needs no constitution backing, so it never
    empty-oracles itself into a dead role.
  - `values` — an argued position grounded in the owner's OWN CONSTITUTION. Each position
    cites constitution principle-ids, checked ⊆ an engine-VERIFIED oracle the runner
    computes OUTSIDE this plugin (the `ztn-roles` SKILL runs `/ztn:check-decision
    --dry_run` on the proposed position POST-thinker and VERIFIES each returned
    principle-id against `0_constitution/` before injecting it as
    `payload["values_oracle"]`). A pure Python plugin cannot invoke a skill, so the
    runner owns the oracle; the plugin only checks membership. No oracle injected → an
    empty oracle → every position rejected (fail-closed: no oracle = no grounding).

The grounding is PER INSTANCE — the plugin declares the supported set
`GROUNDING_MODES = ("records", "values")` and reads its OWN `schema["grounding"]` to pick
the branch each tick. `validate_schema` is fail-closed: `schema.grounding` MUST be exactly
one of the two (the concierge always emits it); a missing or other value RAISES rather
than silently defaulting. The honesty guarantee is the same in both modes: a body cannot
cite a record not in the remit, nor forge a principle not in the constitution — an uncited
position, or one citing outside the grounding set, is REJECTED. One grounding-NEUTRAL
`citations` field carries record stems in records mode and principle-ids in values mode;
its meaning is set by the mode, not the field.

A stance NEVER acts. It has no outward effect and no act op — it surfaces ONLY via the
role's existing `role-nudge` channel (always-HITL, the cumulative nudge budget), which the
runner owns. This plugin merely keeps the position state honest; the proactive surfacing
of a position is the role's bounded, dismissable nudge.

Shape is minimal. The schema is `{grounding: "records" | "values"}` — a stance needs no
other owner-declared shape (unlike registry / metrics / assessment); its positions are
body-created and keyed by the owner's own topic. The schema is overlaid from config each
tick (config is the source of truth).

State = keyed positions, each carrying an APPEND-ONLY history of the argument's evolution
(grow-only, like assessment / metrics): the CURRENT argument + citations plus the trail of
every prior argument it superseded. Latest wins for the present state; a re-argue never
blanks the prior — it is preserved in the position's own grow-only trail. Nothing is ever
deleted; a closed position is flagged, not removed.

Ops (`DELTAS`):
  - `take-position` — open a NEW keyed position with a position headline, an argument,
    and ≥1 citation (a record stem in records mode / a principle-id in values mode).
  - `argue` — advance the argument on an EXISTING OPEN position (new argument + citations;
    the prior is pushed onto the append-only history). A held / resolved position is NOT
    re-argued — that is the backoff, enforced deterministically.
  - `note-counter` — record that the owner pushed back on a position. No grounding (it
    records an owner action, not a role assertion).
  - `resolve` — close a position to `held` (paused, still standing) or `resolved`
    (settled), with an Archive-Contract reason.

Counter-backoff (advisory-only, deterministic): TWO `note-counter` events on the same
position auto-`resolve` it to `held` — "owner said no twice → back off". This is a soft
stop, never a nag: once held, the position is not re-argued. Grounding-independent, like
every op.

Exposes the per-part plugin interface (the SAME hooks the other kinds expose):
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODES, CONCIERGE_MANIFEST,
  STANCE_VERSION, REQUIRES_SCHEMA (config loader requires + validates a schema),
  validate_schema(raw)                  -> dict  (canonical schema; raises on malformed)
  fresh_state()                         -> dict
  known_key_numbers(state)              -> Iterable[int]  (stance mints no keys)
  validate(prior_state, delta_payload)  -> ValidationResult
  persist(prior_state, approved_deltas, key_minter) -> new_state
  render(state)                         -> str
  identity(item, anchors)               -> IdentityResult  (n/a — natural keys)
  gate_identity(role_id, part_id, prior_state, approved) -> (kept, [])
  build_decisions(...)                  -> list[dict]
  cold_materialize_decisions(...)       -> list[dict]
  delta_counts(persisted_deltas)        -> (added, advanced)
  content_view(state)                   -> dict
  adopt_staging(prior_state, staging)   -> new_state
  content_summary(state)                -> list[str]
  consumed_records(state)               -> Iterable[str]  (the cited record stems in
                                           records mode; EMPTY in values mode)
  registry_summary(state)               -> dict

Watermark seam: `consumed_records` yields the cited record stems in RECORDS mode (so a
records stance rides the shared records watermark exactly like assessment) and the empty
unit in VALUES mode (so a values stance stays behind — "always re-examine", correct for a
standing constitution-grounded position). The generalized forward watermark
(`roles_persist._advance_watermark` over `read_records ∪ consumed_records`) and the
runner's freshness check are both generalized per the part's grounding, so a records
stance is watermark-fresh-proxied like any records kind while a values stance (whose
watermark stays None) is content-proxied and not re-armed for cold-start every tick.

Deterministic, no LLM. Cross-platform: pure in-memory transforms; the caller owns all I/O
(atomic writes, hashing) via `roles_common` / `roles_persist`.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from _common import today_iso

from roles_common import (
    ClarificationSignal,
    IdentityResult,
    RoleConfigError,
    ValidationResult,
    decision_row,
    delta_ref,
    grow_provenance,
    nonempty_str,
    normalize_record_ref,
    read_record_corpus,
    truncate,
    ungrounded_refs,
)


# -----------------------------------------------------------------------------
# Archetype identity + vocabulary
# -----------------------------------------------------------------------------

ARCHETYPE = "stance"

# A stance is DUAL-GROUNDED, chosen PER INSTANCE in `schema.grounding`:
#   - `records` — a position cites in-remit record stems (the owner's own notes),
#     checked ⊆ the engine-injected `read_records` corpus, exactly like ledger /
#     narrative / registry / metrics / assessment. The DEFAULT for a push-back role.
#   - `values` — a position cites constitution principle-ids, checked ⊆ the
#     engine-verified `values_oracle` the runner injects.
# The mode is per-instance, so there is NO scalar `GROUNDING_MODEL` (a scalar would lie
# about a dual kind). The plugin declares the SUPPORTED SET below and reads its own
# `schema["grounding"]` to pick the branch; the writer's grounding-mode seams read the
# per-part `PartSpec.grounding` (the SoT), never a plugin constant.
GROUNDING_MODES: tuple[str, ...] = ("records", "values")

# Signals the config loader (`roles_common._parse_parts`) that a stance part MUST carry
# a well-formed `schema:` block, dispatched to `validate_schema` below.
REQUIRES_SCHEMA = True

# Ops the tick body may propose. `take-position` opens a NEW keyed position; `argue`
# advances the argument on an existing OPEN one; `note-counter` records an owner
# pushback; `resolve` closes a position to held / resolved. Order does not dictate
# persist application order. There is deliberately NO act op — a stance never acts.
DELTAS: tuple[str, ...] = ("take-position", "argue", "note-counter", "resolve")

# The ops that ASSERT a position and therefore MUST be grounded — cite ≥1 citation ⊆
# the mode's oracle (record stems ⊆ `read_records` in records mode; principle-ids ⊆ the
# engine-verified oracle in values mode). `note-counter` records an owner action (not an
# assertion) and `resolve` closes a debate — neither carries a citation.
_GROUNDED_OPS: frozenset[str] = frozenset({"take-position", "argue"})

# The debate lifecycle. `open` = the role is actively holding + arguing the position;
# `held` = backed off (owner pushed back, or an explicit soft close) — still standing
# but not re-argued; `resolved` = settled and closed. `held` / `resolved` are the two
# terminal-for-arguing states.
DEBATE_OPEN = "open"
DEBATE_HELD = "held"
DEBATE_RESOLVED = "resolved"
DEBATE_STATUSES: frozenset[str] = frozenset({DEBATE_OPEN, DEBATE_HELD, DEBATE_RESOLVED})
# The two states an explicit `resolve` may move a position to.
_RESOLVE_TARGETS: frozenset[str] = frozenset({DEBATE_HELD, DEBATE_RESOLVED})

# Counter-backoff threshold: this many `note-counter` events on a position auto-hold
# it (advisory-only, "owner said no twice → back off"). Deterministic in `persist`.
COUNTER_BACKOFF_THRESHOLD = 2

# Fields the body may NEVER set on a delta — engine-owned (stamped on persist). A delta
# carrying any of them is rejected (append-not-replace): the body proposes a position /
# argument / citations; the counter tally, the debate status, the trail, provenance and
# date are the engine's.
_BODY_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {"owner_counter", "debate_status", "history", "provenance", "at", "resolve_reason"}
)

# Stance schema version — bumped only on an incompatible shape change (with a matching
# migration). Additive-optional changes keep it stable.
STANCE_VERSION = 1

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned argued-position set. Written ONLY by roles_persist.py through this "
        "plugin. Never hand-edited. Its `schema` (just `{grounding: records|values}`) is "
        "overlaid from config.yml on every load — config is the source of truth for the "
        "shape. Each position holds its CURRENT argument + citations (present state) plus "
        "an append-only trail of the prior arguments it superseded."
    ),
    "top_level": {
        "version": "int (schema version of the stance file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'stance'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": (
            "str|null (per-kind watermark; advances over cited records in records mode, "
            "stays None in values mode — a values stance consumes no records)"
        ),
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "schema": "object {grounding: 'records'|'values'} — overlaid from config (per-instance)",
        "positions": "list[position] (one per keyed position; positions never deleted)",
    },
    "position": {
        "key": "str (the owner-topic natural key — the identity)",
        "position": "str (the stance taken — a short headline)",
        "argument": "str (the CURRENT argument for the position)",
        "citations": (
            "list[str] (what the argument rests on — in-remit record stems in records "
            "mode, constitution principle-ids in values mode)"
        ),
        "owner_counter": "int (how many times the owner pushed back on this position)",
        "debate_status": "str (open | held | resolved)",
        "provenance": "list[str] (grow-only trail of every citation ever made here)",
        "at": "str (YYYY-MM-DD the position was last advanced)",
        "resolve_reason": "str (present iff held/resolved — the Archive-Contract reason)",
        "history": (
            "list[{position, argument, citations, at}] (append-only trail of PRIOR "
            "arguments; an `argue` pushes the superseded one here — grow-only)"
        ),
    },
}


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language. Domain-NEUTRAL by design: the kind is
# "an argued position that pushes back on your drift, grounded in your notes OR your
# principles" — not any specific role. `built: True` marks it installed + composable.
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Hold a position and argue it against your drift. For each thing it takes a "
        "stand on, it keeps the stance, the argument behind it, and what that argument "
        "rests on — and advances the argument as you move. You choose the ground: it can "
        "argue from your OWN NOTES (your expertise — the default for a push-back voice) "
        "or from your OWN PRINCIPLES (your constitution — when you want life-values "
        "push-back). It only ever raises its voice as a dismissable nudge; it never "
        "acts, and it backs off when you push back twice."
    ),
    "triggers": [
        "держи позицию и спорь со мной, когда я дрейфую",
        "оппонируй мне, опираясь на мои же заметки и опыт",
        "напоминай, где я расхожусь со своими установками",
        "оппонент, который стоит на своём — по моим заметкам или по моему кодексу",
        "hold a position and push back on my drift",
        "argue against me from my own notes and expertise",
        "argue against me from my own principles",
        "a standing counter-voice grounded in what I wrote or what I stand for",
    ],
    "produces_preview": (
        "A present-state list of the positions it holds — each with its current "
        "argument, what it rests on (a note of yours, or a principle of yours), whether "
        "you have pushed back, and whether the debate is open, held, or resolved. It "
        "advances an argument as you move and keeps the trail of how it evolved. Every "
        "argument cites something real — a note in its remit, or a principle from your "
        "constitution; it can never invent one."
    ),
    "determinism_note": (
        "MEDIUM determinism: the engine guarantees every argument cites ONLY something "
        "that genuinely exists — a note truly in the role's remit (records-grounded) or "
        "a principle truly in your constitution (values-grounded); a fabricated citation "
        "is rejected. It guarantees a re-argued position keeps the prior one in an "
        "append-only trail (latest wins, nothing rewritten), and that after you push "
        "back twice the position auto-holds and stops arguing (it never nags). WHAT "
        "position to take and HOW to argue it is the role's judgment, shown as such — "
        "never invented. A stance never acts on anything; it only ever surfaces as a "
        "nudge you can dismiss."
    ),
    "built": True,
}


# -----------------------------------------------------------------------------
# Config-time schema hook — the plugin owns its own schema shape (the seam)
# -----------------------------------------------------------------------------

def validate_schema(raw: Any) -> dict:
    """Validate the raw `schema:` block from a stance part's config; return the
    canonical schema dict, or raise `RoleConfigError` on any malformed input.

    The plugin side of the composite loader seam (dispatched from
    `roles_common._parse_part_schema` because `REQUIRES_SCHEMA` is set). A stance
    schema is MINIMAL — just an EXPLICIT `grounding` — because a stance needs no other
    owner-declared shape (its positions are body-created and keyed by the owner's own
    topic). The one contract this enforces is fail-closed: `grounding` MUST be exactly
    one of `GROUNDING_MODES` (`records` — argue from the owner's notes, the default for a
    push-back role; or `values` — argue from the owner's constitution). It is REQUIRED,
    with NO silent default: the concierge always emits it, so a missing or other value
    RAISES rather than guessing a mode.

    Stage 2.5 grounding-check is OFF for a stance in BOTH modes: a position is an argued
    STANCE, not a world-claim verdict like an assessment. Its honesty gate is the
    validate-time `citations ⊆ oracle` check (records ⊆ `read_records`, or principle-ids ⊆
    the engine-verified values-oracle) — not a second adversarial re-read. Error messages
    carry the shape-specific detail only; the loader locates them to `{path}: part {pid!r}`.
    """
    if not isinstance(raw, dict):
        raise RoleConfigError(
            "needs a 'schema:' block with an explicit 'grounding' "
            f"('records' or 'values'), got {type(raw).__name__}"
        )
    grounding = raw.get("grounding")
    if not isinstance(grounding, str) or grounding.strip() not in GROUNDING_MODES:
        raise RoleConfigError(
            "schema 'grounding' for a stance part must be 'records' (argue from your own "
            "notes) or 'values' (argue from your constitution) — it is required, with no "
            f"default, got {grounding!r}"
        )
    return {"grounding": grounding.strip(), "grounding_check": False}


def fresh_state() -> dict:
    """A brand-new stance part's top-level fields with archetype defaults filled.

    `schema` is a `{}` PLACEHOLDER: the sole writer overlays the real config-declared
    schema (`{grounding: values}`) onto both a fresh seed and a loaded state, so this
    stays generic. The common writer overlays the per-instance fields it owns
    (`role_id`, `part_id`, `archetype`, `description`). Returns a fresh dict each call.
    """
    return {
        "version": STANCE_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": {},
        "positions": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Stance mints no `lk-NNNN` keys — a position's identity is the owner's natural
    key for the topic it takes a stand on.

    Yields nothing (present so the writer can build a `KeyMinter` uniformly across
    every part-kind; `persist` never calls the minter)."""
    return ()


# -----------------------------------------------------------------------------
# Schema + state accessors (shape lives in DATA; every hook reads it here)
# -----------------------------------------------------------------------------

def _schema(state: Any) -> dict:
    if not isinstance(state, dict):
        return {}
    schema = state.get("schema")
    return schema if isinstance(schema, dict) else {}


def _positions(state: Any) -> list[dict]:
    """The position list of a live state OR a staging dict (both carry it)."""
    if not isinstance(state, dict):
        return []
    raw = state.get("positions")
    return [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []


def _pos_key(pos: Any) -> str:
    if not isinstance(pos, dict):
        return ""
    key = pos.get("key")
    return key.strip() if isinstance(key, str) else ""


def _pos_status(pos: Any) -> str:
    if not isinstance(pos, dict):
        return ""
    v = pos.get("debate_status")
    return v.strip() if isinstance(v, str) else ""


def _index(positions: Iterable[dict]) -> dict[str, dict]:
    """Positions indexed by natural key (unique — validate blocks a same-tick dup)."""
    out: dict[str, dict] = {}
    for p in positions:
        k = _pos_key(p)
        if k:
            out[k] = p
    return out


def _norm(value: Any) -> str:
    return value.strip() if nonempty_str(value) else ""


def _cited_list(raw: Any) -> list[str]:
    """The non-empty string citations of a `citations` list, stripped, in order,
    de-duplicated (first-seen). Citations are record stems in records mode / principle-ids
    in values mode — the same shape either way. A non-list yields []."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for r in raw:
        if isinstance(r, str) and r.strip() and r.strip() not in seen:
            seen.add(r.strip())
            out.append(r.strip())
    return out


def _values_oracle(delta_payload: Any) -> set[str]:
    """The set of engine-VERIFIED constitution principle-ids the body may cite this
    tick — the values-grounding oracle, parallel to the records `read_records` corpus.
    Read ONLY in values mode.

    The runner (the `ztn-roles` SKILL) computes it out-of-band via `/ztn:check-decision
    --dry_run` and VERIFIES each id against `0_constitution/` before injecting it as
    `payload["values_oracle"]`; this plugin only checks membership. A missing / malformed
    oracle yields the EMPTY set → every values-op is rejected (fail-closed: no oracle =
    no grounding). Accepts a list / tuple / set of ids, or a dict keyed by id (tolerant
    of a `{id: relation}` verdict shape from check-decision)."""
    raw = delta_payload.get("values_oracle") if isinstance(delta_payload, dict) else None
    if isinstance(raw, dict):
        return {p.strip() for p in raw.keys() if isinstance(p, str) and p.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {p.strip() for p in raw if isinstance(p, str) and p.strip()}
    return set()


# -----------------------------------------------------------------------------
# validate — structural + values-grounding gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed stance delta payload before it may be persisted.

    STRUCTURAL: the payload envelope parses; `op` is known; no engine-owned field is
    body-set; the natural `key` is present; a `take-position` targets a NEW key while
    `argue` / `note-counter` / `resolve` target an EXISTING one; an `argue` targets an
    OPEN position (a held / resolved one is not re-argued — the backoff); a `resolve`
    names a valid target status + reason; a key is not touched twice this tick.

    GROUNDING (dual, per the part's own `schema.grounding`): every `take-position` /
    `argue` MUST cite ≥1 citation, and each citation MUST be a member of the mode's
    oracle:
      - records mode → citations are record stems ⊆ the engine-injected `read_records`
        corpus (exactly as ledger / assessment ground).
      - values mode → citations are principle-ids ⊆ the engine-verified `values_oracle`
        (the ids the runner checked exist in `0_constitution/`).
    An uncited position, or one citing outside the mode's oracle, is REJECTED — a body
    cannot cite a record not in the remit nor forge a principle not in the constitution.
    No oracle / empty corpus → every grounded op rejected (fail-closed). `note-counter` /
    `resolve` carry no citation. The plugin reads its OWN `schema.grounding` to pick the
    branch (it sees its own schema, overlaid from config).

    Same contract shape as the other kinds: ok=True persists `approved_deltas` (possibly
    empty); ok=False blocks the whole tick (malformed envelope / corrupt state / unknown
    grounding).
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

    grounding = str(_schema(prior_state).get("grounding") or "").strip()
    if grounding not in GROUNDING_MODES:
        # Defensive — the config loader requires a valid grounding before a stance part
        # loads, but a corrupt state with an unknown grounding cannot be validated. Hold.
        return ValidationResult.rejected(
            rejections=({"ref": "schema",
                         "reason": f"stance schema grounding {grounding!r} is not one of "
                                   f"{list(GROUNDING_MODES)}"},)
        )

    # Per-mode oracle: the principle-id set (values) OR the in-remit record corpus
    # (records). Only the one for this instance's grounding is consulted.
    oracle = _values_oracle(delta_payload) if grounding == "values" else set()
    corpus = read_record_corpus(delta_payload) if grounding == "records" else set()
    index = _index(_positions(prior_state))

    approved: list[dict] = []
    rejections: list[dict] = []
    touched: set[str] = set()

    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": delta_ref(delta, idx, ("key",)),
                               "reason": "delta is not a mapping"})
            continue
        reason = _validate_delta(delta, index, grounding, oracle, corpus, touched)
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": reason})
            continue
        approved.append(delta)

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
    )


def _validate_delta(
    delta: dict, index: dict[str, dict], grounding: str, oracle: set[str],
    corpus: set[str], touched: set[str]
) -> str | None:
    """Return a rejection reason, or None when the delta is well-formed AND (for a
    grounded op) grounded in the part's mode. Mutates `touched` with the key an accepted
    delta addresses, so a second delta touching the same key this tick is a conflict."""
    op = delta.get("op")
    if op not in DELTAS:
        return f"unknown op {op!r}"
    for forbidden in _BODY_FORBIDDEN_FIELDS:
        if forbidden in delta:
            return f"append-not-replace: '{forbidden}' is engine-owned, not body-set"
    key = delta.get("key")
    if not nonempty_str(key):
        return f"{op} missing non-empty 'key'"
    key = key.strip()
    if key in touched:
        return f"{op} 'key' {key!r} is already touched by another delta this tick"

    existing = index.get(key)

    if op == "take-position":
        if existing is not None:
            return (f"take-position 'key' {key!r} already holds a position — use "
                    "'argue' to advance it")
        if not nonempty_str(delta.get("position")):
            return "take-position missing non-empty 'position'"
        if not nonempty_str(delta.get("argument")):
            return "take-position missing non-empty 'argument'"
        reason = _grounding_reason(delta, grounding, oracle, corpus)
        if reason is not None:
            return reason
        touched.add(key)
        return None

    if op == "argue":
        if existing is None:
            return f"argue 'key' {key!r} does not exist as a position"
        status = _pos_status(existing)
        if status != DEBATE_OPEN:
            return (f"argue 'key' {key!r} is {status or 'not open'} — a "
                    f"{status or 'closed'} position is not re-argued (backoff / closed)")
        if not nonempty_str(delta.get("argument")):
            return "argue missing non-empty 'argument'"
        reason = _grounding_reason(delta, grounding, oracle, corpus)
        if reason is not None:
            return reason
        touched.add(key)
        return None

    if op == "note-counter":
        if existing is None:
            return f"note-counter 'key' {key!r} does not exist as a position"
        if _pos_status(existing) == DEBATE_RESOLVED:
            return f"note-counter 'key' {key!r} is resolved — a settled debate takes no counter"
        touched.add(key)
        return None

    if op == "resolve":
        if existing is None:
            return f"resolve 'key' {key!r} does not exist as a position"
        if _pos_status(existing) == DEBATE_RESOLVED:
            return f"resolve 'key' {key!r} is already resolved"
        to = delta.get("to")
        if not isinstance(to, str) or to.strip() not in _RESOLVE_TARGETS:
            return (f"resolve 'to' must be one of {sorted(_RESOLVE_TARGETS)}, "
                    f"got {to!r}")
        if not nonempty_str(delta.get("reason")):
            return "resolve requires a non-empty 'reason' (the Archive-Contract reason)"
        touched.add(key)
        return None

    return f"unhandled op {op!r}"  # unreachable — op membership checked above


def _grounding_reason(
    delta: dict, grounding: str, oracle: set[str], corpus: set[str]
) -> str | None:
    """None when a grounded op cites ≥1 citation AND every citation is in the mode's
    oracle; else a reason. The honesty gate, one per mode:

      - values → each cited principle-id MUST be in the engine-verified `oracle` (which
        only holds ids the runner verified in `0_constitution/`). An empty oracle →
        every citation is out → rejected (fail-closed: no oracle = no grounding).
      - records → each cited record stem MUST be in the in-remit `corpus` (the
        engine-injected `read_records`), the same ⊆-check ledger / assessment run. An
        empty corpus → every citation is out → rejected.

    A body can forge neither: it cannot cite a record not in the remit nor a principle
    not in the constitution."""
    cited = _cited_list(delta.get("citations"))
    if grounding == "values":
        if not cited:
            return f"{delta.get('op')} must cite at least one constitution principle"
        missing = [p for p in cited if p not in oracle]
        if missing:
            return (f"ungrounded: {delta.get('op')} cites principle(s) not in the "
                    f"engine-verified oracle: {missing}")
        return None
    # records mode — mirror assessment's records grounding EXACTLY.
    if not cited:
        return f"{delta.get('op')} must cite at least one in-remit record"
    missing = ungrounded_refs(cited, corpus)
    if missing:
        return (f"ungrounded: {delta.get('op')} cites record(s) not in read_records: "
                f"{missing}")
    return None


# -----------------------------------------------------------------------------
# persist — pure transform (roles_persist is the sole caller / writer)
# -----------------------------------------------------------------------------

def persist(prior_state: Any, approved_deltas: Iterable[dict], key_minter) -> dict:
    """Apply already-validated deltas to a copy of `prior_state`; return new state.

    Pure: no I/O, never mutates inputs, never calls `key_minter` (a position's key is
    the owner's natural topic, not minted). Per op:
      - `take-position` → create the position (open, owner_counter 0, empty history).
      - `argue`         → push the PRIOR argument onto the append-only history, set the
                          new argument + citations as current (grow-only — the prior is
                          never blanked).
      - `note-counter`  → increment the owner-pushback tally; on the SECOND counter the
                          position auto-holds (deterministic backoff — advisory-only).
      - `resolve`       → close the position to held / resolved with its reason.

    Latest wins for the present state; nothing is ever deleted. A closed position is
    flagged (`debate_status` + `resolve_reason`), keeping its argument and trail intact.
    """
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    positions = new_state.get("positions")
    if not isinstance(positions, list):
        positions = []
    new_state["positions"] = positions
    today = today_iso()
    index = _index(it for it in positions if isinstance(it, dict))

    for delta in approved_deltas:
        if not isinstance(delta, dict):
            continue
        op = delta.get("op")
        key = _norm(delta.get("key"))
        if not key:
            continue
        if op == "take-position":
            pos = _new_position(key, delta, today)
            positions.append(pos)
            index[key] = pos
        elif op == "argue":
            _apply_argue(index.get(key), delta, today)
        elif op == "note-counter":
            _apply_counter(index.get(key), delta, today)
        elif op == "resolve":
            _apply_resolve(index.get(key), delta, today)

    return new_state


def _new_position(key: str, delta: dict, today: str) -> dict:
    cited = _cited_list(delta.get("citations"))
    return {
        "key": key,
        "position": _norm(delta.get("position")),
        "argument": _norm(delta.get("argument")),
        "citations": cited,
        "owner_counter": 0,
        "debate_status": DEBATE_OPEN,
        "provenance": grow_provenance([], cited),
        "at": today,
        "history": [],
    }


def _apply_argue(pos: Any, delta: dict, today: str) -> None:
    """Advance the argument on an existing OPEN position: push the superseded argument
    onto the append-only history (grow-only, never blanked), set the new argument +
    citations as current, grow the citation provenance, refresh the date. The position
    headline stays; an `argue` advances HOW the position is argued, not the position."""
    if not isinstance(pos, dict):
        return
    history = pos.get("history")
    if not isinstance(history, list):
        history = []
        pos["history"] = history
    history.append({
        "position": pos.get("position") if isinstance(pos.get("position"), str) else "",
        "argument": pos.get("argument") if isinstance(pos.get("argument"), str) else "",
        "citations": list(pos.get("citations") or []),
        "at": pos.get("at") if isinstance(pos.get("at"), str) else "",
    })
    cited = _cited_list(delta.get("citations"))
    pos["argument"] = _norm(delta.get("argument"))
    pos["citations"] = cited
    pos["provenance"] = grow_provenance(pos.get("provenance"), cited)
    pos["at"] = today


def _apply_counter(pos: Any, delta: dict, today: str) -> None:
    """Record an owner pushback: increment the tally and, on the SECOND counter,
    auto-hold the position (the deterministic backoff — "owner said no twice → back
    off"). The auto-hold is advisory-only: it stops the position being re-argued, and
    it is never a nag. A counter never touches the argument or its trail."""
    if not isinstance(pos, dict):
        return
    count = pos.get("owner_counter")
    count = count + 1 if isinstance(count, int) else 1
    pos["owner_counter"] = count
    pos["at"] = today
    if count >= COUNTER_BACKOFF_THRESHOLD and _pos_status(pos) == DEBATE_OPEN:
        pos["debate_status"] = DEBATE_HELD
        pos["resolve_reason"] = (
            f"auto-held: owner pushed back {count} times — backing off (advisory-only)"
        )


def _apply_resolve(pos: Any, delta: dict, today: str) -> None:
    """Close a position to held / resolved with its Archive-Contract reason. Keeps the
    argument and the trail intact (a stance never deletes a position)."""
    if not isinstance(pos, dict):
        return
    to = delta.get("to")
    pos["debate_status"] = to.strip() if isinstance(to, str) else DEBATE_HELD
    pos["resolve_reason"] = _norm(delta.get("reason"))
    pos["at"] = today


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

# Render order for the debate groups — open first (the live positions), then held
# (backed off), then resolved (settled).
_RENDER_ORDER: tuple[str, ...] = (DEBATE_OPEN, DEBATE_HELD, DEBATE_RESOLVED)


def render(state: Any) -> str:
    """Render the stance as the state.md AUTO-zone markdown body (present-state).

    Grouped by debate status — open, then held, then resolved — so the owner reads the
    live positions first. Each position renders as `- {key} — {position}` with the
    current argument, the principles it rests on, the owner-pushback count when any, and
    a `held/resolved: {reason}` suffix when closed. The caller wraps this in the
    role-state markers."""
    positions = _positions(state)
    if not positions:
        return "_No positions yet._"
    groups: dict[str, list[dict]] = {}
    for p in positions:
        groups.setdefault(_pos_status(p) or DEBATE_OPEN, []).append(p)
    order = list(_RENDER_ORDER)
    order += [s for s in sorted(groups) if s not in order]

    lines: list[str] = []
    for status in order:
        bucket = groups.get(status)
        if not bucket:
            continue
        lines.append(f"### {status}")
        lines.append("")
        for p in sorted(bucket, key=_pos_key):
            lines.append(_render_position(p))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_position(pos: dict) -> str:
    key = _pos_key(pos) or "(no key)"
    line = f"- {key}"
    position = pos.get("position")
    if nonempty_str(position):
        line += f" — {position.strip()}"
    argument = pos.get("argument")
    if nonempty_str(argument):
        line += f"\n  - argument: {argument.strip()}"
    cited = _cited_list(pos.get("citations"))
    if cited:
        line += f"\n  - grounded in: {', '.join(cited)}"
    counter = pos.get("owner_counter")
    if isinstance(counter, int) and counter > 0:
        line += f"\n  - owner pushed back {counter}×"
    status = _pos_status(pos)
    if status in (DEBATE_HELD, DEBATE_RESOLVED):
        reason = _norm(pos.get("resolve_reason"))
        line += f"\n  - {status}" + (f": {reason}" if reason else "")
    return line


# -----------------------------------------------------------------------------
# identity — natural keys; no external anchor concept (never guesses)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Stance positions are identified by the owner's NATURAL KEY for the topic, not an
    external Minder id — there is nothing to anchor and nothing to guess. Returns
    `anchored=True` and never fabricates an anchor. The writer never calls this for a
    stance part; present for interface uniformity."""
    return IdentityResult(anchored=True, anchor=None)


# -----------------------------------------------------------------------------
# Composite-seam hooks (mirror the other kinds; stance-shaped)
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Stance has no anchor-identity concept — every approved delta passes.

    Returns `(approved, [])`. A position is identified by its exact natural key
    (deterministic); there is nothing to anchor-or-HITL. Never fabricates an anchor."""
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
    """One decision row per persisted stance delta, stamped `part`.

    `kind` vocabulary: position-take (a first position for a key) / position-argue (an
    advanced argument) / position-counter (an owner pushback) / position-resolve (a
    close to held / resolved). No keys are minted, so `minted` is ignored and the row
    `key` is the position's natural key. A grounded-op row carries its `cited` citations
    (record stems in records mode / principle-ids in values mode)."""
    rows: list[dict] = []
    for d in approved_deltas:
        if not isinstance(d, dict):
            continue
        op = d.get("op")
        key = d.get("key")
        if op == "take-position":
            rows.append(decision_row(
                "position-take", key, hook, role_id, part_id, ts,
                cited=_cited_list(d.get("citations")),
            ))
        elif op == "argue":
            rows.append(decision_row(
                "position-argue", key, hook, role_id, part_id, ts,
                cited=_cited_list(d.get("citations")),
            ))
        elif op == "note-counter":
            rows.append(decision_row("position-counter", key, hook, role_id, part_id, ts))
        elif op == "resolve":
            rows.append(decision_row(
                "position-resolve", key, hook, role_id, part_id, ts,
                to=d.get("to"), reason=d.get("reason"),
            ))
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts. A `take-position` places a new position →
    ADDED; `argue` / `note-counter` / `resolve` change an existing one → ADVANCED."""
    added = sum(1 for d in persisted_deltas
                if isinstance(d, dict) and d.get("op") == "take-position")
    advanced = sum(1 for d in persisted_deltas
                   if isinstance(d, dict) and d.get("op") in ("argue", "note-counter", "resolve"))
    return added, advanced


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per position when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", p.get("key"), "tick", role_id, part_id, ts,
            cited=_cited_list(p.get("citations")),
            debate_status=_pos_status(p),
        )
        for p in _positions(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start.

    Stance content is its `positions` list. The writer spreads this into the staging
    dict and adopts it later via `adopt_staging`; the SCHEMA (`{grounding: values}`) is
    NOT frozen — the writer re-overlays it from config on every load, so config stays
    the source of truth for the shape."""
    return {"positions": list(_positions(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state.

    Returns a deep copy of `prior_state` (which already carries the config-overlaid
    schema) with its `positions` replaced by the staged draft's. The writer clears
    `staging`, resets the reject counter and advances the (per-kind) watermark over
    `consumed_records` — the cited record stems in records mode (so the adopted part is
    watermark-fresh-proxied like any records kind), or EMPTY in values mode (so the
    watermark stays put and the generalized freshness check treats the adopted part by
    its live content, not its watermark)."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    src = staging.get("positions") if isinstance(staging, dict) else None
    ns["positions"] = [p for p in src if isinstance(p, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification + count).

    ONE label per position — its natural key, its position headline, and its debate
    status. Works on both a live state and a staging dict; an empty list means the part
    carries no content (used by the generalized freshness check to tell an adopted
    stance from a never-adopted one)."""
    return [_position_label(p) for p in _positions(state)]


def _position_label(pos: dict) -> str:
    key = _pos_key(pos) or "(no key)"
    position = pos.get("position")
    label = f"{key}: {position.strip()}" if nonempty_str(position) else key
    status = _pos_status(pos)
    if status and status != DEBATE_OPEN:
        label += f" ({status})"
    return truncate(label)


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites — per the part's grounding mode.

    - records mode → yield each position's cited record stems (its grow-only
      `provenance`, normalised), so a records stance rides the shared records watermark
      EXACTLY like assessment (`roles_persist._advance_watermark` over
      `read_records ∪ consumed_records`).
    - values mode → yield NOTHING. A values stance grounds in the owner's CONSTITUTION
      (principle-ids), not records, so it consumes no record and stays behind on the
      watermark ("always re-examine"). A principle-id is deliberately NOT yielded — it is
      not a record stem, and treating it as one would corrupt the lexical-max watermark.

    The plugin reads its OWN `schema.grounding` to route; any non-`records` grounding
    (values, or a corrupt state) yields nothing — the conservative, watermark-safe path.
    """
    if str(_schema(state).get("grounding") or "").strip() != "records":
        return ()

    def _stems() -> Iterable[str]:
        for p in _positions(state):
            for ref in p.get("provenance") or []:
                stem = normalize_record_ref(ref)
                if stem:
                    yield stem

    return _stems()


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[status,count],...], staged}`. Total = all positions; breakdown
    = present-state count per debate status in render order (open / held / resolved,
    non-zero only); staged = a frozen cold-start draft's positions. The render layer
    reads only this dict, never the internal position shape. Tolerant of a
    partially-written / corrupt state."""
    raw = state.get("positions") if isinstance(state, dict) else None
    positions = raw if isinstance(raw, list) else []
    total = 0
    by_status: dict[str, int] = {}
    for p in positions:
        if not isinstance(p, dict):
            continue
        total += 1
        s = _pos_status(p) or DEBATE_OPEN
        by_status[s] = by_status.get(s, 0) + 1
    order = list(_RENDER_ORDER)
    order += [s for s in sorted(by_status) if s not in order]
    breakdown: list[list] = [[s, by_status[s]] for s in order if by_status.get(s)]
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("positions"), list):
        staged = sum(1 for x in staging["positions"] if isinstance(x, dict))
    return {"total": total, "breakdown": breakdown, "staged": staged}
