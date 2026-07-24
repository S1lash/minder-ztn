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
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import minder_query
import role_state_hash
import roles_act
import roles_budget
import roles_inbox
import roles_mandate
import roles_triggers
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
    ROLES_SUCCESS_STATUSES,
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
    is_role_authored_source,
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

def _is_self_authored_record(unit: dict, role_id: str) -> bool:
    """True when an in-remit unit is a record THIS role emitted. Excluded from the
    role's own grounding corpus (INV-27 no-self-feed). Matches BOTH the raw emission
    (`source: role:{id}`) AND the `/ztn:process`-derived record (whose `source:` is
    the processed path `…/roles/{id}--…`) via the shared `is_role_authored_source`
    matcher — so the emit→process→re-read loop is broken deterministically."""
    fm = unit.get("frontmatter_subset") if isinstance(unit, dict) else None
    src = fm.get("source") if isinstance(fm, dict) else None
    return is_role_authored_source(src, role_id)


def _inject_read_records(cfg: RoleConfig, payload: dict, base: Path | None) -> dict:
    """Overwrite `payload["read_records"]` with the deterministic `minder_query
    --list` stems of the role's remit (BUILD-CONTRACT §4 / §7).

    The engine — not the body — owns the grounding corpus: the body may cite only
    records the runner reports as in-remit. Returns a shallow copy with
    `read_records` replaced by the sorted bare-basename stems of every in-remit
    unit; a body-supplied `read_records` is ignored. A record THIS role emitted
    (`source: role:{id}`) is EXCLUDED (INV-27) — the load-bearing guard on the
    inbox door: a role can never ground a new fact on its own emission.
    """
    index = minder_query.list_index(cfg.remit, base=base)
    stems = sorted({
        normalize_record_ref(Path(unit["path"]).name)
        for unit in index.get("units", [])
        if isinstance(unit, dict) and isinstance(unit.get("path"), str)
        and not _is_self_authored_record(unit, cfg.id)
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


def _inbox_subject(role_id: str, clean: str) -> str:
    """A dedup subject for a firewall-gated emission (mirrors `_proactive_subject`)."""
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:8]
    return f"{role_id} inbox · {clean[:60].strip() or 'note'} [{digest}]"


def _cage_verified() -> bool:
    """True only when the owner has confirmed the no-FS body cage out of band
    (`ZTN_ROLES_CAGE_VERIFIED=1`) — the gate to relaxing the emission owner-confirm to
    firewall-only (INV-15). Env-based so no body / payload can forge it. Unset in PLAN 1
    → every emission stays owner-confirmed."""
    return os.environ.get("ZTN_ROLES_CAGE_VERIFIED") == "1"


def _autonomous_ack() -> bool:
    """True when the owner has explicitly accepted autonomous acting in the un-caged
    harness (`ZTN_ROLES_AUTONOMOUS_ACK=1`). This is the HONEST launch marker — distinct
    from `_cage_verified()`: it asserts owner CONSENT to autonomy (risk knowingly taken),
    not a verified sandbox. It unlocks in-tick execution (no per-act/emission confirm)
    for a role the owner DIALED `autonomy: autonomous`; an `advisory` role still stages
    regardless. Env-based so no body / payload can forge it. Unset → every act/emission
    stays owner-confirmed (the safe default)."""
    return os.environ.get("ZTN_ROLES_AUTONOMOUS_ACK") == "1"


def _load_tool_ctx(tool_ctx: Path | None) -> dict:
    """Read the per-tick TOOL STAGE ctx (or `{}`). Tolerant — an unreadable/corrupt
    ctx never crashes the writer (the tick still finalizes)."""
    if tool_ctx is None:
        return {}
    try:
        data = json.loads(Path(tool_ctx).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}


def _tool_activity_lines(ctx_data: dict) -> list[str]:
    """Log lines making a tool-using tick's activity + failures + external ingestion
    VISIBLE in its own `log_roles.md` block (§3.5 — «every decision recoverable»). A
    silent honest-degrade otherwise looks like a healthy tick, so the owner can't tell a
    tool broke. Empty when no tool ran."""
    counts = ctx_data.get("call_counts") or {}
    total = sum(v for v in counts.values() if isinstance(v, int))
    failures = [f for f in (ctx_data.get("failures") or []) if isinstance(f, dict)]
    lines: list[str] = []
    if total:
        msg = f"tools: {total} call(s)"
        if failures:
            msg += f", {len(failures)} degraded"
        lines.append(msg)
    for f in failures:
        lines.append(
            f"  tool {f.get('tool_id')}: {f.get('status')} — {f.get('reason')}")
    if ctx_data.get("ingested_external"):
        lines.append(
            "ingested external tool content — injection firewall active this tick")
    return lines


def _reauth_tool_ids(ctx_data: dict) -> list[str]:
    """Unique tool ids whose failure needs a human re-auth decision (INV-29) — the
    self-heal is exhausted, so a `role-tool-reauth` CLARIFICATION is surfaced."""
    seen: list[str] = []
    for f in (ctx_data.get("failures") or []):
        if isinstance(f, dict) and f.get("reauth") and f.get("tool_id") not in seen:
            seen.append(str(f.get("tool_id")))
    return seen


def _reauth_signal(role_id: str, tool_id: str, ctx_data: dict) -> ClarificationSignal:
    """Build the `role-tool-reauth` CLARIFICATION for a tool whose bounded self-heal
    could not recover (INV-29) — a HUMAN decision (re-auth / changed scope) is needed."""
    reason = ""
    for f in (ctx_data.get("failures") or []):
        if isinstance(f, dict) and f.get("tool_id") == tool_id and f.get("reauth"):
            reason = str(f.get("reason") or "")
            break
    return ClarificationSignal(
        ctype="role-tool-reauth",
        subject=f"{role_id} · tool {tool_id} needs re-auth",
        context=(
            f"Role {role_id}'s tool {tool_id} failed and the bounded self-heal (retry / "
            f"re-resolve secret / honest-degrade) could not recover: {reason}. A human "
            "decision is needed — re-auth the credential (re-run the concierge secret "
            "step) or adjust the tool's scope. The tick honest-degraded (skipped the "
            "tool, noted it) — it never fabricated a result."
        ),
        source=f"roles tick for {role_id} (tool self-heal exhausted)",
        suggested_action="Re-auth the credential or adjust scope, then the tool resumes.",
        action_taken="Skipped the tool this tick (honest-degrade); surfaced for re-auth.",
    )


def _resolve_firewall_flag(
    cfg: RoleConfig, payload: dict, tool_ctx: Path | None,
) -> bool:
    """Resolve the injection-firewall flag (INV-17) — ENGINE-authored, never the body.
    UNAMBIGUOUS: the ONLY trusted source is the engine-owned TOOL STAGE ctx; there is no
    payload-flag fallback (a body / SKILL heredoc could set it, so trusting it would be a
    forge vector). Two outcomes:

      1. **The tool ctx (the real belt).** The runner ALWAYS passes `--tool-ctx` (the
         per-tick TOOL STAGE ctx it owns); read `ingested_external` from IT — the body
         cannot forge it, exactly as `read_records` is re-authored from `--list`.
      2. **Fail-closed on any absence / corruption.** No ctx (or an unreadable one) → a
         TOOL-BEARING role is treated as INGESTING (HITL-gated — the safe direction); a
         tool-less role cannot ingest, so False. The payload's `ingested_external_tool`
         is IGNORED — the ctx is the sole authority, so `--tool-ctx` is mandatory on any
         tool/act tick to relax the firewall.
    """
    if tool_ctx is not None:
        try:
            ctx = json.loads(Path(tool_ctx).read_text(encoding="utf-8"))
            return bool(ctx.get("ingested_external", False))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            pass  # unreadable ctx → fail-closed below (never trust a payload flag)
    return any(p.tools for p in cfg.parts)  # fail-closed for a tool-bearing role


def _process_inbox_emissions(
    role_id: str, cfg: RoleConfig, payload: dict, read_records: list[str],
    base: Path | None, tool_ctx: Path | None = None,
) -> tuple[int, int, int]:
    """Emit a tick's inbox-door notes (CONTRACT §4.2, INV-4/6/11/17/20/27).

    The body proposes them in an optional `payload["inbox_emissions"]` list of
    `{text, evidence[], is_sensitive?}` — the same judgment as a nudge, but the
    addressee is the BASE, not the owner. Each becomes a human-phrased file under
    `_sources/inbox/roles/{id}--{date}-{hash}.md` (flat `flat-md`) that `/ztn:process`
    folds in like any source
    (propose/dispose — INV-6/11). Rails, in order:

      - OPT-IN (INV-4): a role emits only when `cfg.emit_inbox` is set.
      - GROUNDED: an emission whose evidence does not cite a real in-remit record
        (`read_records`, already self-feed-filtered — INV-27) is DROPPED.
      - EMISSION HITL — the deterministic in-remit-certainty gate. An emission is
        surfaced as a `role-emission-confirm` CLARIFICATION for the owner (never
        silently written to the base) whenever the engine cannot CERTIFY the note's
        free-form `text` stayed in-remit. Two triggers, OR-combined:
          · INJECTION FIREWALL (INV-17): the tick ingested EXTERNAL TOOL content
            (from the engine-owned TOOL STAGE ctx — `_resolve_firewall_flag`, never a
            payload flag) — a confused-deputy risk.
          · UN-CAGED BODY (INV-15 honesty): the tick body ran WITHOUT a verified
            no-FS cage (`payload["body_caged"]` is not true — the shipped honor-system
            runtime). An un-caged body could raw-read an out-of-remit note and
            paraphrase it into `text`, which — unlike `evidence` — is free-form and
            NOT corpus-checkable. So autonomous write requires BOTH no external
            ingestion AND a verified body cage; PLAN 1 ships no verified cage, so
            every emission is owner-confirmed (the leak is closed by construction on
            the WRITE side, independent of whether the body honoured its remit). The
            gate relaxes only when the cage is verified.
      - CUMULATIVE BUDGET (INV-20/28): the anti-salami ceiling on acts + inbox
        writes (`roles_budget`); past it, emissions DEFER (a `role-budget-exhausted`
        surfaces once) rather than pile.

    Returns `(emitted, deferred, gated)` — written / budget-deferred / HITL-gated.
    """
    if not cfg.emit_inbox:
        return 0, 0, 0
    raw = payload.get("inbox_emissions")
    if not isinstance(raw, list) or not raw:
        return 0, 0, 0
    corpus = set(read_records)
    ingested_external = _resolve_firewall_flag(cfg, payload, tool_ctx)
    # Two out-of-band env markers can relax the emission owner-confirm, both unforgeable by
    # a body/payload (a body / a regressed SKILL heredoc cannot set an env var — same trust
    # model as the secret master key / ZTN_DEV):
    #   - the VERIFIED no-FS cage (`ZTN_ROLES_CAGE_VERIFIED`) — the else-branch below relaxes
    #     to firewall-only (no ingestion + body_caged); absent it, that branch is ALWAYS HITL.
    #   - owner-accepted autonomy (`ZTN_ROLES_AUTONOMOUS_ACK`) on an `autonomous`-dialed role
    # relaxes the emission confirm too — an autonomous role feeds the base without nagging
    # (the owner consented to autonomy for THIS role). A role without an autonomous mandate
    # (advisory, or no mandate at all) keeps the safe owner-confirm default.
    if roles_mandate.autonomy_of(cfg.mandate) == "autonomous" and _autonomous_ack():
        hitl = False
    else:
        body_caged = bool(payload.get("body_caged", False)) and _cage_verified()
        hitl = ingested_external or not body_caged
    run_at = payload.get("run_at") or now_iso_utc()
    budget_state = roles_budget.load_budget(role_id, base)
    remaining = roles_budget.budget_remaining(budget_state)

    emitted = deferred = gated = 0
    budget_notified = False
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, (list, tuple)) or not evidence:
            continue  # ungrounded → dropped (a role never emits on unreal ground)
        if ungrounded_refs(evidence, corpus):
            continue  # a citation outside the in-remit corpus → dropped
        is_sensitive = bool(item.get("is_sensitive", False))

        if hitl:
            # HITL rather than auto-write — the engine cannot certify `text` stayed
            # in-remit. Reason is honest about which trigger fired.
            if ingested_external:
                why = ("this tick ALSO read an external tool (injection firewall) — an "
                       "emission derived from external content is owner-confirmed")
            else:
                why = ("this tick's body ran without a verified no-FS cage, so the "
                       "engine cannot certify the note stayed in your role's zone "
                       "(the honor-system runtime — INV-15)")
            subject = _inbox_subject(role_id, " ".join(text.split()))
            if clarification_seen_resolved("role-emission-confirm", subject, base):
                continue
            if emit_clarification(
                ctype="role-emission-confirm",
                subject=subject,
                context=(
                    f"Role {role_id} proposes writing this to your base's inbox, but "
                    f"{why} — so it is surfaced for your confirmation rather than "
                    f"written automatically. Proposed note: «{text[:400]}». Grounded "
                    f"in: {', '.join(str(e) for e in evidence)}."
                ),
                source=f"roles tick for {role_id} (inbox emission, owner-confirm)",
                suggested_action="Approve to let it become a base note, or discard it.",
                action_taken="Held for confirmation; nothing written to the base.",
                base=base,
            ):
                gated += 1
            continue

        if remaining <= 0:
            deferred += 1
            if not budget_notified:
                budget_notified = True
                subject = f"{role_id} inbox budget"
                emit_clarification(
                    ctype="role-budget-exhausted",
                    subject=subject,
                    context=(
                        f"Role {role_id} reached its cumulative inbox/act budget this "
                        "period; further emissions defer to the next period. Raise the "
                        "ceiling via /ztn:role:edit if it is legitimately busier."
                    ),
                    source=f"roles tick for {role_id} (budget)",
                    suggested_action="Leave as-is (they wait), or raise the ceiling.",
                    action_taken="Deferred the remaining emissions this period.",
                    base=base,
                )
            continue

        roles_inbox.write_emission(role_id, text, evidence, is_sensitive, run_at, base)
        roles_budget.record_writes(role_id, 1, base)
        remaining -= 1
        emitted += 1
    return emitted, deferred, gated


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


