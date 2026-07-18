#!/usr/bin/env python3
"""Narrative part-plugin — the second part-kind behind the composite seam.

A "narrative" part holds an entity's LIVING PROSE UNDERSTANDING: a single current
`purpose` headline plus an append-only, versioned trail of narrative statements
and shift-notes. Where a `ledger` part answers "what pieces of work exist and what
status is each", a `narrative` part answers "what is this, what does it mean now,
and how has that reading evolved" — the framing a role needs to say whether the
concrete work still serves the idea (an `alignment` part is a narrative instance
whose hook frames it exactly that way).

The determinism is MEDIUM, and it is disclosed as such (principle-ai-interaction-012):
the ENGINE guarantees the bookkeeping — every statement cites a real in-remit
record, prior versions are never blanked, and a garbled flood of revisions is held
— but the *content* of the prose is the tick body's reading, which the engine does
not itself judge. The role's tick body only proposes a structured delta payload;
this plugin's `validate` gates it and `persist` is the pure transform the sole
writer (`roles_persist.py`) applies. The common layer never names "narrative": it
loads this module dynamically by a part's `kind` (`roles_common.import_archetype`).

Exposes the per-part plugin interface (BUILD-CONTRACT §2 / §3.2):
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODEL, CONCIERGE_MANIFEST,
  fresh_state()                         -> dict
  known_key_numbers(state)              -> Iterable[int]  (narrative mints no keys)
  validate(prior_state, delta_payload)  -> ValidationResult
  persist(prior_state, approved_deltas, key_minter) -> new_state
  render(state)                         -> str   (state.md AUTO sub-zone body)
  identity(item, anchors)               -> IdentityResult  (n/a — no external anchor)
  gate_identity(role_id, part_id, prior_state, approved) -> (kept, [])
  build_decisions(approved, minted, prior_state, role_id, part_id, hook, ts) -> list[dict]
  cold_materialize_decisions(adopted_state, role_id, part_id, ts) -> list[dict]
  delta_counts(persisted_deltas) -> (0, N)
  content_view(state)                   -> dict  (content frozen at cold-start)
  adopt_staging(prior_state, staging)   -> new_state
  content_summary(state)                -> list[str]
  consumed_records(state)               -> Iterable[str]

`GROUNDING_MODEL = "records"` — every statement cites a real in-remit record (the
same grounding oracle the ledger uses, shared via `roles_common`). Deterministic,
no LLM. Cross-platform: pure in-memory transforms; the caller owns all I/O.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from _common import today_iso

from roles_common import (
    ClarificationSignal,
    IdentityResult,
    ValidationResult,
    clean_evidence,
    decision_row,
    delta_ref,
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

ARCHETYPE = "narrative"

# A narrative grounds in real in-remit records — every statement cites one, exactly
# like the ledger. The shared frame parameterises its honesty contract by this
# constant; a future values-grounded part-kind (Stance) would declare "values".
GROUNDING_MODEL = "records"

# Ops the tick body may propose (BUILD-CONTRACT §3.2). All three append a versioned
# entry (prior versions are never blanked); `set-purpose` additionally updates the
# current one-line headline. Order does not dictate persist order.
DELTAS: tuple[str, ...] = ("set-purpose", "revise-narrative", "note-shift")

# The entry kind each op produces. `purpose` records a headline change, `narrative`
# a full re-statement of the current reading, `shift` a lighter "things moved" note.
_OP_ENTRY_KIND: dict[str, str] = {
    "set-purpose": "purpose",
    "revise-narrative": "narrative",
    "note-shift": "shift",
}
ENTRY_KINDS: frozenset[str] = frozenset(_OP_ENTRY_KIND.values())

# Fields the body may NEVER set directly — engine-owned (minted / stamped on
# persist). A delta carrying any of them is rejected (append-not-replace).
_BODY_FORBIDDEN_FIELDS: frozenset[str] = frozenset({"version", "at", "entries", "kind"})

# Narrative schema version — bumped only on an incompatible shape change (with a
# matching migration). Additive-optional changes keep it stable.
NARRATIVE_VERSION = 1

# Default churn ceiling: content-producing deltas per tick over an ESTABLISHED
# narrative. A garbled tick emitting more than this is HELD rather than written.
DEFAULT_CHURN_THRESHOLD = 3

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned living narrative. Written ONLY by roles_persist.py through this "
        "plugin. Never hand-edited."
    ),
    "top_level": {
        "version": "int (schema version of the narrative file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'narrative'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": "str|null (high-water mark of consumed records)",
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "churn_threshold": f"int (content-deltas ceiling per tick; default {DEFAULT_CHURN_THRESHOLD})",
        "purpose": "str (the current one-line headline; replaceable)",
        "entries": "list[entry] (append-only, versioned; never blanked)",
    },
    "entry": {
        "version": "int (monotonic across all entries, 1-based)",
        "at": "str (YYYY-MM-DD)",
        "kind": sorted(ENTRY_KINDS),
        "text": "str (the statement)",
        "evidence": "list[str] ('[[record-basename]]', the records that justify it)",
    },
}


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language WITHOUT ever exposing the word
# "archetype" / "part-kind" to the owner. `plain_purpose` + `triggers` match a
# plain wish to this part; `produces_preview` shows the shape; `determinism_note`
# DISCLOSES the honesty level (MEDIUM — never claims a guarantee it does not hold).
# `built: True` marks it installed + composable now.
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Hold a living understanding of what something IS and what it means right "
        "now — its purpose, the story of how your thinking about it has changed, and "
        "whether the current direction still fits the idea. Prose, not a task list."
    ),
    "triggers": [
        "держи смысл и назначение",
        "следи чтобы работа не разошлась с идеей",
        "что это вообще и куда движется",
        "как менялось моё понимание",
        "статус проекта, не только задач",
        "keep the meaning and intent",
        "watch that the work still serves the idea",
        "what is this and where is it going",
        "how my understanding evolved",
        "the project's status, not just its tasks",
    ],
    "produces_preview": (
        "A short section: the current purpose headline, the latest narrative reading "
        "of where things stand, and (kept in state, not shown) the dated trail of how "
        "that reading evolved — each statement citing the record that prompted it."
    ),
    "determinism_note": (
        "MEDIUM determinism: the engine guarantees every statement cites a real "
        "in-remit record, that prior versions are never overwritten, and that a "
        "garbled flood of revisions is held for review. It does NOT judge whether the "
        "prose reading is right — that is the tick body's interpretation, shown as such."
    ),
    "built": True,
}


def fresh_state() -> dict:
    """A brand-new narrative's top-level fields with archetype defaults filled.

    The SINGLE HOME for the narrative-owned fresh-state defaults — most importantly
    `churn_threshold`, whose sole owner is `DEFAULT_CHURN_THRESHOLD` here. The common
    writer overlays the fields it owns per instance (`role_id`, `part_id`,
    `archetype`, `description`). Returns a fresh dict each call.
    """
    return {
        "version": NARRATIVE_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "churn_threshold": DEFAULT_CHURN_THRESHOLD,
        "purpose": "",
        "entries": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Narrative mints no `lk-NNNN` keys — its key namespace is empty.

    Yields nothing. The common `KeyMinter.for_part` therefore starts at 1, but
    `persist` never calls the minter, so no key is ever minted for a narrative part.
    Present so the writer can call it uniformly across every part-kind (the seam
    never special-cases narrative)."""
    return ()


