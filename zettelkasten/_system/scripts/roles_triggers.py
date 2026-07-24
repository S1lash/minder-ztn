#!/usr/bin/env python3
"""Trigger-gate + cross-tick watermark for the Roles subsystem (CONTRACT §1.3/§7).

A trigger-gate is a RUNNER-evaluated predicate (INV-18) — a logged decision made
BEFORE the body, never a self-reported tool ("the body decided nothing to do" is
unfalsifiable and forbidden). The gate's entries are OR-combined and the whole
block is AND-ed with is_due + activation; an EMPTY block leaves the role ungated
(the additive default — current behaviour preserved).

Two kinds (INV-18):
  - `zone-mention` — fires when the role's own zone mentions a granted entity token,
    matched STT-robustly (EN/RU, garbled) via `roles_common.stt_token_equal`. A
    self-authored record (`source: role:{id}`) is EXCLUDED (INV-27 no-self-feed).
  - `external-state` — fires on EXTERNAL state alone (independent of any zone
    change): a cheap `probe` value moved past a runner-owned watermark held in
    `_system/roles/{id}/triggers.json` (INV-26), keyed by target + device
    (multi-clone). The watermark advances ONLY after a confirmed successful tick
    (INV-26/28 — never before, else a partial failure silently marks it processed).

Skip-streak: `SKIP_STREAK_LIMIT` (5) consecutive `gate:skip` outcomes escalate to a
`role-trigger-skip-streak` CLARIFICATION (the SKILL emits it; this module owns the
counter). Deterministic, no LLM, cross-platform (`pathlib`, atomic write, LF).
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roles_common import (
    RoleConfig,
    TriggerSpec,
    atomic_write_text,
    is_role_authored_source,
    role_dir,
    stt_token_equal,
)

SKIP_STREAK_LIMIT = 5

# Frontmatter_subset keys whose values are candidate mention strings for a
# zone-mention match (the note's own identifiers — cheap, index-only, no bodies).
_MENTION_KEYS: tuple[str, ...] = (
    "title", "name", "tags", "projects", "people", "hubs", "concepts", "aliases",
)


def triggers_path(role_id: str, base: Path | None = None) -> Path:
    """The runner-owned cross-tick trigger state (INV-26) — its OWN home beside
    `decisions.jsonl`, never smeared into a part."""
    return role_dir(role_id, base) / "triggers.json"


def default_device() -> str:
    """A stable per-clone id for multi-clone watermark keying (INV-26). Read from
    `ZTN_DEVICE_ID`; when unset, DERIVE it from the hostname (slugified, ASCII-safe,
    cross-platform) so the device-keying that prevents cross-clone trigger split-brain
    works out of the box — a shared constant `"default"` across clones would make the
    keying inert. Falls back to `"default"` only if the hostname is unavailable."""
    dev = os.environ.get("ZTN_DEVICE_ID", "").strip()
    if dev:
        return dev
    try:
        host = socket.gethostname() or ""
    except Exception:  # noqa: BLE001 — hostname lookup must never crash the gate
        host = ""
    slug = "".join(c if c.isalnum() else "-" for c in host.lower()).strip("-")
    return slug or "default"


def watermark_key(probe: str, device: str) -> str:
    """Key a watermark by target+device (INV-26) — a per-clone-only key would split
    brain on a shared external target."""
    return f"{probe}@{device}"


# -----------------------------------------------------------------------------
# State I/O (tolerant read, atomic write)
# -----------------------------------------------------------------------------

def load_trigger_state(role_id: str, base: Path | None = None) -> dict:
    """Read `triggers.json` → `{watermarks: {...}, skip_streak: int}`. Tolerant:
    a missing/corrupt file → a fresh default (a bad file must not crash the gate)."""
    path = triggers_path(role_id, base)
    default = {"watermarks": {}, "skip_streak": 0, "skip_reasons": []}
    if not path.is_file():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default
    if not isinstance(raw, dict):
        return default
    wm = raw.get("watermarks")
    streak = raw.get("skip_streak")
    reasons = raw.get("skip_reasons")
    return {
        "watermarks": {str(k): str(v) for k, v in wm.items()} if isinstance(wm, dict) else {},
        "skip_streak": int(streak) if isinstance(streak, int) else 0,
        "skip_reasons": [str(r) for r in reasons] if isinstance(reasons, list) else [],
    }


def save_trigger_state(role_id: str, state: dict, base: Path | None = None) -> None:
    atomic_write_text(
        triggers_path(role_id, base),
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


# -----------------------------------------------------------------------------
# Zone-mention matching (STT-robust, self-authored excluded)
# -----------------------------------------------------------------------------

def _unit_source(unit: Any) -> str:
    fm = unit.get("frontmatter_subset") if isinstance(unit, dict) else None
    src = fm.get("source") if isinstance(fm, dict) else None
    return src if isinstance(src, str) else ""


def is_self_authored(unit: Any, role_id: str) -> bool:
    """True when the unit is a record THIS role emitted — excluded from its own
    trigger evaluation (INV-27 no-self-feed). Matches BOTH the raw emission
    (`source: role:{id}`) and the `/ztn:process`-derived record (whose `source:` is
    the processed `…/roles/{id}--…` path) via the shared `is_role_authored_source`."""
    return is_role_authored_source(_unit_source(unit), role_id)


def _mention_tokens(unit: Any) -> list[str]:
    """Candidate mention strings from a `--list` unit: its path stem + the mention
    frontmatter values (strings or string-lists). Index-only (no body) — cheap."""
    out: list[str] = []
    if not isinstance(unit, dict):
        return out
    path = unit.get("path")
    if isinstance(path, str) and path:
        out.append(Path(path).stem)
    fm = unit.get("frontmatter_subset")
    if isinstance(fm, dict):
        for key in _MENTION_KEYS:
            val = fm.get(key)
            if isinstance(val, str):
                out.append(val)
            elif isinstance(val, list):
                out.extend(v for v in val if isinstance(v, str))
    return out


def _tokenise(text: str) -> list[str]:
    """Split a candidate string into words for token-level STT matching."""
    return [w for w in "".join(c if c.isalnum() else " " for c in text).split() if w]


def zone_mention_fires(units: Any, match_tokens: tuple[str, ...], role_id: str) -> str | None:
    """Return the first `match` token that fires against a NON-self unit, else None.

    STT-robust (`stt_token_equal`), token-level (so `"minder"` matches a note tagged
    `minder` or titled "Minder sync" but not "reminder"). Self-authored records are
    skipped (INV-27)."""
    for unit in units if isinstance(units, list) else []:
        if is_self_authored(unit, role_id):
            continue
        words = [w for cand in _mention_tokens(unit) for w in _tokenise(cand)]
        for token in match_tokens:
            if any(stt_token_equal(token, w) for w in words):
                return token
    return None


# -----------------------------------------------------------------------------
# Gate evaluation (PURE — reads state, never mutates; commit is separate)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class GateResult:
    """Outcome of a trigger-gate evaluation (INV-18 — logged in both outcomes).

    `passed` decides whether the body runs. `reasons` is the log line detail
    (`gate:pass`/`gate:skip:{reason}`). `pending_watermarks` are the new
    external-probe values to COMMIT only after a confirmed successful tick
    (INV-26 — advance-after-confirmed, never on evaluation).
    """
    passed: bool
    reasons: tuple[str, ...] = ()
    pending_watermarks: dict = field(default_factory=dict)

    @property
    def log_reason(self) -> str:
        if self.passed:
            return "gate:pass:" + ",".join(self.reasons) if self.reasons else "gate:pass"
        return "gate:skip:" + (",".join(self.reasons) if self.reasons else "no-trigger-fired")


def evaluate_gate(
    cfg: RoleConfig,
    units: Any,
    probe_values: dict | None = None,
    base: Path | None = None,
    device: str | None = None,
) -> GateResult:
    """Evaluate a role's trigger block (OR-combined). PURE — never mutates state.

    `units` — the `--list` zone index units (for `zone-mention`). `probe_values` —
    `{probe: current_value}` the runner obtained via a CHEAP probe (distinct from
    the full read); a probe absent/None means that `external-state` trigger cannot
    fire this tick (honest — never a guessed fire). An empty trigger block → passed
    (ungated). A fired `external-state` records its new value in
    `pending_watermarks` for the runner to COMMIT after a confirmed tick.
    """
    triggers: tuple[TriggerSpec, ...] = cfg.triggers
    if not triggers:
        return GateResult(passed=True, reasons=("ungated",))
    dev = device or default_device()
    probes = probe_values or {}
    state = load_trigger_state(cfg.id, base)
    watermarks = state.get("watermarks", {})
    reasons: list[str] = []
    pending: dict = {}
    for trig in triggers:
        if trig.kind == "zone-mention":
            hit = zone_mention_fires(units, trig.match, cfg.id)
            if hit is not None:
                reasons.append(f"zone-mention:{hit}")
        elif trig.kind == "external-state":
            probe = trig.probe or ""
            current = probes.get(probe)
            if current is None:
                continue  # probe unavailable → cannot fire (honest, not a guess)
            key = watermark_key(probe, dev)
            if str(current) != watermarks.get(key):
                reasons.append(f"external-state:{probe}")
                pending[key] = str(current)
    passed = bool(reasons)
    return GateResult(passed=passed, reasons=tuple(reasons), pending_watermarks=pending)


# -----------------------------------------------------------------------------
# Commit (mutating — called by the runner AFTER the outcome is known)
# -----------------------------------------------------------------------------

# The skip-streak CLARIFICATION surfaces the LAST few skip reasons (SYSTEM_CONFIG
# contract «surface the streak + the last skip reasons») — bounded so triggers.json
# never grows unbounded on a permanently-quiet role.
MAX_SKIP_REASONS = 5


def commit_gate_pass(
    role_id: str, pending_watermarks: dict, base: Path | None = None,
) -> None:
    """A confirmed successful tick: advance the fired watermarks (INV-26) and reset
    the skip-streak + reasons. Called ONLY after the tick succeeded — a failed tick
    leaves the watermark where it was so the change is re-processed next time (no
    silent miss)."""
    state = load_trigger_state(role_id, base)
    if pending_watermarks:
        wm = dict(state.get("watermarks", {}))
        wm.update({str(k): str(v) for k, v in pending_watermarks.items()})
        state["watermarks"] = wm
    state["skip_streak"] = 0
    state["skip_reasons"] = []
    save_trigger_state(role_id, state, base)


def commit_gate_skip(role_id: str, reason: str = "", base: Path | None = None) -> int:
    """A `gate:skip` outcome: increment + persist the skip-streak AND store the skip
    `reason` (bounded to the last `MAX_SKIP_REASONS`); return the new streak. The
    reasons let the `role-trigger-skip-streak` CLARIFICATION surface WHY the role kept
    skipping (its contract), not just a bare count. The SKILL escalates at
    `SKIP_STREAK_LIMIT`."""
    state = load_trigger_state(role_id, base)
    streak = int(state.get("skip_streak", 0)) + 1
    state["skip_streak"] = streak
    if reason:
        reasons = list(state.get("skip_reasons") or [])
        reasons.append(str(reason))
        state["skip_reasons"] = reasons[-MAX_SKIP_REASONS:]
    save_trigger_state(role_id, state, base)
    return streak


def recent_skip_reasons(role_id: str, base: Path | None = None) -> list[str]:
    """The last few skip reasons (for the `role-trigger-skip-streak` CLARIFICATION)."""
    return list(load_trigger_state(role_id, base).get("skip_reasons") or [])


def skip_streak_exceeded(streak: int) -> bool:
    return streak >= SKIP_STREAK_LIMIT