def _process_tool_request(
    role_id: str, payload: dict, read_records: list[str], base: Path | None
) -> int:
    """Surface a role's request for a NEW tool as a `role-tool-request` CLARIFICATION —
    a real colleague says «I'd do this better with access to X». The body proposes an
    optional `payload["tool_request_proposal"]` = `{text, evidence[]}` (what it wants +
    why, grounded in what it actually hit this tick); this surfaces it for the owner, who
    grants via `/ztn:role:edit` (adds the tool to a part's grant / wires a new tool).

    Same safety spine as an identity suggestion — grounded-or-dropped, dedup, always HITL,
    never a self-grant (a role can NEVER give itself a tool — INV-3): it only asks.
    Returns 1 if emitted, else 0."""
    req = payload.get("tool_request_proposal")
    if not isinstance(req, dict):
        return 0
    clean = _clean_nudge_text(req.get("text"))
    if not clean:
        return 0
    evidence = req.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        return 0  # ungrounded → dropped (a role can't ask on unreal ground)
    if ungrounded_refs(evidence, set(read_records)):
        return 0
    subject = _proactive_subject(role_id, clean)
    if clarification_seen_resolved("role-tool-request", subject, base):
        return 0  # already seen + closed → don't re-nag
    wrote = emit_clarification(
        ctype="role-tool-request",
        subject=subject,
        context=(
            f"Role {role_id} would do its job better with a tool it does not have: "
            f"{clean}  —  it is ASKING, never granting itself (a role can never give "
            "itself a tool — INV-3). If you agree, grant it via `/ztn:role:edit` (add the "
            "tool to the relevant part, or wire a new one). "
            f"Grounded in: {', '.join(str(e) for e in evidence)}."
        ),
        source=f"roles tick for {role_id} (tool request)",
        suggested_action=f"Grant via `/ztn:role:edit {role_id}` if you agree, or dismiss.",
        action_taken="Surfaced as a tool request; nothing granted — the role's tools are unchanged.",
        base=base,
    )
    return 1 if wrote else 0