# -----------------------------------------------------------------------------
# State helpers
# -----------------------------------------------------------------------------

def _entries(state: Any) -> list[dict]:
    if not isinstance(state, dict):
        return []
    entries = state.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def _purpose(state: Any) -> str:
    if not isinstance(state, dict):
        return ""
    p = state.get("purpose")
    return p.strip() if isinstance(p, str) else ""


def _next_version(entries: list[dict]) -> int:
    highest = 0
    for e in entries:
        v = e.get("version")
        if isinstance(v, int) and v > highest:
            highest = v
    return highest + 1


def _has_content(state: Any) -> bool:
    """A narrative carries content when it has a purpose or at least one entry."""
    return bool(_purpose(state)) or bool(_entries(state))


def _latest_of_kind(entries: list[dict], kind: str) -> dict | None:
    """The highest-version entry of a given kind (present-state view), or None."""
    best: dict | None = None
    best_v = -1
    for e in entries:
        if e.get("kind") == kind:
            v = e.get("version")
            v = v if isinstance(v, int) else -1
            if v >= best_v:
                best_v = v
                best = e
    return best


# -----------------------------------------------------------------------------
# validate — structural + semantic gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed narrative delta payload before it may be persisted.

    STRUCTURAL: the payload envelope and each delta parse; `op` is known; `text` is
    a non-empty string; no engine-owned field (`version` / `at` / `entries` /
    `kind`) is set by the body.

    SEMANTIC: grounding (every delta's `evidence` cites ≥1 record present in
    `read_records` — uncited is rejected); append-only (structural — every op
    appends, none can blank prior versions); churn-guard (on an ESTABLISHED
    narrative, more than `churn_threshold` content deltas in one tick is HELD as a
    `role-churn-guard` CLARIFICATION rather than written).

    Same contract shape as the ledger: ok=True persists `approved_deltas` (possibly
    empty), ok=False blocks the whole tick (malformed envelope or churn hold).
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

    corpus = read_record_corpus(delta_payload)
    role_id = resolve_role_id(delta_payload, prior_state)

    approved: list[dict] = []
    rejections: list[dict] = []
    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": f"delta#{idx}", "reason": "delta is not a mapping"})
            continue
        reason = _validate_delta(delta, corpus)
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx), "reason": reason})
            continue
        approved.append(delta)

    churn = _churn_guard(prior_state, approved, role_id)
    if churn is not None:
        return ValidationResult(ok=False, clarifications=(churn,))

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
    )


