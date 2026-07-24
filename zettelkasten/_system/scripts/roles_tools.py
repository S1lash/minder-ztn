#!/usr/bin/env python3
"""Tool registry + adapter loader for the Roles subsystem (CONTRACT §2).

A TOOL is a role's reach beyond its own zone — read an external system, verify a
fact, and (in the limit, PLAN 2) act on the world. This module owns the two
archetype-/adapter-AGNOSTIC seams the tools engine hangs on:

  - the **tool spec = DATA** whitelist (`_system/registries/TOOLS.md`), parsed into
    `ToolSpec`s — mirrors SOURCES.md / AUDIENCES.md (a registry the engine reads, not
    code that names a concrete tool);
  - the **adapter loader** `import_tool_adapter(kind)` — dispatch by adapter KIND
    (mirroring `roles_common.import_archetype`), never `if tool ==` / `if adapter ==`
    (INV-19). The taxonomy is closed + small (INV-22): mcp · http · local · web ·
    skill · subagent. No `custom` (customisation lives inside each adapter).

The executable adapters (`roles_tool_{kind}.py`) implement the adapter INTERFACE
documented below; this module never imports one eagerly (fail-closed, on demand).

Tier is a COMPUTED badge, never stored (INV-23): `direction` (read|act) is the rigid
field that cannot lie; T0/T1/T2 is `direction × HITL`, rendered for trust — see
`compute_tier`. `on_error` is FIXED to `declare-unknown` (INV-10 fail-honest).

Deterministic, no LLM, no network. PyYAML-free (the registry is a markdown table,
parsed with the same cell idiom as `_common.parse_extensions_table`). Cross-platform:
`pathlib`, universal-newline reads.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _common import system_dir


# -----------------------------------------------------------------------------
# Closed vocabularies (INV-22, §2.1) — the loader fail-closes on any other value
# -----------------------------------------------------------------------------

TOOL_DIRECTIONS: frozenset[str] = frozenset({"read", "act"})
# Closed + small (INV-22). NO `custom` type; NO inline-prompt "llm-op" tool (a
# reasoning prompt is persona/brief, a bounded sub-call is `subagent`).
TOOL_ADAPTERS: frozenset[str] = frozenset(
    {"mcp", "http", "local", "web", "skill", "subagent"}
)
# Which adapters the CONCIERGE may OFFER to an owner (a proven, exercised capability —
# never a paper tool). `http` is proven end-to-end (read + act, live); `mcp` is
# harness-executed (the SKILL makes the call, exercised via the harness). The rest —
# `web`/`local`/`skill`/`subagent` — are DEFINED seams the registry accepts (a maintainer
# may wire + prove one), but the concierge does NOT propose them until they are proven
# end-to-end, so it never offers a capability that doesn't work. `is_offerable_adapter`
# is the gate the `ztn-role-add` concierge consults.
OFFERABLE_ADAPTERS: frozenset[str] = frozenset({"http", "mcp"})


def is_offerable_adapter(kind: str) -> bool:
    """True when the concierge may OFFER this adapter to an owner (proven end-to-end).
    An unproven-but-defined adapter is refused BY THE CONCIERGE, not the registry — a
    maintainer can still wire one manually once they have proven it (§adapter completeness)."""
    return kind in OFFERABLE_ADAPTERS
TOOL_CADENCE_SLOTS: frozenset[str] = frozenset(
    {"pre-tick-gate", "on-demand", "every-tick"}
)
TOOL_GROUNDING_LANDINGS: frozenset[str] = frozenset(
    {"round-trip", "ephemeral", "verify-existing"}
)

# FIXED (§2.1, INV-10): a tool that cannot complete declares UNKNOWN — never guesses
# a "gone"/empty result. Not a per-tool knob.
ON_ERROR_FIXED = "declare-unknown"

_TOOL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_ADAPTER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# A pinned MCP tool binding — the `mcp__server__tool` shape (INV-23 direction pin).
_MCP_BINDING_RE = re.compile(r"^mcp__[a-zA-Z0-9_]+__[a-zA-Z0-9_]+$")
# A markdown table separator cell: optional leading/trailing colon around one-or-more
# dashes (`---`, `:--`, `--:`, `:-:`). A row of ALL such cells is the header separator.
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_UNLIMITED_TOKENS: frozenset[str] = frozenset({"unlimited", "∞", "inf"})
# A dash / em-dash / empty cell = "no value" in the registry table.
_EMPTY_CELL_TOKENS: frozenset[str] = frozenset({"", "—", "-", "–"})


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------

class ToolError(Exception):
    """Base error for the tools engine."""


class ToolRegistryError(ToolError):
    """`TOOLS.md` is malformed in a way that must surface (rare — the parser is
    tolerant of a single bad ROW, which it drops; this is for a structural break)."""


class ToolAdapterError(ToolError):
    """An adapter kind cannot be loaded / is out of taxonomy / named unsafely."""


# -----------------------------------------------------------------------------
# Tool spec (parsed registry row)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    """One tool the engine may dispatch (a parsed `TOOLS.md` active row).

    `direction` is the RIGID safety field (INV-23). `max_calls_per_run` is the
    per-tool budget: an int cap OR `None` = owner-granted UNLIMITED (INV-20) — the
    cumulative act/inbox ceiling (`roles_budget`) bounds irreversible surfaces
    regardless. `credential_ref` is `secret://<name>` or None (never inline —
    INV-12). `plain_purpose` / `usage_note` are the CONCIERGE_MANIFEST surface the
    runner concatenates into the Stage-1 frame so the body knows what hands it has
    (§2.3, §3). `on_error` is FIXED.
    """
    tool_id: str
    direction: str
    adapter: str
    cadence_slot: str
    grounding_landing: str
    max_calls_per_run: int | None  # None = unlimited
    credential_ref: str | None
    plain_purpose: str
    usage_note: str
    status: str
    on_error: str = ON_ERROR_FIXED
    # For an `mcp` tool: the ONE concrete `mcp__server__tool` this tool_id is PINNED
    # to (INV-23 — the body cannot redirect a `read` tool to an act MCP tool). None
    # for non-mcp adapters. The registry parser drops an `mcp` row with no valid
    # binding (unsafe — an unpinned mcp tool would let the body choose the target).
    mcp_binding: str | None = None
    # For an `act` tool driven by `roles_act` (a REST-board rmw): the endpoint config
    # as DATA (INV-19 — dispatch by config, never `if tool ==`). Parsed from the
    # `Act Config` cell (semicolon-delimited `key=value`): `base_host` (the API host,
    # e.g. https://api.github.com), `collection` (the item collection, e.g. issues),
    # `version_field` (the TOCTOU version, e.g. updated_at), `match_field` (the
    # idempotency key for create, e.g. title), `id_field` (the item id field, e.g.
    # number). The specific target (the repo/board) is the MANDATE `surface`, joined at
    # act time — so tool = "how to talk to the API", surface = "which board" (INV-16).
    # Empty for a read tool. `frozenset`-of-items shape via a tuple so ToolSpec stays
    # hashable/frozen; exposed as a dict by `act_config_map`.
    act_config_items: tuple[tuple[str, str], ...] = ()

    @property
    def is_read(self) -> bool:
        return self.direction == "read"

    @property
    def is_act(self) -> bool:
        return self.direction == "act"

    def act_config_map(self) -> dict[str, str]:
        """The act-endpoint config as a dict (INV-19 data). Empty for a read tool."""
        return dict(self.act_config_items)

    @property
    def credential_host(self) -> str | None:
        """The single API host a CREDENTIAL-bearing `http`/`local` tool may talk to —
        the `base_host` declared in its `Act Config` cell, as a bare host (no scheme).
        None when undeclared. Load-bearing for INV-12: the http adapter attaches the
        Bearer token ONLY to a request whose URL host equals this, so a body-chosen URL
        cannot exfiltrate the secret to an arbitrary host. A read tool that carries a
        `credential_ref` MUST declare `base_host` (else the adapter refuses — fail-closed).
        Act tools already declare it (roles_act builds the URL from it)."""
        base = self.act_config_map().get("base_host", "").strip()
        if not base:
            return None
        # Strip scheme + any path; keep host[:port], lowercased.
        host = base.split("://", 1)[-1].split("/", 1)[0].strip().lower()
        return host or None


def is_unlimited(spec: ToolSpec) -> bool:
    """True when the tool's per-run call budget is owner-granted unlimited."""
    return spec.max_calls_per_run is None