# -----------------------------------------------------------------------------
# Act path (CONTRACT §6.2/§6.5, INV-16/28) — two-phase HITL: stage in the tick,
# execute on owner approval. The engine (`roles_act`) is transport-agnostic; the writer
# owns pending_acts I/O, secret resolution, mandate/HITL gating, budget, watermark, and
# the coupled inbox close-events. Transport is injectable (`exec_http`) for testability;
# in production it is `roles_tool_http.exec_tool` (Python-exec, secret injected in-
# process — INV-12; NEVER an mcp/skill act in the harness).
# -----------------------------------------------------------------------------

def _pending_acts_path(role_id: str, base: Path | None) -> Path:
    """The role's staged-acts store (its own home beside `triggers.json`/`budget.json`).
    Holds acts awaiting owner approval (`role-act-confirm`) with their TOCTOU baselines,
    the coupled inbox close-events, and the pending trigger watermarks."""
    return role_dir(role_id, base) / "pending_acts.json"


def _load_pending_acts(role_id: str, base: Path | None) -> dict:
    path = _pending_acts_path(role_id, base)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}


def _save_pending_acts(role_id: str, data: dict, base: Path | None) -> None:
    _atomic_write_text(_pending_acts_path(role_id, base),
                       json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _clear_pending_acts(role_id: str, base: Path | None) -> None:
    path = _pending_acts_path(role_id, base)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass  # best-effort — a stale pending file is re-derived, never data loss


def _act_transport():
    """The production act transport — `roles_tool_http.exec_tool` (Python-exec; the
    runner injects the resolved secret in-process, out of the LLM's sight — INV-12)."""
    import roles_tool_http
    return roles_tool_http.exec_tool


def _audit_act(role_id: str, tool_id: str, outcome, base: Path | None) -> None:
    """Append one act-outcome row to the shared tool audit (`roles-tool-audit.jsonl`) —
    symmetric with the read-tool audit, so every network act a role takes is
    reconstructable (§3.5). Records only the op/target/status/effect — NEVER a raw
    return, a body, or a secret (INV-10/12). Best-effort; an audit failure never masks
    the act."""
    try:
        import roles_tool_stage
        path = roles_tool_stage.tool_audit_path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "at": now_iso_utc(), "role_id": role_id, "kind": "act",
            "tool_id": tool_id, "op": outcome.op, "target_ref": outcome.target_ref,
            "status": outcome.status, "summary": outcome.effect or outcome.detail,
        }
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — observability must never break the act path
        pass


def _resolve_act_secret(cred_ref: str | None, base: Path | None) -> tuple[str | None, str | None]:
    """Resolve an act tool's `secret://` credential in memory (INV-12). (None, None) when
    no credential; (None, reason) on a resolve failure (honest-degrade — the act refuses,
    never writes with a missing token)."""
    if not cred_ref:
        return None, None
    try:
        import roles_secrets
        secret = roles_secrets.resolve_secret(cred_ref, base)
    except Exception as exc:  # noqa: BLE001 — SecretError / missing module → honest-degrade
        return None, f"credential {cred_ref} could not be resolved: {exc}"
    # An empty resolved secret is a fail-CLOSED case, not «no credential»: without it the
    # write would be attempted UNAUTHENTICATED (the http adapter only adds the header for a
    # truthy secret). Refuse rather than send an unauthenticated act (INV-12 posture).
    if not secret:
        return None, f"credential {cred_ref} resolved empty — refusing an unauthenticated act"
    return secret, None


def _coupled_emissions(payload: dict) -> list[dict]:
    """The tick's inbox close-events, coupled to the acts (emitted only on confirmed
    act success — §6.5). Unlike a standalone emission (`_process_inbox_emissions`, which
    requires in-remit grounding OR the firewall gate), a reconcile close-event is
    EXTERNAL-derived (it reports what the act did to the board), so it is NOT checked
    against the in-remit corpus — its HITL gate is the owner's act approval itself
    (`role-act-confirm`), which the owner sees before anything is written (INV-15/17).
    `evidence` is kept as the informational «grounded in» line for the owner's judgment,
    not a grounding bar. Only a non-empty `text` is required."""
    raw = payload.get("inbox_emissions")
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        ev = item.get("evidence")
        evidence = [str(e) for e in ev] if isinstance(ev, (list, tuple)) else []
        out.append({"text": text, "evidence": evidence,
                    "is_sensitive": bool(item.get("is_sensitive", False))})
    return out


