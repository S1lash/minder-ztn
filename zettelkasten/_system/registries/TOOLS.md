# Tools Registry

Whitelist of the tools a role may be granted (CONTRACT §2, `platform/roles/`). A
tool is a role's reach beyond its own zone — read an external system, verify a
fact, and act on the world. The spec is **data**; the executable adapter
(`roles_tool_{adapter}.py`) lives in `_system/scripts/`. A role grants a tool by
naming its `Tool ID` in a part's `tools:` list; the runner grant-checks against
this registry before executing (never trusts the body's request).

Adding a tool is declarative — append an **active** row here (the concierge does
this on your request) and, if the tool needs auth, store its credential via the
concierge's first-secret flow (`secret://<name>`). No SKILL code change is needed
to grant an existing adapter kind to a role.

---

## Schema (one active row per tool)

| Column | Values | Meaning |
|---|---|---|
| `Tool ID` | kebab-case slug | the ref a part grants in its `tools:` list |
| `Direction` | `read` / `act` | RIGID safety field (INV-23) — `read` pulls context; `act` writes the world (needs a mandate) |
| `Adapter` | `mcp` / `http` / `local` / `web` / `skill` / `subagent` | closed taxonomy (INV-22); selects `roles_tool_{adapter}.py` |
| `Cadence Slot` | `pre-tick-gate` / `on-demand` / `every-tick` | wired (fixed slot) vs reasoned (body-requested) — INV-21 |
| `Grounding Landing` | `round-trip` / `ephemeral` / `verify-existing` | how a return may persist — a `read` tool is `ephemeral` (never grounds state, INV-10) unless it round-trips via the inbox |
| `Budget` | `unlimited` / an int | per-tool call cap per run (INV-20); `unlimited` = conscious owner grant; the cumulative act/inbox ceiling still bounds writes |
| `Credential` | `secret://<name>` / `—` | never inline (INV-12); resolved by the runner in memory at run time |
| `MCP Binding` | `mcp__server__tool` / `—` | for an `mcp` tool: the ONE concrete MCP tool this tool_id is PINNED to (INV-23 — `direction` cannot lie: the body cannot redirect a `read` tool to an act MCP tool). Required for `mcp`; `—` for other adapters. An `mcp` row with no binding is dropped (unsafe). |
| `Act Config` | `k=v;k=v` / `—` | for an `act` tool driven by `roles_act` (a REST-board rmw): the endpoint config as DATA (INV-19 — dispatch by config, never `if tool ==`). Semicolon-delimited. **REQUIRED** (every act tool declares its OWN board vocabulary — refuse-don't-assume, so a non-GitHub board never silently inherits GitHub semantics): `base_host` (API host) `collection` (item collection) `version_field` (TOCTOU version) `match_field` (create-idempotency key) `id_field` (item id) `state_field`/`open_value`/`closed_value` (the status vocabulary) `create_fields`/`update_fields` (comma-lists — which body fields a create/update may write). A missing required key refuses the act with an actionable error. **OPTIONAL:** `search_query` (the dedup-search query) — when absent it is DERIVED from the tool's own `state_field`/`open_value` (no cross-board bias); set it for a board whose «list open items» query differs (e.g. JQL). The SPECIFIC board is the mandate `surface`, joined at act time (tool = how to talk to the API, surface = which board — INV-16). `—` for a read tool. No `\|`. |
| `Plain Purpose` | one line, no `\|` | the CONCIERGE_MANIFEST purpose the frame shows the body (§2.3) |
| `Usage Note` | one line, no `\|` | when/how the body should reach for it (§3) |
| `Status` | `active` / `deprecated` | only `active` rows are grantable |

`on_error` is FIXED (`declare-unknown`, INV-10) — not a column. Tier is a computed
badge (`direction × HITL`), never stored (INV-23).

> **Cells carry no `|`.** A free-text cell containing a pipe breaks the table; keep
> `Plain Purpose` / `Usage Note` single-clause. Longer guidance lives in the tool's
> adapter module docstring, not here.
>
> **`mcp` credential + binding semantics.** For an `mcp` tool the Claude Code harness
> holds the connection's auth (the MCP server is authorised in the harness), so the
> runner does NOT pass a token into the MCP call — a `Credential` on an `mcp` row is a
> «this integration is wired» signal (an unresolvable `secret://` honest-degrades the
> tool). The `secret://` → token injection is used by the Python-exec adapters
> (`http`/`local`/`web`), where the runner adds it as a header. **Pin an `mcp` read
> tool only to a genuinely READ endpoint** — the pin fixes the tool, but its `args`
> are body-authored, so a mis-pin of a `read` tool_id to a mutating `mcp__*` tool would
> let the body drive a mutation. The concierge verifies the binding at creation.

---

## Active Tools

The concierge appends your tools here on request. A generic public-HTTP reader ships
as a baseline; everything else (your Drive, your board, your web search) is added
when you ask for a role that needs it.

| Tool ID | Direction | Adapter | Cadence Slot | Grounding Landing | Budget | Credential | MCP Binding | Act Config | Plain Purpose | Usage Note | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| http-get | read | http | on-demand | ephemeral | 3 | — | — | — | Fetches a public web endpoint over HTTP. | Read a small public JSON/text endpoint when you need a live value. | active |

---

## Act tools — how they run

An `act` tool writes the world. It ships as an `http`/`local` adapter ONLY (never
`mcp`/`skill`) so the deterministic writer injects the secret in-process, out of the
LLM's sight (INV-12): the runner IS the LLM in the harness, so a token in an MCP call
would enter LLM context. An act runs ONLY inside the writer's post-persist step
(`roles_act`), under a **live role `mandate`** whose `scope` names the target tool +
the specific `surface` (the repo / board — INV-16); an act with no live mandate is
refused. In the harness every act is **HITL-staged** (`role-act-confirm`) and executed
on your approval (`/ztn:roles --approve-acts <id>`) — `autonomy: autonomous` degrades
to advisory until a verified sandboxed runtime (`ZTN_ROLES_CAGE_VERIFIED`). Execution
is idempotent + TOCTOU-re-validated + atomic (persist → act → on full success emit the
inbox close-event + advance the watermark; on failure neither — §6.5).

An act board is registered by the concierge as an `act` row carrying an `Act Config`
(a REST-board rmw: `base_host;collection;version_field;match_field;id_field`) — the same
generic engine drives any REST board (a GitHub-issues board, a Jira project, a Notion
database) by config alone; the specific board is the mandate `surface`.