def _validate_delta(delta: dict, corpus: set[str]) -> str | None:
    """Return a rejection reason, or None when the narrative delta is valid."""
    op = delta.get("op")
    if op not in DELTAS:
        return f"unknown op {op!r}"
    for forbidden in _BODY_FORBIDDEN_FIELDS:
        if forbidden in delta:
            return f"append-not-replace: '{forbidden}' is engine-owned, not body-set"
    if not nonempty_str(delta.get("text")):
        return f"{op} missing non-empty 'text'"
    evidence = delta.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return f"{op} 'evidence' must cite at least one read record"
    missing = ungrounded_refs(evidence, corpus)
    if missing:
        return f"ungrounded: {op} evidence not in read_records: {missing}"
    return None


def _churn_guard(
    prior_state: Any, approved: list[dict], role_id: str
) -> ClarificationSignal | None:
    """Hold a tick that floods an ESTABLISHED narrative with revisions.

    Append-only makes narrative safe from silent history loss structurally; the
    remaining risk is a garbled tick emitting an unreasonable BURST of statements.
    A fresh narrative (no purpose, no entries) is cold-start territory (owned by the
    writer's staging), never churn. Otherwise > `churn_threshold` content deltas
    this tick is held for review."""
    if not _has_content(prior_state):
        return None
    threshold = read_int_tunable(prior_state, "churn_threshold", DEFAULT_CHURN_THRESHOLD)
    if len(approved) <= threshold:
        return None
    return ClarificationSignal(
        ctype="role-churn-guard",
        subject=role_id,
        context=(
            f"The tick proposed {len(approved)} narrative statement(s) in one pass, "
            f"exceeding the churn threshold of {threshold}. This is held rather than "
            "written so a garbled or over-eager tick cannot flood the narrative. "
            "Review the proposed statements and confirm before any are applied."
        ),
        source=f"roles tick for {role_id}",
        suggested_action=(
            "Review the held statements; if the burst is intended, re-run the tick "
            "after raising churn_threshold, or approve the statements manually."
        ),
        action_taken="Held — nothing was persisted this tick.",
        confidence_tier="surfaced",
    )


