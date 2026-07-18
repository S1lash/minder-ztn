#!/usr/bin/env python3
"""Assessment part-plugin — the reference kind for "a keyed on/off-track verdict".

An `assessment` part holds ONE verdict per tracked thing, drawn from a short scale
the owner declares — say `on-track / at-risk / off`. Where a `registry` part is the
universal floor for "things with attributes" and a `metrics` part tracks "a number
toward a target", an `assessment` part is a REFERENCE — a plugin tuned for one
common shape (each tracked thing gets a verdict from a declared, ordered set, and
you keep the current call plus the trail of how it moved) so the owner gets a real
present-state read without authoring a plugin per shape.

The load-bearing mechanism, and why this is a REFERENCE rather than a registry
variation, is the PRESENT-VERDICT-PER-KEY PROJECTION OVER AN APPEND-ONLY LOG: each
key carries its LATEST verdict (the present state) plus an append-only `history[]`
of every prior verdict it has held. A verdict CHANGE keeps the prior one (pushes it
onto the history, grow-only, like metrics' provenance grow); a re-assessment with
the same verdict never rewrites the trail. Latest wins; nothing is ever blanked.
That projection — a current call computed as "the last verdict, over the log of all
of them" — is the thing a form-as-data registry cannot COMPUTE, so it earns a tuned
plugin.

Shape is DATA. The verdict vocabulary lives in `state["schema"]` (overlaid by the
sole writer from config — config is the source of truth):

    {"over": <str>,                     # a SIBLING part id, or 'records'
     "verdicts": [<ordered labels>],    # owner-declared, best→worst; form-as-data
     "grounding": "records"}

`verdicts` is owner-declared FORM-AS-DATA — an ordered vocabulary, NOT a fixed enum
this plugin names. The order is meaningful (best→worst) and is preserved end to end:
the render groups by verdict in declared order, so the owner reads the best calls
first and the worst last.

`over` is a read-only BODY-STEER pointer, NOT the grounding. Parts are siloed at the
writer/plugin layer — a plugin never reads a sibling part's state. But the THINKER
(Stage 1) already receives one skeleton PER PART, so an assessment body CAN read the
sibling that `over` names (say a `metrics` part) and reason a verdict from it. That
sibling reading is CONTEXT the thinker weighs; it is NEVER the grounding and NEVER
substitutes for a record cite. An assessment GROUNDS EVERY VERDICT IN A REAL RECORD:
`GROUNDING_MODEL = "records"`, and every `assess` must cite ≥1 in-remit record stem
(uncited → rejected, the records-oracle way ledger / registry / metrics use). Stated
plainly, no honesty over-claim — the `over` context does not lower the grounding bar.

`over` cannot be shape-validated by `validate_schema` (which sees only its own part's
block, never the sibling ids), so it is checked in two places: `validate_schema`
requires `over` to be a NON-EMPTY string; the CROSS-part existence check
(`validate_cross_part`, the new loader hook) requires `over ∈ this role's part ids ∪
{"records"}`, fail-closed against a typo or a retired sibling. The loader calls that
hook only when a plugin exports it (default-absent on the other kinds), so the loader
stays archetype-agnostic — the 17th interface concern, documented at the loader.

Exposes the per-part plugin interface (the SAME hooks ledger / narrative / registry /
metrics expose), plus the cross-part validation seam:
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODEL, CONCIERGE_MANIFEST,
  ASSESSMENT_VERSION, REQUIRES_SCHEMA (config loader requires + validates a schema),
  validate_schema(raw)                  -> dict  (canonical schema; raises on malformed)
  validate_cross_part(schema, sibling_part_ids) -> None  (raises when `over` is neither
    a sibling part id nor 'records'; the loader calls it only if present)
  fresh_state()                         -> dict
  known_key_numbers(state)              -> Iterable[int]  (assessment mints no keys)
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
    RoleConfigError,
    ValidationResult,
    clean_evidence,
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

ARCHETYPE = "assessment"

# Assessment grounds every verdict in a real in-remit record (the body cites the
# record its call rests on), so the part rides the shared records watermark exactly
# like ledger / narrative / registry-records / metrics.
GROUNDING_MODEL = "records"

# Signals the config loader (`roles_common._parse_parts`) that an assessment part
# MUST carry a well-formed `schema:` block, dispatched to `validate_schema` below.
REQUIRES_SCHEMA = True

# Ops the tick body may propose. `assess` assigns or updates ONE key's verdict; WHICH
# verdict is the body's judgment (non-det, records-grounded), but the plugin
# STRUCTURALLY gates it to the declared ordered set. There is deliberately no separate
# mutate op — a re-assessment is another `assess` (latest wins over the append-only
# history).
DELTAS: tuple[str, ...] = ("assess",)

# Fields the body may NEVER set on a delta — engine-owned (stamped on persist). A
# delta carrying any of them is rejected (append-not-replace): the body proposes a
# verdict + a rationale + evidence; the trail, provenance and date are the engine's.
_BODY_FORBIDDEN_FIELDS: frozenset[str] = frozenset({"history", "provenance", "at"})

# Assessment schema version — bumped only on an incompatible shape change (with a
# matching migration). Additive-optional changes keep it stable.
ASSESSMENT_VERSION = 1

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned keyed verdict set. Written ONLY by roles_persist.py through this "
        "plugin. Never hand-edited. Its `schema` (the `over` pointer + the ordered "
        "verdict vocabulary) is overlaid from config.yml on every load — config is the "
        "source of truth for the shape. Each key holds its LATEST verdict (present "
        "state) plus an append-only trail of the prior ones."
    ),
    "top_level": {
        "version": "int (schema version of the assessment file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'assessment'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": "str|null (high-water mark of consumed records)",
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "schema": (
            "object {over, verdicts:[...ordered...], grounding} — overlaid from config; "
            "drives the verdict gate + render order"
        ),
        "assessments": "list[assessment] (one per tracked key; keys never deleted)",
    },
    "assessment": {
        "key": "str (the owner-tracked thing's natural key — the identity)",
        "verdict": "str (the CURRENT verdict; always a member of the declared set)",
        "rationale": "str (optional body-authored one-line why; present-state)",
        "provenance": "list[str] ('[[record-stem]]', append-only, grows)",
        "at": "str (YYYY-MM-DD the current verdict was set)",
        "history": (
            "list[{verdict, rationale, at}] (append-only trail of PRIOR verdicts; a "
            "verdict change pushes the superseded call here — grow-only, never blanked)"
        ),
    },
}


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language. Domain-NEUTRAL by design: the kind is
# "a keyed on/off-track verdict", not any specific subject — the verdict scale is
# whatever the owner declares. `built: True` marks it installed + composable now.
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Keep an on/off-track read on a set of things you track — each tracked thing "
        "gets one verdict from a short scale you name (say on-track / at-risk / off). "
        "You declare the scale, best to worst; each tick the role reads what your "
        "records say and assigns the fitting verdict per thing, keeping the current "
        "call plus the trail of how it moved."
    ),
    "triggers": [
        "оцени каждый пункт: в норме / под риском / сорвано",
        "держи вердикт по каждому отслеживаемому",
        "статус-светофор по моим пунктам",
        "on-track / at-risk / off per thing",
        "keep a verdict on each thing I track",
        "a status read per item from my own scale",
        "traffic-light call on each of these",
    ],
    "produces_preview": (
        "A present-state list grouped by verdict, best to worst — each tracked thing "
        "under its current call, with the short reason and the record that prompted it, "
        "and a 'was …' note when the verdict moved from a prior one. Only the verdicts "
        "you declared are ever used; every call cites a real record."
    ),
    "determinism_note": (
        "MEDIUM determinism: the engine guarantees every verdict is one of YOUR "
        "declared set (nothing off-scale is ever recorded), that each call cites a real "
        "in-remit record, and that a changed verdict keeps the prior one in an "
        "append-only trail (latest wins, nothing rewritten). WHICH verdict fits — and "
        "any short reason — is the role's judgment, read from your records and shown as "
        "such, never invented. If the part reads over a sibling part, that reading is "
        "context the role weighs; it never replaces the record citation."
    ),
    "built": True,
}


# -----------------------------------------------------------------------------
# Config-time schema hook — the plugin owns its own schema shape (the seam)
# -----------------------------------------------------------------------------

def validate_schema(raw: Any) -> dict:
    """Validate the raw `schema:` block from an assessment part's config; return the
    canonical schema dict, or raise `RoleConfigError` on any malformed input.

    The plugin side of the composite loader seam (dispatched from
    `roles_common._parse_part_schema` because `REQUIRES_SCHEMA` is set). THIS plugin
    owns the assessment schema contract — a non-empty `over` string (a sibling part id
    or the literal `records`), a non-empty ORDERED list of unique non-empty verdict
    labels (owner-declared form-as-data, best→worst — NOT a fixed enum this plugin
    names), and `grounding: records` (an assessment grounds each verdict in a record;
    any other mode fail-closes rather than silently degrading).

    `over` is only SHAPE-checked here (a non-empty string) — its cross-part EXISTENCE
    (`over ∈ this role's part ids ∪ {records}`) is checked later by
    `validate_cross_part`, because `validate_schema` sees only its own part's block and
    cannot know the sibling ids. Error messages carry the shape-specific detail only
    (they name no config path or part id); the loader locates them to
    `{path}: part {pid!r}` when it catches.
    """
    if not isinstance(raw, dict):
        raise RoleConfigError(
            "needs a 'schema:' block (an 'over' target + an ordered 'verdicts' "
            f"vocabulary), got {type(raw).__name__}"
        )
    over = raw.get("over")
    if not isinstance(over, str) or not over.strip():
        raise RoleConfigError(
            "schema 'over' must be a non-empty part id (a sibling part, or 'records'), "
            f"got {over!r}"
        )
    over = over.strip()

    raw_verdicts = raw.get("verdicts")
    if not isinstance(raw_verdicts, list) or not raw_verdicts:
        raise RoleConfigError(
            "schema 'verdicts' must be a non-empty ordered list of verdict labels "
            "(best to worst)"
        )
    verdicts: list[str] = []
    seen: set[str] = set()
    for vidx, v in enumerate(raw_verdicts):
        if not isinstance(v, str) or not v.strip():
            raise RoleConfigError(
                f"schema verdicts[{vidx}] must be a non-empty string, got {v!r}"
            )
        v = v.strip()
        if v in seen:
            raise RoleConfigError(f"schema has a duplicate verdict {v!r}")
        seen.add(v)
        verdicts.append(v)

    grounding = raw.get("grounding", "records")
    if not isinstance(grounding, str) or grounding.strip() != "records":
        raise RoleConfigError(
            "schema 'grounding' for an assessment part must be 'records' "
            f"(an assessment grounds each verdict in a record), got {grounding!r}"
        )
    # Stage 2.5 grounding-check is ON for assessment: a verdict is a CLAIM about the
    # world, so a second pass re-reads each proposed call against what the zone
    # actually says before it reaches the deterministic writer.
    return {
        "over": over,
        "verdicts": verdicts,
        "grounding": "records",
        "grounding_check": True,
    }


def validate_cross_part(schema: Any, sibling_part_ids: Any) -> None:
    """Cross-part existence check for `over` — raise `RoleConfigError` when it names
    neither a part in this role nor the literal `records`.

    The plugin side of the NEW cross-part loader seam: `validate_schema` shape-checks
    `over` (a non-empty string) but cannot verify it points somewhere real, because it
    sees only its own part's block. AFTER every part is parsed the loader knows all the
    role's part ids and calls THIS hook (only when a plugin exports it — default-absent
    on the other kinds, so the loader stays archetype-agnostic), fail-closing `over`
    against a typo or a retired sibling BEFORE the role ever ticks.

    `sibling_part_ids` is the set of part ids declared in this role; a valid `over` is
    one of them or the literal `records`. The error carries shape-detail only (no path
    or part id); the loader locates it to `{path}: part {pid!r}` when it catches.
    """
    over = schema.get("over") if isinstance(schema, dict) else None
    if not isinstance(over, str) or not over.strip():
        # Shape is `validate_schema`'s job; a malformed `over` never reaches here in the
        # normal flow. Defensive no-op so a direct caller cannot trip on a None.
        return
    over = over.strip()
    valid = {str(p) for p in sibling_part_ids} | {"records"}
    if over not in valid:
        raise RoleConfigError(
            f"schema 'over' {over!r} names neither a part in this role nor 'records' "
            f"— it must be a sibling part id or 'records' (parts: "
            f"{sorted(str(p) for p in sibling_part_ids)})"
        )


def fresh_state() -> dict:
    """A brand-new assessment part's top-level fields with archetype defaults filled.

    `schema` is a `{}` PLACEHOLDER: the sole writer overlays the real config-declared
    schema (the `over` pointer + verdict vocabulary) onto both a fresh seed and a
    loaded state, so this stays generic. The common writer overlays the per-instance
    fields it owns (`role_id`, `part_id`, `archetype`, `description`). Returns a fresh
    dict each call.
    """
    return {
        "version": ASSESSMENT_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": {},
        "assessments": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Assessment mints no `lk-NNNN` keys — a call's identity is the owner's natural
    key for the tracked thing.

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


def _verdicts(schema: Any) -> list[str]:
    """The declared verdict vocabulary in schema order (best→worst); [] when absent."""
    raw = schema.get("verdicts") if isinstance(schema, dict) else None
    if not isinstance(raw, list):
        return []
    return [v.strip() for v in raw if isinstance(v, str) and v.strip()]


def _entries(state: Any) -> list[dict]:
    """The assessment list of a live state OR a staging dict (both carry it)."""
    if not isinstance(state, dict):
        return []
    raw = state.get("assessments")
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def _entry_key(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    key = entry.get("key")
    return key.strip() if isinstance(key, str) else ""


def _entry_verdict(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    v = entry.get("verdict")
    return v.strip() if isinstance(v, str) else ""


def _index(entries: Iterable[dict]) -> dict[str, dict]:
    """Assessments indexed by natural key (unique — validate blocks a same-tick dup)."""
    out: dict[str, dict] = {}
    for e in entries:
        k = _entry_key(e)
        if k:
            out[k] = e
    return out


def _norm(value: Any) -> str:
    return value.strip() if nonempty_str(value) else ""


# -----------------------------------------------------------------------------
# validate — structural + semantic gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed assessment delta payload before it may be persisted.

    STRUCTURAL: the payload envelope parses; `op` is known; no engine-owned field is
    body-set; the natural `key` is present; the proposed `verdict` is a member of the
    DECLARED ordered set (out-of-set is rejected — WHICH verdict is the body's
    judgment, but only a declared one is ever recorded); an optional `rationale` is a
    string when present; a key is not assessed twice this tick.

    SEMANTIC / grounding: every `assess` grounds in RECORDS — it must cite ≥1 record
    present in the shared `read_records` corpus (the engine-injected oracle the body
    cannot forge; the sibling `over` reading is context, never a substitute). Uncited
    or out-of-zone → rejected.

    Same contract shape as the other kinds: ok=True persists `approved_deltas`
    (possibly empty); ok=False blocks the whole tick (malformed envelope / corrupt
    state / missing verdict vocabulary).
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
    verdicts = _verdicts(schema)
    if not verdicts:
        # Defensive — the config loader requires a valid schema before an assessment
        # part loads, but a corrupt state with no verdict vocabulary cannot be
        # validated against. Hold rather than guess.
        return ValidationResult.rejected(
            rejections=({"ref": "schema",
                         "reason": "assessment schema declares no verdicts"},)
        )

    corpus = read_record_corpus(delta_payload)
    approved: list[dict] = []
    rejections: list[dict] = []
    touched: set[str] = set()

    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": delta_ref(delta, idx, ("key",)),
                               "reason": "delta is not a mapping"})
            continue
        reason = _validate_delta(delta, verdicts, touched)
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": reason})
            continue
        g_reason = _grounding_reason(delta, corpus)
        if g_reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": g_reason})
            continue
        approved.append(delta)

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
    )


def _validate_delta(delta: dict, verdicts: list[str], touched: set[str]) -> str | None:
    """Return a STRUCTURAL rejection reason, or None when the delta is well-formed.

    Grounding is checked separately (`_grounding_reason`). Mutates `touched` with the
    key an accepted `assess` addresses, so a second delta touching the same key this
    tick is a conflict (one call per key per tick — latest wins is across ticks)."""
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
    verdict = delta.get("verdict")
    if not nonempty_str(verdict):
        return f"{op} missing non-empty 'verdict'"
    verdict = verdict.strip()
    if verdict not in verdicts:
        return (f"{op} 'verdict' {verdict!r} is not in the declared verdict set "
                f"{verdicts}")
    rationale = delta.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        return f"{op} 'rationale' must be a string when set, got {type(rationale).__name__}"
    if key in touched:
        return f"{op} 'key' {key!r} is already assessed by another delta this tick"
    touched.add(key)
    return None


def _grounding_reason(delta: dict, corpus: set[str]) -> str | None:
    """None when the `assess` cites ≥1 real in-remit record; else a reason. Records is
    the deterministic oracle (`corpus` is the engine-injected `read_records`, which the
    body cannot forge). A verdict is a claim about the world — the record it rests on is
    the anchor; the sibling `over` reading is context, never the grounding."""
    op = delta.get("op")
    evidence = delta.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return f"{op} 'evidence' must cite at least one read record"
    missing = ungrounded_refs(evidence, corpus)
    if missing:
        return f"ungrounded: {op} evidence not in read_records: {missing}"
    return None


# -----------------------------------------------------------------------------
# persist — pure transform (roles_persist is the sole caller / writer)
# -----------------------------------------------------------------------------

def persist(prior_state: Any, approved_deltas: Iterable[dict], key_minter) -> dict:
    """Apply already-validated deltas to a copy of `prior_state`; return new state.

    Pure: no I/O, never mutates inputs, never calls `key_minter` (a call's key is the
    owner's natural value, not minted). Per `assess`:
      - new key → create the entry with the verdict / rationale / provenance / date and
        an empty history.
      - existing key, verdict CHANGED → push the PRIOR verdict onto the append-only
        history (grow-only, never blanked), set the new verdict as current.
      - existing key, verdict UNCHANGED → a reaffirmation: no history push; provenance
        grows and the date refreshes; a fresh rationale updates the reason, an empty
        one leaves the standing reason in place.

    Latest wins for the present state; a verdict change never erases the prior call —
    it is preserved in the entry's own grow-only trail.
    """
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    entries = new_state.get("assessments")
    if not isinstance(entries, list):
        entries = []
    new_state["assessments"] = entries
    today = today_iso()
    index = _index(it for it in entries if isinstance(it, dict))

    for delta in approved_deltas:
        if not isinstance(delta, dict) or delta.get("op") != "assess":
            continue
        key = _norm(delta.get("key"))
        verdict = _norm(delta.get("verdict"))
        if not key or not verdict:
            continue
        rationale = delta.get("rationale").strip() if isinstance(delta.get("rationale"), str) else ""
        evidence = delta.get("evidence") or []
        existing = index.get(key)
        if existing is None:
            entry = _new_entry(key, verdict, rationale, evidence, today)
            entries.append(entry)
            index[key] = entry
        else:
            _apply_assess(existing, verdict, rationale, evidence, today)

    return new_state


def _new_entry(key: str, verdict: str, rationale: str, evidence: Any, today: str) -> dict:
    return {
        "key": key,
        "verdict": verdict,
        "rationale": rationale,
        "provenance": grow_provenance([], evidence or []),
        "at": today,
        "history": [],
    }


def _apply_assess(
    entry: dict, verdict: str, rationale: str, evidence: Any, today: str
) -> None:
    """Apply an `assess` to an existing entry (present-verdict-per-key projection).

    A verdict CHANGE pushes the superseded call `{verdict, rationale, at}` onto the
    append-only history before the new one becomes current — grow-only, so no prior
    verdict is ever lost. A same-verdict reaffirmation adds no history entry; it grows
    provenance and refreshes the date, and updates the reason only when a fresh
    rationale is given (never blanking a standing reason with an empty re-assessment).
    """
    old_verdict = entry.get("verdict")
    changed = isinstance(old_verdict, str) and old_verdict != verdict
    if changed:
        history = entry.get("history")
        if not isinstance(history, list):
            history = []
            entry["history"] = history
        history.append({
            "verdict": old_verdict,
            "rationale": entry.get("rationale") if isinstance(entry.get("rationale"), str) else "",
            "at": entry.get("at") if isinstance(entry.get("at"), str) else "",
        })
        entry["rationale"] = rationale  # the new verdict gets its own (possibly empty) reason
    elif rationale:
        entry["rationale"] = rationale  # same verdict — refresh the reason only when given
    entry["verdict"] = verdict
    entry["provenance"] = grow_provenance(entry.get("provenance"), evidence or [])
    entry["at"] = today


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

def render(state: Any) -> str:
    """Render the assessment as the state.md AUTO-zone markdown body (present-state).

    Grouped by verdict in DECLARED order (best→worst), so the owner reads the best
    calls first and the worst last; within a group, entries sort by natural key. Each
    entry renders as `- {key} — {rationale} (as of {date}) · was {prior}`, showing the
    reason and the last verdict change when present. The caller wraps this in the
    role-state markers."""
    entries = _entries(state)
    if not entries:
        return "_No assessments yet._"
    verdicts = _verdicts(_schema(state))
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(_entry_verdict(e) or "—", []).append(e)
    # Declared verdicts first (in order), then any stray verdict not in the schema
    # (defensive — should not occur), then the empty bucket.
    order = list(verdicts)
    order += [v for v in sorted(groups) if v not in order]

    lines: list[str] = []
    for verdict in order:
        bucket = groups.get(verdict)
        if not bucket:
            continue
        lines.append(f"### {verdict}")
        lines.append("")
        for e in sorted(bucket, key=_entry_key):
            lines.append(_render_entry(e))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_entry(entry: dict) -> str:
    key = _entry_key(entry) or "(no key)"
    line = f"- {key}"
    rationale = entry.get("rationale")
    if nonempty_str(rationale):
        line += f" — {rationale.strip()}"
    at = entry.get("at")
    if nonempty_str(at):
        line += f" (as of {at.strip()})"
    history = entry.get("history")
    if isinstance(history, list) and history and isinstance(history[-1], dict):
        prior = history[-1].get("verdict")
        if nonempty_str(prior):
            line += f" · was {prior.strip()}"
    return line


# -----------------------------------------------------------------------------
# identity — natural keys; no external anchor concept (never guesses)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Assessment calls are identified by the owner's NATURAL KEY for the tracked
    thing, not an external Minder id — there is nothing to anchor and nothing to guess.
    Returns `anchored=True` and never fabricates an anchor. The writer never calls this
    for an assessment part; present for interface uniformity."""
    return IdentityResult(anchored=True, anchor=None)


# -----------------------------------------------------------------------------
# Composite-seam hooks (mirror the other kinds; assessment-shaped)
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Assessment has no anchor-identity concept — every approved delta passes.

    Returns `(approved, [])`. A call is identified by its exact natural key
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
    """One decision row per persisted assessment delta, stamped `part`.

    `kind` vocabulary: verdict-set (a first call for a key) / verdict-change (an
    existing key whose verdict moved) / verdict-reaffirm (an existing key re-called the
    same). No keys are minted, so `minted` is ignored and the row `key` is the tracked
    thing's natural key."""
    prior = _index(_entries(prior_state))
    rows: list[dict] = []
    for d in approved_deltas:
        if not isinstance(d, dict) or d.get("op") != "assess":
            continue
        key = d.get("key")
        verdict = _norm(d.get("verdict"))
        evidence = clean_evidence(d.get("evidence"))
        prior_entry = prior.get(_norm(key))
        if prior_entry is None:
            kind = "verdict-set"
        elif _entry_verdict(prior_entry) != verdict:
            kind = "verdict-change"
        else:
            kind = "verdict-reaffirm"
        rows.append(decision_row(kind, key, hook, role_id, part_id, ts,
                                 verdict=verdict, evidence=evidence))
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts. Every `assess` places a verdict → counted
    as ADDED; there is no separate mutate op, so `advanced` is always 0. (The pure
    delta list carries no prior state to tell a first call from a re-call; splitting it
    would need the prior state — the imprecision is cosmetic run-count only.)"""
    added = sum(1 for d in persisted_deltas
                if isinstance(d, dict) and d.get("op") == "assess")
    return added, 0


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per assessment when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", e.get("key"), "tick", role_id, part_id, ts,
            evidence=[r for r in e.get("provenance") or [] if isinstance(r, str)],
            verdict=_entry_verdict(e),
        )
        for e in _entries(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start.

    Assessment content is its `assessments` list. The writer spreads this into the
    staging dict and adopts it later via `adopt_staging`; the SCHEMA (the verdict
    vocabulary) is NOT frozen — the writer re-overlays it from config on every load, so
    config stays the source of truth for the shape."""
    return {"assessments": list(_entries(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state.

    Returns a deep copy of `prior_state` (which already carries the config-overlaid
    schema) with its `assessments` replaced by the staged draft's. The writer clears
    `staging`, resets the reject counter and advances the watermark over
    `consumed_records`."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    src = staging.get("assessments") if isinstance(staging, dict) else None
    ns["assessments"] = [e for e in src if isinstance(e, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification + count).

    ONE label per assessment — its natural key, its current verdict, and its reason
    when present. Works on both a live state and a staging dict; an empty list means
    the part carries no content."""
    return [_entry_label(e) for e in _entries(state)]


def _entry_label(entry: dict) -> str:
    key = _entry_key(entry) or "(no key)"
    verdict = _entry_verdict(entry) or "?"
    label = f"{key}: {verdict}"
    rationale = entry.get("rationale")
    if nonempty_str(rationale):
        label += f" — {rationale.strip()}"
    return truncate(label)


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites (watermark advance on adopt).

    Works on both a live state and a staging dict. Assessment content grounds in each
    call's provenance trail (the records the verdicts rest on); non-record refs
    normalise to empty and are dropped. Yielding these stems is what keeps assessment
    on the shared records watermark — a strict superset, no watermark-seam change."""
    for e in _entries(state):
        for ref in e.get("provenance") or []:
            stem = normalize_record_ref(ref)
            if stem:
                yield stem


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[verdict,count],...], staged}`. Total = all tracked keys;
    breakdown = present-state count per verdict in DECLARED order (non-zero only, so
    the owner sees the distribution best→worst); staged = a frozen cold-start draft's
    entries. The render layer reads only this dict, never the internal entry shape.
    Tolerant of a partially-written / corrupt state."""
    raw = state.get("assessments") if isinstance(state, dict) else None
    entries = raw if isinstance(raw, list) else []
    total = 0
    by_verdict: dict[str, int] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        total += 1
        v = _entry_verdict(e) or "?"
        by_verdict[v] = by_verdict.get(v, 0) + 1
    verdicts = _verdicts(_schema(state))
    order = list(verdicts)
    order += [v for v in sorted(by_verdict) if v not in order]
    breakdown: list[list] = [[v, by_verdict[v]] for v in order if by_verdict.get(v)]
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("assessments"), list):
        staged = sum(1 for x in staging["assessments"] if isinstance(x, dict))
    return {"total": total, "breakdown": breakdown, "staged": staged}