def _stage_acts(
    role_id: str, cfg: RoleConfig, payload: dict, read_records: list[str],
    base: Path | None, tool_ctx: Path | None, pending_watermarks: dict,
    exec_http=None,
) -> dict:
    """Phase 1: validate the mandate + ground each act + capture the TOCTOU baseline
    (a READ, never a write), stage the acts + coupled inbox close-events + pending
    watermarks into `pending_acts.json`, and — for an HITL tick (the default: an advisory
    role, or an autonomous role with no consent marker) — emit ONE `role-act-confirm`.
    Executes NOTHING, advances no watermark (§6.5).

    When the tick is NON-HITL (`autonomy: autonomous` + the owner's consent marker
    `ZTN_ROLES_AUTONOMOUS_ACK`, or a future verified cage), `run()` auto-approves inline via
    `_execute_pending_acts` after parts persist. Returns a stats dict
    `{staged, refused, executed, skipped, drift, failed, hitl, refusals[]}`."""
    from roles_tools import get_tool
    exec_http = exec_http or _act_transport()
    raw = payload.get("acts")
    stats = {"staged": 0, "refused": 0, "executed": 0, "skipped": 0,
             "drift": 0, "failed": 0, "hitl": False, "pending_exists": False,
             "refusals": []}
    if cfg.mandate is None or not isinstance(raw, list) or not raw:
        return stats

    # Do NOT overwrite an un-approved pending set: if acts are already staged awaiting the
    # owner's `--approve-acts`, this re-tick must not silently swap what the owner is about
    # to approve (the external-state trigger re-fires every tick while the watermark is
    # held, so an unguarded re-stage would overwrite the shown set daily). Skip re-staging;
    # the existing pending stands — its TOCTOU baseline guards staleness at approval, and a
    # drift re-reconciles from fresh state. The watermark stays held (act_stats is a dict).
    if _load_pending_acts(role_id, base).get("acts"):
        stats["pending_exists"] = True
        return stats

    today = date.fromisoformat(today_iso())
    ingested_external = _resolve_firewall_flag(cfg, payload, tool_ctx)
    # The act gate keys on the env cage marker directly (`_cage_verified()`), NOT on the
    # payload `body_caged` flag the emission gate ANDs in (§_process_inbox_emissions). This
    # asymmetry is intentional, not a bug: an act is structured + already mandate/TOCTOU/
    # allowlist-gated, so the unforgeable env marker is a sufficient cage signal; a free-form
    # inbox emission (its `text` is not corpus-checkable) is held to the stricter
    # `body_caged AND env` bar. Both fail-closed today (env unset ⇒ both HITL).
    cage = _cage_verified()
    ack = _autonomous_ack()
    autonomy = roles_mandate.autonomy_of(cfg.mandate)

    staged_ops: list[dict] = []
    refusals: list[str] = []
    tick_hitl = False
    for raw_act in raw:
        op = roles_act.ActOperation.from_dict(raw_act)
        if op is None:
            refusals.append("malformed act delta")
            continue
        # Per-part grant (CONTRACT §1.1) — an act must name a REAL part of this role, and
        # its tool must be granted to THAT part. A tool granted to part A cannot be invoked
        # while acting as part B, and an act cannot be attributed to a part that does not
        # exist. Defence-in-depth beside the mandate (which names tool + surface): this
        # scopes the tool to the part that earned it, mirroring the read TOOL STAGE's
        # per-part grant-check — the body cannot borrow another part's hand.
        part_spec = next((p for p in cfg.parts if p.id == op.part), None)
        if part_spec is None:
            refusals.append(f"act names unknown part {op.part!r}")
            continue
        if op.tool not in part_spec.tools:
            refusals.append(f"tool {op.tool!r} is not granted to part {op.part!r}")
            continue
        # An act is EXTERNAL-driven (justified by the ephemeral tool read — INV-10), NOT
        # grounded against the in-remit record corpus: the gate is the MANDATE
        # (authorization) + TOCTOU (a real, unchanged target) + idempotency + the HITL
        # act-confirm (the owner sees it before any write) + the firewall — not a
        # record citation. `op.evidence`/`op.reason` document WHY for the owner's
        # judgment; they are informational, never a drop bar.
        surface, sreason = roles_mandate.resolve_surface(cfg.mandate, op.tool)
        if surface is None:
            refusals.append(sreason)
            continue
        decision = roles_mandate.authorize_act(cfg.mandate, op.tool, surface, today)
        if not decision.allowed:
            refusals.append(decision.reason)
            continue
        spec = get_tool(op.tool, base)
        if spec is None or not spec.is_act:
            refusals.append(f"tool {op.tool!r} is not an active act tool")
            continue
        secret, serr = _resolve_act_secret(spec.credential_ref, base)
        if serr is not None:
            refusals.append(serr)
            continue
        staged_op, stage_out = roles_act.stage_act(spec, surface, op, secret, exec_http)
        if not stage_out.ok:
            refusals.append(f"{op.op} {op.target_ref or ''}: {stage_out.detail}")
            continue
        hitl, _hreason = roles_mandate.act_is_hitl(decision, autonomy, ingested_external, cage, ack)
        tick_hitl = tick_hitl or hitl
        staged_ops.append({**staged_op.to_dict(), "surface": surface})

    stats["staged"] = len(staged_ops)
    stats["refused"] = len(refusals)
    stats["refusals"] = refusals
    if not staged_ops:
        # ALL acts refused (no live secret, expired/out-of-scope mandate, malformed) —
        # the role silently would not act. Surface it as a CLARIFICATION, not just a log
        # line, so the owner sees WHY the role's hands stopped and can fix it.
        if refusals:
            reauth = any("credential" in r or "resolved empty" in r or "expired" in r
                         for r in refusals)
            stats["refused_clar"] = "role-tool-reauth" if reauth else "role-act-failed"
            emit_clarification(
                ctype=stats["refused_clar"],
                subject=f"{role_id} · all {len(refusals)} proposed act(s) refused",
                context=(f"Role {role_id} wanted to act on its board but EVERY proposed "
                         f"act was refused, so nothing was staged and the role did not "
                         "act this tick. Reasons:\n"
                         + "\n".join(f"· {r}" for r in refusals[:20])
                         + ("\n\nA credential / mandate issue — re-auth via the concierge "
                            "or renew the mandate via /ztn:role:edit." if reauth else
                            "\n\nReview the role's mandate / act config.")),
                source=f"roles tick for {role_id} (act staging — all refused)",
                suggested_action="Fix the credential / mandate, then the role resumes acting.",
                action_taken="Nothing staged, nothing written; surfaced the refusals.",
                base=base)
        return stats

    stats["hitl"] = tick_hitl
    # The coupled close-events feed the BASE — gate them on the same opt-in every other
    # inbox write obeys (INV-4): a role with a mandate but `emit_inbox: false` acts on the
    # board but must NOT push anything into the owner's memory.
    coupled = _coupled_emissions(payload) if cfg.emit_inbox else []
    pending = {
        "staged_at": now_iso_utc(),
        "run_at": payload.get("run_at") or now_iso_utc(),
        "pending_watermarks": pending_watermarks or {},
        "acts": staged_ops,
        "inbox_emissions": coupled,
    }
    _save_pending_acts(role_id, pending, base)

    if tick_hitl:
        _emit_act_confirm(role_id, staged_ops, coupled, refusals, base)
    # NON-HITL (autonomous — the owner set `ZTN_ROLES_AUTONOMOUS_ACK`, or a future verified
    # cage): the acts are STAGED here but executed AFTER the tick persists its parts (§6.5
    # ordering: persist parts → execute act → advance watermark). The caller (`run`) runs
    # the autonomous execute post-finalize; `stats["hitl"]` False + `staged` > 0 is the
    # signal. Absent the marker `tick_hitl` is true and the acts wait for `--approve-acts`.
    return stats