# -----------------------------------------------------------------------------
# persist — pure transform (roles_persist is the sole caller / writer)
# -----------------------------------------------------------------------------

def persist(prior_state: Any, approved_deltas: Iterable[dict], key_minter) -> dict:
    """Apply already-validated deltas to a copy of `prior_state`; return new state.

    Pure: no I/O, never mutates inputs, never calls `key_minter` (narrative mints no
    keys). Each delta appends a versioned entry in body-proposed order; `set-purpose`
    additionally updates the current headline. Prior versions are never blanked —
    the trail only grows.
    """
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    entries = new_state.get("entries")
    if not isinstance(entries, list):
        entries = []
    new_state["entries"] = entries
    if not isinstance(new_state.get("purpose"), str):
        new_state["purpose"] = ""
    today = today_iso()

    for delta in approved_deltas:
        if not isinstance(delta, dict):
            continue
        op = delta.get("op")
        kind = _OP_ENTRY_KIND.get(op)
        if kind is None:
            continue
        text = str(delta.get("text", "")).strip()
        entry = {
            "version": _next_version(entries),
            "at": today,
            "kind": kind,
            "text": text,
            "evidence": clean_evidence(delta.get("evidence")),
        }
        entries.append(entry)
        if op == "set-purpose":
            new_state["purpose"] = text

    return new_state


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

def _headline_label(state: Any) -> str:
    """The bold label for the narrative headline, derived from the part's id.

    The headline field is generically «the current one-line statement of where this
    part stands» — for a `purpose` part it is the purpose, for an `alignment` part
    the alignment verdict, etc. Labelling it from the part id keeps a non-purpose
    narrative part from mislabelling its headline as "Purpose" (so a composite role's
    state.md does not render two "Purpose:" sections). Falls back to "Headline" when
    the part id is absent (a fresh/legacy state the writer has not stamped)."""
    pid = state.get("part_id") if isinstance(state, dict) else None
    if isinstance(pid, str) and pid.strip():
        return pid.replace("-", " ").replace("_", " ").strip().capitalize()
    return "Headline"


