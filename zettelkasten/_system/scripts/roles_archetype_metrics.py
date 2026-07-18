#!/usr/bin/env python3
"""Metrics part-plugin — the reference kind for "a number moving toward a target".

A `metrics` part tracks a small set of NUMBERS the owner is steering toward a
target: current value, the target, and the gap between them, per metric. Where a
`registry` part is the universal floor for "things with attributes", a `metrics`
part is a REFERENCE — a plugin tuned for one common shape (current vs target, and
the distance still to close) so the owner gets a real progress view without
authoring a plugin per number.

The load-bearing invariant is SoT-cleanliness: the raw daily numbers live in the
metric-day source (the records + their σ-baselines), NOT here. A metrics part
persists ONLY the derived progress SCALARS (`current`, a `trend` verdict, the
provenance POINTER to the record the reading came from) — never a copy of the
series. Every number the plugin holds is COMPUTED deterministically from a
runner-injected reading; the tick body may reason "improving / stalling" in prose
but NEVER authors a number. The target is CONFIG-only — declared in the part's
schema, overlaid onto state each tick exactly like a registry's schema — so the
body cannot move a target and there is no second source of truth for it.

Shape is DATA. The metric set lives in `state["schema"]` (overlaid by the sole
writer from config — config is the source of truth):

    {"metrics": [{"key":  <natural id>,      # the metric's identity in this part
                  "source": <metric-key>,    # which reading feeds it (baseline key)
                  "target": <number>,        # the number being steered toward
                  "direction": "higher"|"lower",  # which way is "good"
                  "unit": <str>},            # display unit ("" = unitless)
                 ...],
     "grounding": "records"}

`GROUNDING_MODEL = "records"`: a metric's reading is injected by the runner from a
real in-remit metric-day record, so the metric grounds in that record's stem and
the part rides the existing records watermark (`consumed_records` yields those
stems). The one honesty subtlety vs ledger/registry: a `refresh` is grounded by
the ENGINE-INJECTED reading (whose stem the runner authored), not by a body
citation — the body cannot fabricate a number, so it need not cite one. A `note`
(body prose about a metric) is body-authored and IS records-grounded the ordinary
way (it must cite an in-remit record).

Compute-locus. The pure plugin cannot read record bodies or `baselines.json`; the
runner's readings-injection lane (`roles_persist._inject_readings`, the sibling to
`_inject_read_records`) reads each declared metric's latest value + trend context
and injects them as `payload["readings"]`. `validate` computes `current` and the
`trend` verdict from that injection and stamps them onto the approved delta;
`persist` writes only those derived scalars. The `gap` is derived on read (`_view`)
from the stored `current` and the config target, so the target lives in exactly
one place.

Gap sign convention (documented once, load-bearing):

    gap = (current − target)  when direction == "lower"   (you want current ≤ target)
    gap = (target − current)  when direction == "higher"  (you want current ≥ target)

so a POSITIVE gap ALWAYS means "distance still to close" regardless of direction,
and a gap ≤ 0 means the target is reached or passed. For direction=lower a gap > 0
means current is ABOVE the target — still to lose; for direction=higher a gap > 0
means current is BELOW the target — still to gain.

Cold-start / no data. A metric with no injected reading yet renders honestly as
"no data yet" — `current` / `gap` / `trend` are null, never a fabricated 0 or a
spurious target-hit. The schema-driven `_view` always lists every DECLARED metric,
so a never-refreshed metric is visible-but-empty, not missing.

Exposes the per-part plugin interface (the SAME hooks ledger / narrative /
registry expose), plus the readings capability seam:
  ARCHETYPE, STATE_SHAPE, DELTAS, GROUNDING_MODEL, CONCIERGE_MANIFEST,
  METRICS_VERSION, REQUIRES_SCHEMA (config loader requires + validates a schema),
  REQUIRES_READINGS + reading_sources(schema) (the runner's readings-lane seam:
    the flag says "inject readings for this part", the hook says which sources),
  validate_schema(raw)                  -> dict  (canonical schema; raises on malformed)
  fresh_state()                         -> dict
  known_key_numbers(state)              -> Iterable[int]  (metrics mints no keys)
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
all I/O (the readings-lane reads baselines; this plugin never touches disk).
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

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

ARCHETYPE = "metrics"

# Metrics grounds every reading in a real in-remit metric-day record (the runner
# injects the reading FROM that record), so the part rides the shared records
# watermark exactly like ledger / narrative / registry-records.
GROUNDING_MODEL = "records"

# Signals the config loader (`roles_common._parse_parts`) that a metrics part MUST
# carry a well-formed `schema:` block, dispatched to `validate_schema` below.
REQUIRES_SCHEMA = True

# Signals the runner's readings-injection lane (`roles_persist._inject_readings`)
# that this part needs metric readings injected before its tick. The runner reads
# the flag (never the kind), asks `reading_sources` which sources to fetch, and
# injects `payload["readings"]` as a shared `{source: reading}` map (not per-part —
# one readings set is shared across parts, per the envelope contract in
# `roles_common`). A kind without this flag (ledger / narrative / registry) gets no
# readings lane — its `part_payload` is unchanged.
REQUIRES_READINGS = True

# Ops the tick body may propose. `refresh` recomputes ONE metric from the latest
# injected reading (the numbers come only from injection); `note` attaches a short
# prose annotation to a metric (body-authored → records-grounded). Order does not
# dictate persist application order. There is deliberately no op that sets a number
# or a target — those are engine-owned / config-owned respectively.
DELTAS: tuple[str, ...] = ("refresh", "note")

# Fields the body may NEVER set on a delta — engine-computed (from the injected
# reading) or config-owned (the target). A delta carrying any of them is rejected:
# the body cannot author a number and cannot move a target. `_reading` is the
# engine-stamped enrichment (validate → persist); a body-supplied one is refused.
_BODY_FORBIDDEN_FIELDS: frozenset[str] = frozenset({
    "current", "target", "direction", "unit", "gap", "trend",
    "last_reading_at", "provenance", "_reading",
})

_DIRECTIONS: frozenset[str] = frozenset({"higher", "lower"})

# Trend verdict vocabulary — a deterministic word computed from the reading, never
# body-authored. "improving" = current moved toward the target vs the reference,
# "regressing" = away, "stalling" = flat (or no reference to compare against).
TREND_IMPROVING = "improving"
TREND_REGRESSING = "regressing"
TREND_STALLING = "stalling"

# Metrics schema version — bumped only on an incompatible shape change (with a
# matching migration). Additive-optional changes keep it stable.
METRICS_VERSION = 1

STATE_SHAPE: dict[str, Any] = {
    "archetype": ARCHETYPE,
    "doc": (
        "Role-owned metric progress views. Written ONLY by roles_persist.py through "
        "this plugin. Never hand-edited. Its `schema` (the metric set + targets) is "
        "overlaid from config.yml on every load — config is the source of truth. "
        "Holds only derived scalars per metric, never the daily series (that lives "
        "in the metric-day source records + baselines)."
    ),
    "top_level": {
        "version": "int (schema version of the metrics file; currently 1)",
        "role_id": "str (owning role id)",
        "archetype": "str = 'metrics'",
        "description": "str (human note; engine-written-only warning)",
        "seen_watermark": "str|null (high-water mark of consumed records)",
        "staging": "object|null (frozen cold-start draft until owner approval)",
        "state_auto_hash": "str|null (sha256 of state.md AUTO zone at last render)",
        "consecutive_rejects": "int (auto-pause counter; 3 → paused)",
        "schema": (
            "object {metrics:[{key,source,target,direction,unit}], grounding} — "
            "overlaid from config; the config source of truth for the targets"
        ),
        "metrics": (
            "list[reading] (per-metric derived scalars; target/gap are joined from "
            "the schema at read time, never persisted here)"
        ),
    },
    "reading": {
        "key": "str (the metric's natural id — matches a declared schema metric)",
        "current": "number|null (the latest injected reading; null = no data yet)",
        "trend": "str|null (improving|stalling|regressing — computed from readings)",
        "last_reading_at": "str|null (YYYY-MM-DD of the reading current came from)",
        "provenance": "list[str] ('[[record-stem]]' the current reading came from)",
        "note": "str (optional body-authored prose annotation; records-grounded)",
    },
}


# Plain-language self-description the concierge (`ztn:role:add` / `edit`) reads to
# compose a role's parts from natural language. Domain-NEUTRAL by design: the kind
# is "a number toward a target", not any specific number — no coach / weight /
# sleep / OKR framing here. `built: True` marks it installed + composable now.
CONCIERGE_MANIFEST: dict[str, Any] = {
    "plain_purpose": (
        "Track a small set of numbers you are steering toward a target — for each, "
        "where it is now, where you want it, and the distance still to close. You "
        "name each number, its target, and which way is good (higher or lower); the "
        "engine keeps the current value and the gap honest from your own data, and "
        "tells you whether it is improving, stalling, or regressing."
    ),
    "triggers": [
        "следи за числом к цели",
        "показывай, сколько осталось до цели",
        "текущее значение против целевого",
        "движется ли показатель в нужную сторону",
        "track a number toward a target",
        "how far am I from the target",
        "current value vs the goal, and the gap",
        "is this number moving the right way",
        "progress toward a numeric goal",
    ],
    "produces_preview": (
        "A present-state list of your numbers — for each, the current value, the "
        "target, the gap still to close, and a trend word (improving / stalling / "
        "regressing). A number with no reading yet shows honestly as 'no data yet', "
        "never a made-up value; every value cites the record it was read from."
    ),
    "determinism_note": (
        "HIGH determinism: the engine guarantees every value is COMPUTED from your "
        "own injected reading — the role never authors a number and never moves a "
        "target (the target is yours, set in config). The gap and the trend follow "
        "deterministically from the reading and the target. What is NOT deterministic "
        "is any prose note the role adds about WHY a number moved — shown as the "
        "role's reading, and grounded in a real record."
    ),
    "built": True,
}


# -----------------------------------------------------------------------------
# Config-time schema hook — the plugin owns its own schema shape (the seam)
# -----------------------------------------------------------------------------

def validate_schema(raw: Any) -> dict:
    """Validate the raw `schema:` block from a metrics part's config; return the
    canonical schema dict, or raise `RoleConfigError` on any malformed input.

    The plugin side of the composite loader seam (dispatched from
    `roles_common._parse_part_schema` because `REQUIRES_SCHEMA` is set). THIS plugin
    owns the metrics schema contract — a non-empty `metrics` list, each entry a
    `{key, source, target, direction, unit?}` with a unique key, a non-empty source,
    a numeric target, a `direction` in {higher, lower}, and an optional string unit
    — plus `grounding: records` (metrics grounds in readings, which are records; any
    other mode fail-closes rather than silently degrading).

    Error messages carry the shape-specific detail only (they name no config path or
    part id); the loader locates them to `{path}: part {pid!r}` when it catches.
    """
    if not isinstance(raw, dict):
        raise RoleConfigError(
            "needs a 'schema:' block (a 'metrics:' list of numbers + targets), got "
            f"{type(raw).__name__}"
        )
    raw_metrics = raw.get("metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        raise RoleConfigError(
            "schema 'metrics' must be a non-empty list of "
            "{key, source, target, direction} entries"
        )
    metrics: list[dict] = []
    seen_keys: set[str] = set()
    for midx, m in enumerate(raw_metrics):
        if not isinstance(m, dict):
            raise RoleConfigError(
                f"schema metrics[{midx}] must be a mapping with "
                "'key', 'source', 'target', 'direction'"
            )
        key = m.get("key")
        if not isinstance(key, str) or not key.strip():
            raise RoleConfigError(
                f"schema metrics[{midx}].key must be a non-empty string, got {key!r}"
            )
        key = key.strip()
        if key in seen_keys:
            raise RoleConfigError(f"schema has a duplicate metric key {key!r}")
        source = m.get("source")
        if not isinstance(source, str) or not source.strip():
            raise RoleConfigError(
                f"schema metric {key!r} must declare a non-empty 'source' "
                f"(the reading key), got {source!r}"
            )
        target = m.get("target")
        if isinstance(target, bool) or not isinstance(target, (int, float)):
            raise RoleConfigError(
                f"schema metric {key!r} 'target' must be a number, got {target!r}"
            )
        direction = m.get("direction")
        if not isinstance(direction, str) or direction.strip() not in _DIRECTIONS:
            raise RoleConfigError(
                f"schema metric {key!r} 'direction' must be one of "
                f"{sorted(_DIRECTIONS)}, got {direction!r}"
            )
        unit = m.get("unit", "")
        if unit is None:
            unit = ""
        if not isinstance(unit, str):
            raise RoleConfigError(
                f"schema metric {key!r} 'unit' must be a string, got {unit!r}"
            )
        seen_keys.add(key)
        metrics.append({
            "key": key,
            "source": source.strip(),
            "target": target,
            "direction": direction.strip(),
            "unit": unit.strip(),
        })

    grounding = raw.get("grounding", "records")
    if not isinstance(grounding, str) or grounding.strip() != "records":
        raise RoleConfigError(
            "schema 'grounding' for a metrics part must be 'records' "
            f"(metrics grounds in injected readings), got {grounding!r}"
        )
    # Stage 2.5 grounding-check is OFF for metrics: the numbers are engine-computed
    # from the injection, so a refresh cannot drift. A body `note` is checked at the
    # writer (records grounding), not by the Stage 2.5 re-read.
    return {"metrics": metrics, "grounding": "records", "grounding_check": False}


def fresh_state() -> dict:
    """A brand-new metrics part's top-level fields with archetype defaults filled.

    `schema` is a `{}` PLACEHOLDER: the sole writer overlays the real config-declared
    schema (the metric set + targets) onto both a fresh seed and a loaded state, so
    this stays generic. The common writer overlays the per-instance fields it owns
    (`role_id`, `part_id`, `archetype`, `description`). Returns a fresh dict each call.
    """
    return {
        "version": METRICS_VERSION,
        "role_id": "",
        "archetype": ARCHETYPE,
        "description": "",
        "seen_watermark": None,
        "staging": None,
        "state_auto_hash": None,
        "consecutive_rejects": 0,
        "schema": {},
        "metrics": [],
    }


def known_key_numbers(state: Any) -> Iterable[int]:
    """Metrics mints no `lk-NNNN` keys — a metric's identity is its declared key.

    Yields nothing (present so the writer can build a `KeyMinter` uniformly across
    every part-kind; `persist` never calls the minter)."""
    return ()


def reading_sources(schema: Any) -> list[str]:
    """The distinct metric-source keys the runner's readings-lane should fetch.

    The plugin side of the readings seam: the runner holds the flag
    (`REQUIRES_READINGS`) and asks THIS hook which sources to read, so it never has
    to parse the metrics schema shape itself. Returns the de-duplicated `source`
    strings in declared order. A malformed / empty schema yields an empty list (the
    runner injects nothing → every metric reads as no-data)."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _schema_metrics(schema if isinstance(schema, dict) else {}):
        source = m.get("source")
        if isinstance(source, str) and source.strip() and source.strip() not in seen:
            seen.add(source.strip())
            out.append(source.strip())
    return out