def _emit_act_confirm(role_id: str, staged_ops: list[dict], coupled: list[dict],
                      refusals: list[str], base: Path | None) -> None:
    """Surface the staged acts for the owner's approval (`role-act-confirm`) — the
    harness HITL gate (INV-16/PLAN-2 §1). Shows the exact acts AND the coupled inbox
    close-events that will reach the base on approval (so the owner confirms BOTH the
    outward writes and what the base will learn), plus any acts refused this tick (so a
    dropped act — e.g. an expired mandate — is never invisible). Nothing is written to
    the external system until the owner runs `/ztn:roles --approve-acts {id}`."""
    lines = []
    for a in staged_ops:
        ref = a.get("target_ref")
        tgt = f"#{ref}" if ref else "(new)"
        lines.append(f"· {a.get('op')} {tgt}: {a.get('reason') or a.get('dedup_match') or ''}".strip())
    body = "Proposed acts:\n" + "\n".join(lines)
    if coupled:
        body += ("\n\nAnd these notes will be fed to your base (as close-events) on "
                 "success:\n" + "\n".join(f"· {e.get('text', '')}" for e in coupled))
    if refusals:
        body += ("\n\nAlso proposed but REFUSED this tick (not staged):\n"
                 + "\n".join(f"· {r}" for r in refusals))
    # Subject is the bare role id (one open block per role) — MUST match the three
    # `resolve_clarification("role-act-confirm", role_id, …)` calls on the approve-acts
    # paths, mirroring `_cold_start_signal`. The act count lives in the context/body, not
    # the subject; baking a per-tick count into the subject would (a) leave the block
    # unresolved after `--approve-acts` (subject mismatch) and (b) spawn a second block on
    # a re-tick with a different count instead of deduping.
    subject = role_id
    emit_clarification(
        ctype="role-act-confirm",
        subject=subject,
        context=(
            f"Role {role_id} reconciled its zone against an external board and proposes "
            f"{len(staged_ops)} act(s) — staged, NOT yet executed (in the harness every "
            "act is owner-confirmed, INV-16). The TOCTOU baseline is captured; on approval "
            "each act runs idempotently and is re-validated against drift immediately "
            "before the write. " + body + "\n\n"
            f"Approve with `/ztn:roles --approve-acts {role_id}` (executes them, then "
            "feeds the base the close-events + advances the watermark), or discard."
        ),
        source=f"roles tick for {role_id} (act staging)",
        suggested_action=f"Run `/ztn:roles --approve-acts {role_id}` to execute, or discard.",
        action_taken="Staged the act(s); nothing written to the external system yet.",
        base=base,
    )