def render(state: Any) -> str:
    """Render the current purpose + the latest narrative reading (present-state).

    The evolution trail is kept in state, not shown — the render is the reading NOW
    (purpose headline + latest `narrative` entry), with the latest `shift` note when
    one exists. The caller wraps this in the role-state markers."""
    if not _has_content(state):
        return "_No narrative yet._"
    entries = _entries(state)
    lines: list[str] = []

    purpose = _purpose(state)
    if purpose:
        lines.append(f"**{_headline_label(state)}:** {purpose}")
        lines.append("")

    latest_narrative = _latest_of_kind(entries, "narrative")
    if latest_narrative is not None:
        lines.append(str(latest_narrative.get("text") or "").strip())
        lines.append("")

    latest_shift = _latest_of_kind(entries, "shift")
    if latest_shift is not None:
        n_v = latest_narrative.get("version") if latest_narrative else None
        s_v = latest_shift.get("version")
        # Show the shift only when it is newer than the latest full narrative (an
        # unincorporated observation); once a narrative supersedes it, it is history.
        if not isinstance(n_v, int) or not isinstance(s_v, int) or s_v > n_v:
            lines.append(f"_Recent shift:_ {str(latest_shift.get('text') or '').strip()}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# -----------------------------------------------------------------------------
# identity — not applicable to narrative content (no external anchor concept)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Narrative statements do not anchor onto an external Minder id — they cite
    evidence records, which grounding already checks. Returns `anchored=True`
    (nothing to gate). The writer never calls this for a narrative part (no `add`
    op reaches the identity gate); present for interface uniformity."""
    return IdentityResult(anchored=True, anchor=None)


# -----------------------------------------------------------------------------
# Composite-seam hooks (mirror the ledger's; narrative-shaped)
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Narrative has no anchor-identity concept — every approved delta passes.

    Returns `(approved, [])`. The anchor-else-HITL gate is a ledger-item mechanic;
    a narrative statement grounds in evidence records, checked in `validate`."""
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
    """One decision row per persisted narrative delta, stamped `part`.

    Narrative `kind` vocabulary: purpose-set / narrative-revised / shift-noted. No
    keys are minted, so `minted` is ignored and `key` is null; the entry `version`
    the delta produced is recorded (recomputed the same deterministic way persist
    does, so a reader can join a row to its entry)."""
    prior_entries = _entries(prior_state)
    next_version = _next_version(prior_entries)
    kind_map = {
        "set-purpose": "purpose-set",
        "revise-narrative": "narrative-revised",
        "note-shift": "shift-noted",
    }
    rows: list[dict] = []
    for d in approved_deltas:
        op = d.get("op")
        kind = kind_map.get(op)
        if kind is None:
            continue
        rows.append(decision_row(
            kind, None, hook, role_id, part_id, ts,
            version=next_version, evidence=clean_evidence(d.get("evidence")),
        ))
        next_version += 1
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts. A narrative creates no keyed items, so
    every statement is an ADVANCE of the current reading — `(0, N)`."""
    return 0, sum(1 for d in persisted_deltas if isinstance(d, dict))


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per entry when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", None, "tick", role_id, part_id, ts,
            version=e.get("version"), entry_kind=e.get("kind"),
            evidence=clean_evidence(e.get("evidence")),
        )
        for e in _entries(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start.

    Narrative content is its `purpose` headline plus its `entries` trail. The writer
    spreads this into the staging dict and adopts it later via `adopt_staging`."""
    return {"purpose": _purpose(state), "entries": list(_entries(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state.

    Returns a deep copy of `prior_state` with its content replaced by the draft's
    (staged `purpose` + `entries`). The writer clears `staging`, resets the reject
    counter and advances the watermark over `consumed_records`."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    if not isinstance(staging, dict):
        staging = {}
    purpose = staging.get("purpose")
    ns["purpose"] = purpose.strip() if isinstance(purpose, str) else ""
    src = staging.get("entries")
    ns["entries"] = [e for e in src if isinstance(e, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification + count).

    ONE label per entry — the entries ARE the units (each a distinct statement the
    body proposed). The current `purpose` headline is a derived view of the latest
    purpose entry, NOT a separate unit, so it is not listed again (else a single
    set-purpose would report two units of duplicated text). Works on both a live
    state and a staging dict; an empty list means the part carries no content."""
    return [
        f"{str(e.get('kind') or 'entry')} v{e.get('version')}: {truncate(str(e.get('text') or ''))}"
        for e in _entries(state)
    ]


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites (watermark advance on adopt).

    Works on both a live state and a staging dict. Narrative content grounds in each
    entry's evidence; non-record refs normalise to empty and are dropped."""
    for e in _entries(state):
        for ref in clean_evidence(e.get("evidence")):
            stem = normalize_record_ref(ref)
            if stem:
                yield stem


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[label,count],...], staged}`. Total = versioned entries;
    breakdown = entries by kind (purpose / narrative / shift, then any other). The
    render layer reads only this dict, never the narrative's internal shape. Staged
    counts a frozen cold-start draft's entries."""
    entries = _entries(state)
    kinds: dict[str, int] = {}
    for e in entries:
        k = e.get("kind")
        if isinstance(k, str) and k:
            kinds[k] = kinds.get(k, 0) + 1
    order = ("purpose", "narrative", "shift")
    breakdown: list[list] = [[k, kinds[k]] for k in order if kinds.get(k)]
    breakdown += [[k, kinds[k]] for k in sorted(kinds) if k not in order]
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("entries"), list):
        staged = sum(1 for x in staging["entries"] if isinstance(x, dict))
    return {"total": len(entries), "breakdown": breakdown, "staged": staged}