# -----------------------------------------------------------------------------
# Schema + state accessors (shape lives in DATA; every hook reads it here)
# -----------------------------------------------------------------------------

def _schema(state: Any) -> dict:
    if not isinstance(state, dict):
        return {}
    schema = state.get("schema")
    return schema if isinstance(schema, dict) else {}


def _schema_metrics(schema: dict) -> list[dict]:
    """The declared metric configs in schema order (each {key, source, target, ...})."""
    raw = schema.get("metrics") if isinstance(schema, dict) else None
    return [m for m in raw if isinstance(m, dict)] if isinstance(raw, list) else []


def _metric_by_key(schema: dict) -> dict[str, dict]:
    """`{metric key: its config dict}` for the declared metrics."""
    out: dict[str, dict] = {}
    for m in _schema_metrics(schema):
        key = m.get("key")
        if isinstance(key, str) and key.strip():
            out[key.strip()] = m
    return out


def _stored_metrics(state: Any) -> list[dict]:
    """The per-metric reading list of a live state OR a staging dict."""
    if not isinstance(state, dict):
        return []
    raw = state.get("metrics")
    return [m for m in raw if isinstance(m, dict)] if isinstance(raw, list) else []


def _stored_by_key(state: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in _stored_metrics(state):
        key = m.get("key")
        if isinstance(key, str) and key.strip():
            out[key.strip()] = m
    return out


def _gap(current: Any, target: Any, direction: Any) -> Any:
    """The signed distance still to close (see the module docstring's convention):
    positive → not there yet; ≤ 0 → target reached or passed. None when the current
    value is missing (no data) or the target is not numeric."""
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return None
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        return None
    if direction == "higher":
        return target - current
    return current - target  # direction == "lower" (default-safe)


def _view(state: Any) -> list[dict]:
    """The schema-driven progress view — one entry per DECLARED metric, joining the
    config (target / direction / unit) with the stored reading (current / trend /
    provenance) and computing the gap. This is the plugin's computed projection: the
    full `{key, current, target, direction, unit, gap, trend, last_reading_at,
    provenance, note?}` progress-view the render / summary read. A declared metric
    with no stored reading shows honestly as current=null (no data yet); a stored
    metric no longer in the schema is dropped from the view (config is authoritative).
    """
    schema = _schema(state)
    stored = _stored_by_key(state)
    out: list[dict] = []
    for m in _schema_metrics(schema):
        key = m.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        key = key.strip()
        target = m.get("target")
        direction = m.get("direction")
        unit = m.get("unit") if isinstance(m.get("unit"), str) else ""
        rec = stored.get(key, {})
        current = rec.get("current")
        current = current if isinstance(current, (int, float)) and not isinstance(current, bool) else None
        entry = {
            "key": key,
            "current": current,
            "target": target,
            "direction": direction,
            "unit": unit,
            "gap": _gap(current, target, direction),
            "trend": rec.get("trend") if isinstance(rec.get("trend"), str) else None,
            "last_reading_at": rec.get("last_reading_at")
            if nonempty_str(rec.get("last_reading_at")) else None,
            "provenance": [r for r in rec.get("provenance") or [] if isinstance(r, str)],
        }
        note = rec.get("note")
        if nonempty_str(note):
            entry["note"] = note.strip()
        out.append(entry)
    return out


# -----------------------------------------------------------------------------
# Trend — a deterministic verdict from the injected reading (never body-authored)
# -----------------------------------------------------------------------------

def _trend(current: Any, reading: dict, direction: Any) -> Any:
    """Compute the trend verdict from the injected reading and the metric direction.

    Reference preference: the σ-baseline mean (`mu`) when present (a smoother "today
    vs your recent norm" read), else the prior reading, else None → no verdict yet.
    "improving" = current moved TOWARD the target vs the reference; "regressing" =
    away; "stalling" = flat (delta == 0) or no reference to compare against.
    """
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return None
    ref = reading.get("mu")
    if not isinstance(ref, (int, float)) or isinstance(ref, bool):
        ref = reading.get("prior")
    if not isinstance(ref, (int, float)) or isinstance(ref, bool):
        return TREND_STALLING  # a reading with no comparison point is not a trend
    delta = current - ref
    if delta == 0:
        return TREND_STALLING
    toward = (direction == "higher" and delta > 0) or (direction == "lower" and delta < 0)
    return TREND_IMPROVING if toward else TREND_REGRESSING


# -----------------------------------------------------------------------------
# validate — structural + semantic gate
# -----------------------------------------------------------------------------

def validate(prior_state: Any, delta_payload: Any) -> ValidationResult:
    """Gate a body-proposed metrics delta payload before it may be persisted.

    STRUCTURAL: the payload envelope parses; `op` is known; no engine-owned /
    config-owned field is body-set (the body cannot author a number or move a
    target); the `key` is a DECLARED metric; a key is not touched twice this tick.

    SEMANTIC / grounding, per op:
      - `refresh` grounds on the ENGINE-INJECTED reading (`payload["readings"]`),
        not a body citation — the body cannot fabricate a number, so it need not
        cite one. Always accepted; the approved delta is ENRICHED with the computed
        `_reading` (`{current, trend, at, stem}`) or `None` (honest no-data).
      - `note` is body-authored prose → records-grounded the ordinary way: it must
        cite ≥1 record present in the shared `read_records` corpus.

    There is no churn guard: the metric key set is small and config-bounded, and
    refreshing every declared metric each tick is the expected behaviour, not a
    flood. Same contract shape as the other kinds: ok=True persists
    `approved_deltas`; ok=False blocks the whole tick (malformed envelope / state).
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
    declared = _metric_by_key(schema)
    if not declared:
        # Defensive — the config loader requires a valid schema before a metrics
        # part loads, but a corrupt state with no declared metrics cannot be
        # validated against. Hold rather than guess.
        return ValidationResult.rejected(
            rejections=({"ref": "schema",
                         "reason": "metrics schema declares no metrics"},)
        )

    corpus = read_record_corpus(delta_payload)
    readings = delta_payload.get("readings")
    readings = readings if isinstance(readings, dict) else {}

    approved: list[dict] = []
    rejections: list[dict] = []
    touched: set[str] = set()

    for idx, delta in enumerate(raw_deltas):
        if not isinstance(delta, dict):
            rejections.append({"ref": delta_ref(delta, idx, ("key",)),
                               "reason": "delta is not a mapping"})
            continue
        enriched, reason = _validate_delta(delta, declared, readings, corpus, touched)
        if reason is not None:
            rejections.append({"ref": delta_ref(delta, idx, ("key",)), "reason": reason})
            continue
        approved.append(enriched)

    return ValidationResult(
        ok=True,
        approved_deltas=tuple(approved),
        rejections=tuple(rejections),
    )


def _validate_delta(
    delta: dict,
    declared: dict[str, dict],
    readings: dict,
    corpus: set[str],
    touched: set[str],
) -> tuple[dict, str | None]:
    """Return `(enriched_delta, None)` when well-formed, or `({}, reason)` on failure.

    A `refresh` is enriched with `_reading` (the engine-computed reading, or None for
    no-data); a `note` is returned as-is after its record grounding is checked."""
    op = delta.get("op")
    if op not in DELTAS:
        return {}, f"unknown op {op!r}"
    for forbidden in _BODY_FORBIDDEN_FIELDS:
        if forbidden in delta:
            return {}, (f"'{forbidden}' is engine-/config-owned, not body-set "
                        "(the body never authors a number or moves a target)")
    key = delta.get("key")
    if not nonempty_str(key):
        return {}, f"{op} missing non-empty metric 'key'"
    key = key.strip()
    metric_cfg = declared.get(key)
    if metric_cfg is None:
        return {}, (f"{op} 'key' {key!r} is not a declared metric "
                    f"{sorted(declared)}")
    if key in touched:
        return {}, f"{op} 'key' {key!r} is already touched by another delta this tick"

    if op == "refresh":
        touched.add(key)
        return {**delta, "_reading": _compute_reading(metric_cfg, readings, corpus)}, None

    # op == "note": a body-authored annotation → records-grounded like any prose.
    text = delta.get("text")
    if not nonempty_str(text):
        return {}, "note requires non-empty 'text'"
    g_reason = _note_grounding_reason(delta, corpus)
    if g_reason is not None:
        return {}, g_reason
    touched.add(key)
    return delta, None


def _compute_reading(metric_cfg: dict, readings: dict, corpus: set[str]) -> dict | None:
    """The engine-computed reading for a metric, or None when there is no usable data.

    Reads the runner-injected reading for the metric's `source`, verifies its record
    stem is genuinely in the shared `read_records` corpus (defence in depth — the
    lane already scopes it, but a refresh never asserts a number from a record not in
    the zone), then computes `current` and the `trend` verdict. Returns
    `{current, trend, at, stem}` or None (→ honest no-data)."""
    source = metric_cfg.get("source")
    if not nonempty_str(source):
        return None
    reading = readings.get(source.strip())
    if not isinstance(reading, dict):
        return None
    current = reading.get("current")
    if not isinstance(current, (int, float)) or isinstance(current, bool):
        return None
    stem = normalize_record_ref(str(reading.get("stem") or ""))
    if not stem or stem not in corpus:
        return None  # the reading's record is not in the injected zone — no assertion
    return {
        "current": current,
        "trend": _trend(current, reading, metric_cfg.get("direction")),
        "at": normalize_record_ref(str(reading.get("at") or "")) or stem,
        "stem": stem,
    }


def _note_grounding_reason(delta: dict, corpus: set[str]) -> str | None:
    """None when a `note` cites ≥1 real in-remit record; else a reason. Records is
    the deterministic oracle (`corpus` is the engine-injected `read_records`)."""
    evidence = delta.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return "note 'evidence' must cite at least one read record"
    missing = ungrounded_refs(evidence, corpus)
    if missing:
        return f"ungrounded: note evidence not in read_records: {missing}"
    return None


# -----------------------------------------------------------------------------
# persist — pure transform (roles_persist is the sole caller / writer)
# -----------------------------------------------------------------------------

def persist(prior_state: Any, approved_deltas: Iterable[dict], key_minter) -> dict:
    """Apply already-validated deltas to a copy of `prior_state`; return new state.

    Pure: no I/O, never mutates inputs, never calls `key_minter` (a metric's key is
    its declared id, not minted). Per op:
      - `refresh` with data     → set current / trend / last_reading_at / provenance
                                   from the engine-enriched `_reading` (create the
                                   per-metric record if absent).
      - `refresh` with no data  → create a null record (no data yet) when the metric
                                   has none; a NO-OP when the metric already holds a
                                   value (never overwrite a known reading with null).
      - `note`                  → set the prose note on the metric's record; grow
                                   provenance with the note's cited record(s).

    Only the derived scalars are persisted — never the daily series and never the
    config target (the target lives in the schema; `_view` joins + computes gap)."""
    new_state = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    metrics = new_state.get("metrics")
    if not isinstance(metrics, list):
        metrics = []
    new_state["metrics"] = metrics
    index = {m.get("key"): m for m in metrics if isinstance(m, dict) and nonempty_str(m.get("key"))}

    for delta in approved_deltas:
        if not isinstance(delta, dict):
            continue
        op = delta.get("op")
        key = delta.get("key")
        key = key.strip() if nonempty_str(key) else ""
        if not key:
            continue
        if op == "refresh":
            _apply_refresh(metrics, index, key, delta.get("_reading"))
        elif op == "note":
            _apply_note(index.get(key), delta.get("text"), delta.get("evidence"))

    return new_state


def _fresh_record(key: str) -> dict:
    return {"key": key, "current": None, "trend": None,
            "last_reading_at": None, "provenance": []}


def _apply_refresh(
    metrics: list[dict], index: dict[str, dict], key: str, reading: Any
) -> None:
    """Set a metric's derived scalars from the engine-enriched reading, or leave a
    known value untouched when this tick has no data (create a null record only when
    the metric has never had one — the honest cold-start no-data state)."""
    rec = index.get(key)
    if isinstance(reading, dict):
        if rec is None:
            rec = _fresh_record(key)
            metrics.append(rec)
            index[key] = rec
        rec["current"] = reading.get("current")
        rec["trend"] = reading.get("trend")
        rec["last_reading_at"] = reading.get("at")
        stem = reading.get("stem")
        rec["provenance"] = [f"[[{stem}]]"] if nonempty_str(stem) else []
        return
    # No data this tick: materialise a null record for a never-seen metric (so it is
    # visible-but-empty at cold-start); otherwise preserve the last known reading.
    if rec is None:
        metrics.append(_fresh_record(key))


def _apply_note(rec: Any, text: Any, evidence: Any) -> None:
    """Attach a body-authored prose note to a metric and grow its provenance with the
    cited record(s). A note leaves the numbers (current / trend / last_reading_at)
    untouched. A note on a metric that has no record yet is dropped (there is nothing
    to annotate — validate allowed the op, but a note needs a metric)."""
    if not isinstance(rec, dict):
        return
    rec["note"] = str(text or "").strip()
    rec["provenance"] = grow_provenance(rec.get("provenance"), evidence or [])


# -----------------------------------------------------------------------------
# render — the state.md AUTO-zone body (markers spliced by roles_persist)
# -----------------------------------------------------------------------------

def render(state: Any) -> str:
    """Render the metrics part as the state.md AUTO-zone markdown body (present-state).

    Schema-driven: one line per DECLARED metric, in declared order. A metric with a
    reading shows `current unit → target unit · gap … · trend (as of date)`; a metric
    with no reading shows `no data yet (target …)` — never a fabricated value."""
    view = _view(state)
    if not view:
        return "_No metrics configured._"
    lines: list[str] = [_render_metric(m) for m in view]
    return "\n".join(lines).rstrip() + "\n"


def _fmt_num(value: Any) -> str:
    """Compact numeric formatting: drop a trailing `.0` on whole numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _render_metric(m: dict) -> str:
    key = m.get("key") or "(no key)"
    unit = m.get("unit") or ""
    unit_suffix = f" {unit}" if unit else ""
    target = m.get("target")
    if m.get("current") is None:
        line = f"- {key}: no data yet (target {_fmt_num(target)}{unit_suffix})"
    else:
        gap = m.get("gap")
        parts = [f"- {key}: {_fmt_num(m['current'])}{unit_suffix} → "
                 f"{_fmt_num(target)}{unit_suffix}"]
        if gap is not None:
            parts.append(f"gap {_fmt_num(gap)}{unit_suffix}")
        trend = m.get("trend")
        if nonempty_str(trend):
            parts.append(str(trend))
        at = m.get("last_reading_at")
        detail = " · ".join(parts)
        if nonempty_str(at):
            detail += f" (as of {at})"
        line = detail
    note = m.get("note")
    if nonempty_str(note):
        line += f"\n  - note: {note.strip()}"
    return line


# -----------------------------------------------------------------------------
# identity — natural keys; no external anchor concept (never guesses)
# -----------------------------------------------------------------------------

def identity(item: Any, anchors: Any = None) -> IdentityResult:
    """Metrics are identified by their declared key, not an external Minder id — there
    is nothing to anchor and nothing to guess. Returns `anchored=True` and never
    fabricates an anchor. The writer never calls this for a metrics part; present for
    interface uniformity."""
    return IdentityResult(anchored=True, anchor=None)


# -----------------------------------------------------------------------------
# Composite-seam hooks (mirror the other kinds; metrics-shaped)
# -----------------------------------------------------------------------------

def gate_identity(
    role_id: str,
    part_id: str,
    prior_state: Any,
    approved: list[dict],
) -> tuple[list[dict], list[ClarificationSignal]]:
    """Metrics has no anchor-identity concept — every approved delta passes.

    Returns `(approved, [])`. A metric is identified by its exact declared key
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
    """One decision row per persisted metrics delta, stamped `part`.

    `kind` vocabulary: metric-refresh (a reading recompute — carries the reading date
    + whether it had data) / metric-note (a prose annotation). No keys are minted, so
    `minted` is ignored and the row `key` is the metric's declared key."""
    rows: list[dict] = []
    for d in approved_deltas:
        op = d.get("op")
        key = d.get("key")
        if op == "refresh":
            reading = d.get("_reading")
            has_data = isinstance(reading, dict)
            rows.append(decision_row(
                "metric-refresh", key, hook, role_id, part_id, ts,
                had_data=has_data,
                at=(reading.get("at") if has_data else None),
                evidence=([f"[[{reading.get('stem')}]]"] if has_data
                          and nonempty_str(reading.get("stem")) else []),
            ))
        elif op == "note":
            rows.append(decision_row(
                "metric-note", key, hook, role_id, part_id, ts,
                evidence=clean_evidence(d.get("evidence")),
            ))
    return rows


def delta_counts(persisted_deltas: list[dict]) -> tuple[int, int]:
    """(added, advanced) for the run counts. A `refresh` puts/updates a reading →
    ADDED; a `note` annotates an existing metric → ADVANCED. (The pure delta list
    carries no prior state to tell a first reading from a re-read; the imprecision is
    cosmetic run-count only.)"""
    added = sum(1 for d in persisted_deltas
                if isinstance(d, dict) and d.get("op") == "refresh")
    advanced = sum(1 for d in persisted_deltas
                   if isinstance(d, dict) and d.get("op") == "note")
    return added, advanced


def cold_materialize_decisions(
    adopted_state: Any, role_id: str, part_id: str, ts: str
) -> list[dict]:
    """One `cold-materialize` row per stored metric when a frozen draft goes live."""
    return [
        decision_row(
            "cold-materialize", m.get("key"), "tick", role_id, part_id, ts,
            evidence=[r for r in m.get("provenance") or [] if isinstance(r, str)],
            has_data=m.get("current") is not None,
        )
        for m in _stored_metrics(adopted_state)
    ]


def content_view(state: Any) -> dict:
    """The content-only projection frozen into `staging` at cold-start.

    Metrics content is its per-metric reading list. The writer spreads this into the
    staging dict and adopts it later via `adopt_staging`; the SCHEMA (the targets) is
    NOT frozen — the writer re-overlays it from config on every load, so config stays
    the source of truth for the targets."""
    return {"metrics": list(_stored_metrics(state))}


def adopt_staging(prior_state: Any, staging: Any) -> dict:
    """Adopt a frozen cold-start draft into a live state.

    Returns a deep copy of `prior_state` (which already carries the config-overlaid
    schema) with its `metrics` replaced by the staged draft's. The writer clears
    `staging`, resets the reject counter and advances the watermark over
    `consumed_records`."""
    ns = copy.deepcopy(prior_state) if isinstance(prior_state, dict) else {}
    src = staging.get("metrics") if isinstance(staging, dict) else None
    ns["metrics"] = [m for m in src if isinstance(m, dict)] if isinstance(src, list) else []
    return ns


def content_summary(state: Any) -> list[str]:
    """Human labels of this part's content units (cold-start clarification + count).

    ONE label per STORED metric — its key plus its current value and trend, or "no
    data yet". Works on both a live state and a staging dict (neither of which is
    guaranteed to carry the schema, so the label uses only the stored reading)."""
    return [_metric_label(m) for m in _stored_metrics(state)]


def _metric_label(rec: dict) -> str:
    key = rec.get("key") or "(no key)"
    current = rec.get("current")
    if current is None:
        body = "no data yet"
    else:
        body = _fmt_num(current)
        trend = rec.get("trend")
        if nonempty_str(trend):
            body += f", {trend}"
    return truncate(f"{key}: {body}")


def consumed_records(state: Any) -> Iterable[str]:
    """Record stems this part's content cites (watermark advance on adopt).

    Works on both a live state and a staging dict. Metric content grounds in each
    metric's provenance trail (the reading's source record); non-record refs
    normalise to empty and are dropped."""
    for m in _stored_metrics(state):
        for ref in m.get("provenance") or []:
            stem = normalize_record_ref(ref)
            if stem:
                yield stem


def registry_summary(state: Any) -> dict:
    """The ROLES.md registry projection of this part — a plain-dict count summary.

    `{total, breakdown:[[label,count],...], staged}`. Total = declared metrics (the
    schema-driven view); breakdown = with-data vs no-data present-state counts
    (non-zero only); staged = a frozen cold-start draft's metrics. Tolerant of a
    partially-written / corrupt state (falls back to the stored metrics when the
    schema is missing)."""
    view = _view(state)
    if view:
        total = len(view)
        with_data = sum(1 for m in view if m.get("current") is not None)
    else:
        # No schema (corrupt / mid-write) — count the stored readings directly so the
        # projection is never silently zero when metrics exist.
        stored = _stored_metrics(state)
        total = len(stored)
        with_data = sum(1 for m in stored if m.get("current") is not None)
    no_data = total - with_data
    breakdown: list[list] = []
    if with_data:
        breakdown.append(["with-data", with_data])
    if no_data:
        breakdown.append(["no-data", no_data])
    staged = 0
    staging = state.get("staging") if isinstance(state, dict) else None
    if isinstance(staging, dict) and isinstance(staging.get("metrics"), list):
        staged = sum(1 for x in staging["metrics"] if isinstance(x, dict))
    return {"total": total, "breakdown": breakdown, "staged": staged}
