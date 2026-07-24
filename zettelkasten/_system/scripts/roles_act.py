#!/usr/bin/env python3
"""Act orchestrator — the deterministic rmw/idempotency/TOCTOU/atomicity engine
(CONTRACT §6.2/§6.5, DOCTRINE INV-16/28). Writer-owned; the body NEVER executes here.

An ACT is a role's write on the world. It runs ONLY inside the deterministic writer's
post-persist step, under a live mandate (`roles_mandate`), against a scoped surface,
via a Python-executable `http`/`local` adapter that injects the secret out of the LLM's
sight (INV-12 — never `mcp`/`skill` in the harness). This module owns the safety spine
around the raw HTTP transport (`roles_tool_http.exec_tool`, injected as `exec_http` so
this engine is testable with a fake transport):

  - **generic REST-board verbs** (`create` / `update` / `close`) mapped to concrete
    requests by the act tool's `act_config` DATA + the mandate `surface` (INV-19 —
    dispatch by config, never `if tool ==`): `{base_host}/{surface}/{collection}`;
  - **idempotency** (INV-28): `create` searches the collection by `match_field` first
    and SKIPS when a live item already matches — no double-create across retries;
  - **TOCTOU** (INV-16/§6.2): the writer captures a `baseline` version (`version_field`)
    when it STAGES the act (Phase 1); at execution (Phase 2) it re-reads and refuses to
    write when the version drifted — someone changed the target between propose+approve;
  - **atomicity** (INV-28/§6.5): the caller (`roles_persist`) advances the watermark +
    emits the inbox close-events ONLY on confirmed FULL success; on any failure/drift,
    neither. A non-idempotent op that fails ambiguously SURFACES, never blind-retries
    (every op here is idempotent, so the ambiguous branch is the guard, not the norm).

Deterministic, cross-platform. No LLM. The only network is via the injected transport.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from roles_tools import ToolResult, ToolSpec

# The generic REST-board verbs the body may propose (INV-19 — kind, not endpoint).
OP_KINDS: frozenset[str] = frozenset({"create", "update", "close"})
# A safe item id for `target_ref` — the body-authored ref is concatenated into the write
# URL, so it MUST NOT carry a slash / `..` / a query (a path-traversal escape past the
# mandated surface — INV-16). A REST item id is an opaque token; anything else is refused.
_TARGET_REF_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
# The act_config keys `roles_act` REQUIRES to build requests — REFUSE-DON'T-ASSUME
# (INV-19, the owner's rails-not-frames concern): EVERY act tool declares its own board
# vocabulary explicitly, so a non-GitHub board (Jira, Notion) can NEVER silently inherit
# GitHub's status/field semantics. A missing key refuses the act with an actionable error,
# never a hidden default. Endpoint keys: `base_host`/`collection`/`version_field`/
# `match_field`/`id_field`. Status vocabulary: `state_field`/`open_value`/`closed_value`.
# Field allowlists (comma-lists): `create_fields`/`update_fields` — which body fields a
# create/update may write.
REQUIRED_ACT_CONFIG: tuple[str, ...] = (
    "base_host", "collection", "version_field", "match_field", "id_field",
    "state_field", "open_value", "closed_value", "create_fields", "update_fields")
# The ONE optional key: `search_query` (the dedup-search query, open items only). It is
# not GitHub-hardcoded — when absent it is DERIVED from the tool's OWN declared status
# vocab (`{state_field}={open_value}&per_page={n}`), so there is still no cross-board
# bias. A board whose «list open items» query differs (e.g. JQL) sets it explicitly.
# Default per-page when the search_query declares none. A page THIS full may have a next
# page — the dedup pager fetches the next until a short page (the true end) or the hard
# cap below.
_SEARCH_PAGE_LIMIT = 100
# Hard upper bound on dedup pagination: MAX_PAGES × per_page items. Past it the dedup is
# genuinely inconclusive → the create refuses (surface, never a blind double-post). Keeps
# the reconcile bounded (INV-28 wall-clock) on a pathologically large board.
_SEARCH_MAX_PAGES = 10

# The transport signature: (spec, request-dict, secret) -> ToolResult. In production
# this is `roles_tool_http.exec_tool`; tests inject a fake.
ExecHttp = Callable[[ToolSpec, dict, "str | None"], ToolResult]


class ActError(Exception):
    """A structural act-config / mandate error that must surface (not a per-call
    failure — those become an `ActOutcome` with status `failed`, honest-degrade)."""


@dataclass(frozen=True)
class ActOperation:
    """One act the body proposed (a Stage-2 delta in `payload["acts"]`), plus the
    writer-captured `baseline` (added at Phase-1 stage time — NEVER body-authored).

    `op` ∈ OP_KINDS. `target_ref` names the existing item (update/close); None for
    create. `fields` is the write content the body reasoned (title/body/state).
    `dedup_match` is the idempotency key for create (matched against `match_field`).
    `evidence` cites the in-remit records that justify the act (grounded like an
    emission). `reason` is the human 'why' for the CLARIFICATION + the inbox
    close-event. `baseline` is the version captured at stage time for the TOCTOU
    compare (update/close)."""
    part: str
    tool: str
    op: str
    target_ref: str | None = None
    fields: dict = field(default_factory=dict)
    dedup_match: str = ""
    evidence: tuple[str, ...] = ()
    reason: str = ""
    baseline: str | None = None

    def to_dict(self) -> dict:
        return {
            "part": self.part, "tool": self.tool, "op": self.op,
            "target_ref": self.target_ref, "fields": dict(self.fields),
            "dedup_match": self.dedup_match, "evidence": list(self.evidence),
            "reason": self.reason, "baseline": self.baseline,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "ActOperation | None":
        """Parse a body-proposed act delta. None on a malformed shape (the caller
        drops it, never guesses)."""
        if not isinstance(raw, dict):
            return None
        part = str(raw.get("part") or "").strip()
        tool = str(raw.get("tool") or "").strip()
        op = str(raw.get("op") or "").strip()
        if not part or not tool or op not in OP_KINDS:
            return None
        target_ref = raw.get("target_ref")
        target_ref = str(target_ref).strip() if target_ref not in (None, "") else None
        # create needs no ref but a dedup key; update/close need a ref.
        if op in ("update", "close") and not target_ref:
            return None
        # A present ref MUST be a safe opaque id — it is concatenated into the write URL,
        # so a slash / `..` / query would let the body escape the mandated surface
        # (INV-16). Refuse anything that is not a plain item id (surface, don't guess).
        if target_ref is not None and not _TARGET_REF_RE.match(target_ref):
            return None
        fields = raw.get("fields")
        fields = dict(fields) if isinstance(fields, dict) else {}
        ev = raw.get("evidence")
        evidence = tuple(str(e) for e in ev if str(e).strip()) if isinstance(ev, (list, tuple)) else ()
        return cls(
            part=part, tool=tool, op=op, target_ref=target_ref, fields=fields,
            dedup_match=str(raw.get("dedup_match") or "").strip(),
            evidence=evidence, reason=str(raw.get("reason") or "").strip(),
            # Preserve a captured-empty baseline ("") DISTINCT from "never captured"
            # (None): a target that had no version at stage but gains one at execute must
            # still register as drift, so "" must round-trip as "" (not collapse to None,
            # which skips the TOCTOU compare).
            baseline=(str(raw["baseline"])
                      if "baseline" in raw and raw["baseline"] is not None else None),
        )


@dataclass(frozen=True)
class ActOutcome:
    """The result of staging or executing one act. `status`:
      - `executed`  — the write happened (create POST / update|close PATCH);
      - `skipped`   — idempotent no-op (create matched a live item already present);
      - `drift`     — TOCTOU: the target changed since staging → aborted, surfaced;
      - `failed`    — the transport/HTTP failed (honest-degrade, surfaced);
      - `refused`   — mandate/config refused before any network.
    `effect` is the human one-line summary for the inbox close-event + the log."""
    op: str
    target_ref: str | None
    status: str
    detail: str = ""
    effect: str = ""
    baseline: str | None = None  # set on a successful stage capture

    @property
    def ok(self) -> bool:
        return self.status in ("executed", "skipped")


# -----------------------------------------------------------------------------
# Endpoint construction (INV-19 — from act_config DATA + the mandate surface)
# -----------------------------------------------------------------------------

def build_endpoints(spec: ToolSpec, surface: str) -> dict:
    """Build the REST endpoints from the act tool's `act_config` + the mandate
    `surface`. Raises `ActError` when a required key is missing (surface, don't guess).

    tool = "how to talk to the API" (`base_host`/`collection`/field names); surface =
    "which board" (the mandate-scoped repo/board path). Joined here — never hard-bound
    (INV-16)."""
    cfg = spec.act_config_map()
    missing = [k for k in REQUIRED_ACT_CONFIG if not cfg.get(k)]
    if missing:
        raise ActError(
            f"act tool {spec.tool_id!r} missing act_config keys {missing} — cannot act")
    surface = (surface or "").strip().strip("/")
    if not surface:
        raise ActError(f"act tool {spec.tool_id!r} has no mandate surface — cannot act")
    base = f"{cfg['base_host'].rstrip('/')}/{surface}/{cfg['collection'].strip('/')}"
    create_fields = tuple(f.strip() for f in cfg["create_fields"].split(",") if f.strip())
    update_fields = tuple(f.strip() for f in cfg["update_fields"].split(",") if f.strip())
    if not create_fields or not update_fields:
        raise ActError(
            f"act tool {spec.tool_id!r} has empty create_fields/update_fields — cannot act")
    # `search_query` is derived from the tool's OWN declared status vocab when absent —
    # never a GitHub-hardcoded default (no cross-board bias).
    search_query = cfg.get("search_query") or \
        f"{cfg['state_field']}={cfg['open_value']}&per_page={_SEARCH_PAGE_LIMIT}"
    # Extract the declared per_page (for the dedup pager's short-page detection); default
    # when the query names none.
    per_page = _SEARCH_PAGE_LIMIT
    for frag in search_query.split("&"):
        if frag.strip().lower().startswith("per_page="):
            try:
                per_page = max(1, int(frag.split("=", 1)[1]))
            except (ValueError, IndexError):
                pass
    return {
        "collection_url": base,
        "search_url": f"{base}?{search_query}",
        "per_page": per_page,
        "item_url": base + "/{ref}",
        "version_field": cfg["version_field"],
        "match_field": cfg["match_field"],
        "id_field": cfg["id_field"],
        "state_field": cfg["state_field"],
        "open_value": cfg["open_value"],
        "closed_value": cfg["closed_value"],
        "create_fields": create_fields,
        "update_fields": update_fields,
    }


def _parse_json_result(result: ToolResult) -> tuple[bool, Any, str]:
    """Fold a transport `ToolResult` → (ok, parsed_json, detail). ok is False on a
    non-ok status, a TRUNCATED body, OR an unparseable body (honest-degrade — never a
    guessed value).

    A truncated response (the transport hit its size cap) MUST fail: a partial JSON
    array would make a dedup search look empty and double-create, and a partial item
    body would yield a wrong TOCTOU baseline. Fail-honest is the only safe read."""
    if not result.ok:
        return False, None, result.summary or result.error or "http failed"
    data = result.data if isinstance(result.data, dict) else {}
    body = data.get("body")
    status_code = data.get("status_code")
    if data.get("truncated"):
        return False, None, (f"http {status_code} response truncated at the size cap — "
                             "cannot dedup/re-validate safely (refusing, not guessing)")
    if not isinstance(body, str):
        return False, None, f"http {status_code}: no body"
    try:
        return True, json.loads(body), f"http {status_code}"
    except (TypeError, ValueError):
        # A 2xx with a non-JSON body is still a success for a write that returns text;
        # surface the raw text so the caller can decide (rare for a JSON REST board).
        return True, body, f"http {status_code} (non-json)"


def _http(exec_http: ExecHttp, spec: ToolSpec, secret: str | None,
          method: str, url: str, json_body: dict | None = None) -> tuple[bool, Any, str]:
    """One transport round-trip → (ok, parsed, detail). Any adapter exception becomes
    a clean (False, None, reason) — an act never crashes the writer."""
    req: dict = {"method": method, "url": url}
    if json_body is not None:
        req["json"] = json_body
    try:
        result = exec_http(spec, req, secret)
    except Exception as exc:  # noqa: BLE001 — an adapter bug must not crash the tick
        return False, None, f"transport raised: {exc}"
    if not isinstance(result, ToolResult):
        return False, None, "transport returned a non-ToolResult"
    return _parse_json_result(result)


def _find_live_match(items: Any, match_field: str, needle: str,
                     state_field: str, closed_value: str) -> dict | None:
    """Find a LIVE (not-closed) collection item whose `match_field` equals `needle`
    (case-insensitive, trimmed). Used for create idempotency (INV-28) — a closed item
    does not block a re-open of the same title, only a live duplicate does. The
    state/closed vocabulary is board-configurable (INV-19)."""
    if not isinstance(items, list) or not needle:
        return None
    want = needle.strip().casefold()
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get(state_field, "")).strip().casefold() == closed_value.strip().casefold():
            continue  # skip closed items — only a live duplicate blocks a create
        if str(it.get(match_field, "")).strip().casefold() == want:
            return it
    return None


# -----------------------------------------------------------------------------
# Phase 1 — stage capture (read the baseline; NEVER write)
# -----------------------------------------------------------------------------

def stage_act(
    spec: ToolSpec, surface: str, op: ActOperation, secret: str | None,
    exec_http: ExecHttp,
) -> tuple[ActOperation, ActOutcome]:
    """Phase 1: capture the TOCTOU baseline for an update/close (a READ, never a
    write), or note create-dedup state. Returns (op_with_baseline, stage_outcome).

    A stage that cannot read its target (404 / transport error) yields a `failed`
    outcome and the op is not staged — surfaced honestly, no blind write later. This
    read is the writer's own (baseline is writer-authored, not body-trusted — INV-1)."""
    try:
        ep = build_endpoints(spec, surface)
    except ActError as exc:
        return op, ActOutcome(op.op, op.target_ref, "refused", str(exc))
    if op.op in ("update", "close"):
        url = ep["item_url"].format(ref=op.target_ref)
        ok, parsed, detail = _http(exec_http, spec, secret, "GET", url)
        if not ok or not isinstance(parsed, dict):
            return op, ActOutcome(op.op, op.target_ref, "failed",
                                  f"could not read target for baseline: {detail}")
        baseline = str(parsed.get(ep["version_field"], ""))
        staged = replace(op, baseline=baseline)
        # `status="executed"` here is the internal OK-signal that the stage-time baseline
        # READ succeeded (`stage_out.ok`) — NOT a write. `stage_act` never writes the board;
        # the actual write happens later in `execute_act`. (The value is reused as the ok
        # token to avoid a second status vocabulary; it never surfaces to the owner.)
        return staged, ActOutcome(op.op, op.target_ref, "executed",
                                  detail=f"baseline {ep['version_field']}={baseline}",
                                  baseline=baseline)
    # create — validate the dedup key exists NOW (so a create with no match_field is
    # refused at STAGE, surfaced with the other refusals, not silently at execute). No
    # baseline (idempotency is a re-search at execute).
    if not str(op.fields.get(ep["match_field"], "")).strip():
        return op, ActOutcome(op.op, None, "refused",
                              f"create has no {ep['match_field']} to dedup on")
    return op, ActOutcome(op.op, None, "executed", detail="create staged (dedup at execute)")


def _dedup_find(exec_http: ExecHttp, spec: ToolSpec, secret: str | None, ep: dict,
                needle: str) -> tuple[dict | None, str, str]:
    """Search the board for a LIVE item matching `needle`, PAGING until found or the last
    page. Returns (match|None, status, detail): status ∈ `ok` (searched to the end — match
    is the result or None), `failed` (a transport/parse error), `inconclusive` (past the
    `_SEARCH_MAX_PAGES` cap without reaching the end — the create must refuse, not
    double-post). Appends `&page=N` (the near-universal REST convention); a short page
    (< per_page) is the true end."""
    per_page = ep.get("per_page", _SEARCH_PAGE_LIMIT)
    sep = "&" if "?" in ep["search_url"] else "?"
    for page in range(1, _SEARCH_MAX_PAGES + 1):
        url = f"{ep['search_url']}{sep}page={page}"
        ok, items, detail = _http(exec_http, spec, secret, "GET", url)
        if not ok:
            return None, "failed", detail
        if not isinstance(items, list):
            return None, "failed", "dedup search did not return a list"
        match = _find_live_match(items, ep["match_field"], needle,
                                 ep["state_field"], ep["closed_value"])
        if match is not None:
            return match, "ok", ""
        if len(items) < per_page:
            return None, "ok", ""  # short page = the end; searched fully, no match
    return (None, "inconclusive",
            f"dedup search exceeded {_SEARCH_MAX_PAGES} pages (× {per_page}) without "
            "reaching the end — cannot confirm the item is absent; refusing to avoid a "
            "double-post (the board is unusually large for this reconcile)")


# -----------------------------------------------------------------------------
# Phase 2 — execute (TOCTOU re-validate → write; idempotent)
# -----------------------------------------------------------------------------

def execute_act(
    spec: ToolSpec, surface: str, op: ActOperation, secret: str | None,
    exec_http: ExecHttp,
) -> ActOutcome:
    """Phase 2: execute ONE act idempotently with a TOCTOU re-validate. Returns an
    `ActOutcome`; never raises for a call failure (honest-degrade)."""
    try:
        ep = build_endpoints(spec, surface)
    except ActError as exc:
        return ActOutcome(op.op, op.target_ref, "refused", str(exc))

    if op.op == "create":
        # The idempotency key is the value we are ABOUT TO WRITE for `match_field` — NOT a
        # free-floating body `dedup_match` (which could be decoupled from the posted title,
        # so a retry searches for a needle that never matches and double-posts). Derive it
        # from `fields[match_field]` so dedup is tied to the content (INV-28).
        needle = str(op.fields.get(ep["match_field"], "")).strip()
        if not needle:
            return ActOutcome(op.op, None, "refused",
                              f"create has no {ep['match_field']} to dedup on — refused")
        # Idempotency (INV-28): re-search NOW, PAGING through the board until a live match
        # is found or the last (short) page is reached. A match → skip; a genuinely
        # inconclusive search (past the page cap) → refuse (never a blind double-post).
        match, status, detail = _dedup_find(exec_http, spec, secret, ep, needle)
        if status == "failed":
            return ActOutcome(op.op, None, "failed", f"dedup search failed: {detail}")
        if status == "inconclusive":
            return ActOutcome(op.op, None, "failed", detail)
        if match is not None:
            ref = str(match.get(ep["id_field"], "?"))
            return ActOutcome(op.op, ref, "skipped",
                              detail=f"already present as #{ref}",
                              effect=f"«{needle}» already on the board (#{ref})")
        payload = {k: v for k, v in op.fields.items() if k in ep["create_fields"]}
        ok, created, detail = _http(exec_http, spec, secret, "POST", ep["collection_url"], payload)
        if not ok or not isinstance(created, dict):
            return ActOutcome(op.op, None, "failed", f"create failed: {detail}")
        ref = str(created.get(ep["id_field"], "?"))
        return ActOutcome(op.op, ref, "executed",
                          detail=f"created #{ref}",
                          effect=f"created «{needle}» (#{ref})")

    # update / close — TOCTOU re-validate against the staged baseline.
    url = ep["item_url"].format(ref=op.target_ref)
    ok, current, detail = _http(exec_http, spec, secret, "GET", url)
    if not ok or not isinstance(current, dict):
        return ActOutcome(op.op, op.target_ref, "failed",
                          f"could not re-read target: {detail}")
    now_version = str(current.get(ep["version_field"], ""))
    if op.baseline is not None and now_version != op.baseline:
        return ActOutcome(op.op, op.target_ref, "drift",
                          detail=f"{ep['version_field']} changed {op.baseline} → {now_version} "
                                 "since staged — aborted, not written")
    if op.op == "close":
        # Idempotent: an already-closed item is a no-op success.
        if str(current.get(ep["state_field"], "")).strip().casefold() == ep["closed_value"].casefold():
            return ActOutcome(op.op, op.target_ref, "skipped",
                              detail=f"#{op.target_ref} already closed",
                              effect=f"#{op.target_ref} already closed ({op.reason})")
        body = {ep["state_field"]: ep["closed_value"]}
    else:  # update
        body = {k: v for k, v in op.fields.items() if k in ep["update_fields"]}
        if not body:
            return ActOutcome(op.op, op.target_ref, "refused", "update has no fields")
        # Idempotent (INV-28): if the target already holds exactly these field values, a
        # re-run is a no-op — skip the PATCH so re-reconciling never churns the board.
        if all(str(current.get(k, "")) == str(v) for k, v in body.items()):
            return ActOutcome(op.op, op.target_ref, "skipped",
                              detail=f"#{op.target_ref} already matches — no change",
                              effect=f"#{op.target_ref} already up to date ({op.reason})")
    ok, updated, detail = _http(exec_http, spec, secret, "PATCH", url, body)
    if not ok or not isinstance(updated, dict):
        return ActOutcome(op.op, op.target_ref, "failed", f"{op.op} failed: {detail}")
    verb = "closed" if op.op == "close" else "updated"
    return ActOutcome(op.op, op.target_ref, "executed",
                      detail=f"{verb} #{op.target_ref}",
                      effect=f"{verb} #{op.target_ref} ({op.reason})")
