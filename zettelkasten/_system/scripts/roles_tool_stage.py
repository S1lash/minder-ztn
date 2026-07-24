#!/usr/bin/env python3
"""TOOL STAGE — the deterministic tool pipeline (CONTRACT §3, INV-1/10/17/20/29).

Sits between the tick body's Stage 1 (which may emit `tool_requests[]`) and Stage 2.
The body PROPOSES a tool request; this runner DISPOSES (INV-1). For every request it
runs, deterministically and in order:

  grant-check  → the tool must be in a part's granted `tools:` list AND an active
                 registry row (never trusts the body's request)
  budget       → per-tool call cap (INV-20; `unlimited` = owner grant); refuse past it
  secret       → resolve `credential_ref` (`secret://…`) in memory (INV-12); a failed
                 resolve triggers bounded self-heal → honest-degrade + reauth signal (INV-29)
  dispatch     → adapter by KIND (INV-19): Python-executable adapters run in-process;
                 harness-executed adapters (mcp/skill) return a descriptor the SKILL
                 invokes, then `absorb_harness_return` folds the raw return back
  audit        → hash + one-line summary appended to the tool audit (INV-10 — the RAW
                 return is EPHEMERAL, never committed to the repo)
  firewall     → any external-tool return marks the tick `ingested_external` (INV-17)

BOUNDED-ITERATIVE (INV-20/21), NOT ReAct: the body may request → observe → request
again WITHIN a tick, bounded by the per-tool budget. The runner holds the per-tick
call counts + the firewall flag in a small `ctx` file across the body↔runner turns.

Library + thin CLI (the `ztn-roles` SKILL drives the CLI across turns). Deterministic,
cross-platform (`pathlib`, atomic-append, LF).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import roles_budget
from _common import now_iso_utc, state_dir
from roles_common import RoleConfig, atomic_write_text, load_role_config
from roles_tools import (
    ToolResult,
    ToolSpec,
    get_tool,
    import_tool_adapter,
    is_harness_executed,
    is_unlimited,
)


def tool_audit_path(base: Path | None = None) -> Path:
    """Append-only tool audit — hash + one-line summary per call (NEVER the raw
    return; INV-10). Observability without repo bloat."""
    return state_dir(base) / "roles-tool-audit.jsonl"


# -----------------------------------------------------------------------------
# Per-tick context (call counts + firewall flag) — runner-owned, small
# -----------------------------------------------------------------------------

@dataclass
class ToolStageContext:
    """The per-tick working memory the runner holds across body↔runner turns.

    `call_counts` bounds the bounded-iterative loop per tool; `ingested_external`
    is the injection-firewall flag (INV-17) — set once any external-tool return
    lands, read by the writer to HITL-gate an external-derived write. `failures`
    records each non-ok outcome (`{tool_id, status, reason, reauth}`) so the tick's
    OWN run log can surface a broken tool + escalate a `role-tool-reauth` — a silent
    honest-degrade otherwise looks like a healthy tick (observability, §3.5).
    """
    role_id: str
    call_counts: dict[str, int] = field(default_factory=dict)
    ingested_external: bool = False
    failures: list[dict] = field(default_factory=list)
    started_at: str = ""  # ISO of the first tool call — the wall-clock deadline anchor

    def to_dict(self) -> dict:
        return {
            "role_id": self.role_id,
            "call_counts": dict(self.call_counts),
            "ingested_external": bool(self.ingested_external),
            "failures": list(self.failures),
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, raw: Any, role_id: str) -> "ToolStageContext":
        if not isinstance(raw, dict):
            return cls(role_id=role_id)
        # Tolerant (like load_budget / load_trigger_state): a non-numeric / null count
        # from a corrupt or adversarial ctx is DROPPED per-key, never crashes the read.
        counts: dict[str, int] = {}
        raw_counts = raw.get("call_counts")
        if isinstance(raw_counts, dict):
            for k, v in raw_counts.items():
                try:
                    counts[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
        raw_fail = raw.get("failures")
        failures = [f for f in raw_fail if isinstance(f, dict)] if isinstance(raw_fail, list) else []
        return cls(
            role_id=str(raw.get("role_id") or role_id),
            call_counts=counts,
            ingested_external=bool(raw.get("ingested_external", False)),
            failures=failures,
            started_at=str(raw.get("started_at") or ""),
        )


def load_ctx(path: Path, role_id: str) -> ToolStageContext:
    if not path.is_file():
        return ToolStageContext(role_id=role_id)
    try:
        return ToolStageContext.from_dict(
            json.loads(path.read_text(encoding="utf-8")), role_id)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ToolStageContext(role_id=role_id)


def save_ctx(path: Path, ctx: ToolStageContext) -> None:
    atomic_write_text(path, json.dumps(ctx.to_dict(), ensure_ascii=False))


# -----------------------------------------------------------------------------
# Descriptor for a harness-executed step (mcp / skill)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class HarnessStep:
    """A tool request the SKILL must fulfil via the harness (an MCP/skill call).

    The runner already grant-checked, budgeted, and resolved the secret; the SKILL
    reads `descriptor`, makes the call, and hands the raw return to
    `absorb_harness_return`. `secret` is the resolved credential (or None) — the
    SKILL passes it to the harness call out of band, NEVER into a body prompt.
    """
    tool_id: str
    descriptor: dict
    secret: str | None = None
    part_id: str | None = None  # the part the grant was checked against (§1.1)

    @property
    def is_harness(self) -> bool:
        return True


# -----------------------------------------------------------------------------
# Request parse + grant + budget + secret
# -----------------------------------------------------------------------------

def parse_tool_request(req: Any) -> tuple[str | None, str | None, dict]:
    """Split a body `tool_request` into (tool_id, part_id, args). Malformed → (None, …).

    A `tool_request` names both the tool AND the `part` the body is acting as — the
    grant is PER-PART (CONTRACT §1.1: "the tool-refs a PART may request"), so the runner
    must know which part to grant-check against. `part` is required; its absence yields
    a None part_id and the caller refuses (surface — never fall back to a role-wide grant)."""
    if not isinstance(req, dict):
        return None, None, {}
    tid = req.get("tool")
    if not isinstance(tid, str) or not tid.strip():
        return None, None, {}
    part = req.get("part")
    part_id = part.strip() if isinstance(part, str) and part.strip() else None
    # An explicit `args` mapping (even empty `{}`) is used as-is. Only when `args` is
    # ABSENT do we fold the sibling keys (e.g. `mcp_tool`, `url`) into args — branch on
    # PRESENCE, not truthiness, so an explicit `args: {}` is not re-folded onto itself.
    # `part` is metadata, never a tool arg.
    if "args" in req:
        args = req.get("args")
        args = args if isinstance(args, dict) else {}
    else:
        args = {k: v for k, v in req.items() if k not in ("tool", "part")}
    return tid.strip(), part_id, args


def _part_grant_ids(cfg: RoleConfig, part_id: str) -> set[str] | None:
    """The tool-refs granted to the NAMED part (per-part grant, CONTRACT §1.1). None
    when the role has no such part (an unroutable part id → the caller refuses)."""
    for part in cfg.parts:
        if part.id == part_id:
            return set(part.tools)
    return None


def grant_and_budget(
    cfg: RoleConfig, tool_id: str, part_id: str | None, ctx: ToolStageContext,
    base: Path | None,
) -> tuple[ToolSpec | None, ToolResult | None]:
    """Grant-check (PER-PART) + per-tool budget. Returns (spec, None) on pass, else
    (None, refusal).

    The tool must be granted to the SPECIFIC part the body named (not any part of the
    role — CONTRACT §1.1), and be an active registry row. A missing/unknown part, an
    ungranted tool, or an over-budget tool is REFUSED (declare-unknown — the runner
    never trusts a body request). `unlimited` never caps.
    """
    if part_id is None:
        return None, ToolResult.unknown(
            tool_id, f"tool_request for {tool_id!r} named no 'part' — per-part grant "
            "cannot be checked (surface, don't guess)", is_external=False)
    grants = _part_grant_ids(cfg, part_id)
    if grants is None:
        return None, ToolResult.unknown(
            tool_id, f"role {cfg.id!r} has no part {part_id!r}", is_external=False)
    if tool_id not in grants:
        return None, ToolResult.unknown(
            tool_id, f"tool {tool_id!r} is not granted to part {part_id!r} of role "
            f"{cfg.id!r}", is_external=False)
    spec = get_tool(tool_id, base)
    if spec is None:
        return None, ToolResult.unknown(
            tool_id, f"tool {tool_id!r} is not an active tool in the registry",
            is_external=False)
    # HARD GUARD (INV-1/3/16/28) — an `act`-direction tool is executable ONLY through the
    # deterministic writer's act spine (`roles_act`: mandate authorization + TOCTOU +
    # idempotency + create/update field allowlist + HITL act-confirm + injection firewall +
    # cumulative budget). It IS presented to the body in the frame (so it knows it has
    # outward hands and proposes `acts[]`), but a body `tool_request` NAMING it is refused
    # here. Without this guard the read TOOL STAGE is a side-door: the body could emit a
    # tool_request with an arbitrary method/URL/json, the http adapter permits write verbs
    # for an act tool, and the write executes with the live secret — bypassing the entire
    # act spine (the mandate surface is void when the URL is body-chosen). The guard keys
    # on `spec.is_act` (the rigid direction field, INV-19/23), never a tool-id.
    if spec.is_act:
        return None, ToolResult.unknown(
            tool_id, f"tool {tool_id!r} is an ACT tool — not invocable via the tool stage; "
            "the body PROPOSES acts[] and the deterministic writer (roles_act) disposes "
            "under mandate + TOCTOU + HITL", is_external=False)
    used = ctx.call_counts.get(tool_id, 0)
    if not is_unlimited(spec) and used >= spec.max_calls_per_run:
        return None, ToolResult.unknown(
            tool_id,
            f"tool {tool_id!r} hit its per-run budget "
            f"({spec.max_calls_per_run} calls)",
            is_external=False)
    return spec, None


def resolve_secret_for(spec: ToolSpec, base: Path | None) -> tuple[str | None, str | None]:
    """Resolve the tool's credential in memory (INV-12). Returns (secret, error).

    No credential_ref → (None, None). A resolve failure → (None, reason) — the
    caller honest-degrades (declare-unknown) and signals a `role-tool-reauth`
    CLARIFICATION (INV-29: a secret that will not resolve is a human decision, not a
    mechanical retry). The secret is returned to the runner ONLY, never logged.
    """
    if not spec.credential_ref:
        return None, None
    try:
        import roles_secrets  # lazy — a role with no secret never imports crypto
        secret = roles_secrets.resolve_secret(spec.credential_ref, base)
        return secret, None
    except Exception as exc:  # noqa: BLE001 — SecretError (or a missing module) → honest-degrade
        return None, f"credential {spec.credential_ref} could not be resolved: {exc}"


# -----------------------------------------------------------------------------
# Audit (hash + summary ONLY — never the raw return)
# -----------------------------------------------------------------------------

def audit_tool_call(role_id: str, result: ToolResult, base: Path | None) -> None:
    """Append one hash+summary audit line (INV-10 — no raw return in the repo)."""
    path = tool_audit_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": now_iso_utc(),
        "role_id": role_id,
        "tool_id": result.tool_id,
        "status": result.status,
        "summary": result.summary,
        "raw_hash": result.raw_hash,
        "is_external": result.is_external,
    }
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _count_call(ctx: ToolStageContext, tool_id: str) -> None:
    """Consume one per-tool budget slot. Counted at DISPATCH (not at result) so the
    budget is self-enforcing across the harness round-trip: a harness call counts when
    the HarnessStep is issued, so a SKILL issuing N requests before absorbing cannot
    exceed the cap (the next grant_and_budget sees the incremented count)."""
    ctx.call_counts[tool_id] = ctx.call_counts.get(tool_id, 0) + 1


def _record_outcome(
    ctx: ToolStageContext, tool_id: str, result: ToolResult, base: Path | None,
    count: bool = True,
) -> ToolResult:
    """Set the firewall flag on an external return + audit; count the call unless it
    was already counted at dispatch (`count=False`, the harness-absorb path); record a
    non-ok outcome in `ctx.failures` so the tick's run log can surface a broken tool.
    Shared by the Python-exec and harness paths so both bound the budget + mark
    ingestion + stay observable."""
    if count:
        _count_call(ctx, tool_id)
    if result.status == "ok" and result.is_external:
        ctx.ingested_external = True
    if result.status != "ok":
        ctx.failures.append({
            "tool_id": tool_id,
            "status": result.status,
            "reason": result.summary or result.error,
            "reauth": result.error.startswith("reauth:"),
        })
    audit_tool_call(ctx.role_id, result, base)
    return result


# -----------------------------------------------------------------------------
# The pipeline
# -----------------------------------------------------------------------------

def _elapsed_seconds(started_iso: str) -> float:
    """Seconds since `started_iso` (a `now_iso_utc` stamp). 0.0 if unparseable —
    fail-safe (a bad stamp never fabricates an over-deadline refusal)."""
    try:
        start = datetime.strptime(started_iso, "%Y-%m-%dT%H:%M:%SZ")
        now = datetime.strptime(now_iso_utc(), "%Y-%m-%dT%H:%M:%SZ")
        return max(0.0, (now - start).total_seconds())
    except (ValueError, TypeError):
        return 0.0


def _over_wall_clock(ctx: ToolStageContext, base: Path | None) -> bool:
    """True once the tick's tool loop has exceeded the role's `max_tick_seconds`
    (INV-28). Enforced in CODE (not just the SKILL prompt) so an `unlimited` read tool
    + a looping body cannot hold `.roles.lock` and starve `/ztn:process`: past the
    deadline every further tool call is refused, so the loop cannot make progress."""
    if not ctx.started_at:
        return False
    limit = roles_budget.max_tick_seconds(roles_budget.load_budget(ctx.role_id, base))
    return _elapsed_seconds(ctx.started_at) > limit


def run_tool_request(
    cfg: RoleConfig, tool_request: Any, ctx: ToolStageContext, base: Path | None,
) -> ToolResult | HarnessStep:
    """Run ONE body tool request through the full deterministic pipeline.

    Returns a completed `ToolResult` (Python-executable adapter, or any refusal /
    budget / secret / wall-clock failure — all honest `declare-unknown`), OR a
    `HarnessStep` the SKILL must fulfil (mcp/skill), after which the SKILL calls
    `absorb_harness_return`. Mutates `ctx` (counts + firewall) and appends the audit
    for the completed cases; the harness case counts + audits in `absorb`.
    """
    tool_id, part_id, args = parse_tool_request(tool_request)
    if tool_id is None:
        return ToolResult.unknown(
            "?", "malformed tool_request (needs a 'tool' id)", is_external=False)

    # Wall-clock deadline (INV-28) — code-enforced. Stamp the loop start on the first
    # call; once past `max_tick_seconds`, refuse further calls (audited, no slot spent).
    if not ctx.started_at:
        ctx.started_at = now_iso_utc()
    elif _over_wall_clock(ctx, base):
        refusal = ToolResult.unknown(
            tool_id, "tick wall-clock budget exceeded — tool loop stopped",
            is_external=False)
        audit_tool_call(ctx.role_id, refusal, base)
        return refusal

    spec, refusal = grant_and_budget(cfg, tool_id, part_id, ctx, base)
    if refusal is not None:
        # A refusal does NOT consume a call slot or set the firewall — nothing ran.
        audit_tool_call(ctx.role_id, refusal, base)
        return refusal

    secret, secret_err = resolve_secret_for(spec, base)
    if secret_err is not None:
        result = ToolResult(
            tool_id=tool_id, status="unknown", summary=secret_err,
            error=f"reauth: {secret_err}", is_external=spec.direction != "read" or False,
        )
        return _record_outcome(ctx, tool_id, result, base)

    try:
        adapter = import_tool_adapter(spec.adapter)
    except Exception as exc:  # noqa: BLE001 — adapter load failure → honest-degrade
        result = ToolResult.unknown(
            tool_id, f"adapter {spec.adapter!r} unavailable: {exc}", is_external=False)
        return _record_outcome(ctx, tool_id, result, base)

    if is_harness_executed(adapter):
        descriptor = adapter.prepare(spec, args, secret)
        if not descriptor.get("ok", False):
            result = ToolResult.unknown(
                tool_id, descriptor.get("reason", "harness prepare refused"),
                is_external=False)
            return _record_outcome(ctx, tool_id, result, base)
        # Count the slot AT DISPATCH so the per-tool budget is self-enforcing across the
        # harness round-trip (a SKILL issuing N steps before absorbing cannot exceed the
        # cap — the next grant_and_budget sees this increment). `absorb` does NOT re-count.
        _count_call(ctx, tool_id)
        return HarnessStep(tool_id=tool_id, descriptor=descriptor, secret=secret,
                           part_id=part_id)

    # Python-executable adapter — run it in-process now.
    try:
        result = adapter.exec_tool(spec, args, secret)
    except Exception as exc:  # noqa: BLE001 — an adapter bug must never crash the tick
        result = ToolResult.unknown(
            tool_id, f"adapter {spec.adapter} raised: {exc}")
    if not isinstance(result, ToolResult):
        result = ToolResult.unknown(tool_id, "adapter returned a non-ToolResult")
    return _record_outcome(ctx, tool_id, result, base)


def absorb_harness_return(
    cfg: RoleConfig, tool_id: str, raw_result: Any, ctx: ToolStageContext,
    base: Path | None, part_id: str | None = None,
) -> ToolResult:
    """Fold a harness (mcp/skill) raw return into a `ToolResult` — the second half
    of a `HarnessStep`. The PER-PART grant is re-checked (defence in depth — pass the
    `HarnessStep.part_id`), then the adapter's `normalize` runs; the outcome is counted
    + audited like the Python-exec path."""
    spec = get_tool(tool_id, base)
    grants = _part_grant_ids(cfg, part_id) if part_id else None
    if spec is None or grants is None or tool_id not in grants:
        result = ToolResult.unknown(
            tool_id, f"tool {tool_id!r} not grantable to part {part_id!r} at absorb",
            is_external=False)
        audit_tool_call(ctx.role_id, result, base)
        return result
    try:
        adapter = import_tool_adapter(spec.adapter)
        result = adapter.normalize(spec, raw_result)
    except Exception as exc:  # noqa: BLE001
        result = ToolResult.unknown(tool_id, f"normalize failed: {exc}")
    if not isinstance(result, ToolResult):
        result = ToolResult.unknown(tool_id, "normalize returned a non-ToolResult")
    # count=False: the slot was already consumed at DISPATCH (`_count_call`); absorb
    # only sets the firewall flag + audits + records the failure (never re-counts).
    return _record_outcome(ctx, tool_id, result, base, count=False)


# -----------------------------------------------------------------------------
# CLI — the SKILL drives this across body↔runner turns
# -----------------------------------------------------------------------------

def _result_json(result: ToolResult | HarnessStep) -> str:
    if isinstance(result, HarnessStep):
        return json.dumps({
            "kind": "harness",
            "tool_id": result.tool_id,
            "part_id": result.part_id,  # SKILL echoes it back on --absorb --part
            "descriptor": result.descriptor,
            "has_secret": result.secret is not None,
        }, ensure_ascii=False)
    return json.dumps({
        "kind": "result",
        "tool_id": result.tool_id,
        "status": result.status,
        "data": result.data,
        "summary": result.summary,
        "raw_hash": result.raw_hash,
        "is_external": result.is_external,
        "error": result.error,
    }, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, help="role id")
    parser.add_argument("--ctx", required=True, help="per-tick ctx file (json)")
    parser.add_argument("--base", default=None, help="zettelkasten base override")
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument("--request", default=None, help="a body tool_request (json)")
    sub.add_argument("--absorb", default=None,
                     help="tool_id to absorb a harness raw return for (with --raw)")
    parser.add_argument("--raw", default=None, help="harness raw return (json) for --absorb")
    parser.add_argument("--part", default=None,
                        help="the part id from the HarnessStep (per-part grant re-check on --absorb)")
    args = parser.parse_args(argv)

    base = Path(args.base).resolve() if args.base else None
    ctx_path = Path(args.ctx)
    ctx = load_ctx(ctx_path, args.role)
    try:
        cfg = load_role_config(args.role, base)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"kind": "error", "error": str(exc)}), file=sys.stderr)
        return 1

    if args.request is not None:
        try:
            req = json.loads(args.request)
        except json.JSONDecodeError as exc:
            print(json.dumps({"kind": "error", "error": f"bad --request json: {exc}"}))
            return 1
        out = run_tool_request(cfg, req, ctx, base)
    else:
        raw = None
        if args.raw is not None:
            try:
                raw = json.loads(args.raw)
            except json.JSONDecodeError:
                raw = args.raw  # a bare string return is valid
        out = absorb_harness_return(cfg, args.absorb, raw, ctx, base, args.part)

    save_ctx(ctx_path, ctx)
    print(_result_json(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