def _execute_pending_acts(
    role_id: str, cfg: RoleConfig, base: Path | None, exec_http=None,
) -> dict:
    """Phase 2: execute the staged acts idempotently with a TOCTOU re-validate. On
    confirmed FULL success (§6.5): emit the coupled inbox close-events + advance the
    watermark + record the cumulative budget + clear the pending store. On ANY
    failure/drift: surface it, clear the pending store (avoid a stale-baseline loop —
    the next tick re-reconciles from fresh state), and advance NEITHER the inbox nor the
    watermark. Returns a stats dict."""
    from roles_tools import get_tool
    exec_http = exec_http or _act_transport()
    stats = {"executed": 0, "skipped": 0, "drift": 0, "failed": 0,
             "inbox_emitted": 0, "watermark_advanced": False, "budget_hit": False,
             "outcomes": []}
    pending = _load_pending_acts(role_id, base)
    acts = pending.get("acts") or []
    if not acts:
        return stats

    # Re-check the mandate at EXECUTE time (Phase 2), not only at stage: the mandate can
    # expire (or be revoked / re-pointed) in the stage→approve window, and a staged act
    # must not execute under a mandate that is no longer live (INV-16 re-consent). On
    # expiry: refuse the whole set, surface it, hold the watermark, clear the stale
    # pending — the owner renews via /ztn:role:edit and the next tick re-stages.
    if not roles_mandate.mandate_is_live(cfg.mandate, date.fromisoformat(today_iso())):
        emit_clarification(
            ctype="role-act-failed",
            subject=f"{role_id} · mandate expired — staged acts not executed",
            context=(f"Role {role_id} had {len(acts)} act(s) staged, but its act mandate "
                     "is no longer live (expired or revoked) — nothing was executed "
                     "(INV-16 re-consent). Renew or re-point the mandate via "
                     "`/ztn:role:edit`; the next tick re-reconciles."),
            source=f"roles act execution for {role_id} (mandate)",
            suggested_action="Renew the mandate `until` (or re-point its surface) via /ztn:role:edit.",
            action_taken="Refused the staged acts (mandate not live); cleared pending; watermark held.",
            base=base)
        stats["failed"] = len(acts)
        _clear_pending_acts(role_id, base)
        resolve_clarification("role-act-confirm", role_id, "mandate expired — not executed", base=base)
        return stats

    # The cumulative anti-salami ceiling (INV-20/28) bounds ACTS + inbox emissions
    # TOGETHER. Gate each WRITE against the remaining budget BEFORE it happens: a real
    # write (an `executed` act / an emitted close-event) consumes one; an idempotent
    # `skip` consumes none (so an all-idempotent re-run never budget-stops). Once the
    # ceiling is reached, stop — never over-write past it (the earlier code only gated
    # emissions and clamped acts at the ledger AFTER writing — a no-op bound).
    budget_state = roles_budget.load_budget(role_id, base)
    remaining = roles_budget.budget_remaining(budget_state)
    outcomes: list[roles_act.ActOutcome] = []
    writes_done = 0
    budget_hit = False
    for staged in acts:
        if writes_done >= remaining:
            budget_hit = True  # ceiling reached — do not execute further writes
            break
        op = roles_act.ActOperation.from_dict(staged)
        surface = staged.get("surface")
        spec = get_tool(op.tool, base) if op is not None else None
        # Re-check `is_act` at EXECUTE, not only at stage (INV-23): a tool flipped
        # read↔act (or deactivated) in the registry between stage and approve must not
        # drive a write on a now-wrong direction.
        if op is None or spec is None or not surface or not spec.is_act:
            outcomes.append(roles_act.ActOutcome(
                str((staged or {}).get("op", "?")), (staged or {}).get("target_ref"),
                "failed", "staged act no longer resolvable / not an active act tool "
                          "(config/tool changed since staging)"))
            continue
        secret, serr = _resolve_act_secret(spec.credential_ref, base)
        if serr is not None:
            outcomes.append(roles_act.ActOutcome(op.op, op.target_ref, "failed", serr))
            continue
        outcome = roles_act.execute_act(spec, surface, op, secret, exec_http)
        outcomes.append(outcome)
        _audit_act(role_id, op.tool, outcome, base)
        if outcome.status == "executed":
            writes_done += 1
            # Record each write to the cumulative ledger AS IT LANDS (incremental), not
            # once at the end — so a crash after a write but before finalisation still
            # charges it (a re-run finds it idempotent → skip → 0, which would otherwise
            # never charge the landed write, eroding the ceiling over crashes — INV-20).
            roles_budget.record_writes(role_id, 1, base)

    for o in outcomes:
        stats[o.status if o.status in ("executed", "skipped", "drift") else "failed"] += 1
    stats["outcomes"] = [
        {"op": o.op, "target_ref": o.target_ref, "status": o.status,
         "detail": o.detail, "effect": o.effect} for o in outcomes]

    executed_all_acts = len(outcomes) == len(acts)  # false when the budget stopped us
    acts_clean = executed_all_acts and all(o.ok for o in outcomes) and not budget_hit

    # Coupled inbox close-events — only when the ACTS fully succeeded, and only within the
    # SAME cumulative ceiling (a budget-truncated emission set is NOT a full success —
    # otherwise the board mutates, the base never learns, and the watermark would falsely
    # mark it processed: silent loss / laundering).
    run_at = pending.get("run_at") or now_iso_utc()
    emissions = pending.get("inbox_emissions") or []
    emissions_emitted = 0
    if acts_clean:
        for em in emissions:
            # Crash-safe budget accounting: an emission whose content-hashed file is
            # already on disk (a prior --approve-acts run crashed after the write but
            # before pending was cleared, and it re-uses the SAME persisted run_at →
            # same filename) must NOT be re-charged or re-gated — it already landed and
            # was charged once. Count it emitted so the tick still reaches full success.
            if roles_inbox.emission_path(role_id, run_at, em["text"], base).exists():
                emissions_emitted += 1
                continue
            if writes_done >= remaining:
                budget_hit = True
                break
            roles_inbox.write_emission(
                role_id, em["text"], em.get("evidence", []),
                bool(em.get("is_sensitive", False)), run_at, base)
            writes_done += 1
            emissions_emitted += 1
            roles_budget.record_writes(role_id, 1, base)  # incremental (crash-safe)
    stats["inbox_emitted"] = emissions_emitted

    stats["budget_hit"] = budget_hit
    full_success = acts_clean and emissions_emitted == len(emissions) and not budget_hit
    # A `refused` outcome (a create with no dedup key, an update with no fields) is a
    # real problem too — surface it, don't let it fall through as an unexplained "failed".
    has_problem = any(o.status in ("drift", "failed", "refused") for o in outcomes)

    if full_success:
        # Advance the watermark ONLY now — after the confirmed act (INV-26).
        roles_triggers.commit_gate_pass(role_id, pending.get("pending_watermarks") or {}, base)
        stats["watermark_advanced"] = True
        _clear_pending_acts(role_id, base)
        # Close the loop: the acts executed → resolve the role-act-confirm the owner
        # answered (mirrors _approve_coldstart resolving role-cold-start).
        resolve_clarification("role-act-confirm", role_id, "executed via approve-acts", base=base)
        return stats

    # Not a full success — advance NEITHER the inbox nor the watermark, clear the pending
    # store so a stale baseline never loops (the next reconcile re-derives from the real
    # board state — any act that DID write is idempotent and re-confirms as a skip).
    # Honest disclosure (mirrors the budget branch): when SOME acts executed this tick but
    # the tick did not fully succeed, the executed acts' coupled close-events were held and
    # are NOT auto-recovered — the body won't re-propose a note for an act it already
    # completed. Surface that loss so it is never silent (§6.5, INV-3 no-silent).
    some_executed = any(o.status == "executed" for o in outcomes)
    dropped_note = (
        " NOTE, honestly: a close-event for an act that ALREADY executed this tick is NOT "
        "auto-recovered — the act is done, so the body won't re-propose it, and that "
        "base-note is missed (the board is correct; your memory just won't record those "
        "specific closes)."
    ) if some_executed else ""
    for o in outcomes:
        if o.status == "drift":
            emit_clarification(
                ctype="role-act-drift",
                subject=f"{role_id} · act drift on {o.op} #{o.target_ref}",
                context=(f"Role {role_id}'s staged act ({o.op} #{o.target_ref}) was "
                         f"aborted: {o.detail}. The target changed since it was staged, "
                         "so the write was NOT applied over someone else's change "
                         "(TOCTOU — INV-16/28). The next tick re-reconciles from fresh "
                         "state; the watermark did not advance." + dropped_note),
                source=f"roles act execution for {role_id}",
                suggested_action="Nothing to do — the next reconcile picks up the current state.",
                action_taken="Aborted the drifted act; no double-write. Pending cleared.",
                base=base)
        elif o.status in ("failed", "refused"):
            emit_clarification(
                ctype="role-act-failed",
                subject=f"{role_id} · act {o.status} on {o.op} {o.target_ref or ''}".strip(),
                context=(f"Role {role_id}'s staged act ({o.op} {o.target_ref or ''}) "
                         f"{o.status}: {o.detail}. The bounded self-heal could not recover, "
                         "so the reconcile did not fully succeed — no close-event was "
                         "fed to the base and the watermark did not advance (§6.5). Any "
                         "acts that DID succeed are idempotent and re-confirm next tick."
                         + dropped_note),
                source=f"roles act execution for {role_id}",
                suggested_action="Re-auth / adjust if needed; the next tick re-reconciles.",
                action_taken="Surfaced the failure; pending cleared to re-derive next tick.",
                base=base)
    if budget_hit and not has_problem:
        # The reconcile could not complete within the cumulative ceiling this period.
        emit_clarification(
            ctype="role-budget-exhausted",
            subject=f"{role_id} act/inbox budget",
            context=(f"Role {role_id} reconciled but hit its cumulative act/inbox ceiling "
                     "this period — some acts/close-events could not be written and the "
                     "watermark did not advance (§6.5, INV-20). Next period (budget reset) "
                     "any UNDONE act re-reconciles idempotently. NOTE, honestly: a "
                     "close-event for an act that ALREADY executed this tick is NOT "
                     "auto-recovered — the act is done, so the body won't re-propose it, "
                     "and that base-note is missed (the board is correct; your memory just "
                     "won't record those specific closes). If this role is legitimately "
                     "busy, RAISE the ceiling via /ztn:role:edit so a tick finishes within "
                     "budget and no close-events are dropped."),
            source=f"roles act execution for {role_id} (budget)",
            suggested_action="Leave as-is (it completes next period) or raise the ceiling.",
            action_taken="Wrote up to the ceiling; held the rest + the watermark; pending cleared.",
            base=base)
    _clear_pending_acts(role_id, base)
    # The staged set is consumed (cleared) — resolve the confirm the owner answered; the
    # drift/failed/budget clarifications above now carry what actually happened.
    resolve_clarification("role-act-confirm", role_id,
                          "consumed via approve-acts (partial — see act-drift/failed/budget)",
                          base=base)
    return stats