@dataclass(frozen=True)
class ToolResult:
    """The envelope a tool call returns to the TOOL STAGE (CONTRACT §3, INV-10).

    `data` is EPHEMERAL, tick-local reasoning input — the runner feeds it to the
    body and NEVER commits the raw return to the repo (that would bloat it) and it
    NEVER grounds a persisted delta. Only `raw_hash` + `summary` land in the
    append-only tool audit for observability. `status` is `ok` | `unknown` | `error`
    — `on_error: declare-unknown` (INV-10) means an adapter that cannot complete
    returns `unknown`, never a guessed value. `is_external` marks external-tool
    content so the injection firewall (INV-17) can HITL-gate a write derived from
    this tick — reading the role's own zone is NOT external ingestion.
    """
    tool_id: str
    status: str
    data: Any = None
    summary: str = ""
    raw_hash: str = ""
    is_external: bool = True
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @staticmethod
    def unknown(tool_id: str, reason: str, is_external: bool = True) -> "ToolResult":
        """The FIXED `on_error: declare-unknown` outcome — honest, never a guess."""
        return ToolResult(
            tool_id=tool_id, status="unknown", summary=reason, error=reason,
            is_external=is_external,
        )


def compute_tier(spec: ToolSpec, hitl: bool) -> str:
    """The computed trust badge (INV-23) — NEVER a stored field.

    `direction × HITL`: a read tool is T0 (read-hand); an act behind HITL is T1
    (round-trip / owner-gated); an autonomous act is T2. Rendered for UI/trust only.
    """
    if spec.is_read:
        return "T0"
    return "T1" if hitl else "T2"


