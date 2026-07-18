#!/usr/bin/env python3
"""Sole writer + control boundary for the composite Roles subsystem.

A role is an ORDERED LIST OF PARTS (`config.parts[]`), each `{id, kind}` backed
by an archetype plugin loaded dynamically by its `kind`
(`roles_common.import_archetype`). This module is the single thing that turns a
body-proposed delta payload into persisted state, and it does so PER PART behind
each part's archetype validator:

    inject read_records (minder_query --list)  →  route deltas by delta.part
      for each part:
        load parts/{part}.json  →  plugin.validate  →  (reject | churn-hold |
                                   identity-hold | cold-start | progress)
                               →  plugin.persist  →  parts/{part}.json (atomic)
                               →  plugin.render    →  splice its state.md sub-zone
                               →  per-part state_auto_hash  →  decisions.jsonl (+part)
      →  one roles-runs.jsonl entry + one log_roles.md block for the whole tick

Every delta carries `part` (delta payload v2, BUILD-CONTRACT §4); an ungrounded /
invalid / churny delta is refused per THAT part's plugin regardless of body
intent. The body NEVER writes — this module is the only thing in the subsystem
that mutates role state on disk. Grounding is honor-system: `read_records` is
ENGINE-INJECTED (the runner overwrites any body-supplied value with the
deterministic `minder_query --list` stems of the role's remit), and the validator
only checks that each citation is a subset of that injected corpus — reading is
lens-style, not independently re-verified. The values-grounding oracle
(`values_oracles`, a stance's cited constitution principle-ids) is the same shape: its
RELEVANCE half is prompt-stage (the `ztn-roles` SKILL's Stage 2.6), but its EXISTENCE
half is ENGINE-INJECTED here — `_inject_values_oracles` deterministically drops any id
that does not resolve to a real file under `0_constitution/`, mirroring
`_inject_read_records`, so a fabricated principle-id can never ground a position even if
the prompt stage regresses.

Composite state layout:
  - state is per-part: one `parts/{part_id}.json` per part (SRP).
  - state.md is a portrait + N contiguous AUTO sub-zones, one per part in
    `config.parts[]` order; each sub-zone is spliced independently and guarded by
    its OWN `state_auto_hash` (stored in that part's json), so an owner edit to
    one part's zone never blocks the engine from rewriting another's.
  - decisions.jsonl rows carry a `part` field.
  - 3-reject auto-pause, churn / identity holds, and cold-start staging are all
    PER PART (each part cold-starts into its own frozen `staging`); a single
    `--approve-coldstart` adopts every pending part at once.

The common layer never names a concrete part-kind. This writer is fully
archetype-agnostic: it dispatches EVERY shape-specific decision through the part
plugin and only ever touches the generic per-part envelope fields it owns —
`seen_watermark`, `staging`, `state_auto_hash`, `consecutive_rejects`, and the
engine-written auto-pause `status` / `paused_reason` stop. The plugin owns:
  - the DATA transform: validate / persist / render / fresh_state / known_key_numbers
  - identity routing: gate_identity (anchor-else-HITL for parts that anchor; a
    pass-through for parts that do not) + identity
  - the decision vocabulary: build_decisions / cold_materialize_decisions
  - cold-start content: content_view (freeze) / adopt_staging (adopt) /
    content_summary (labels) / consumed_records (watermark stems)
Adding a part-kind is implementing that interface — this writer never changes.

CLI:
    python3 roles_persist.py --role <id> --payload <path|-> [--approve-coldstart]

Deterministic, no LLM. Cross-platform: `pathlib`, atomic writes (`.tmp` +
`Path.replace`, LF-forced), reads via universal-newline `read_text`. Per-part
files are written derived-then-record (state.md before parts/*.json) so a crash
between them re-surfaces as a conservative owner-edit flag on the next run, never
as silent data loss.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import minder_query
import role_state_hash
from _common import constitution_principle_ids, now_iso_utc, state_dir, today_iso
from roles_common import (
    ROLE_NUDGE_OPEN_BUDGET,
    ClarificationSignal,
    KeyMinter,
    PartSpec,
    RoleArchetypeError,
    RoleConfig,
    RoleConfigError,
    RoleError,
    RunRecord,
    append_roles_log,
    append_run,
    clarification_seen_resolved,
    count_open_role_nudges,
    delta_part,
    emit_clarification,
    emit_clarification_signal,
    format_run_log_section,
    import_archetype,
    is_valid_iso_date,
    load_role_config,
    make_run_counts,
    normalize_record_ref,
    part_state_path,
    part_subject,
    resolve_clarification,
    role_dir,
    ungrounded_refs,
)

# 3 consecutive genuine validator rejections auto-pause a PART (§1.5 / §3.7).
AUTO_PAUSE_THRESHOLD = 3

_PART_DESCRIPTION = (
    "Role part state. Engine-written only (roles_persist.py). Do not hand-edit."
)


# -----------------------------------------------------------------------------
# Instance paths (per-part json comes from roles_common.part_state_path)
# -----------------------------------------------------------------------------

def _state_path(role_id: str, base: Path | None) -> Path:
    return role_dir(role_id, base) / "state.md"


def _decisions_path(role_id: str, base: Path | None) -> Path:
    return role_dir(role_id, base) / "decisions.jsonl"


def _config_path(role_id: str, base: Path | None) -> Path:
    return role_dir(role_id, base) / "config.yml"


# -----------------------------------------------------------------------------
# Low-level IO (atomic; LF-forced for cross-platform determinism)
# -----------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    tmp.replace(path)


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)


def _dump_state(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2) + "\n"


# -----------------------------------------------------------------------------
# Per-part state load / seed
# -----------------------------------------------------------------------------

def _fresh_part_state(role_id: str, part_id: str, kind: str) -> dict:
    """A brand-new part state seed — canonical field order from the plugin.

    The archetype-owned shape + tunables come from the plugin's `fresh_state()`
    (the single home, §11.11); the writer overlays only the fields it owns per
    instance: `role_id` (runtime identity), `part_id` (which part this file is),
    `archetype` (the config-selected kind), and `description` (the
    engine-written-only note).
    """
    plugin = import_archetype(kind)
    seed = plugin.fresh_state()
    seed["role_id"] = role_id
    seed["part_id"] = part_id
    seed["archetype"] = kind
    seed["description"] = _PART_DESCRIPTION
    return seed


def _overlay_schema(state: dict, part: PartSpec) -> None:
    """Overlay the config-declared schema onto a part's state (config is the source
    of truth for a schema-bearing part's shape — a registry).

    Overlaid on BOTH a fresh seed and a loaded state, so an owner schema edit via
    `config.yml` propagates on the next tick (the on-disk `schema` is refreshed from
    config every load, never trusted as the SoT). A part with no schema (ledger /
    narrative carry an empty `PartSpec.schema`) is left untouched — no `schema` key is
    added and its state stays byte-identical. Deep-copied so the shared `PartSpec`
    dict never aliases per-role state.
    """
    if part.schema:
        state["schema"] = copy.deepcopy(part.schema)


def _load_part_state(role_id: str, part: PartSpec, base: Path | None) -> dict:
    """Return a part's prior state, or a fresh seed when its file does not exist.

    A present file whose `archetype` disagrees with the config part's `kind`, or
    whose `part_id` disagrees with the part's id, is a blocking integrity error —
    never silently coerced (surface, don't guess). The config-declared schema is
    overlaid onto whichever state is returned (fresh seed or loaded file), so a
    schema-bearing part always reflects the current config shape.
    """
    path = part_state_path(role_id, part.id, base)
    if not path.exists():
        state = _fresh_part_state(role_id, part.id, part.kind)
        _overlay_schema(state, part)
        return state
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoleError(f"{path}: cannot read part state ({exc})") from exc
    if not isinstance(raw, dict):
        raise RoleError(f"{path}: part state root must be a JSON object")
    prior_kind = raw.get("archetype")
    if prior_kind != part.kind:
        raise RoleError(
            f"{path}: part archetype {prior_kind!r} does not match config kind "
            f"{part.kind!r}"
        )
    prior_pid = raw.get("part_id")
    if prior_pid is not None and prior_pid != part.id:
        raise RoleError(
            f"{path}: stored part_id {prior_pid!r} does not match config part "
            f"{part.id!r}"
        )
    _overlay_schema(raw, part)
    return raw


def _orphaned_part_ids(role_id: str, cfg: RoleConfig, base: Path | None) -> list[str]:
    """On-disk `parts/*.json` stems the config's `parts[]` no longer declares.

    A part dropped from `config.yml` strands its state: the tick iterates only
    `cfg.parts`, so the orphaned `parts/{id}.json` is never processed and its
    `state.md` AUTO sub-zone is never re-synced — it silently goes stale. Parts
    shape is create-time (the `/ztn:role:add` concierge composes it; `/ztn:role:edit`
    refuses a shape change and hands off), so any on-disk part missing from the
    config is a real mismatch, not a transient. The engine SURFACES it — never
    deletes (surface, don't decide silently)."""
    pdir = part_state_path(role_id, "_", base).parent
    if not pdir.is_dir():
        return []
    declared = set(cfg.part_ids)
    return sorted(p.stem for p in pdir.glob("*.json") if p.stem not in declared)


def _surface_orphaned_parts(
    role_id: str, cfg: RoleConfig, run_at: str, base: Path | None
) -> None:
    """Surface a `role-orphaned-part` CLARIFICATION when the config dropped a part
    whose state still sits on disk. Deduped (once per open mismatch); deletes
    nothing — the owner reconciles via `/ztn:role:edit`."""
    orphans = _orphaned_part_ids(role_id, cfg, base)
    if not orphans:
        return
    listed = ", ".join(f"`{o}`" for o in orphans)
    emit_clarification(
        ctype="role-orphaned-part",
        subject=role_id,
        context=(
            f"Role `{role_id}` has part state on disk that its `config.yml` `parts:` "
            f"no longer declares: {listed}. The tick processes only the declared "
            f"parts, so the orphaned `parts/{{id}}.json` and its `state.md` sub-zone "
            f"are frozen and drift stale — nothing was deleted. This usually means a "
            f"parts-shape change slipped past `/ztn:role:edit` (which refuses one and "
            f"hands off to `/ztn:role:add`), or the config was hand-edited."
        ),
        source=f"roles tick for {role_id} (part-state integrity)",
        suggested_action=(
            f"Reconcile via `/ztn:role:edit`: restore {listed} to `parts:` to resume "
            f"it, or intentionally retire the role and re-create the new shape via "
            f"`/ztn:role:add`."
        ),
        action_taken="Surfaced; no state deleted (surface, don't decide silently).",
        date_str=run_at[:10],
        base=base,
    )


# -----------------------------------------------------------------------------
# Engine-owned envelope accessors (generic — no Ledger shape)
# -----------------------------------------------------------------------------

def _part_paused(state: Any) -> bool:
    """True when a part carries the engine-written auto-pause stop (§1.5)."""
    return isinstance(state, dict) and state.get("status") == "paused"


def _part_is_fresh(state: Any, grounding: str = "records", plugin: Any = None) -> bool:
    """A part is fresh (cold-start-armed) when it has never gone live — no frozen draft
    pending AND no adopted content yet. An envelope-first test, generalized per the
    PART's grounding (`PartSpec.grounding`, the SoT — NOT a plugin constant) so it is
    correct for a records-grounded part AND a values-grounded one.

    A records-grounded part's content always cites records, so adopting a draft advances
    `seen_watermark` off None; `seen_watermark is None` is therefore an exact proxy for
    "never adopted", and the envelope test alone decides freshness (no plugin needed).
    A records-grounded stance rides this SAME branch — it consumes its cited records on
    adopt, so its watermark leaves None exactly like a ledger.

    A values-grounded part (a values stance) consumes NO records, so its `seen_watermark`
    can stay None even after it has adopted a live position ("always re-examine"). For
    such a part the watermark is NOT a freshness proxy, so when `grounding != "records"`
    and `plugin` is supplied, freshness falls back to whether the part actually holds LIVE
    CONTENT (`plugin.content_summary`): an adopted values stance has content → not fresh →
    not re-armed for cold-start every tick. Records-grounded parts (`grounding ==
    "records"`, the default) never enter this branch, so their behaviour is
    byte-identical."""
    if not isinstance(state, dict):
        return True
    if state.get("staging") is not None:
        return False
    if state.get("seen_watermark") is not None:
        return False
    # seen_watermark is None and no staging. Exact "never adopted" for a records-grounded
    # part. For a non-records grounding the watermark can be None post-adopt, so consult
    # live content to tell an adopted part from a never-adopted one.
    if grounding != "records" and plugin is not None:
        return not list(plugin.content_summary(state))
    return True


def _has_staging(state: Any) -> bool:
    return isinstance(state, dict) and isinstance(state.get("staging"), dict)


# -----------------------------------------------------------------------------
# Record-stem normalisation + watermark (archetype-agnostic; records are records)
# -----------------------------------------------------------------------------

def _record_stem(ref: Any) -> str:
    """Normalise a record ref to its bare basename (single home §11.11)."""
    return normalize_record_ref(ref)


def _read_records(payload: dict) -> list[str]:
    raw = payload.get("read_records")
    if not isinstance(raw, (list, tuple)):
        return []
    return [normalize_record_ref(r) for r in raw if isinstance(r, str) and r.strip()]


def _advance_watermark(prior_wm: Any, stems: list[str]) -> Any:
    """High-water mark = lexical max of (prior watermark, records read this tick).

    Records are date-prefixed basenames, so a lexical max is the latest looked-at
    record — a deterministic, monotonic watermark (§3.1). The scalar-watermark
    caveat (out-of-order / backdated stems) is bounded by the `by_elapsed_time`
    activation floor.
    """
    candidates = [s for s in (normalize_record_ref(x) for x in stems) if s]
    if isinstance(prior_wm, str) and prior_wm.strip():
        prior = normalize_record_ref(prior_wm)
        if prior:
            candidates.append(prior)
    return max(candidates) if candidates else prior_wm


# -----------------------------------------------------------------------------
# read_records injection (ENGINE-INJECTED — the runner is the grounding oracle)
# -----------------------------------------------------------------------------

def _inject_read_records(cfg: RoleConfig, payload: dict, base: Path | None) -> dict:
    """Overwrite `payload["read_records"]` with the deterministic `minder_query
    --list` stems of the role's remit (BUILD-CONTRACT §4 / §7).

    The engine — not the body — owns the grounding corpus: the body may cite only
    records the runner reports as in-remit. Returns a shallow copy with
    `read_records` replaced by the sorted bare-basename stems of every in-remit
    unit; a body-supplied `read_records` is ignored.
    """
    index = minder_query.list_index(cfg.remit, base=base)
    stems = sorted({
        normalize_record_ref(Path(unit["path"]).name)
        for unit in index.get("units", [])
        if isinstance(unit, dict) and isinstance(unit.get("path"), str)
    })
    out = dict(payload)
    out["read_records"] = stems
    return out


# -----------------------------------------------------------------------------
# readings injection (ENGINE-INJECTED — the deterministic metric-readings lane)
# -----------------------------------------------------------------------------
# A SIBLING to `_inject_read_records`: for any part whose plugin declares the
# `REQUIRES_READINGS` capability (the flag pattern, mirroring `REQUIRES_SCHEMA` — the
# runner names no kind), read the LATEST daily value + trend context of each declared
# metric source from the in-remit metric-day source (the records' σ-baselines) and
# inject them as a shared `payload["readings"]`. SoT: the lane READS the source's
# derived state; it never writes it. The metric-day path shape + baselines home is
# ZTN SOURCE infra (the same infra biometric / activity lenses read), isolated in the
# named helpers below — it is dispatched by a capability flag, not a role-kind gate.

def _metric_day_ref(rel_path: str) -> tuple[str, str, str] | None:
    """`(family, source, date-stem)` when `rel_path` is a metric-day record
    `_records/<family>/<source>/<YYYY-MM-DD>.md`, else None. Cross-platform: parses
    via `Path.parts`, so a Windows-native relative path resolves identically."""
    parts = Path(rel_path).parts
    if len(parts) != 4 or parts[0] != "_records":
        return None
    family, source, leaf = parts[1], parts[2], parts[3]
    if not leaf.endswith(".md"):
        return None
    stem = leaf[:-3]
    return (family, source, stem) if is_valid_iso_date(stem) else None


def _metric_day_namespaces(cfg: RoleConfig, base: Path | None) -> dict[tuple[str, str], set[str]]:
    """The in-remit metric-day namespaces → the set of in-remit record date-stems.

    Resolved from the SAME zone index `_inject_read_records` uses, so a reading's
    stem is always a subset of the shared `read_records` corpus (a metric's value is
    only ever read from a record genuinely in the role's remit)."""
    index = minder_query.list_index(cfg.remit, base=base)
    namespaces: dict[tuple[str, str], set[str]] = {}
    for unit in index.get("units", []):
        if not isinstance(unit, dict) or not isinstance(unit.get("path"), str):
            continue
        ref = _metric_day_ref(unit["path"])
        if ref is None:
            continue
        family, source, stem = ref
        namespaces.setdefault((family, source), set()).add(stem)
    return namespaces


def _baselines_metrics(family: str, source: str, base: Path | None) -> dict:
    """The `metrics` block of a namespace's `baselines.json` (the σ-baseline SoT),
    or `{}` when absent / unreadable. Read-only — the lane never writes it."""
    path = state_dir(base) / family / source / "baselines.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    metrics = data.get("metrics") if isinstance(data, dict) else None
    return metrics if isinstance(metrics, dict) else {}


def _as_number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _latest_reading(source: str, namespaces: dict, base: Path | None) -> dict | None:
    """The latest in-remit reading for a metric `source` across the in-remit
    namespaces, or None when the source has no in-remit value anywhere.

    Reading = `{current, prior, mu, sigma, at, stem}` — `current` is the latest
    `values[]` entry whose date is an in-remit record stem (so the cited stem is
    always in the corpus); `prior` is the previous numeric value (trend context);
    `mu`/`sigma` are the σ-baseline. When the same source appears in more than one
    in-remit namespace (e.g. two devices reporting the same metric), the reading with
    the LATEST date wins — a deterministic tiebreak."""
    best_at: str | None = None
    best: dict | None = None
    for (family, source_ns), stems in namespaces.items():
        metrics = _baselines_metrics(family, source_ns, base)
        m = metrics.get(source)
        if not isinstance(m, dict):
            continue
        values = m.get("values")
        if not isinstance(values, list) or not values:
            continue
        chosen = None
        for i in range(len(values) - 1, -1, -1):
            v = values[i]
            if (isinstance(v, dict) and v.get("date") in stems
                    and _as_number(v.get("value")) is not None):
                chosen = i
                break
        if chosen is None:
            continue
        cur = values[chosen]
        prior = None
        for j in range(chosen - 1, -1, -1):
            pv = values[j]
            if isinstance(pv, dict) and _as_number(pv.get("value")) is not None:
                prior = _as_number(pv.get("value"))
                break
        at = str(cur.get("date"))
        if best_at is None or at > best_at:
            best_at = at
            best = {
                "current": _as_number(cur.get("value")),
                "prior": prior,
                "mu": _as_number(m.get("mu")),
                "sigma": _as_number(m.get("sigma")),
                "at": at,
                "stem": at,
            }
    return best


def _inject_readings(cfg: RoleConfig, plugins: dict[str, Any], payload: dict,
                     base: Path | None) -> dict:
    """Overwrite `payload["readings"]` with the deterministic latest metric readings
    for every reading-needing part's declared sources (shared across the role's parts
    like `read_records` — one remit, one readings set). A role with no reading-needing
    part is returned unchanged. Any body-supplied `readings` is ignored (the engine
    owns the numbers)."""
    needy = [p for p in cfg.parts
             if bool(getattr(plugins[p.id], "REQUIRES_READINGS", False))]
    if not needy:
        return payload
    sources: list[str] = []
    seen: set[str] = set()
    for part in needy:
        for source in plugins[part.id].reading_sources(part.schema):
            if isinstance(source, str) and source and source not in seen:
                seen.add(source)
                sources.append(source)
    namespaces = _metric_day_namespaces(cfg, base)
    readings: dict[str, dict] = {}
    for source in sources:
        reading = _latest_reading(source, namespaces, base)
        if reading is not None:
            readings[source] = reading
    out = dict(payload)
    out["readings"] = readings
    return out


# -----------------------------------------------------------------------------
# values-oracle existence filter (ENGINE-INJECTED — the writer owns the
# EXISTENCE half of the values-grounding oracle)
# -----------------------------------------------------------------------------
# A SIBLING to `_inject_read_records`: the runner (the `ztn-roles` SKILL, Stage 2.6)
# AUTHORS `values_oracles` — the per-part set of constitution principle-ids a
# values-grounded part (a stance) may cite — and owns the RELEVANCE half (did
# `/ztn:check-decision` judge a principle applicable). This writer owns the EXISTENCE
# half: it re-checks every id in every values part's oracle against `0_constitution/`
# and drops any that does not resolve to a real principle file, exactly as
# `_inject_read_records` re-authors the records corpus from `minder_query --list`. So the
# honesty guarantee — a body cannot forge a principle NOT in `0_constitution/` — is
# deterministic at the writer, not merely the prompt-stage grep in Stage 2.6.

def _existence_filter_oracle(oracle: Any, existing_ids: set[str]) -> Any:
    """Drop from ONE part's oracle every principle-id NOT in `existing_ids` (the ids
    that resolve to a real file under `0_constitution/`). Preserves the oracle's shape —
    a list stays a list, a `{id: relation}` verdict dict stays a dict — so the plugin
    reads it exactly as authored, only existence-pruned. An unrecognised shape is
    returned untouched (the plugin fail-closes on it anyway)."""
    if isinstance(oracle, dict):
        return {pid: rel for pid, rel in oracle.items()
                if isinstance(pid, str) and pid.strip() in existing_ids}
    if isinstance(oracle, (list, tuple)):
        return [pid for pid in oracle
                if isinstance(pid, str) and pid.strip() in existing_ids]
    if isinstance(oracle, set):
        return {pid for pid in oracle
                if isinstance(pid, str) and pid.strip() in existing_ids}
    return oracle


def _inject_values_oracles(cfg: RoleConfig, plugins: dict[str, Any], payload: dict,
                           base: Path | None) -> dict:
    """Deterministically EXISTENCE-filter `payload["values_oracles"]` against
    `0_constitution/` before it reaches any values-grounded part's `validate`.

    Mirrors `_inject_read_records`: the engine — not the prompt stage — owns the oracle's
    existence half. Even if Stage 2.6 regressed and let a fabricated principle-id into
    the oracle, the downstream values `citations ⊆ oracle` check can only ever see ids
    that resolve to a real principle file, so the honesty guarantee (a body cannot forge
    a principle NOT in `0_constitution/`) is deterministic at the writer, not merely a
    prompt-stage grep. The RELEVANCE half (did check-decision judge the principle
    applicable) legitimately stays Stage 2.6's responsibility and is untouched here — the
    filter drops only on EXISTENCE.

    Archetype-agnostic AND per-instance: gated on the PART's `PartSpec.grounding ==
    "values"` (the SoT — never a plugin constant), so a DUAL-grounded kind (a stance,
    which can be `records` or `values` per instance) is selected only in its values-mode
    instances; a records-grounded stance rides the records path and is skipped here. A
    role with no values-grounded part is returned unchanged and the constitution is not
    walked; when it IS walked, the id-set is read ONCE per tick and reused across every
    part and id (no per-id re-walk). Any body-supplied `values_oracles` is already
    engine-authored by the runner; this only prunes it, never trusts a shape."""
    values_parts = [p for p in cfg.parts
                    if getattr(p, "grounding", "records") == "values"]
    if not values_parts:
        return payload
    raw = payload.get("values_oracles")
    if not isinstance(raw, dict):
        return payload
    existing_ids = constitution_principle_ids(base)  # walked ONCE per tick
    filtered = dict(raw)
    for part in values_parts:
        if part.id in raw:
            filtered[part.id] = _existence_filter_oracle(raw[part.id], existing_ids)
    out = dict(payload)
    out["values_oracles"] = filtered
    return out


# -----------------------------------------------------------------------------
# Delta routing (by delta.part → the addressed part's plugin)
# -----------------------------------------------------------------------------

def _route_deltas(
    cfg: RoleConfig, deltas: Any
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Group deltas by the part they address; collect unroutable ones.

    Returns `(by_part, unroutable)`. A delta whose `part` is missing / blank or
    names a part not in `config.parts[]` is unroutable (the caller surfaces it as
    a role-level rejection — surface, don't guess a target part). Every declared
    part gets an entry (possibly empty) so a part with no deltas this tick still
    ticks (clean-empty → watermark advance).
    """
    by_part: dict[str, list[dict]] = {p.id: [] for p in cfg.parts}
    unroutable: list[dict] = []
    if not isinstance(deltas, list):
        return by_part, unroutable
    for idx, delta in enumerate(deltas):
        pid = delta_part(delta)
        if pid is None or pid not in by_part:
            unroutable.append(
                {"ref": _unroutable_ref(delta, idx), "reason": "unroutable part"}
            )
            continue
        by_part[pid].append(delta)
    return by_part, unroutable


def _unroutable_ref(delta: Any, idx: int) -> str:
    if isinstance(delta, dict):
        for f in ("part", "provisional_key", "key"):
            v = delta.get(f)
            if isinstance(v, str) and v:
                return v
    return f"delta#{idx}"


# -----------------------------------------------------------------------------
# state.md sub-zone markers + multi-zone splice (portrait preserved)
# -----------------------------------------------------------------------------

_PORTRAIT_HINT = (
    "<!-- Portrait: describe this role's remit and stance in your own words here, "
    "above the markers. This zone is owner-owned; the engine never edits it. -->"
)


def _begin_marker(part_id: str) -> str:
    return (
        f"<!-- AUTO: role-state/{part_id} — maintained by roles_persist.py; "
        "do not hand-edit -->"
    )


def _end_marker(part_id: str) -> str:
    return f"<!-- END AUTO: role-state/{part_id} -->"


def _zone_block(part_id: str, body: str) -> str:
    """A full sub-zone block: BEGIN marker line, body (ends with \\n), END line."""
    if not body.endswith("\n"):
        body += "\n"
    return f"{_begin_marker(part_id)}\n{body}{_end_marker(part_id)}\n"


def _begin_offset(text: str, part_id: str) -> int | None:
    i = text.find(f"<!-- AUTO: role-state/{part_id} ")
    return i if i >= 0 else None


def _zone_span(text: str, part_id: str) -> tuple[int, int] | None:
    """(inner_start, end_marker_start) char offsets of a part's sub-zone, or None."""
    i = _begin_offset(text, part_id)
    if i is None:
        return None
    line_end = text.find("\n", i)
    if line_end < 0:
        return None
    inner_start = line_end + 1
    j = text.find(_end_marker(part_id), inner_start)
    if j < 0:
        return None
    return inner_start, j


def _zone_end_offset(text: str, part_id: str) -> int | None:
    """Char offset just past a part's END-marker line (incl. its newline), or None."""
    span = _zone_span(text, part_id)
    if span is None:
        return None
    _, end_start = span
    after = end_start + len(_end_marker(part_id))
    if after < len(text) and text[after] == "\n":
        after += 1
    return after


def _splice_zone(text: str, part_id: str, body: str) -> str:
    """Replace a present sub-zone's inner content with `body` (ends with \\n)."""
    span = _zone_span(text, part_id)
    if span is None:
        return text
    inner_start, end_start = span
    if not body.endswith("\n"):
        body += "\n"
    return text[:inner_start] + body + text[end_start:]


def _insert_zone(text: str, order: list[str], part_id: str, body: str) -> str:
    """Insert a NEW sub-zone for `part_id` in `config.parts[]` order.

    Placed just before the first later-ordered part that already has a zone, else
    just after the last earlier-ordered part's zone, else appended (a role with no
    other zones yet). Keeps the on-disk sub-zone order equal to the declared order.
    """
    block = _zone_block(part_id, body)
    try:
        my_idx = order.index(part_id)
    except ValueError:
        my_idx = len(order)
    for later in order[my_idx + 1:]:
        off = _begin_offset(text, later)
        if off is not None:
            return text[:off] + block + "\n" + text[off:]
    for earlier in reversed(order[:my_idx]):
        off = _zone_end_offset(text, earlier)
        if off is not None:
            return text[:off] + "\n" + block + text[off:]
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + "\n" + block


def _fresh_state_file(
    role_id: str, display: str, order: list[str], renders: dict[str, str]
) -> str:
    """Seed a new state.md — owner portrait ABOVE, one AUTO sub-zone per rendered
    part below, in `config.parts[]` order."""
    header = (
        f"---\nrole: {role_id}\ntype: role-state\n---\n\n"
        f"# {display} — role state\n\n"
        f"{_PORTRAIT_HINT}\n\n"
    )
    blocks = [_zone_block(pid, renders[pid]) for pid in order if pid in renders]
    return header + "\n".join(blocks) + ("\n" if blocks else "")


def _sync_state_md(
    role_id: str,
    display: str,
    order: list[str],
    renders: dict[str, str],
    prior_hashes: dict[str, Any],
    base: Path | None,
) -> dict[str, tuple[Any, str]]:
    """Render + splice every rendered part's sub-zone into state.md, once.

    `renders` maps each part id that should appear (its rendered body) — only the
    role's LIVE parts (a fresh, never-adopted part has no zone). Each part's
    sub-zone is guarded INDEPENDENTLY by its own stored hash: an owner edit to one
    zone flags that zone (`auto-zone-edited`) and preserves it, without blocking
    the splice of any other part.

    Returns `{part_id: (hash_to_store, flag)}`. `flag` ∈ {"", "noop",
    "auto-zone-edited", "markers-missing"}. On a flag the prior hash is returned
    unchanged, so the divergence re-surfaces every run until the owner reconciles.
    The owner portrait above the markers is preserved verbatim.
    """
    path = _state_path(role_id, base)
    ordered = [pid for pid in order if pid in renders]
    results: dict[str, tuple[Any, str]] = {}

    if not path.exists():
        text = _fresh_state_file(role_id, display, order, renders)
        _atomic_write_text(path, text)
        for pid in ordered:
            results[pid] = (role_state_hash.hash_inner(renders[pid]), "")
        return results

    on_disk = path.read_text(encoding="utf-8")
    text = on_disk
    for pid in ordered:
        body = renders[pid]
        if not body.endswith("\n"):
            body += "\n"
        predicted = role_state_hash.hash_inner(body)
        prior = prior_hashes.get(pid)
        try:
            current = role_state_hash.hash_part_zone(on_disk, pid)
            present = True
        except role_state_hash.RoleStateHashError:
            current = None
            present = False

        if isinstance(prior, str) and prior:
            # This part was rendered before → its owner-edit guard is armed.
            if not present:
                results[pid] = (prior, "markers-missing")
                continue
            if current != prior:
                results[pid] = (prior, "auto-zone-edited")
                continue
            if predicted == prior:
                results[pid] = (prior, "noop")
                continue

        if present:
            text = _splice_zone(text, pid, body)
        else:
            text = _insert_zone(text, order, pid, body)
        results[pid] = (predicted, "")

    # Only touch the file when a splice / insert actually changed it (every splice
    # normally does; a progress whose render is byte-identical, e.g. an advance
    # that touches no rendered field, leaves it unchanged — don't rewrite then).
    if text != on_disk:
        _atomic_write_text(path, text)
    return results


# -----------------------------------------------------------------------------
# Key minter that records mint order (for decision-log attribution)
# -----------------------------------------------------------------------------

class _RecordingMinter:
    """Wraps a `KeyMinter`, recording every minted key in mint order so the
    decision log can attribute minted keys to their originating delta without
    re-implementing persist's mint values (SoT stays in the plugin)."""

    def __init__(self, inner: KeyMinter) -> None:
        self._inner = inner
        self.minted: list[str] = []

    def mint(self) -> str:
        key = self._inner.mint()
        self.minted.append(key)
        return key

    def peek(self) -> str:
        return self._inner.peek()


# -----------------------------------------------------------------------------
# Config auto-pause (role-level, best-effort; Archive-Contract reason inline)
# -----------------------------------------------------------------------------

def _auto_pause_config(role_id: str, part_id: str, base: Path | None) -> bool:
    """Flip a top-level `status: active` → `status: paused` in config.yml with an
    inline Archive-Contract reason, preserving everything else.

    Role-level (a role's config has one status); the offending part is named in
    the reason. Returns True when flipped, False when there was no top-level active
    status to flip (already paused / unusual layout) — idempotent.
    """
    path = _config_path(role_id, base)
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    reason = (
        f"  # auto-paused {today_iso()}: part '{part_id}' had "
        f"{AUTO_PAUSE_THRESHOLD} consecutive validator rejects"
    )
    out: list[str] = []
    flipped = False
    for line in text.splitlines():
        if not flipped and line.startswith("status:"):
            code = line[len("status:"):].split("#", 1)[0].strip()
            if code == "active":
                out.append(f"status: paused{reason}")
                flipped = True
                continue
        out.append(line)
    if not flipped:
        return False
    trailing = "\n" if text.endswith("\n") else ""
    _atomic_write_text(path, "\n".join(out) + trailing)
    return True


# -----------------------------------------------------------------------------
# CLARIFICATION signal builders
# -----------------------------------------------------------------------------

def _cold_start_signal(
    role_id: str, staged: list[tuple[str, list[str]]]
) -> ClarificationSignal:
    """Role-level cold-start clarification aggregating every pending part.

    `staged` is `[(part_id, [titles])]` across the parts currently frozen. Subject
    is the role id (one open block per role), so a re-tick re-surfacing the frozen
    draft(s) dedups to the same block.
    """
    lines: list[str] = []
    total = 0
    for pid, titles in staged:
        total += len(titles)
        listed = ", ".join(f"'{t}'" for t in titles) if titles else "no items"
        lines.append(f"part '{pid}' ({len(titles)}): {listed}")
    detail = "; ".join(lines) if lines else "no items"
    return ClarificationSignal(
        ctype="role-cold-start",
        subject=role_id,
        context=(
            f"First tick(s) over an empty part for role {role_id}. The frozen "
            f"draft ({detail}) is staged and is NOT live. Ticks before approval "
            "re-surface the same frozen draft(s) and write nothing — records "
            "arriving meanwhile stay un-seen until the first tick after approval "
            "reviews them. Approve to adopt every pending part's draft live."
        ),
        source=f"roles cold-start for {role_id}",
        suggested_action=(
            f"Review the frozen draft(s), then run "
            f"`python3 roles_persist.py --role {role_id} --approve-coldstart` to "
            "adopt them, or dismiss to discard."
        ),
        action_taken=(
            "Draft(s) staged (frozen); not live; watermark(s) not advanced."
        ),
        confidence_tier="surfaced",
    )


def _unroutable_signal(
    role_id: str, cfg: RoleConfig, unroutable: list[dict]
) -> ClarificationSignal:
    """Role-level clarification for deltas addressing a part the role does not have.

    Subject is the role id (one open block per role, deduped). Names the offending
    refs and the role's actual part ids so the owner can align the body / config.
    """
    refs = ", ".join(
        str(u.get("ref")) for u in unroutable[:8] if isinstance(u, dict)
    ) or "unnamed"
    valid_parts = ", ".join(cfg.part_ids) or "none"
    return ClarificationSignal(
        ctype="role-unroutable",
        subject=role_id,
        context=(
            f"{len(unroutable)} delta(s) this tick addressed a part the role does "
            f"not have and were dropped (refs: {refs}). The role's parts are: "
            f"{valid_parts}. A persistent mismatch usually means the tick body used "
            "a stale or renamed part id, so its work silently fails every tick — "
            "surfaced here so it is fixed rather than lost."
        ),
        source=f"roles tick for {role_id}",
        suggested_action=(
            "Check the tick body / structurer against the role's current part ids; "
            "if a part was renamed in config.yml, align the body (or restore the id)."
        ),
        action_taken=(
            f"{len(unroutable)} unroutable delta(s) dropped; nothing persisted for them."
        ),
        confidence_tier="surfaced",
    )


def _auto_paused_signal(
    role_id: str, part_id: str, paused_config: bool
) -> ClarificationSignal:
    config_note = (
        " Its config status was also flipped to `paused`."
        if paused_config
        else " Its config status could not be flipped automatically (indented / "
        "quoted / non-standard layout), but the per-part stop is authoritative on "
        "its own."
    )
    return ClarificationSignal(
        ctype="role-auto-paused",
        subject=part_subject(role_id, part_id),
        context=(
            f"Part '{part_id}' of role {role_id} produced {AUTO_PAUSE_THRESHOLD} "
            "consecutive validator rejections, so the engine wrote an authoritative "
            "auto-pause stop onto that part to halt the role re-failing unattended."
            f"{config_note} Investigate the tick body / remit before resuming — the "
            "role stays paused until the part's auto-pause stop is cleared."
        ),
        source=f"roles tick for {role_id} (part {part_id})",
        suggested_action=(
            "Inspect the recent rejected runs in log_roles.md, fix the tick body "
            "or remit, then clear the part's auto-pause stop to resume."
        ),
        action_taken=(
            f"Part '{part_id}' auto-paused after {AUTO_PAUSE_THRESHOLD} consecutive "
            "rejects: authoritative per-part stop written"
            + ("; config status flipped." if paused_config else "; config flip skipped.")
        ),
        confidence_tier="surfaced",
    )


def _schema_version_signal(
    role_id: str, part_id: str, prior_v: Any, current_v: Any, mode: str
) -> ClarificationSignal:
    scoped = part_subject(role_id, part_id)
    if mode == "future":
        context = (
            f"Part '{part_id}' of role {role_id} is schema version {prior_v}, but "
            f"this engine understands version {current_v} — a NEWER part than this "
            "engine can safely read. The tick was REFUSED: nothing was processed, "
            "validated or written, to avoid corrupting a shape this engine does not "
            "know. Update the engine (e.g. `/ztn:update`), then the tick resumes."
        )
        suggested_action = (
            f"Update the ZTN engine to a build that supports part schema v{prior_v}; "
            "do not hand-edit the part down a version."
        )
        action_taken = (
            "Tick refused; part left untouched (its version is ahead of the engine)."
        )
    else:  # degraded
        context = (
            f"Part '{part_id}' of role {role_id} is schema version {prior_v}, older "
            f"than this engine's version {current_v}, and no migration path is "
            "registered for that gap. The tick proceeds in DEGRADED mode — validated "
            "against the CURRENT schema best-effort — because the part could not be "
            "migrated forward first. Review whether the older part is still "
            "well-formed for the current engine."
        )
        suggested_action = (
            "Verify the part against the current schema, or provide a migration "
            f"from v{prior_v} to v{current_v} so it upgrades cleanly."
        )
        action_taken = (
            "Proceeded in degraded mode (no migration path registered); validated "
            "against the current schema."
        )
    return ClarificationSignal(
        ctype="role-schema-version",
        subject=scoped,
        context=context,
        source=f"roles tick for {role_id} (part {part_id})",
        suggested_action=suggested_action,
        action_taken=action_taken,
        confidence_tier="surfaced",
    )


def _emit(signal: ClarificationSignal, base: Path | None) -> bool:
    return emit_clarification_signal(signal, base=base)


def _emit_pending(signal: ClarificationSignal, base: Path | None) -> bool:
    """Emit a HOLD's clarification and report it pending regardless of dedup.

    A role held by an already-open block is STILL blocked awaiting the owner, so a
    digest reading `roles-runs.jsonl` must see it counted (minor #4). Returns True
    whenever the signal carries a ctype. Use only on block-awaiting-owner paths
    (churn hold, identity hold, cold-start re-surface).
    """
    if not getattr(signal, "ctype", None):
        return False
    _emit(signal, base)
    return True


# -----------------------------------------------------------------------------
# Schema-version tolerance (migrate-before-validate; §6 / B1) — per part
# -----------------------------------------------------------------------------

# Single-step schema-version migrations, keyed `(from_version, to_version)`; each
# value is a pure `migrate(state) -> state`. EMPTY today — only v1 exists, so no
# migration is authored (the "build the discipline, author no migration" posture).
# The seam is real: when a v2 part shape lands, register the `(1, 2)` step and
# `migrate_part` carries friends' v1 states forward on their first post-update
# tick, BEFORE the archetype validator ever sees them. Do NOT pre-author a
# speculative step (anti-speculation §0.6).
MIGRATIONS: dict[tuple[int, int], Any] = {}


def migrate_part(state: dict, from_v: int, to_v: int) -> dict | None:
    """Migrate a part state up from `from_v` to `to_v`, or None when no path exists.

    Walks single-step migrations (v(n) → v(n+1)); returns the migrated state (with
    `version` stamped to `to_v`) on a COMPLETE path, or None the moment any step is
    missing. On None the caller proceeds in DEGRADED mode. Pure, no I/O, does not
    mutate the input.
    """
    if from_v >= to_v:
        return state
    cur = copy.deepcopy(state)
    v = from_v
    while v < to_v:
        step = MIGRATIONS.get((v, v + 1))
        if step is None:
            return None
        cur = step(cur)
        v += 1
    cur["version"] = to_v
    return cur


def _archetype_version(plugin) -> Any:
    """The schema version the loaded archetype currently WRITES (its fresh seed).

    Read generically through the seam. A plugin whose fresh_state omits / mis-types
    `version` yields None → the gate treats the comparison as indeterminate.
    """
    try:
        return plugin.fresh_state().get("version")
    except Exception:  # noqa: BLE001 — a plugin probe must never crash the tick
        return None


# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------

def _summary(
    role_id: str,
    outcome: str,
    run_status: str,
    counts: dict,
    clarifications: list[str],
    parts: dict | None = None,
    consecutive_rejects: int = 0,
    exit_code: int = 0,
) -> dict:
    return {
        "role_id": role_id,
        "outcome": outcome,
        "run_status": run_status,
        "counts": counts,
        "clarifications": clarifications,
        "parts": parts or {},
        "consecutive_rejects": consecutive_rejects,
        "exit": exit_code,
    }


def _sum_counts(items: list[dict]) -> dict:
    total = make_run_counts()
    for c in items:
        for k in total:
            total[k] += int((c or {}).get(k, 0))
    return total


# -----------------------------------------------------------------------------
# Per-part processing — returns a neutral result the orchestrator writes
# -----------------------------------------------------------------------------

@dataclass
class _PartResult:
    """The outcome of processing ONE part this tick — computed in memory; the
    orchestrator performs the writes (state.md sync needs every part's new state
    first, so no part writes state.md alone)."""
    part_id: str
    outcome: str  # staged|resurfaced|progress|empty|held|rejected|paused
    counts: dict
    new_state: dict | None            # None → do not write this part's json
    decisions: list[dict] = field(default_factory=list)
    clar_signals: list[ClarificationSignal] = field(default_factory=list)
    clar_pending: bool = False        # emit via _emit_pending (held paths)
    consecutive_rejects: int = 0
    staged_titles: list[str] | None = None   # for role-level cold-start aggregation
    log_line: str = ""

    @property
    def is_progress(self) -> bool:
        return self.outcome == "progress"


def _process_part(
    role_id: str,
    part: PartSpec,
    plugin,
    prior: dict,
    part_deltas: list[dict],
    read_records: list[str],
    readings: dict | None = None,
    values_oracle: Any = None,
) -> _PartResult:
    """Validate + resolve one part's deltas into a `_PartResult` (no I/O).

    Control paths per part: pending staging → re-surface; fresh →
    cold-start-stage / reject / benign-empty; established → churn-hold / reject /
    identity-hold / progress.

    A part with NO deltas addressed to it this tick is left UNTOUCHED (outcome
    "empty", no write): a composite tick addresses parts explicitly, so silence for
    a part is "not this part's turn", not "reviewed and found nothing".
    `seen_watermark` therefore advances only on
    real progress; it never drives activation (cadence reads roles-runs.jsonl), so
    a frozen watermark on an idle part is honest, not a re-fire risk.

    `readings` (the metric-readings lane) and `values_oracle` (this part's slice of the
    values-grounding oracle) reach the plugin's `validate` through the per-part payload
    alongside `read_records`. A plugin that needs neither ignores them; a metrics part
    reads `readings`; a VALUES-grounded stance reads `values_oracle` (an absent oracle →
    the plugin fail-closes: no oracle = no grounding), while a RECORDS-grounded stance
    ignores `values_oracle` (which is None for it, since `_inject_values_oracles` only
    creates entries for values parts) and grounds in `read_records` like any records kind.
    The `values_oracle` handed here has ALREADY been existence-filtered against
    `0_constitution/` by `_inject_values_oracles` (the writer owns the EXISTENCE half —
    every id resolves to a real principle file), so the plugin's values `citations ⊆
    oracle` check is a pure membership test over ids the engine deterministically verified
    exist; RELEVANCE stays the prompt-stage Stage 2.6 responsibility.
    """
    pid = part.id

    # Pending frozen draft → re-surface only; write nothing (§1.6 / §11.7).
    if _has_staging(prior):
        staging = prior.get("staging") or {}
        titles = plugin.content_summary(staging)
        return _PartResult(
            part_id=pid, outcome="resurfaced", counts=make_run_counts(),
            new_state=None, staged_titles=titles,
            log_line=f"part '{pid}': cold-start pending — re-surfaced; nothing written",
        )

    part_payload = {
        "role_id": role_id, "read_records": read_records, "deltas": part_deltas,
        "readings": readings if isinstance(readings, dict) else {},
        "values_oracle": values_oracle,
    }
    result = plugin.validate(prior, part_payload)
    fresh = _part_is_fresh(prior, part.grounding, plugin)

    if not result.ok:
        # A churn hold (plugin clarifications) vs a genuine reject.
        if result.clarifications:
            return _held(role_id, pid, prior, result.clarifications)
        return _reject(role_id, pid, prior, result.rejections)

    res = _process_approved(role_id, pid, plugin, prior, result, read_records, fresh)
    # ok=True clarifications — e.g. an owner-confirm registry's `role-owner-confirm`
    # proposals (uncited owner-facts the role may never auto-write) — are surfaced
    # alongside whatever the approved deltas did, never dropped.
    if result.clarifications:
        res.clar_signals = list(res.clar_signals) + list(result.clarifications)
    return res


def _process_approved(
    role_id: str, pid: str, plugin, prior: dict, result, read_records: list[str],
    fresh: bool,
) -> _PartResult:
    """The ok=True path: stage a fresh draft, or route an established part's approved
    deltas through identity → persist. Split from `_process_part` so the validator's
    ok=True clarifications can ride out on the returned result."""
    approved = list(result.approved_deltas)
    rejections = result.rejections

    if fresh:
        # On a fresh part every approved delta is content-producing (a plugin's
        # validate rejects any mutating op that needs an existing target), so the
        # whole approved set is the draft the cold-start freezes.
        if approved:
            return _stage(role_id, pid, plugin, prior, approved)
        if rejections:
            return _reject(role_id, pid, prior, rejections)
        # Benign empty tick over a fresh part: write nothing, stay cold-start-armed.
        return _PartResult(
            part_id=pid, outcome="empty", counts=make_run_counts(),
            new_state=None,
            log_line=f"part '{pid}': empty tick over a fresh part — cold-start armed",
        )

    # Established part with NO deltas addressed to it → untouched (no write).
    if not approved and not rejections:
        return _PartResult(
            part_id=pid, outcome="empty", counts=make_run_counts(), new_state=None,
            log_line=f"part '{pid}': no deltas this tick — untouched",
        )

    # Established part with work to do. Identity routing is the plugin's call:
    # a ledger routes unanchored adds anchor-else-HITL (sourcing its own
    # identity_strictness from prior state); a narrative passes through. The writer
    # never reads a plugin-owned tunable — it hands the plugin the whole prior state.
    kept, id_signals = plugin.gate_identity(role_id, pid, prior, approved)
    did_persist = bool(kept)
    held = bool(id_signals) and not did_persist

    if did_persist:
        return _progress(
            role_id, pid, plugin, prior, kept, id_signals, rejections, read_records
        )
    if held:
        return _PartResult(
            part_id=pid, outcome="held", counts=make_run_counts(),
            new_state=None, clar_signals=id_signals, clar_pending=True,
            consecutive_rejects=int(prior.get("consecutive_rejects") or 0),
            log_line=(f"part '{pid}': identity hold — all new items unanchored "
                      "under strict identity; nothing persisted"),
        )
    return _reject(role_id, pid, prior, rejections)


def _stage(role_id: str, pid: str, plugin, prior: dict, content_deltas: list[dict]) -> _PartResult:
    """Freeze a fresh part's first draft into `staging` (not live); watermark stays
    None; contributes to the role-level cold-start clarification (§1.6).

    The plugin owns the draft shape: `content_view` projects the just-persisted
    candidate to its content-only fields, which are spread into `staging`
    (`content_summary` labels them). The generic envelope never enters the draft."""
    minter = KeyMinter.for_part(plugin, prior)
    staged_state = plugin.persist(prior, content_deltas, minter)
    content = plugin.content_view(staged_state)
    new_state = copy.deepcopy(prior)
    new_state["staging"] = {"drafted_at": now_iso_utc(), **content}
    new_state["consecutive_rejects"] = 0
    titles = plugin.content_summary(new_state["staging"])
    return _PartResult(
        part_id=pid, outcome="staged",
        counts=make_run_counts(added=len(titles)),
        new_state=new_state, staged_titles=titles,
        log_line=f"part '{pid}': cold-start staged — {len(titles)} unit(s) frozen",
    )


def _reject(role_id: str, pid: str, prior: dict, rejections: tuple) -> _PartResult:
    """A no-progress validation rejection: bump the part's reject counter,
    auto-pause on the 3rd (§1.5). Nothing from the payload is persisted."""
    counter = int(prior.get("consecutive_rejects") or 0) + 1
    new_state = copy.deepcopy(prior)
    new_state["consecutive_rejects"] = counter
    reasons = "; ".join(
        str(r.get("reason")) for r in rejections if isinstance(r, dict)
    ) or "validation failed"

    if counter >= AUTO_PAUSE_THRESHOLD:
        new_state["status"] = "paused"
        new_state["paused_reason"] = (
            f"auto-paused {today_iso()}: {AUTO_PAUSE_THRESHOLD} consecutive "
            f"validator rejects (part '{pid}')"
        )
        return _PartResult(
            part_id=pid, outcome="paused",
            counts=make_run_counts(rejected=len(rejections)),
            new_state=new_state, consecutive_rejects=counter,
            # The auto-paused signal + config flip are role-level side effects the
            # orchestrator applies (config is one file); marker carried via outcome.
            log_line=(f"part '{pid}': rejected ({counter}/{AUTO_PAUSE_THRESHOLD}): "
                      f"{reasons}; auto-paused"),
        )
    return _PartResult(
        part_id=pid, outcome="rejected",
        counts=make_run_counts(rejected=len(rejections)),
        new_state=new_state, consecutive_rejects=counter,
        log_line=f"part '{pid}': rejected ({counter}/{AUTO_PAUSE_THRESHOLD}): {reasons}",
    )


def _held(role_id: str, pid: str, prior: dict, clarifications: tuple) -> _PartResult:
    """A churn-guard hold from the plugin: surface (part-scoped), persist nothing,
    leave the reject counter untouched (a hold is not a failure)."""
    scoped = [
        dataclasses.replace(sig, subject=part_subject(role_id, pid))
        for sig in clarifications
    ]
    return _PartResult(
        part_id=pid, outcome="held", counts=make_run_counts(),
        new_state=None, clar_signals=scoped, clar_pending=True,
        consecutive_rejects=int(prior.get("consecutive_rejects") or 0),
        log_line=f"part '{pid}': churn-guard hold — nothing persisted; awaiting owner",
    )


def _progress(
    role_id: str,
    pid: str,
    plugin,
    prior: dict,
    kept: list[dict],
    id_signals: list[ClarificationSignal],
    rejections: tuple,
    read_records: list[str],
) -> _PartResult:
    """Forward-progress: persist kept deltas, advance the watermark, reset the
    reject counter. state.md sync + json write are done by the orchestrator."""
    minter = _RecordingMinter(KeyMinter.for_part(plugin, prior))
    new_state = plugin.persist(prior, kept, minter)
    new_state["consecutive_rejects"] = 0
    # Per-kind forward watermark: advance over `read_records ∪ consumed_records`, not
    # `read_records` alone. A records kind's consumed stems are a subset of what it read
    # (grounding requires it) and never exceed the prior watermark, so the union is a
    # no-op → byte-identical. A values kind (a stance) consumes no records, so the union
    # is just `read_records`; where a part reads no records the union degenerates to its
    # own consumed units (empty for a stance → watermark stays put, "always re-examine"),
    # so the path never breaks on a missing records corpus.
    consumed = list(plugin.consumed_records(new_state))
    new_state["seen_watermark"] = _advance_watermark(
        prior.get("seen_watermark"), read_records + consumed
    )
    ts = now_iso_utc()
    decisions = plugin.build_decisions(
        kept, minter.minted, prior, role_id, pid, "tick", ts
    )
    # The plugin owns its op vocabulary → it splits the run counts (the writer never
    # names a concrete op like "add"): a ledger counts adds vs mutations, a
    # narrative reports (0, N).
    added, advanced = plugin.delta_counts(kept)
    return _PartResult(
        part_id=pid, outcome="progress",
        counts=make_run_counts(added=added, advanced=advanced, rejected=len(rejections)),
        new_state=new_state, decisions=decisions,
        clar_signals=list(id_signals), clar_pending=False,
        consecutive_rejects=0,
        log_line=(f"part '{pid}': persisted {added} added, {advanced} advanced; "
                  f"{len(rejections)} rejected; {len(id_signals)} identity hold(s)"),
    )


# -----------------------------------------------------------------------------
# Run + log writers
# -----------------------------------------------------------------------------

def _write_run(
    role_id: str,
    run_at: str,
    status: str,
    counts: dict,
    log_lines: list[str],
    base: Path | None,
) -> None:
    append_run(
        RunRecord(role_id=role_id, run_at=run_at, status=status, hook="tick",
                  counts=counts),
        base=base,
    )
    header = [f"**{role_id}** — {status}"]
    append_roles_log(format_run_log_section(run_at, header + log_lines), base=base)


# -----------------------------------------------------------------------------
# Cold-start approval (role-level — adopts every pending part at once)
# -----------------------------------------------------------------------------

def _approve_coldstart(
    role_id: str,
    cfg: RoleConfig,
    prior_states: dict[str, dict],
    plugins: dict[str, Any],
    run_at: str,
    base: Path | None,
) -> dict:
    """Adopt every part with a pending frozen draft live; advance each adopted
    part's watermark over the ADOPTED items' provenance ONLY (§11.7)."""
    adopted: list[str] = []
    new_states: dict[str, dict] = {}
    decisions: list[dict] = []
    ts = now_iso_utc()

    for part in cfg.parts:
        prior = prior_states[part.id]
        plugin = plugins[part.id]
        staging = prior.get("staging")
        if not isinstance(staging, dict):
            new_states[part.id] = prior
            continue
        # The plugin owns adoption: it merges the frozen draft's content into a
        # live state; the watermark advances over the ADOPTED content's stems only.
        ns = plugin.adopt_staging(prior, staging)
        ns["staging"] = None
        ns["consecutive_rejects"] = 0
        stems = [_record_stem(r) for r in plugin.consumed_records(ns)]
        ns["seen_watermark"] = _advance_watermark(prior.get("seen_watermark"), stems)
        new_states[part.id] = ns
        adopted.append(part.id)
        decisions.extend(plugin.cold_materialize_decisions(ns, role_id, part.id, ts))

    if not adopted:
        raise RoleError(
            f"no cold-start draft to approve for role {role_id!r} (no part is staged)"
        )

    display = cfg.name or role_id
    order = list(cfg.part_ids)
    renders, prior_hashes = _renders_for_live(cfg, plugins, new_states)
    sync = _sync_state_md(role_id, display, order, renders, prior_hashes, base)
    _apply_hashes(cfg, new_states, sync)

    for part in cfg.parts:
        if part.id in adopted:
            _atomic_write_text(part_state_path(role_id, part.id, base),
                               _dump_state(new_states[part.id]))
    _append_jsonl(_decisions_path(role_id, base), decisions)

    # Close the loop: the frozen draft(s) are adopted → answer the role-cold-start
    # ask. Best-effort — the adopt already landed, so a queue that cannot be read
    # must not fail the approval (it re-surfaces as an owner-visible open item).
    try:
        resolve_clarification(
            "role-cold-start", role_id, "adopted via approve-coldstart", base=base
        )
    except RoleError:
        pass

    counts = make_run_counts(
        added=sum(len(plugins[p].content_summary(new_states[p])) for p in adopted)
    )
    flags = [f"{p}:{sync[p][1]}" for p in adopted if p in sync and sync[p][1] in (
        "auto-zone-edited", "markers-missing")]
    log_lines = [f"cold-start approved: {len(adopted)} part(s) adopted live "
                 f"({', '.join(adopted)})"]
    if flags:
        log_lines.append(f"state.md NOT written for: {', '.join(flags)} — preserved")
    _write_run(role_id, run_at, "ok", counts, log_lines, base)

    parts_detail = {
        p: {"outcome": "cold-start-approved" if p in adopted else "unchanged",
            "state_flag": sync.get(p, (None, ""))[1]}
        for p in cfg.part_ids
    }
    return _summary(
        role_id, "cold-start-approved", "ok", counts, [], parts_detail,
    )


# -----------------------------------------------------------------------------
# state.md render helpers (which parts appear, and hash application)
# -----------------------------------------------------------------------------

def _renders_for_live(
    cfg: RoleConfig, plugins: dict[str, Any], new_states: dict[str, dict]
) -> tuple[dict[str, str], dict[str, Any]]:
    """Render every LIVE part (adopted — not fresh) + collect its prior stored hash.

    A fresh, never-adopted part has no sub-zone and is excluded. Returns
    `(renders, prior_hashes)` keyed by part id.
    """
    renders: dict[str, str] = {}
    prior_hashes: dict[str, Any] = {}
    for part in cfg.parts:
        state = new_states.get(part.id)
        # Skip a part with no LIVE content: fresh (never adopted) OR still holding a
        # frozen cold-start draft (staged, not yet adopted). A staged part's live
        # content is empty, so rendering it would leak an empty AUTO sub-zone into
        # state.md whenever a SIBLING progresses in the same tick — violating the
        # invariant that a not-yet-adopted part has no sub-zone. The approve path is
        # unaffected: an adopted part has `staging=None`, so it renders normally.
        if state is None or _part_is_fresh(state, part.grounding, plugins[part.id]) or _has_staging(state):
            continue
        body = plugins[part.id].render(state)
        if not isinstance(body, str):
            body = str(body)
        if not body.endswith("\n"):
            body += "\n"
        renders[part.id] = body
        prior_hashes[part.id] = state.get("state_auto_hash")
    return renders, prior_hashes


def _apply_hashes(
    cfg: RoleConfig, new_states: dict[str, dict], sync: dict[str, tuple[Any, str]]
) -> None:
    """Fold the synced sub-zone hashes back into each live part's state (skip the
    parts whose zone was edited / lost — keep their prior hash so it re-surfaces)."""
    for pid, (stored, flag) in sync.items():
        state = new_states.get(pid)
        if state is None:
            continue
        if flag not in ("auto-zone-edited", "markers-missing"):
            state["state_auto_hash"] = stored


# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Emission — the proactive voice (bounded, grounded, always-HITL)
# -----------------------------------------------------------------------------
# Two channels, both owner-facing CLARIFICATIONs (never a canonical write, never
# auto-applied): `role-nudge` (about the WORK in the zone) and `role-identity-suggest`
# (about the ROLE ITSELF — a suggested remit / persona change the owner applies via
# `/ztn:role:edit`). Both share the same safety spine below.

def _clean_nudge_text(raw: Any) -> str:
    """Sanitise free-form proactive text for use in a markdown header + a hidden
    `<!-- ... -->` dedup marker: collapse all whitespace (incl newlines, which would
    split the block) to single spaces and strip `-->` (which would close the comment
    early). Returns the cleaned text (may be empty — the caller drops an empty one)."""
    return " ".join(str(raw or "").split()).replace("-->", "").strip()


def _proactive_subject(role_id: str, clean: str) -> str:
    """The dedup subject `{role_id} · {summary} [{digest}]` — the digest is over the
    FULL cleaned text so two distinct items sharing a 60-char prefix stay distinct."""
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:8]
    return f"{role_id} · {clean[:60].strip() or 'note'} [{digest}]"


def _process_nudges(
    role_id: str, payload: dict, read_records: list[str], base: Path | None
) -> tuple[int, int]:
    """Surface a tick's proactive nudges as owner-facing `role-nudge` CLARIFICATIONs.

    A nudge is the role's proactive voice — the coach's push, «that workstream is
    blocking three others», «что горит». The body proposes them in an optional
    `payload["nudges"]` list of `{text, evidence[]}`; this turns each into an
    always-HITL owner-facing CLARIFICATION. It is deliberately NOT an Action-Hint:
    a role nudge NEVER auto-applies and writes no canonical note — the Action-Hint
    substrate is apply-oriented (every type has an applier), so an always-surface
    nudge belongs on the CLARIFICATION front door (which `/ztn:resolve-clarifications`
    also triages), tagged origin `role:{id}` = non-personal, never auto-merged.

    Safety rails (design §5): GROUNDED — a nudge with no evidence citing a real
    in-remit record (`read_records`) is DROPPED (a role never nudges on unreal
    ground). CUMULATIVE ANTI-SALAMI — a role holds at most `ROLE_NUDGE_OPEN_BUDGET`
    OPEN nudges; beyond it, new nudges DEFER rather than pile an unread backlog.
    DEDUP — the same nudge text does not re-pile across ticks (subject-keyed). ROUND
    -TRIP — the role writes no record; the outward effect is the owner SEEING the
    nudge, and any action becomes a record event only when the owner acts (no
    self-reinforcing loop; a role's own state.md is already outside every role's
    queryable corpus, so self-wake is structurally impossible).

    Returns `(emitted, deferred)`.
    """
    raw = payload.get("nudges")
    if not isinstance(raw, list) or not raw:
        return 0, 0
    corpus = set(read_records)
    budget_left = max(0, ROLE_NUDGE_OPEN_BUDGET - count_open_role_nudges(role_id, base))
    emitted = 0
    deferred = 0
    for n in raw:
        if not isinstance(n, dict):
            continue
        clean = _clean_nudge_text(n.get("text"))
        if not clean:
            continue
        evidence = n.get("evidence")
        if not isinstance(evidence, (list, tuple)) or not evidence:
            continue  # ungrounded → dropped (no nudge without a real record)
        if ungrounded_refs(evidence, corpus):
            continue  # a citation not in the remit corpus → dropped
        subject = _proactive_subject(role_id, clean)
        # Anti-flip-flop: a nudge the owner already saw and closed does not re-nag.
        if clarification_seen_resolved("role-nudge", subject, base):
            continue
        if budget_left <= 0:
            deferred += 1
            continue  # cumulative budget exhausted → defer, don't pile
        wrote = emit_clarification(
            ctype="role-nudge",
            subject=subject,
            context=(
                f"{clean}  —  a proactive nudge from role {role_id} (origin "
                f"role:{role_id}: non-personal, always surfaced for you, never "
                "auto-applied). It writes nothing; it is here for you to act on or "
                f"dismiss. Grounded in: {', '.join(str(e) for e in evidence)}."
            ),
            source=f"roles tick for {role_id} (proactive nudge)",
            suggested_action="Act on the nudge, or dismiss it — nothing is written either way.",
            action_taken="Surfaced as a proactive nudge; no state written.",
            base=base,
        )
        if wrote:
            emitted += 1
            budget_left -= 1
        # A deduped nudge (already open) is already counted in the budget — no change.
    return emitted, deferred


def _process_identity_suggestion(
    role_id: str, payload: dict, read_records: list[str], base: Path | None
) -> int:
    """Surface a role's OWN-identity suggestion as a `role-identity-suggest`
    CLARIFICATION — the mechanism by which a role proposes a change to its remit /
    persona (owner-sovereign identity) WITHOUT ever self-editing it. The body
    proposes an optional `payload["identity_suggestion"]` = `{text, evidence[]}`;
    this surfaces it for the owner, who applies it via `/ztn:role:edit`.

    Same safety spine as a nudge — grounded-or-dropped, dedup, anti-flip-flop, never
    a canonical write, always HITL — but a single suggestion per tick (an identity
    change is rare) routed to `edit`, not an action. Returns 1 if emitted, else 0.
    """
    sug = payload.get("identity_suggestion")
    if not isinstance(sug, dict):
        return 0
    clean = _clean_nudge_text(sug.get("text"))
    if not clean:
        return 0
    evidence = sug.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return 0  # ungrounded → dropped
    if ungrounded_refs(evidence, set(read_records)):
        return 0
    subject = _proactive_subject(role_id, clean)
    if clarification_seen_resolved("role-identity-suggest", subject, base):
        return 0  # already seen + closed → don't re-nag
    wrote = emit_clarification(
        ctype="role-identity-suggest",
        subject=subject,
        context=(
            f"Role {role_id} suggests a change to its OWN identity (remit / persona): "
            f"{clean}  —  it never self-edits its identity; this is a proposal for you "
            "to apply or dismiss. "
            f"Grounded in: {', '.join(str(e) for e in evidence)}."
        ),
        source=f"roles tick for {role_id} (identity suggestion)",
        suggested_action=f"Apply via `/ztn:role:edit {role_id}` if you agree, or dismiss.",
        action_taken="Surfaced as an identity suggestion; the role's identity is unchanged.",
        base=base,
    )
    return 1 if wrote else 0


def run(
    role_id: str,
    payload: dict | None,
    approve_coldstart: bool = False,
    base: Path | None = None,
) -> dict:
    """Persist one role tick (or approve a cold-start). Returns a summary dict.

    The control boundary: it validates before it writes, holds / rejects rather
    than guessing, and is the ONLY function in the subsystem that mutates role
    state on disk. Deltas are routed per part; each part is gated by its own
    archetype validator.
    """
    run_at = now_iso_utc()
    cfg = load_role_config(role_id, base)
    # Integrity backstop (surface, don't decide): a part dropped from config while
    # its state sits on disk is stranded — surface it before doing anything else, so
    # it is caught even on a paused role or an approve tick.
    _surface_orphaned_parts(role_id, cfg, run_at, base)
    plugins = {p.id: import_archetype(p.kind) for p in cfg.parts}
    prior_states = {p.id: _load_part_state(role_id, p, base) for p in cfg.parts}

    # Schema-version gate (migrate-before-validate), FIRST + per part. A future
    # part refuses the WHOLE tick untouched; an older one migrates forward (or
    # drops to degraded mode). Applies to the approve path too.
    prior_states, degraded_signals, refusal = _apply_version_gates(
        role_id, cfg, plugins, prior_states, run_at, base
    )
    if refusal is not None:
        return refusal

    if approve_coldstart:
        return _approve_coldstart(role_id, cfg, prior_states, plugins, run_at, base)

    if payload is None or not isinstance(payload, dict):
        raise RoleError("a delta payload is required for a tick")
    hook = payload.get("hook") or "tick"
    if hook == "ask":
        raise RoleError("the 'ask' hook is read-only and does not persist state")

    # A paused role never ticks. The stop is authoritative from EITHER the config
    # status (owner-set) OR any part's engine-written auto-pause stop — checked
    # BEFORE validate and ABOVE the per-part staging branch, so a paused role
    # short-circuits without re-running any body deltas and cannot re-fail its way
    # back live, and a pending cold-start on a paused role writes nothing.
    if not cfg.is_active or any(_part_paused(s) for s in prior_states.values()):
        _write_run(role_id, run_at, "paused", make_run_counts(),
                   ["role is paused — tick refused"], base)
        return _summary(
            role_id, "paused-role", "paused", make_run_counts(), [],
            {p: {"outcome": "paused-role"} for p in cfg.part_ids},
            consecutive_rejects=max(
                (int(s.get("consecutive_rejects") or 0) for s in prior_states.values()),
                default=0),
        )

    # ENGINE-INJECT the grounding corpus + metric readings (both overwrite any
    # body-supplied value — the engine owns the grounding oracle and the numbers).
    payload = _inject_read_records(cfg, payload, base)
    payload = _inject_readings(cfg, plugins, payload, base)
    payload = _inject_values_oracles(cfg, plugins, payload, base)
    read_records = _read_records(payload)
    readings = payload.get("readings") if isinstance(payload.get("readings"), dict) else {}
    # The values-grounding oracle for each values-grounded part (a stance): a per-part
    # set of constitution principle-ids the part may cite. Its RELEVANCE half — which
    # principles check-decision judged applicable — is computed out-of-band by the
    # `ztn-roles` SKILL (a pure-Python writer cannot invoke `/ztn:check-decision`, and a
    # role must never call it in write mode — SDD §10 #8), which injects it as
    # `payload["values_oracles"]` keyed by part id. Its EXISTENCE half is OWNED HERE:
    # `_inject_values_oracles` above has already existence-filtered every id in that map
    # against `0_constitution/` (deterministic, no LLM), exactly as `_inject_read_records`
    # re-authors the records corpus — so a fabricated id cannot survive even if Stage 2.6
    # regressed, and the plugin's ⊆-check can only see ids that truly exist. Absent → the
    # part's plugin fail-closes (no oracle = no grounding).
    values_oracles = (payload.get("values_oracles")
                      if isinstance(payload.get("values_oracles"), dict) else {})

    by_part, unroutable = _route_deltas(cfg, payload.get("deltas"))

    results: list[_PartResult] = []
    for part in cfg.parts:
        results.append(_process_part(
            role_id, part, plugins[part.id], prior_states[part.id],
            by_part[part.id], read_records, readings, values_oracles.get(part.id),
        ))

    # Emission — the proactive voice. Role-level (not per-part): a bounded, grounded
    # nudge surfaced for the owner, never a canonical write. Gated OFF while the role
    # is still cold-starting (any part staged / re-surfaced this tick) — a role does
    # not speak proactively before the owner has adopted its first draft.
    cold_starting = any(r.outcome in ("staged", "resurfaced") for r in results)
    if cold_starting:
        nudge_stats = (0, 0)
        identity_emitted = 0
    else:
        nudge_stats = _process_nudges(role_id, payload, read_records, base)
        identity_emitted = _process_identity_suggestion(role_id, payload, read_records, base)

    return _finalize_tick(
        role_id, cfg, plugins, prior_states, results, unroutable,
        degraded_signals, nudge_stats, identity_emitted, run_at, base,
    )


def _finalize_tick(
    role_id: str,
    cfg: RoleConfig,
    plugins: dict[str, Any],
    prior_states: dict[str, dict],
    results: list[_PartResult],
    unroutable: list[dict],
    degraded_signals: list[ClarificationSignal],
    nudge_stats: tuple[int, int],
    identity_emitted: int,
    run_at: str,
    base: Path | None,
) -> dict:
    """Aggregate per-part results into one tick: sync state.md, write part jsons,
    append decisions, emit clarifications, write one run + log, return a summary."""
    by_id = {r.part_id: r for r in results}
    new_states = {
        pid: (by_id[pid].new_state if by_id[pid].new_state is not None
              else prior_states[pid])
        for pid in cfg.part_ids
    }

    any_progress = any(r.is_progress for r in results)

    # state.md sync FIRST (derived-then-record) so the per-part hash embeds into
    # the json below. Only when a part actually persisted new content this tick.
    if any_progress:
        display = cfg.name or role_id
        renders, prior_hashes = _renders_for_live(cfg, plugins, new_states)
        sync = _sync_state_md(role_id, display, list(cfg.part_ids),
                              renders, prior_hashes, base)
        _apply_hashes(cfg, new_states, sync)
    else:
        sync = {}

    # Persist each part's json (only parts that produced a new state this tick).
    for r in results:
        if r.new_state is not None:
            _atomic_write_text(part_state_path(role_id, r.part_id, base),
                               _dump_state(new_states[r.part_id]))

    # Decisions (append-only, already stamped with `part`).
    all_decisions = [row for r in results for row in r.decisions]
    _append_jsonl(_decisions_path(role_id, base), all_decisions)

    # Config auto-pause is a single role-level side effect: flip once for the first
    # part that hit the threshold this tick, and append its role-auto-paused signal.
    paused_parts = [r for r in results if r.outcome == "paused"]
    if paused_parts:
        first = paused_parts[0]
        flipped = _auto_pause_config(role_id, first.part_id, base)
        for r in paused_parts:
            r.clar_signals = list(r.clar_signals) + [
                _auto_paused_signal(role_id, r.part_id, flipped if r is first else False)
            ]

    # Emit clarifications: degraded schema-version signals, then per-part, then the
    # aggregated role-level cold-start. Count each (pending paths count even when
    # deduped, minor #4).
    clar_types: list[str] = []
    for sig in degraded_signals:
        if _emit(sig, base):
            clar_types.append(sig.ctype)

    for r in results:
        emit_fn = _emit_pending if r.clar_pending else _emit
        emitted = 0
        for sig in r.clar_signals:
            if emit_fn(sig, base):
                emitted += 1
                clar_types.append(sig.ctype)
        r.counts = dict(r.counts)
        r.counts["clarifications"] = emitted

    cold_start = [
        (r.part_id, r.staged_titles or [])
        for r in results if r.outcome in ("staged", "resurfaced")
    ]
    cold_emitted = 0
    if cold_start:
        if _emit_pending(_cold_start_signal(role_id, cold_start), base):
            cold_emitted = 1
            clar_types.append("role-cold-start")

    # Unroutable deltas (a body naming a `part` the role does not have) are a body /
    # config-drift bug that would otherwise vanish into a `counts.rejected` bump on
    # an `empty`-success run. SURFACE it: emit a role-unroutable CLARIFICATION so a
    # persistent orphan (e.g. a renamed part id) is actionable, not silent.
    unroutable_emitted = 0
    if unroutable:
        if _emit_pending(_unroutable_signal(role_id, cfg, unroutable), base):
            unroutable_emitted = 1
            clar_types.append("role-unroutable")

    nudge_emitted, nudge_deferred = nudge_stats
    if nudge_emitted:
        clar_types.append("role-nudge")
    if identity_emitted:
        clar_types.append("role-identity-suggest")

    counts = _sum_counts([r.counts for r in results])
    counts["clarifications"] += (
        cold_emitted + unroutable_emitted + nudge_emitted + identity_emitted
    )
    counts["rejected"] += len(unroutable)

    run_status = _role_run_status(results)
    outcome = _role_outcome(results)
    # A tick whose ONLY work was unroutable must NOT read as a clean `empty` success
    # (which would advance the cadence window and hide the dropped work). Degrade it
    # to `rejected` so it retries next due and shows as a failure, not a no-op.
    if unroutable and run_status == "empty":
        run_status = "rejected"
        outcome = "rejected"

    log_lines = [r.log_line for r in results if r.log_line]
    if unroutable:
        log_lines.append(f"{len(unroutable)} unroutable delta(s) rejected")
    if nudge_emitted or nudge_deferred or identity_emitted:
        parts_msg = f"{nudge_emitted} nudge(s) surfaced"
        if nudge_deferred:
            parts_msg += f", {nudge_deferred} deferred (anti-salami budget)"
        if identity_emitted:
            parts_msg += f", {identity_emitted} identity suggestion(s)"
        log_lines.append(f"proactive voice: {parts_msg}")
    _write_run(role_id, run_at, run_status, counts, log_lines, base)

    parts_detail = {
        r.part_id: {
            "outcome": r.outcome,
            "counts": r.counts,
            "state_flag": sync.get(r.part_id, (None, ""))[1],
            "consecutive_rejects": r.consecutive_rejects,
        }
        for r in results
    }
    return _summary(
        role_id, outcome, run_status, counts, _dedup(clar_types), parts_detail,
        consecutive_rejects=max((r.consecutive_rejects for r in results), default=0),
    )


def _role_run_status(results: list[_PartResult]) -> str:
    outcomes = {r.outcome for r in results}
    if "paused" in outcomes:
        return "paused"
    if outcomes & {"progress", "staged"}:
        return "ok"
    if outcomes & {"resurfaced", "held", "rejected"}:
        return "rejected"
    return "empty"


def _role_outcome(results: list[_PartResult]) -> str:
    outcomes = {r.outcome for r in results}
    for label, mapped in (
        ("paused", "paused"),
        ("progress", "progress"),
        ("staged", "cold-start-staged"),
        ("resurfaced", "cold-start-resurfaced"),
        ("held", "held"),
        ("rejected", "rejected"),
    ):
        if label in outcomes:
            return mapped
    return "empty"


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# -----------------------------------------------------------------------------
# Schema-version gate (per part; future refuses whole tick, past migrates/degrades)
# -----------------------------------------------------------------------------

def _apply_version_gates(
    role_id: str,
    cfg: RoleConfig,
    plugins: dict[str, Any],
    prior_states: dict[str, dict],
    run_at: str,
    base: Path | None,
) -> tuple[dict[str, dict], list[ClarificationSignal], dict | None]:
    """Migrate-before-validate schema tolerance across every part.

    Returns `(states, degraded_signals, refusal)`. A FUTURE part refuses the whole
    tick (writes an error run + a role-schema-version CLARIFICATION, returns a
    refusal summary). A PAST part migrates forward when a complete path exists,
    else its state is left as-is and a degraded `role-schema-version` signal is
    collected (emitted at tick finalisation).
    """
    states = dict(prior_states)
    degraded: list[ClarificationSignal] = []
    for part in cfg.parts:
        plugin = plugins[part.id]
        prior = states[part.id]
        current_v = _archetype_version(plugin)
        prior_v = prior.get("version")
        if not isinstance(prior_v, int) or not isinstance(current_v, int) or prior_v == current_v:
            continue
        if prior_v > current_v:
            emitted = 1 if _emit(
                _schema_version_signal(role_id, part.id, prior_v, current_v, "future"),
                base,
            ) else 0
            counts = make_run_counts(clarifications=emitted)
            _write_run(
                role_id, run_at, "error", counts,
                [f"schema-version refuse: part '{part.id}' v{prior_v} is newer than "
                 f"engine v{current_v} — tick not processed"],
                base,
            )
            refusal = _summary(
                role_id, "schema-version-future", "error", counts,
                ["role-schema-version"] if emitted else [],
                {part.id: {"outcome": "schema-version-future"}},
                consecutive_rejects=int(prior.get("consecutive_rejects") or 0),
                exit_code=0,
            )
            return states, degraded, refusal
        migrated = migrate_part(prior, prior_v, current_v)
        if migrated is not None:
            states[part.id] = migrated
        else:
            degraded.append(
                _schema_version_signal(role_id, part.id, prior_v, current_v, "degraded")
            )
    return states, degraded, None


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _load_payload(arg: str | None) -> dict | None:
    if arg is None:
        return None
    if arg == "-":
        text = sys.stdin.read()
    else:
        text = Path(arg).read_text(encoding="utf-8")
    if not text.strip():
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RoleError("delta payload must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, help="role id under _system/roles/<id>/")
    parser.add_argument(
        "--payload", default=None,
        help="delta-payload JSON path, or '-' for stdin (omit with --approve-coldstart)",
    )
    parser.add_argument(
        "--approve-coldstart", action="store_true",
        help="adopt every pending cold-start draft live and advance the watermarks",
    )
    parser.add_argument(
        "--base", default=None,
        help="zettelkasten base override (else ZTN_BASE / derived)",
    )
    args = parser.parse_args(argv)

    base = Path(args.base).resolve() if args.base else None

    try:
        payload = _load_payload(args.payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RoleError) as exc:
        summary = _summary(args.role, "error", "error", make_run_counts(), [],
                           exit_code=1)
        summary["error"] = f"cannot read payload: {exc}"
        json.dump(summary, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 1

    try:
        summary = run(args.role, payload, args.approve_coldstart, base)
    except (RoleConfigError, RoleArchetypeError, RoleError) as exc:
        # `ask` is read-only by contract: it never persists and never leaves a run
        # in the tick index. Genuine tick / cold-start errors are still recorded.
        _hook = payload.get("hook") if isinstance(payload, dict) else None
        if _hook != "ask":
            try:
                append_run(
                    RunRecord(role_id=args.role, run_at=now_iso_utc(), status="error",
                              hook="tick", counts=make_run_counts()),
                    base=base,
                )
            except Exception:  # noqa: BLE001 — logging the error must never mask it
                pass
        summary = _summary(args.role, "error", "error", make_run_counts(), [],
                           exit_code=1)
        summary["error"] = str(exc)
        json.dump(summary, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 1

    json.dump(summary, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return int(summary.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