def _approve_acts(role_id: str, cfg: RoleConfig, run_at: str, base: Path | None,
                  exec_http=None) -> dict:
    """The `--approve-acts` mode (mirrors `--approve-coldstart`): execute the role's
    staged acts (Phase 2). Writes one run + log entry and returns a summary. On full
    success the reconcile's close-events reach the base + the watermark advances; on
    drift/failure those are surfaced and neither advances (§6.5)."""
    stats = _execute_pending_acts(role_id, cfg, base, exec_http)
    total = stats["executed"] + stats["skipped"] + stats["drift"] + stats["failed"]
    clar_types: list[str] = []
    if total == 0:
        run_status, outcome = "empty", "no-pending-acts"
        log_lines = ["no pending acts to approve"]
    elif stats["watermark_advanced"]:
        # Full success — every act ran cleanly + every close-event was fed to the base.
        run_status, outcome = "ok", "acts-executed"
        log_lines = [_act_log_line(stats)] + _act_effect_lines(stats)
    else:
        # Not a full success: a drift/failure OR the cumulative budget stopped us — the
        # watermark did not advance, the reconcile completes next tick/period.
        run_status, outcome = "rejected", "acts-partial"
        if stats["drift"]:
            clar_types.append("role-act-drift")
        if stats["failed"]:
            clar_types.append("role-act-failed")
        if stats["budget_hit"] and not (stats["drift"] or stats["failed"]):
            clar_types.append("role-budget-exhausted")
        log_lines = [_act_log_line(stats)] + _act_effect_lines(stats)
    counts = make_run_counts(added=stats["executed"] + stats["inbox_emitted"])
    _write_run(role_id, run_at, run_status, counts, log_lines, base)
    return _summary(role_id, outcome, run_status, counts, clar_types, {}, exit_code=0)


def _act_log_line(stats: dict) -> str:
    """A one-line summary of an act execution for the run log (§3.5 observability)."""
    parts = [f"acts: {stats.get('executed', 0)} executed"]
    if stats.get("skipped"):
        parts.append(f"{stats['skipped']} skipped (idempotent)")
    if stats.get("drift"):
        parts.append(f"{stats['drift']} drift")
    if stats.get("failed"):
        parts.append(f"{stats['failed']} failed")
    if stats.get("inbox_emitted"):
        parts.append(f"{stats['inbox_emitted']} close-event(s) fed to base")
    if stats.get("budget_hit"):
        parts.append("budget ceiling reached — reconcile incomplete (watermark held)")
    if stats.get("watermark_advanced"):
        parts.append("watermark advanced")
    return ", ".join(parts)


def _act_effect_lines(stats: dict) -> list[str]:
    """Per-target act effects for the run log (§3.5 — «which #id was touched», not just a
    count). One bounded line per non-trivial outcome; empty when nothing meaningful."""
    lines: list[str] = []
    for o in stats.get("outcomes") or []:
        eff = o.get("effect") or o.get("detail") or ""
        if eff:
            lines.append(f"  · {o.get('op')} {o.get('status')}: {eff}")
    return lines[:20]  # bounded — a huge reconcile never floods the log