# -----------------------------------------------------------------------------
# Registry parse (data whitelist — mirrors SOURCES/AUDIENCES)
# -----------------------------------------------------------------------------

def tools_registry_path(base: Path | None = None) -> Path:
    return system_dir(base) / "registries" / "TOOLS.md"


def _parse_budget(cell: str) -> int | None | str:
    """Parse the Budget cell → int cap, None (unlimited), or the sentinel
    `"__bad__"` when neither (so the caller drops the row — a budget must be
    explicit, never silently defaulted to unlimited)."""
    token = cell.strip().lower()
    if token in _UNLIMITED_TOKENS:
        return None
    try:
        n = int(token)
    except ValueError:
        return "__bad__"
    return n if n >= 1 else "__bad__"


def _parse_credential(cell: str) -> str | None:
    token = cell.strip()
    return None if token in _EMPTY_CELL_TOKENS else token


def _parse_act_config(cell: str) -> tuple[tuple[str, str], ...]:
    """Parse the `Act Config` cell (semicolon-delimited `key=value`) → sorted items.

    Empty / dash → `()`. Malformed pairs (no `=`, empty key) are skipped tolerantly
    (a bad fragment never takes the row down; `roles_act` validates the REQUIRED keys
    at act time and refuses honestly if one is missing). No `|` may appear (table
    safety); keys/values are trimmed. Deterministic order (sorted) so the frozen
    ToolSpec is stable across reads."""
    token = cell.strip()
    if token in _EMPTY_CELL_TOKENS:
        return ()
    out: dict[str, str] = {}
    for pair in token.split(";"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return tuple(sorted(out.items()))


def _row_to_spec(cells: list[str]) -> ToolSpec | None:
    """Build a ToolSpec from a parsed table row, or None to DROP a malformed row.

    A single bad row is dropped (not fatal) so one typo cannot take the whole
    registry down — the same tolerance SOURCES/AUDIENCES parsing uses. A dropped
    tool simply is not grantable; the grant-check surfaces its absence honestly.
    """
    if len(cells) < 12:
        return None
    (tool_id, direction, adapter, cadence_slot, landing, budget_cell,
     cred_cell, binding_cell, act_config_cell, purpose, usage, status) = cells[:12]
    tool_id = tool_id.strip()
    adapter = adapter.strip()
    if not _TOOL_ID_RE.match(tool_id):
        return None
    if direction.strip() not in TOOL_DIRECTIONS:
        return None
    if adapter not in TOOL_ADAPTERS:
        return None
    if cadence_slot.strip() not in TOOL_CADENCE_SLOTS:
        return None
    if landing.strip() not in TOOL_GROUNDING_LANDINGS:
        return None
    budget = _parse_budget(budget_cell)
    if budget == "__bad__":
        return None
    if status.strip().lower() != "active":
        return None
    # MCP binding: an `mcp` tool MUST pin a valid `mcp__server__tool` (INV-23) — an
    # unpinned mcp row is dropped (the body must never choose the MCP target). A
    # non-mcp tool ignores the cell (None).
    binding = binding_cell.strip()
    mcp_binding: str | None = None
    if adapter == "mcp":
        if not _MCP_BINDING_RE.match(binding):
            return None  # drop — unsafe unpinned mcp tool
        mcp_binding = binding
    return ToolSpec(
        tool_id=tool_id,
        direction=direction.strip(),
        adapter=adapter,
        cadence_slot=cadence_slot.strip(),
        grounding_landing=landing.strip(),
        max_calls_per_run=budget,  # int or None
        credential_ref=_parse_credential(cred_cell),
        plain_purpose=purpose.strip(),
        usage_note=usage.strip(),
        status="active",
        mcp_binding=mcp_binding,
        act_config_items=_parse_act_config(act_config_cell),
    )


_HEADER_TOKENS: frozenset[str] = frozenset({"tool id", "toolid", "id"})


def load_tools_registry(base: Path | None = None) -> dict[str, ToolSpec]:
    """Parse the ACTIVE tools whitelist from `TOOLS.md` → `{tool_id: ToolSpec}`.

    Tolerant: a missing file → `{}`; a malformed row → dropped; only `status:
    active` rows are returned (the grant path never sees a deprecated/reserved
    tool). The single home for reading the registry — the runner grant-checks a
    body's `tool_request` against this.
    """
    path = tools_registry_path(base)
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out: dict[str, ToolSpec] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        # A markdown separator row is EVERY cell matching `:?-+:?` — detect it
        # structurally, NOT by a `---` substring (which would also drop a real data
        # row whose cell text happens to contain `---`, e.g. a purpose «3---5 items»).
        if all(_SEPARATOR_CELL_RE.match(c) for c in cells):
            continue
        if cells[0].lower() in _HEADER_TOKENS:  # header row
            continue
        spec = _row_to_spec(cells)
        if spec is not None:
            out[spec.tool_id] = spec
    return out


def get_tool(tool_id: str, base: Path | None = None) -> ToolSpec | None:
    """Return the active `ToolSpec` for `tool_id`, or None when absent/inactive."""
    return load_tools_registry(base).get(tool_id)


# -----------------------------------------------------------------------------
# Adapter loader — the seam (this module never hardcodes an adapter kind)
# -----------------------------------------------------------------------------
# ADAPTER INTERFACE CONTRACT (implemented by each `roles_tool_{kind}.py`, CONTRACT
# §2.2 — an entirely NEW interface, nothing like a part plugin's):
#
#   ADAPTER_KIND: str                    — must equal the kind (self-identifying)
#   HARNESS_EXECUTED: bool               — capability flag (dispatch by flag, INV-19):
#       False → Python-executable: the TOOL STAGE calls
#           exec_tool(spec, request, secret) -> ToolResult   (runs in-process; http/local/web)
#       True  → harness-executed: Python cannot make the call (an MCP tool / a skill is
#           driven by the Claude Code harness), so the adapter splits into
#           prepare(spec, request, secret) -> dict           (the descriptor the SKILL invokes)
#           normalize(spec, raw_result) -> ToolResult        (fold the harness return back)
#
# In BOTH shapes the deterministic runner owns grant-check → secret-resolve →
# per-tool budget → tool audit; only the actual call site differs. `on_error` is
# FIXED `declare-unknown` — an adapter that cannot complete returns a `ToolResult`
# with status `unknown`, never a guessed value (INV-10 fail-honest). `ToolResult`
# is defined above (shared home — both the TOOL STAGE and every adapter import it
# from here, so there is no import cycle).

def import_tool_adapter(kind: str):
    """Import the adapter module `roles_tool_{kind}` by its adapter KIND.

    Mirrors `roles_common.import_archetype`: validate the name is a safe lowercase
    identifier AND a member of the closed taxonomy (INV-22 — `custom` and any
    out-of-taxonomy name are refused BEFORE import), then `importlib.import_module`.
    Fail-closed: raises `ToolAdapterError` on an unsafe name, an out-of-taxonomy
    kind, or an absent module.
    """
    if not isinstance(kind, str) or not _ADAPTER_NAME_RE.match(kind):
        raise ToolAdapterError(f"unsafe adapter kind: {kind!r}")
    if kind not in TOOL_ADAPTERS:
        raise ToolAdapterError(
            f"adapter kind {kind!r} is not in the closed taxonomy "
            f"{sorted(TOOL_ADAPTERS)} (no `custom` type — INV-22)"
        )
    module_name = f"roles_tool_{kind}"
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ToolAdapterError(
            f"adapter module {module_name!r} not found ({exc})"
        ) from exc


def is_harness_executed(adapter_module: Any) -> bool:
    """True when the adapter needs the Claude Code harness to make the call (mcp /
    skill) rather than executing in-process (http / local / web). Capability-flag
    dispatch (INV-19) — the TOOL STAGE branches on this, never on the kind name."""
    return bool(getattr(adapter_module, "HARNESS_EXECUTED", False))
