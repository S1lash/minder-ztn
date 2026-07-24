#!/usr/bin/env python3
"""MCP read adapter for the Roles tool seam (CONTRACT §2.2, adapter kind `mcp`).

A HARNESS-EXECUTED adapter (`HARNESS_EXECUTED = True`): a Python process cannot
call an MCP server — the Claude Code harness makes MCP calls on the LLM side. So
this adapter does NOT run the call in-process; it splits into two deterministic
halves the TOOL STAGE + SKILL drive around the harness (INV-1 stays clean — the
deterministic runner owns grant-check → secret-resolve → budget → audit; only the
actual call site is the harness):

  prepare(spec, request, secret) -> descriptor   # what the SKILL must invoke
  normalize(spec, raw_result)   -> ToolResult    # fold the harness return back

The runner (the `ztn-roles` SKILL) grant-checks the tool_id, resolves the secret,
budget-checks, then — for a harness-executed adapter — reads the descriptor, makes
the MCP call itself (the granted tool is available to the tool-restricted subagent
runtime, INV-15), and hands the raw return to `normalize`. The result is EPHEMERAL
(INV-10): fed to the body, never committed to the repo, never grounds state.
`on_error: declare-unknown` (INV-10) — a failed/empty MCP return normalises to
`unknown`, never a guess.

> **MCP-tool binding is PINNED in the registry (INV-23).** The concrete `mcp__*`
> tool a tool_id maps to is `spec.mcp_binding` (the `MCP Binding` column in TOOLS.md),
> NOT chosen by the body. `prepare` uses the pinned binding and REJECTS a body-supplied
> `mcp_tool` that differs — so a prompt-injected body cannot redirect a `read` tool
> (e.g. `notion-board`) to an act MCP tool (e.g. `notion__update_page` / a Slack send).
> `direction: read` therefore cannot lie: a read tool_id is structurally bound to one
> read MCP tool. The registry parser drops an `mcp` row with no valid binding, so a
> live-granted mcp tool always carries one.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from roles_tools import ToolResult, ToolSpec

ADAPTER_KIND = "mcp"
HARNESS_EXECUTED = True

# An MCP tool name the harness may be asked to call — the `mcp__server__tool` shape.
_MCP_TOOL_RE = re.compile(r"^mcp__[a-zA-Z0-9_]+__[a-zA-Z0-9_]+$")


def prepare(spec: ToolSpec, request: Any, secret: str | None) -> dict:
    """Build the descriptor the SKILL invokes for one MCP read.

    Returns `{ok: bool, ...}`. On a malformed request → `{ok: False, reason}` so
    the TOOL STAGE emits a `declare-unknown` without ever touching the harness.
    `secret` is NOT placed in the descriptor as plaintext (INV-12); it is passed
    to the harness call out of band by the runner (most MCP servers are pre-
    authorised in the harness, so `secret` is often None). `requires_secret`
    tells the runner whether a resolved credential must accompany the call.
    """
    tid = spec.tool_id
    if not isinstance(request, dict):
        return {"ok": False, "tool_id": tid,
                "reason": "mcp request must be a mapping"}
    # The MCP tool is PINNED in the registry (INV-23) — the body does NOT choose it.
    pinned = spec.mcp_binding
    if not isinstance(pinned, str) or not _MCP_TOOL_RE.match(pinned):
        return {"ok": False, "tool_id": tid,
                "reason": f"tool {tid} has no valid pinned MCP binding — refusing "
                          "(an unpinned mcp tool would let the body choose the target)"}
    proposed = request.get("mcp_tool")
    if proposed is not None and proposed != pinned:
        # A body attempt to REDIRECT the tool to a different MCP tool — refuse (this is
        # the confused-deputy / direction-lie attack: a read tool → an act MCP tool).
        return {"ok": False, "tool_id": tid,
                "reason": f"tool {tid} is pinned to {pinned!r}; body proposed "
                          f"{proposed!r} — redirect refused (INV-23 direction pin)"}
    mcp_tool = pinned
    args = request.get("args")
    if args is not None and not isinstance(args, dict):
        return {"ok": False, "tool_id": tid,
                "reason": "mcp request 'args' must be a mapping when present"}
    return {
        "ok": True,
        "tool_id": tid,
        "mcp_tool": mcp_tool,
        "args": args or {},
        "requires_secret": spec.credential_ref is not None,
        "direction": spec.direction,
    }


def normalize(spec: ToolSpec, raw_result: Any) -> ToolResult:
    """Fold the harness's raw MCP return into a `ToolResult` (ephemeral, hashed).

    A None / empty return normalises to `unknown` (declare-unknown — never a
    guessed value). A structured/text return becomes ephemeral `data` with a
    one-line `summary` and a `raw_hash` for the audit; `is_external=True` so the
    injection firewall (INV-17) HITL-gates any write derived from this tick.
    """
    tid = spec.tool_id
    if raw_result is None:
        return ToolResult.unknown(tid, f"mcp tool {tid} returned nothing")
    try:
        serialised = json.dumps(raw_result, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        serialised = str(raw_result)
    if not serialised.strip() or serialised.strip() in ("{}", "[]", '""'):
        return ToolResult.unknown(tid, f"mcp tool {tid} returned an empty result")
    raw_bytes = serialised.encode("utf-8")
    return ToolResult(
        tool_id=tid,
        status="ok",
        data=raw_result,
        summary=f"mcp {tid} — {len(raw_bytes)} bytes",
        raw_hash=hashlib.sha256(raw_bytes).hexdigest(),
        is_external=True,
    )