def run(
    role_id: str,
    payload: dict | None,
    approve_coldstart: bool = False,
    base: Path | None = None,
    tool_ctx: Path | None = None,
    pending_watermarks: dict | None = None,
    approve_acts: bool = False,
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

    if approve_acts:
        return _approve_acts(role_id, cfg, run_at, base)

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
    acts_proposed = (cfg.mandate is not None
                     and isinstance(payload.get("acts"), list) and payload.get("acts"))
    act_stats: dict | None = None
    if cold_starting:
        nudge_stats = (0, 0)
        identity_emitted = 0
        tool_request_emitted = 0
        inbox_stats = (0, 0, 0)
    else:
        nudge_stats = _process_nudges(role_id, payload, read_records, base)
        identity_emitted = _process_identity_suggestion(role_id, payload, read_records, base)
        tool_request_emitted = _process_tool_request(role_id, payload, read_records, base)
        if acts_proposed:
            # ACTING tick: stage the acts (§6.5 two-phase) — this couples the inbox
            # close-events + the trigger watermarks with the acts, emitted/advanced only
            # on confirmed act success (Phase 2). The Phase-1 inbox path is SKIPPED so an
            # emission never reaches the base before its act is confirmed.
            act_stats = _stage_acts(role_id, cfg, payload, read_records, base, tool_ctx,
                                    pending_watermarks or {})
            inbox_stats = (0, 0, 0)
        else:
            inbox_stats = _process_inbox_emissions(
                role_id, cfg, payload, read_records, base, tool_ctx)

    gate_reason = payload.get("gate_reason") if isinstance(payload.get("gate_reason"), str) else ""
    acts_proposed_but_coldstart = bool(cold_starting and acts_proposed)
    summary = _finalize_tick(
        role_id, cfg, plugins, prior_states, results, unroutable,
        degraded_signals, nudge_stats, identity_emitted, inbox_stats, run_at, base,
        tool_ctx, gate_reason, act_stats, pending_watermarks or {},
        acts_proposed_but_coldstart, tool_request_emitted,
    )

    # Autonomous acts (`hitl` False — an owner who DIALED `autonomy: autonomous` AND set
    # the consent marker `ZTN_ROLES_AUTONOMOUS_ACK`, or a future verified cage) execute
    # AFTER parts have persisted (§6.5 ordering: persist parts → execute act → advance
    # watermark), so a part-persist failure can never leave the watermark advanced over
    # un-persisted state. Absent the marker every act stays HITL (staged), so this branch
    # is inert by default. `_execute_pending_acts` writes its own outcome clarifications +
    # audit; fold its counts into the summary.
    if (act_stats and act_stats.get("staged") and not act_stats.get("hitl")
            and not act_stats.get("pending_exists")):
        exec_stats = _execute_pending_acts(role_id, cfg, base)
        summary["counts"]["added"] += exec_stats.get("executed", 0)
        for t in ("role-act-drift", "role-act-failed"):
            if (t == "role-act-drift" and exec_stats.get("drift")) or \
               (t == "role-act-failed" and exec_stats.get("failed")):
                if t not in summary["clarifications"]:
                    summary["clarifications"].append(t)
    return summary


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
    inbox_stats: tuple[int, int, int],
    run_at: str,
    base: Path | None,
    tool_ctx: Path | None = None,
    gate_reason: str = "",
    act_stats: dict | None = None,
    pending_watermarks: dict | None = None,
    acts_proposed_but_coldstart: bool = False,
    tool_request_emitted: int = 0,
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
    if tool_request_emitted:
        clar_types.append("role-tool-request")

    # Tools observability (§3.5): surface tool failures needing a HUMAN decision as a
    # `role-tool-reauth` CLARIFICATION (the self-heal exhausted — INV-29), and keep the
    # activity/failure/firewall lines for the run log below.
    ctx_data = _load_tool_ctx(tool_ctx)
    reauth_emitted = 0
    for tid in _reauth_tool_ids(ctx_data):
        if _emit(_reauth_signal(role_id, tid, ctx_data), base):
            reauth_emitted += 1
            clar_types.append("role-tool-reauth")

    # Inbox door (§4.2): written emissions are NOT clarifications (they land as
    # source files); firewall-gated + budget-deferred ones ARE clarifications.
    inbox_emitted, inbox_deferred, inbox_gated = inbox_stats
    if inbox_gated:
        clar_types.append("role-emission-confirm")
    if inbox_deferred:
        clar_types.append("role-budget-exhausted")

    # Act path (§6.2/§6.5): a HITL-staged tick surfaced a `role-act-confirm` (emitted in
    # `_stage_acts`); an autonomous tick that executed inline may have surfaced drift /
    # failed (emitted in `_execute_pending_acts`). Count them for the summary.
    acts_staged_hitl = bool(act_stats and act_stats.get("staged") and act_stats.get("hitl"))
    act_confirm_emitted = 1 if acts_staged_hitl else 0
    act_drift = act_stats.get("drift", 0) if act_stats else 0
    act_failed = act_stats.get("failed", 0) if act_stats else 0
    if act_confirm_emitted:
        clar_types.append("role-act-confirm")
    if act_drift:
        clar_types.append("role-act-drift")
    if act_failed:
        clar_types.append("role-act-failed")
    if act_stats and act_stats.get("refused_clar"):  # all-refused stage surfaced one
        clar_types.append(act_stats["refused_clar"])

    counts = _sum_counts([r.counts for r in results])
    counts["clarifications"] += (
        cold_emitted + unroutable_emitted + nudge_emitted + identity_emitted
        + tool_request_emitted
        + inbox_gated + (1 if inbox_deferred else 0) + reauth_emitted
        + act_confirm_emitted + act_drift + act_failed
    )
    counts["added"] += inbox_emitted + (act_stats.get("executed", 0) if act_stats else 0)
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
    if gate_reason:
        log_lines.append(f"gate: {gate_reason}")  # which trigger fired (observability)
    if unroutable:
        log_lines.append(f"{len(unroutable)} unroutable delta(s) rejected")
    if nudge_emitted or nudge_deferred or identity_emitted:
        parts_msg = f"{nudge_emitted} nudge(s) surfaced"
        if nudge_deferred:
            parts_msg += f", {nudge_deferred} deferred (anti-salami budget)"
        if identity_emitted:
            parts_msg += f", {identity_emitted} identity suggestion(s)"
        log_lines.append(f"proactive voice: {parts_msg}")
    # Inbox door + tool activity — make them visible in the tick's own log block, not
    # only in the separate audit/source files (§3.5 observability).
    if inbox_emitted or inbox_gated or inbox_deferred:
        imsg = f"inbox: {inbox_emitted} emitted"
        if inbox_gated:
            imsg += f", {inbox_gated} HITL-gated (firewall)"
        if inbox_deferred:
            imsg += f", {inbox_deferred} deferred (budget)"
        log_lines.append(imsg)
    # Act path observability (§3.5) — every act outcome legible from the run log alone.
    if act_stats is not None:
        if act_stats.get("pending_exists"):
            log_lines.append("acts: a staged set already awaits approval — not re-staged "
                             "(run `--approve-acts` or discard it first)")
        elif acts_staged_hitl:
            amsg = f"acts: {act_stats.get('staged', 0)} staged for approval (role-act-confirm)"
            if act_stats.get("refused"):
                amsg += f", {act_stats['refused']} refused"
            log_lines.append(amsg)
        elif act_stats.get("executed") or act_drift or act_failed or act_stats.get("skipped"):
            log_lines.append(_act_log_line(act_stats))  # autonomous inline execution
            log_lines.extend(_act_effect_lines(act_stats))
        elif act_stats.get("refused"):
            log_lines.append(f"acts: {act_stats['refused']} refused (mandate/grounding)")
        # The exact refusal reasons — so a dropped act (expired mandate, malformed) is
        # never invisible, even when some acts DID stage (O1).
        for r in (act_stats.get("refusals") or [])[:20]:
            log_lines.append(f"  · act refused: {r}")
    elif acts_proposed_but_coldstart:
        # A cold-starting tick holds proposed acts (parts not yet adopted) — make the
        # deferral visible rather than silently dropping the acts.
        log_lines.append("acts: proposed but held — role is cold-starting (adopt its "
                         "draft via --approve-coldstart, then acts resume)")
    log_lines.extend(_tool_activity_lines(ctx_data))

    # Watermark ownership (INV-26, §8): the WRITER advances the trigger watermark on a
    # confirmed successful tick. For an ACTING tick (acts were proposed → `act_stats is
    # not None`) the watermark is coupled to the act — advanced in Phase 2 by
    # `_execute_pending_acts` (or, on refusal/failure, deliberately NOT advanced so the
    # external change is re-processed) — so `_finalize_tick` never advances it here. A
    # cold-starting tick has not reconciled the external state yet (its parts are frozen
    # for approval), so it HOLDS the watermark too — advancing it would mark the external
    # change «processed» before the role ever acted on it (INV-26). A live non-acting
    # tick advances it now.
    cold_starting_final = any(r.outcome in ("staged", "resurfaced") for r in results)
    if (act_stats is None and pending_watermarks and not cold_starting_final
            and run_status in ROLES_SUCCESS_STATUSES):
        roles_triggers.commit_gate_pass(role_id, pending_watermarks, base)

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
        "--approve-acts", action="store_true",
        help="execute the role's staged acts (Phase 2 — CONTRACT §6.5): idempotent + "
             "TOCTOU-revalidated; on full success emits the coupled inbox close-events "
             "and advances the watermark, on failure neither. Omit --payload.",
    )
    parser.add_argument(
        "--pending-watermarks", default=None,
        help="the gate's pending trigger watermarks (JSON), authored by the runner from "
             "the trigger-gate. The WRITER commits them (INV-26/§8): now on a successful "
             "non-acting tick, or coupled to a confirmed act (Phase 2) on an acting tick.",
    )
    parser.add_argument(
        "--base", default=None,
        help="zettelkasten base override (else ZTN_BASE / derived)",
    )
    parser.add_argument(
        "--tool-ctx", default=None,
        help="the per-tick TOOL STAGE ctx file — the ENGINE-authored injection-firewall "
             "belt (INV-17): the writer reads `ingested_external` from it, so a body-"
             "supplied flag can never open the firewall. Omit when no tool ran.",
    )
    args = parser.parse_args(argv)

    base = Path(args.base).resolve() if args.base else None
    tool_ctx = Path(args.tool_ctx) if args.tool_ctx else None
    pending_watermarks: dict = {}
    if args.pending_watermarks:
        try:
            parsed = json.loads(args.pending_watermarks)
            pending_watermarks = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            pending_watermarks = {}

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
        summary = run(args.role, payload, args.approve_coldstart, base, tool_ctx,
                      pending_watermarks, args.approve_acts)
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
