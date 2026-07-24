---
name: ztn:roles
description: >
  Tick runner for the ZTN Roles subsystem. Discovers roles under
  _system/roles/{id}/, filters by cadence (is_due) and activation
  (by_change / by_elapsed_time), and for each due role assembles the shared
  frame (_system/roles/_frame.md) + persona/remit + standing brief + one
  body-free prior skeleton per composed part +
  the minder_query zone index + a granted-tools manifest (the tool-restricted body
  is a pure reasoner — it PROPOSES read_requests/tool_requests the runner fulfils
  via `minder_query --enforced --role` + the TOOL STAGE, INV-15), runs
  thinker→structurer to a delta-payload JSON (may reach external tools + emit inbox
  notes), and hands it to roles_persist.py — the SOLE writer and control boundary.
  The body never edits parts/*.json or state.md. `--approve-coldstart` adopts a
  frozen cold-start draft; `--approve-acts` executes a role's staged outward acts
  (Phase 2). Asking a role a question is a separate read-only skill,
  /ztn:role:ask (not here). Best-effort, idempotent, scheduler-safe.
disable-model-invocation: false
---

# /ztn:roles — Roles tick runner

A **role** is a standing agent that watches ONE zone (remit) of the owner's ZTN
base and keeps a small composition of working PARTS about what is happening there
— with its own persona, its own cadence, and its own parts (each an archetype:
`ledger`, `narrative`, …). This skill is the orchestrator that runs a role's
`tick` (update its parts from what changed). Answering a role's questions is a
separate read-only skill, `/ztn:role:ask`.

**The safety model — read this first.** The tick BODY (the LLM) only *proposes*
a structured delta payload; it **never writes state**. The sole writer is the
deterministic `roles_persist.py`, which runs the archetype validator FIRST and
only then persists. An ungrounded, invalid, or churny delta is rejected
regardless of what the body intended. This control boundary is what lets the
free-form body run safely — the skill orchestrates the body and then routes its
proposal through `roles_persist.py`; it never touches any `parts/{part_id}.json`
or `state.md` itself.

**Philosophy:**

- **Control boundary, not trust.** Two LLM stages (thinker → structurer) produce
  a delta payload; the deterministic third stage (`roles_persist.py`) is the only
  thing that writes. The skill is the wiring between them, never a writer.
- **Part-kind-agnostic.** The skill NEVER names a concrete part-kind. A role is a
  composition of parts (`config.parts[]`, each `{id, kind}`); `roles_persist.py`
  loads each part's plugin by its `kind` and validates / persists through the
  composite seam. `ledger` and `narrative` are built; a third kind plugs in without
  any change here.
- **Hard-locked reading (propose/dispose — INV-1/15).** A role reasons about its
  own zone but CANNOT read it directly. It is handed the zone INDEX (`minder_query
  --list` — path / type / status / trio per in-remit note, no bodies) and decides
  what it wants to open; it PROPOSES `read_requests[]` and the runner fulfils each
  via `minder_query.py --enforced --role {id} --read <path>` (role-bound — an
  out-of-remit path is refused, and `--config`/`--remit-json` are refused
  unconditionally). The body holds no filesystem or query tool. `minder_query` is a thin scoped
  resolver that FEEDS and BOUNDS the frame, not a hard filesystem gate: it never
  returns anything out of remit (an out-of-remit `--read` is refused, an
  out-of-remit sensitive note is never listed), so the thinker navigates freely
  WITHIN its remit and cannot reach past it.
- **Cold-start = frozen staging + HITL.** The first tick over an empty PART is
  minted into that part's `staging` (not live) and surfaced as `role-cold-start`;
  the same frozen draft re-surfaces until the owner approves it. New records before
  approval do not change the frozen draft and are not marked seen — the first
  tick after approval reviews them; never re-drafted. Each part cold-starts
  independently; one `--approve-coldstart` adopts every pending part.
- **Per-role isolation.** Roles are independent — no cross-role synthesis, no
  carry-over. Each role's frame stages run in fresh context. One role's error
  never aborts the sweep.
- **Best-effort over hard-fail.** A single role error (bad config, resolver
  failure) logs an `error` run and is skipped; the sweep continues. Surface,
  don't decide silently (doctrine §3.1).
- **Cadence-honest.** The scheduler fires the tick daily; per-role cadence is
  enforced inside the skill via `is_due()`. A daily tick is not a daily role run.
- **Tick-only.** This runner updates role state; it never answers questions — the
  read-only `ask` path lives in `/ztn:role:ask`.

**Language convention (load-bearing):**

Lock the user-facing language at the first turn.

- **User-facing output** — exit-status lines, summaries, cold-start / approval
  prompts surfaced to the owner — MUST be in the owner's language. Detect from:
  (1) most recent records in `_records/` (last 7 days, language of body text),
  (2) `_system/SOUL.md` body text, (3) fall back to English. Detection happens in
  Step 1.
- **Generated role content** — the thinker's reasoning — MUST be in the language
  the role's persona and remit are written in (the role's `config.yml` / hook
  bodies establish it). The frame carries no language of its own.
- **Internal artefacts** — `log_roles.md` block headers, `roles-runs.jsonl` field
  values, exit-status tokens, `CLARIFICATIONS.md` machine fields, file paths —
  English only. Never localised. (`roles_persist.py` renders these itself.)

This mirrors `/ztn:process` and `/ztn:agent-lens`: user-facing in the owner's
language, machine state in English.

**Documentation convention:** on any edit to this SKILL, follow
`_system/docs/CONVENTIONS.md` — describe current behaviour, no version / phase /
rename history, no personal names (placeholders, or read `SOUL.md` at runtime).

**Contracts:**

- `_system/docs/ENGINE_DOCTRINE.md` — operating philosophy (load first): §3.1
  surface-don't-decide, §3.3 idempotency, §3.4 lock matrix, §3.5 logs, §3.6
  owner-LLM contract.
- `_system/docs/SYSTEM_CONFIG.md` — cross-skill lock matrix, log ownership,
  CLARIFICATIONS format, the `role-*` CLARIFICATION types (registered in SYSTEM_CONFIG.md).
- `_system/roles/_frame.md` — the shared three-stage frame (thinker / structurer
  / writer) every role tick runs inside.
- `_system/scripts/minder_query.py` — scoped remit resolver (remit → zone index /
  search / read; the body's navigation tool).
- `_system/scripts/roles_persist.py` — SOLE WRITER + control boundary.
- `_system/scripts/roles_common.py` — discovery, config loader, `is_due`, run/log
  writers (the skill imports these for the deterministic pre-flight steps).

> **Schema expectations.** The skill relies on: `_system/roles/_frame.md`, each
> role's `_system/roles/{id}/config.yml` + `hooks/tick.md`, the helper
> scripts above, `_system/state/roles-runs.jsonl`, `_system/state/log_roles.md`.
> A missing engine file (`_frame.md`, a helper script) is catastrophic — abort
> with a clear status + log entry. A single malformed role (`config.yml`
> unreadable) is role-level — log an `error` run and skip, continue with the rest.

---

## Arguments

`$ARGUMENTS` supports:

| Invocation | Mode | Purpose |
|---|---|---|
| `--all-due` (default if no other mode) | **tick sweep** | Run every active role whose cadence has elapsed AND whose activation gate fires. Used by the scheduled tick. |
| `--role <id>` | **single tick** | Run one named active role regardless of due-status. Owner-driven testing. |
| `--approve-coldstart <role-id>` | **cold-start approval** | Adopt the role's frozen cold-start draft live. Writes via `roles_persist.py`; takes the lock. |
| `--approve-acts <role-id>` | **act approval** | Execute the role's staged outward acts (Phase 2 — idempotent + TOCTOU-revalidated). On full success feeds the coupled inbox close-events + advances the watermark; on drift / failure neither. Writes via `roles_persist.py`; takes the lock. |
| `--dry-run` | modifier | With `--all-due` / `--role`: run the frame stages and print the delta payload, but do NOT call `roles_persist.py` — nothing is persisted, no runs / logs / CLARIFICATIONS written. For prompt iteration. |
| `--force` | modifier | Bypass the Step-0.3 recent-run guard. The scheduled tick passes it implicitly via cron timing. |

Modes are mutually exclusive in spirit: `--role X` overrides `--all-due`;
`--approve-coldstart` and `--approve-acts` are standalone. The scheduled tick uses
`--all-due` (with `--force` by cron alignment).

**Asking a role a question is NOT here.** The read-only `ask` path is its own skill,
`/ztn:role:ask` (the 3-tier ladder + STT-tolerant reference resolution). This runner
is tick-only: it updates role state and never answers questions. `roles_persist.py`
still refuses an `ask`-hook payload as a safety, but this skill never produces one.

---

## Mode: `--approve-coldstart <role-id>` — adopt the frozen draft

A write mode: it goes through the competitor-lock check (Step 0.2) and acquires
`.roles.lock` (Step 0.5), then:

```bash
python3 _system/scripts/roles_persist.py --role <id> --approve-coldstart
```

`roles_persist.py` adopts the frozen `staging` draft live, advances the
`seen_watermark` (the go-live moment), writes `state.md`, appends
`decisions.jsonl`, and — as the sole writer — appends the `roles-runs.jsonl` +
`log_roles.md` entries itself. Parse its stdout summary (`outcome:
"cold-start-approved"`, `run_status`, `counts`) and surface it. If there is no
frozen draft (`staging` empty), `roles_persist.py` raises and prints an `error`
summary — surface it («no cold-start draft to approve for '{id}'»). Release the
lock in the finally.

---

## Mode: `--approve-acts <role-id>` — execute the staged acts (Phase 2)

The owner-approval half of the two-phase HITL act (§6.5). Phase 1 ran inside a tick:
the body proposed `acts[]`, and `roles_persist.py` validated the mandate, captured the
TOCTOU baseline, staged the acts into `_system/roles/{id}/pending_acts.json`, and
surfaced ONE `role-act-confirm` CLARIFICATION — executing nothing. This mode is what
the owner runs to carry them out.

A write mode: it goes through the competitor-lock check (Step 0.2) and acquires
`.roles.lock` (Step 0.5), then:

```bash
python3 _system/scripts/roles_persist.py --role <id> --approve-acts
```

`roles_persist.py` executes each staged act idempotently with a fresh TOCTOU
re-validate (create = search-by-title first; update / close = re-read the target,
compare `updated_at` to the captured baseline, then PATCH). Then:

- **On confirmed FULL success:** it emits the coupled inbox close-events, advances the
  trigger watermark (the act-coupled commit — INV-26), records the cumulative act /
  inbox budget, and clears `pending_acts.json`. Prints `outcome: "acts-executed"`,
  `run_status: "ok"`.
- **On any drift / failure:** it surfaces `role-act-drift` (the target changed since
  staging — no write over someone else's change) and / or `role-act-failed` (the write
  itself failed), advances NEITHER the inbox nor the watermark (§6.5 atomicity), and
  clears the pending store so the next tick re-reconciles from fresh state. Prints
  `outcome: "acts-partial"`, `run_status: "rejected"`.
- **No staged acts** (`pending_acts.json` empty / absent) → `outcome: "no-pending-acts"`,
  `run_status: "empty"` — surface it («no staged acts to approve for '{id}'»).

As the sole writer, `roles_persist.py` appends the `roles-runs.jsonl` + `log_roles.md`
entries itself. Parse its stdout summary (`outcome`, `run_status`, `counts`,
`clarifications`) and surface it. Release the lock in the finally.

---

## Pre-flight: data freshness (non-blocking; tick / approve modes only)

Multi-device safeguard. If `origin` has commits not yet pulled, a tick may
observe a stale corpus. The scheduled tick runs `/ztn:sync-data` in Step 3 of its
prompt, so this is a courtesy nudge for interactive runs.

```bash
if git remote get-url origin >/dev/null 2>&1; then
  git fetch origin --quiet 2>/dev/null || true
  branch=$(git rev-parse --abbrev-ref HEAD)
  remote_ahead=$(git rev-list --count "HEAD..origin/${branch}" 2>/dev/null || echo 0)
fi
```

- `origin` not configured, or fetch failed (offline) → silently proceed.
- `remote_ahead == 0` → silently proceed.
- `remote_ahead > 0` → offer the owner `[s]` run `/ztn:sync-data` first (abort),
  `[c]` continue on current local state, `[d]` show pending commits then re-prompt.
  `c` is always safe.

---

## Error handling principle (applies to every step)

Single rule: **any unexpected condition → log + proceed-or-exit per severity**.
Never silent failure, never owner pause.

| Class | Examples | Action |
|---|---|---|
| **Catastrophic** (cannot proceed at all) | `_frame.md` missing, a helper script missing / unrunnable, lock acquisition failed mid-tick, unhandled exception | Write `log_roles.md` entry, release `.roles.lock` (finally), exit non-success. Do NOT continue to other roles. In autonomous mode the scheduler prompt's failure-handling surfaces it to the owner. |
| **Role-level** (one role broken, others fine) | `config.yml` missing / unreadable / `RoleConfigError`, `id` mismatch, `minder_query` / `roles_persist` fails for one role | Append an `error` run to `roles-runs.jsonl` (via `roles_common.append_run`), log it, **skip this role, continue** with the rest. |
| **Body-produced but rejected** (delta invalid) | `roles_persist.py` returns `run_status: rejected` (grounding / churn / identity hold) | This is a normal, handled outcome — `roles_persist.py` already logged the run and (for churn / identity / cold-start) emitted the CLARIFICATION. Surface its summary; continue. NOT a skill error. |
| **Owner-action-required** | `roles_persist.py` reports a `role-*` CLARIFICATION (e.g. `role-cold-start`, `role-new-key`, `role-churn-guard`, `role-auto-paused`, `role-schema-version`, `role-unroutable`, `role-identity-suggest`, `role-nudge`, `role-emission-confirm`, `role-act-confirm`, `role-act-drift`, `role-act-failed`, `role-budget-exhausted`, `role-tool-request`, `role-tool-reauth`) in its summary | `roles_persist.py` owns the CLARIFICATION emission; the skill surfaces the count + a one-line pointer in the run summary. Continue. |

The `role-*` CLARIFICATION types (the canonical set is registered in
`SYSTEM_CONFIG.md`) are emitted by `roles_persist.py` on a tick — all except
`role-remit-changed`, which `/ztn:role:edit` emits on a remit change, and
`role-trigger-skip-streak`, which the SKILL itself emits at Step 4.25 on a
gate-**skip** (the ONE type the skill raises directly — a gate-skip means
`roles_persist.py` never runs this tick, so nothing else can surface it). Both use
the same `roles_common.emit_clarification` (which refuses any non-`role-*` type).
Other engine-infra failures surface via the log + exit status (+ the scheduler
failure-note in autonomous mode).

---

## Step 0 — Mode dispatch + early exit + cross-skill lock awareness

**FIRST action. No context load, no work until passed.**

### 0.0 Mode dispatch

- `--approve-coldstart <role-id>` → continue through 0.2 + 0.5 (it writes), then
  run **Mode: --approve-coldstart** above.
- `--approve-acts <role-id>` → continue through 0.2 + 0.5 (it writes), then run
  **Mode: --approve-acts** above.
- `--all-due` / `--role <id>` → continue below.

### 0.1 Early exit check (tick sweep only)

For `--all-due`: compute the due set (Step 2). If empty → report «no roles due
today» and **exit immediately** — no lock, no further loading. For `--role <id>`
skip this check (an explicit target). This saves lock churn on no-op days (most
roles are weekly+ cadence).

### 0.2 Cross-skill lock check (HARD contract — symmetric mutual exclusion)

Read the six competitor lock files under `_sources/`, in order; abort on the
first present:

1. `.processing.lock` → «/ztn:process running, try again later»
2. `.maintain.lock` → «/ztn:maintain running, try again later»
3. `.lint.lock` → «/ztn:lint running, try again later»
4. `.agent-lens.lock` → «/ztn:agent-lens running, try again later»
5. `.content.lock` → «/ztn:content running, try again later»
6. `.resolve.lock` → «/ztn:resolve-clarifications running, try again later»

The full pipeline lock set is the seven `.processing .maintain .lint .agent-lens
.content .resolve .roles`; this skill's own is `.roles`, so the six above are its
competitors. All seven are mutually exclusive (doctrine §3.4 lock matrix).

Stale lock (>2h old, parse the ISO timestamp from the file) → warn, report the
PID if present, offer manual removal, **do NOT auto-delete** (a human may be
inspecting a crashed run). Auto-clean is the scheduler prompt's job, not the
skill's.

### 0.3 Recent-run check

Read the last entry of `_system/state/roles-runs.jsonl`. If the most recent
entry across all roles has `run_at` < 30 minutes ago, report «roles ran {N}
minutes ago; pass --force to proceed» and exit unless `--force`. The scheduled
tick passes `--force` (its 06:30 cron alignment is never <30 min from a prior tick).

---

## Step 0.5 — Concurrency lock (tick / approve modes)

**FIRST check the roles-family lock itself.** Step 0.2 checks the six COMPETITOR
pipeline locks; `.roles.lock` is this family's OWN lock, shared with
`/ztn:role:edit` (and `/ztn:role:add` while creating a role) and any other roles
tick. Before creating it, read `_sources/.roles.lock`: if it exists and is < 2h old,
another roles run / edit holds it — report «the roles system is mid-run or being
edited — try again in a few minutes» and **exit without writing** (never clobber a
held lock). A stale lock (> 2h) is warned + surfaced for manual removal, never
auto-deleted (a human may be inspecting a crash). Only when no live lock is present
do you create it.

Create `_sources/.roles.lock` with content:

```
{ISO UTC timestamp} — roles run, PID {pid}, mode: {all-due|role X|approve-coldstart X}, args: {$ARGUMENTS}
```

**Finally semantics mandatory:** release the lock in every exit path (normal
completion, per-role skip, exception, catastrophic abort). Wrap Steps 1–7 in
try/finally; delete the lock in finally. `--dry-run` still acquires and releases
it (LLM calls hold the exclusive resource).

---

## Step 1 — Context load

Read, in order:

1. `_system/docs/ENGINE_DOCTRINE.md` (operating philosophy + lock matrix)
2. `_system/docs/SYSTEM_CONFIG.md` (log ownership, exclusion matrix, CLARIFICATIONS format)
3. `_system/roles/_frame.md` (the three-stage frame bodies)

Detect the owner's user-facing language here (per the Language convention). If
any of these is missing → catastrophic: log, release lock, exit.

---

## Step 2 — Discover + filter due roles

Roles are per-instance directories, not a registry table. Compute the due set
deterministically via `roles_common` (the single source of truth for discovery,
config validation, and cadence semantics). Run once at the top of the sweep:

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, "_system/scripts")
from roles_common import (
    discover_role_ids, load_role_config, is_due,
    last_successful_run, append_run, RunRecord, make_run_counts,
    now_iso_utc, RoleConfigError,
)

due, errors = [], []
for rid in discover_role_ids():
    try:
        cfg = load_role_config(rid)
    except RoleConfigError as exc:
        # Role-level: record one 'error' run and skip. Never aborts the sweep.
        append_run(RunRecord(role_id=rid, run_at=now_iso_utc(), status="error",
                             hook="tick", counts=make_run_counts()))
        errors.append({"role_id": rid, "error": str(exc)})
        continue
    if not cfg.is_active:
        continue                       # paused role never runs
    if is_due(cfg, last_successful_run(rid)):
        due.append(rid)                # cadence window open; activation gated in Step 4
print(json.dumps({"due": due, "errors": errors}))
PY
```

- `discover_role_ids()` returns instance dirs holding a `config.yml`; `_`-prefixed
  entries (e.g. `_frame.md`) are engine files, not roles, and are skipped.
- `is_due()` mirrors AGENT_LENSES cadence semantics — daily / weekly / biweekly /
  monthly against `cadence_anchor`; first run fires when today matches the anchor;
  no catch-up. `last_run` is the latest `roles-runs.jsonl` entry with status ∈
  {ok, empty} (rejected / error / paused runs do not advance the window, so the
  role retries next due-day). Paused roles are never due.
- For `--role <id>`: skip the loop; load that one config (a `RoleConfigError` →
  record an `error` run + report + exit), require `status: active` (a paused role
  → report «role '{id}' is paused; un-pause in config.yml to run» and exit), and
  treat it as the sole candidate regardless of cadence.

`is_due` is **cadence-only**. The `activation` gate (`by_change` / `by_elapsed_time`)
is applied per-role in Step 4, after the corpus is resolved — because it needs the
corpus to answer «did anything change».

---

## Step 3 — Per-role isolation + the hard read-lock runtime (load-bearing)

Every role runs in isolation, and the tick body runs **tool-restricted** — the
enforced runtime that gates acting + shipping to friends (INV-15). The runner
enforces both; violating either breaks the design.

- **Per-role isolation.** Role N's frame stages have zero visibility into role
  N-1's input, output, or intermediate state. The orchestrator keeps no
  cross-role conversation and passes no «what other roles found» between roles.
  Each role gets its own body run.
- **Fresh context per stage.** Each body invocation has **system prompt** =
  exactly the corresponding `_frame.md` stage body (nothing prepended / appended:
  no skill preamble, no CLAUDE.md, no environment block), **user message** = the
  assembled input for that stage, **conversation history** = empty. Stage 2
  receives Stage 1's output as INPUT TEXT, not as a conversation continuation —
  the structurer strictly reformats, not argues.
- **HARD READ-LOCK — honest split (INV-15, CONTRACT §6.1).** The body is DESIGNED as a
  tool-restricted PURE REASONER: it reasons, and **PROPOSES** what it wants —
  `read_requests[]` (zone note bodies) and `tool_requests[]` (external tools) — and the
  **runner disposes** (INV-1): each read is fulfilled via `minder_query.py --enforced
  --role {id} --read <path>` (the role-bound wrapper — `--enforced` refuses
  `--config`/`--remit-json` UNCONDITIONALLY, §6.1) and each tool goes through the TOOL
  STAGE (Step 4.45), enforcing grant + budget + secret. **What holds by construction**
  is this write/oracle side: the enforced wrapper, the engine-authored grounding oracle,
  the writer-monopoly. **What is honor-system** (until a verified sandbox — the shipped
  runtime is the in-context body, which retains raw FS): that the body does not read
  around its remit via raw FS instead of `read_requests`. So the runner sets
  `body_caged=false` and **every inbox emission is owner-confirmed** (Step 4.5 /
  `role-emission-confirm`) — closing, on the write side, any out-of-remit paraphrase
  before it reaches the base, regardless of what the body read.
  The body's «only reads are the granted tools + the role-bound `minder_query`
  wrapper» is realised as these runner-fulfilled mediated requests — strictly
  stronger than handing the body tools, because grant/budget/secret enforcement is
  runner-side and the body holds no read-around capability at all.
  - **Why the no-FS cage is NOT built here.** A custom-agent `tools:` frontmatter is an
    ALLOWLIST, and an EMPTY allowlist inherits ALL tools (the opposite of a cage) — there
    is no "zero tools" form to express a pure reasoner, so a no-FS body cannot be defined
    + verified via the current agent-type mechanism. A real cage therefore needs a
    sandboxed runtime (the service era), not shipped now. Meanwhile the runner keeps
    `body_caged=false` and the **unforgeable owner-confirm gate** (below) is the
    guarantee — not a trusted subagent.
- **The body cannot forge the grounding oracle.** Even though the body proposes
  `read_records` in its payload, the runner OVERWRITES it (Step 4.5) with the
  deterministic `--enforced` zone-index stems — a fabricated stem never survives.

Roles are independent, so the per-role body runs are safe to run in parallel —
they read only (all writes are the runner's). The Stage-3 PERSIST (Step 4.5,
`roles_persist.py`) MUST stay sequential: it read-modify-writes shared files
(`CLARIFICATIONS.md`, the append-only `roles-runs.jsonl` / `log_roles.md`,
`triggers.json`, `budget.json`), so two persists in flight could lose a write.
Default is **sequential, in sorted-id order** for the whole tick.

> **Runtime, honestly.** The SHIPPED runtime is the in-context body — it retains raw FS,
> so the no-FS cage is honor-system (`body_caged=false`), and no custom-agent frontmatter
> can express a zero-tool cage (empty `tools:` inherits ALL tools). What holds
> regardless: every read is routed through `minder_query --enforced --role {id}` (scope
> override refused), every tool through the TOOL STAGE, and **every inbox emission is
> owner-confirmed** so nothing out-of-remit reaches the base silently. The emission gate
> relaxes to firewall-only ONLY when a real sandboxed runtime exists AND the owner sets
> the out-of-band `ZTN_ROLES_CAGE_VERIFIED=1` (Step 4.5's `body_caged` payload flag alone
> is NOT trusted — the writer AND-gates it with that env marker, so nothing forgeable
> opens the gate). The honest floor is the owner-confirm gate + the enforced wrapper.

---

## Step 4 — Per-role tick execution

For each due role (sorted id order), run 4.1–4.6. An error in one role does NOT
abort the loop (role-level → `error` run + skip).

### 4.1 Resolve the zone index

Resolve the role's zone INDEX once (not the full-body corpus) and keep it in a
per-role temp file — it is reused by the activation gate (4.2), the frame
assembly (4.3), and the read-records oracle (4.4):

```bash
INDEX=$(mktemp)
python3 _system/scripts/minder_query.py --role {id} --list --compact > "$INDEX" || { echo "resolver failed"; }
```

`--list` returns the zone index: `units[]` (one lightweight entry per in-remit
note — `path` / `type` / `trio` / `frontmatter_subset`, NO body), `entity_stubs[]`,
`counts`. This is the role's table of contents; the bodies are fetched on demand by
the runner fulfilling the body's `read_requests` via `--enforced --read` (4.4), not
dumped here.
If `minder_query` fails (non-zero exit / unreadable) → role-level error: `error`
run + skip (and `rm -f "$INDEX"`).

The **read-records oracle** = the full set of index stems (the `path` stem of
every `units[]` entry from `--list`). This is the whole in-remit zone — the same
grounding set a full dump would carry, because `--list` and a full resolve share
one fail-closed in-remit split, so the validator's grounding check is unchanged.
This oracle is **engine-authored**: the runner injects it directly into the
payload's `read_records` at 4.5 (overwriting whatever the structurer echoed), so
the body never authors the grounding set — a body could fabricate both a stem and
a matching citation, but the fabricated stem cannot survive the injection to reach
the validator. Keep the `$INDEX` file resolved here for that injection. A note
counts toward the oracle whether or not the thinker opened its body: the index is
the whole zone.

### 4.2 Activation gate + cold-start detection

Load the prior PER-PART states and decide whether this cadence-due role actually
needs to tick (activation), and whether it is a cold-start. A role is a composite
of parts, each with its own `seen_watermark` / `staging` in `parts/{part_id}.json`;
the gate is archetype-agnostic (it uses each part plugin's `consumed_records` hook,
never a concrete state shape):

```bash
# argv: <role-id> <index-file>  (stdin is the heredoc, so the index is a FILE arg)
python3 - "{id}" "$INDEX" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "_system/scripts")
from roles_common import (load_role_config, last_successful_run,
                          part_state_path, import_archetype)
from datetime import date

rid = sys.argv[1]
index = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
cfg = load_role_config(rid)

def stem(p):
    return Path(str(p)).stem

# Per-part prior states (parts/{part_id}.json) + their plugins.
parts = []
for p in cfg.parts:
    pp = part_state_path(rid, p.id)
    st = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}
    # Carry the PART's grounding (per-instance, `PartSpec.grounding`) — the SAME source
    # the writer's `_part_is_fresh` uses. A `stance` plugin has NO scalar GROUNDING_MODEL
    # (grounding is per-instance via `schema.grounding`), so reading a plugin constant
    # would default to "records" and spuriously cold-start a values-grounded part.
    parts.append((st, import_archetype(p.kind), getattr(p, "grounding", "records")))

# cold_start (role-level): ANY part is fresh (never advanced, no draft, no content)
# OR has a frozen draft pending → tell the thinker a first draft is due for it. A
# records-grounded part's watermark is an exact "never adopted" proxy; a values-grounded
# part (a stance) consumes no records, so its watermark can stay None even after it has
# adopted a live position — for such a kind, freshness falls back to its live content.
def is_fresh(st, plugin, grounding):
    if st.get("staging") is not None:
        return False
    if st.get("seen_watermark") is not None:
        return False
    if grounding != "records":
        return not list(plugin.content_summary(st))
    return True
cold_start = (not parts) or any(
    is_fresh(st, plugin, g) or isinstance(st.get("staging"), dict) for st, plugin, g in parts
)

# Effective watermark PER PART: while a part's cold-start draft is frozen, compare
# against what the draft already covers (its content's cited stems, via the part
# plugin's consumed_records hook) so an unchanged pending part does not burn a tick;
# otherwise the part's seen_watermark. (A pending re-tick is re-surface-only.)
def eff_wm(st, plugin):
    staging = st.get("staging")
    if isinstance(staging, dict):
        seen = [stem(r) for r in plugin.consumed_records(staging)]
        return max(seen) if seen else None
    return st.get("seen_watermark")

index_stems = [stem(u.get("path")) for u in (index.get("units") or []) if u.get("path")]
newest = max(index_stems) if index_stems else None
# by_change: the role ticks if ANY part is behind the newest record — a part with
# eff_wm None (fresh / empty draft) is behind by definition. Parts share one remit,
# so a genuinely newer note may warrant work in any part that has not seen it.
wms = [eff_wm(st, plugin) for st, plugin, _g in parts] or [None]
if any(w is None for w in wms):
    by_change = True
else:
    by_change = newest is not None and newest > min(wms)

act = cfg.activation
elapsed = act.get("by_elapsed_time") or {}
by_elapsed = False
if elapsed.get("enabled") and elapsed.get("threshold_weeks"):
    last = last_successful_run(rid)
    if last is None:
        by_elapsed = True
    else:
        try:
            last_d = date.fromisoformat(str(last.get("run_at"))[:10])
            by_elapsed = (date.today() - last_d).days >= int(elapsed["threshold_weeks"]) * 7
        except (ValueError, TypeError):
            by_elapsed = True

activated = bool(act.get("by_change", True)) and by_change or by_elapsed

# Held-pending body-skip: this role already has outward acts STAGED awaiting the owner's
# `--approve-acts`, and nothing new changed in the zone (no by_change) and no elapsed
# floor fired. Re-running the body would only re-derive the same reconcile (and the
# pending-swap guard refuses to overwrite it anyway) — burning the body + tool calls for
# nothing. Skip the tick until the owner acts on the pending or the zone actually moves.
from roles_common import role_dir
held_pending = (role_dir(rid) / "pending_acts.json").is_file()
if held_pending and not by_change and not by_elapsed:
    activated = False
print(json.dumps({"activated": activated, "cold_start": cold_start,
                  "by_change": by_change, "by_elapsed": by_elapsed,
                  "held_pending": held_pending}))
PY
```

The index is passed as the `$INDEX` file arg (the heredoc owns stdin). If
`activated` is false → the role is cadence-due but nothing changed and no elapsed
floor fired: **skip silently** (no run recorded, mirroring a not-due role),
`rm -f "$INDEX"`, and count it under «skipped: not activated» in the log
summary. When `held_pending` is true (the false was caused by staged acts awaiting
approval + an unchanged zone), log it as «skipped: acts staged awaiting approval» so
the deferral is legible — the owner runs `--approve-acts` (or the zone moves) to resume.
If `activated` is true → proceed. `cold_start` selects the framing in
4.3. Remove `$INDEX` in the role's finally once the tick completes.

### 4.25 Trigger-gate (runner-evaluated predicate — INV-18)

After activation passes, evaluate the role's trigger block (from `config.triggers`)
BEFORE running the body. A role with no triggers is **ungated** (passes — the
additive default). The gate is a logged predicate, never a self-reported «nothing to
do»:

Capture the gate result into shell vars — `$GATE_JSON` (the whole result),
`$PENDING_JSON` (the watermarks to commit in 4.6 on success):
```bash
# argv: <role-id> <index-file>  (stdin = the probe values JSON, may be '{}')
GATE_JSON=$(python3 - "{id}" "$INDEX" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "_system/scripts")
from roles_common import load_role_config
import roles_triggers as tg

rid = sys.argv[1]
index = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
cfg = load_role_config(rid)
# probe_values: for each `external-state` trigger, obtain the CHEAP probe (a
# projection distinct from the full read) and map it to the trigger's `probe` key.
# The runner obtains it out-of-band: for an `http` board like `github-board`, a small
# GET of the collection and take the max version field, e.g. for probe
# `github-board.issues-updated` → GET the repo issues (sorted by updated, per_page=1) and
# read its `updated_at`; for an `mcp` probe, the small MCP call. Unavailable (no secret,
# a failed call) → OMIT the key: the trigger then honestly cannot fire this tick — never
# a guessed fire (a `zone-mention` trigger still wakes the role independently).
probe_values = {}   # e.g. {"github-board.issues-updated": "2026-07-19T15:07:40Z"} when obtained
res = tg.evaluate_gate(cfg, index.get("units") or [], probe_values)
print(json.dumps({"passed": res.passed, "reason": res.log_reason,
                  "pending": res.pending_watermarks}))
PY
)
PENDING_JSON=$(printf '%s' "$GATE_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['pending']))")
```
`$PENDING_JSON` carries forward to Step 4.6 (committed only on a successful tick).

- **`passed: false` → `gate:skip`.** Persist the streak + the reason, and on a streak
  of `SKIP_STREAK_LIMIT` (5) surface a `role-trigger-skip-streak` CLARIFICATION. Because
  a gate-skip means `roles_persist.py` never runs this tick, the SKILL is the emitter
  here (the ONE CLARIFICATION the skill raises directly — see Step 6):
  ```bash
  python3 - "{id}" "$GATE_JSON" <<'PY'
  import json, sys
  sys.path.insert(0, "_system/scripts")
  import roles_triggers as tg, roles_common as rc
  rid, reason = sys.argv[1], json.loads(sys.argv[2]).get("reason", "gate:skip")
  streak = tg.commit_gate_skip(rid, reason)          # stores streak + the reason
  if tg.skip_streak_exceeded(streak):
      rc.emit_clarification(
          ctype="role-trigger-skip-streak",
          subject=f"{rid} trigger skipped {streak} ticks",
          context=("This role's trigger-gate skipped it "
                   f"{streak} cadence-due ticks in a row — the trigger may be mis-wired "
                   "(a probe that never moves, a match that never fires). Recent skip "
                   f"reasons: {', '.join(tg.recent_skip_reasons(rid)) or 'n/a'}. Review "
                   "the trigger config via /ztn:role:edit. The role is NOT paused."),
          source=f"roles gate for {rid}",
          suggested_action="Review the trigger config, or leave it if the zone is genuinely quiet.",
          action_taken="Surfaced the skip streak; the role keeps evaluating each cadence.")
  PY
  ```
  Then **skip the role** (no run recorded, mirroring not-activated), `rm -f "$INDEX"
  "$CTX"`, and record it in the Step 6 sweep under «skipped (gate: {reason})». The role
  is NOT paused — a genuinely quiet zone is valid.
- **`passed: true` → `gate:pass`.** Set `payload["gate_reason"]` (engine-authored from
  `$GATE_JSON.reason`) so `roles_persist` logs which trigger fired in the tick's own log
  block; **hold** the `pending` watermarks — committed only AFTER a confirmed successful
  tick (INV-26/28, Step 4.6), never here. Proceed to 4.3.

The gate is AND-ed with is_due + activation: a role runs only when cadence-due AND
activated AND (ungated OR a trigger fired). Self-authored records
(`source: role:{id}`) are excluded from the zone-mention match (INV-27), matched
STT-robustly (`minder` / `миндер` / `миндера` all fire).

### 4.3 Assemble the frame input

Build the tick body the way `_frame.md` describes — the runner concatenates, as
the Stage-1 user message:

1. The role's **identity** — `persona` (voice / values / worldview / tempo) and
   `remit` from `config.yml`. Owner-sovereign: the body may reason about it and
   may SUGGEST a change, but never rewrites it. If the role has a `brief.md`
   (path from `config.yml → brief`, resolved by `roles_common.role_brief_path`),
   include its content here **labelled STEER**: the owner's standing notes on
   what to weigh. It is owner-sovereign and NON-GROUNDING — the engine never
   writes it, and it never substitutes for a real record citation.
2. The **prior per-part skeletons** — ONE body-free skeleton per part in
   `config.parts[]` order, each LABELLED with its `part.id` and `part.kind`,
   projected from that part's `parts/{part_id}.json`. Provenance, history, and
   timestamps are withheld on purpose. Project each part per the shape `_frame.md`
   Stage-1 describes for its kind:
     · a `ledger` part → one line per LIVE item (skip `archived` / `merged` /
       superseded): `key · title · status · anchor` (+ `priority` / `owner` /
       `due` / `needs` only when set). The body reasons against the KEYS.
     · a `narrative` part → the current `purpose` headline plus a count of prior
       versions (`entries`). The body reasons against the current statement.
     · a `registry` part → one line per LIVE entry (skip `retired`): its natural
       `key` plus its currently-set fields (a catalog shows each entry's current
       field values; a log shows the appended entries). The body reasons against
       the entries that already exist — updating one by key, or adding a new one.
   For a cold-start (`cold_start: true`) a part has no prior content — tell the
   thinker plainly that this is the first draft for that part: synthesise it from
   the whole remit, do not assume prior state.
3. The **zone index** from 4.1 — the table of contents of the remit (`path` /
   `type` / `status` / `trio` per in-remit note, no bodies), PLUS the read-request
   protocol: the body proposes `read_requests: ["<path>", …]` and the runner opens
   each via `minder_query --enforced --role {id} --read <path>` (remit-bound), feeds
   the bodies back, and the body decides what
   to open. This is the handed map, not a handed pile of bodies. It is SHARED
   across the role's parts (one remit → one index).
4. The **granted-tools manifest** (INV-21, INV-24) — for each part and each tool-ref in
   that part's `tools`, resolve its `ToolSpec` from the registry
   (`roles_tools.get_tool`) and present, GROUPED BY PART, its `plain_purpose` +
   `usage_note` (its CONCIERGE_MANIFEST surface), `direction`, and per-tool budget — so
   the body knows **which hands each part has**. An `act`-direction tool is presented
   the SAME way as a read tool (plain_purpose / usage_note / `direction: act`), so the
   body knows it has outward hands: it PROPOSES `acts[]` naming that tool, and the
   runner / writer dispose (mandate + TOCTOU + HITL act-confirm — nothing else changes
   here). Grants are PER-PART (§1.1): the body names the part in its `tool_request` and
   the runner refuses a tool requested for a part it was not granted to. The body still
   only PROPOSES; the runner disposes (grant + budget + secret).
   If a part grants no tools, omit this block. Never present the adapter / endpoint
   / credential — only the plain purpose.
5. The role's `hooks/tick.md` body (its role-specific tick instruction / voice).

Render each part skeleton deterministically from its `parts/{part_id}.json`. A
body-free projection — never leak the withheld fields. The runner never names a
kind of its own invention: it projects the shape `_frame.md` documents for each
`part.kind` it finds.

### 4.4 Run the frame stages → delta payload

**Open the per-tick tool ctx UNCONDITIONALLY first** (every tick, tool-bearing or
not) and seed it with valid JSON so the firewall heredoc (4.5) + `roles_persist
--tool-ctx` never read an empty file:
```bash
CTX=$(mktemp)
printf '%s' '{"role_id":"{id}","call_counts":{},"ingested_external":false,"failures":[],"started_at":""}' > "$CTX"
```
`$CTX` holds the per-tool call counts, the `ingested_external` firewall flag, the
per-tool `failures`, and the wall-clock `started_at` — the runner (`roles_tool_stage`)
updates it across the loop. A tool-less tick leaves it at the seed (`ingested_external:
false`), so the writer reads a real «no external content» rather than fail-closed
over-gating. Removed in the role's finally.

- **Stage 1 — Thinker** (tool-restricted subagent, Step 3; system = `_frame.md`
  Stage-1 body; user = the 4.3 assembly — zone index + granted-tools manifest;
  fresh context): the thinker reasons free-form about what changed against the given
  keys. It has **no filesystem or query tools** — it PROPOSES what it wants to read
  and the runner disposes (INV-1/15):
  - `read_requests: ["<in-remit path>", …]` — note bodies it wants opened. The
    runner fulfils each via `minder_query.py --enforced --role {id} --read <path>`
    (role-bound; an out-of-remit path is refused) and feeds the bodies back.
  - `tool_requests: [{part, tool, args}, …]` — external tools it wants, each naming the
    PART it is reasoning as (grants are per-part — §1.1) and a tool in that part's
    manifest. The runner drives each through the TOOL STAGE below.

  **TOOL STAGE + read fulfilment (runner-driven, bounded-iterative — INV-20/21).**
  Reuse the `$CTX` opened above. For each `tool_request` the body emitted (`$REQUEST_JSON` = that
  one request's JSON, e.g. `{"part":"workstreams","tool":"notion-board","args":{"q":"tasks"}}` —
  the body names the PART it is reasoning as (grants are per-part — §1.1) + the granted
  tool_id + args; an `mcp` tool's concrete MCP tool is PINNED in the registry, NOT chosen
  by the body, so a read tool can never be redirected to an act MCP tool — INV-23), run:
  ```bash
  python3 _system/scripts/roles_tool_stage.py --role {id} --ctx "$CTX" \
      --request "$REQUEST_JSON"
  ```
  It returns either `{kind: result, …}` (a completed `ToolResult` — Python-exec
  adapter, or an honest `declare-unknown` refusal / budget / secret failure) OR
  `{kind: harness, part_id, descriptor: …}` for an `mcp`/`skill` tool: the runner then
  MAKES the MCP/skill call itself (the granted tool), and folds the raw return back —
  passing back the `part_id` from the harness result so the per-part grant is re-checked:
  ```bash
  python3 _system/scripts/roles_tool_stage.py --role {id} --ctx "$CTX" \
      --absorb {tool_id} --part {part_id} --raw "$RAW_JSON"
  ```
  Feed each result's ephemeral `data` back to the body (NEVER commit a raw return —
  INV-10; the stage already appended a hash+summary to the tool audit). The body may
  observe returns and request AGAIN within the tick — **bounded by the per-tool
  budget** the stage enforces (an `unlimited` tool iterates until done; a capped one
  stops at its cap with a budget-exhausted `declare-unknown`). This is bounded-
  iterative, NOT unbounded ReAct. Loop read_requests + tool_requests until the body
  emits neither (or the budget bounds it), then it produces its reasoning.

  **Wall-clock bound (INV-28).** Also stamp the loop start and, before each iteration,
  stop if elapsed exceeds the role's `max_tick_seconds`
  (`roles_budget.max_tick_seconds(roles_budget.load_budget("{id}"))`) — so an
  `unlimited` read tool cannot hold `.roles.lock` long enough to delay `/ztn:process`.
  On the wall-clock bound, honest-degrade the outstanding requests (the body reasons
  with what it has) rather than blocking.

  Capture the reasoning verbatim. Up to 2 fresh-context retries on transient error;
  on exhaustion → role-level `error` run + skip. Read the ctx's `ingested_external`
  flag after the loop — it is the injection-firewall input for Step 4.5.
- **Stage 2 — Structurer** (cheaper LLM; system = `_frame.md` Stage-2 body; user
  = the thinker output + the prior per-part skeletons + the **read-records oracle**
  from 4.1 (the full zone-index stem set) + the delta contract of EACH addressed
  part (its op vocabulary + payload shape, keyed by `part.id`); fresh context):
  produce exactly one delta-payload JSON object (§ the payload shape in
  `_frame.md`). Every delta carries the `part` it changes. The structurer echoes
  the oracle into `read_records` for a well-formed payload, but that field is
  **engine-authored** — the runner overwrites it at 4.5, so the body's copy carries
  no trust; every records-grounded citation (a ledger `add` provenance / mutating
  evidence, a narrative statement's evidence) must still cite a real in-zone
  basename (validated against the engine-authored oracle). Output JSON only. Same
  2-retry policy.

The structurer targets each part's delta schema (a ledger part's keyed ops, a
narrative part's statement ops, a registry part's entry ops); it never mints keys
(the engine does), never invents an anchor (unanchored → `anchor: null`, honestly),
and emits an empty `deltas` list when the thinker described no change.

The payload MAY also carry the optional top-level `acts[]` field — the role's outward
hands — alongside `nudges` / `inbox_emissions`, only when the role has a granted
`act` tool AND a mandate. Each act is `{part, tool, op: create|update|close,
target_ref, fields, dedup_match, reason, evidence}`. The body only PROPOSES the act;
it NEVER executes one — the deterministic writer disposes (INV-1). **Grounding differs
by field.** A records-grounded delta / an `inbox_emissions` note grounds against the
in-remit record corpus (its `evidence` must cite a real in-zone basename). An `act`,
by contrast, is **EXTERNAL-driven, NOT grounded against the record corpus** (INV-10 —
its justification is the ephemeral tool read of the live board, not a record). The
writer therefore never drops an act for lack of a record citation; the act's `evidence`
/ `reason` are informational (the owner's «why»), and the gate is instead the mandate +
TOCTOU re-validate + idempotency + the HITL act-confirm + the injection firewall.

- **Stage 2.5 — Grounding check (conditional; `_frame.md` Stage 2.5).** If ANY
  addressed part has `schema.grounding_check: true` (the concierge sets it for a part
  that makes claims / readings about the world, not for a plain catalog / log of owner
  facts), run one cheap fresh-context adversarial pass over the deltas addressed to
  that part: for each, re-read the note(s) it cites and ask «does this hold up against
  what the zone / the owner actually says, or did the reasoning drift past it?». DROP
  a drifting delta from the payload before 4.5 — do not rewrite it. Parts without the
  flag skip this pass. It only tightens a claims-making part's honesty; it never
  overrides the deterministic validator in 4.5.

- **Stage 2.6 — Values oracle (conditional; a `values`-grounded part).** Gated on the
  PART's grounding, per-instance — NOT on the kind. If ANY addressed part has
  `schema.grounding: values` with a `take-position` / `argue` delta in the payload, that
  part grounds each position in the owner's OWN constitution, not in records — so the
  runner computes its grounding ORACLE here. A stance is DUAL-grounded: a `grounding:
  values` stance runs this stage; a `grounding: records` stance (the default for a
  push-back voice — it argues from the owner's own notes) SKIPS this stage entirely and
  grounds each position in `read_records` like any records kind, exactly as a ledger /
  assessment part does (its `take-position` / `argue` cites in-remit record stems, checked
  ⊆ the engine-authored `read_records` at 4.5). This is the ONE grounding computation that
  lives in the SKILL, not in `roles_persist.py`:
  the writer is pure Python and cannot invoke a skill, and a role MUST NEVER call
  check-decision in WRITE mode (SDD §10 #8). The SKILL can, in read-only `--dry_run`.
  For each such part:
  1. Gather the proposed position(s) — the `argument` (and `position` headline) text of
     each `take-position` / `argue` delta the structurer addressed to that part.
  2. For each proposed position, run `/ztn:check-decision --dry_run` with `situation` =
     the position's argument. `--dry_run` makes check-decision return its verdict + cited
     principle-ids and **SUPPRESSES its Evidence-Trail / `last_applied` write into
     `0_constitution/`** — the role consults the constitution but never mutates it (SDD
     §10 #8). Collect every `citations[].id` it returns.
  3. **VERIFY each returned principle-id EXISTS — do not merely trust the return.** A
     model can hallucinate an id. Read the tree: an id is real iff
     `grep -R "^id: {pid}$" 0_constitution/` matches a file. DROP any id that does not
     resolve to a real principle, so a fabricated id can never become grounding.
  4. Inject the VERIFIED id set as that part's oracle:
     `payload["values_oracles"][{part_id}]` = the sorted, deduped list of verified
     principle-ids. This is ENGINE-AUTHORED, exactly like `read_records`: the structurer
     never writes `values_oracles`, and whatever it echoed is discarded.

  This existence grep is backstopped deterministically at the writer: `roles_persist`
  re-filters `values_oracles` against `0_constitution/` (pure-Python id walk) before
  the validator sees it, dropping any id that does not resolve to a real principle — so
  the «no forged principle» guarantee holds by construction even if this prompt-stage
  grep regresses. This stage still owns RELEVANCE (which real principle applies); the
  writer owns only EXISTENCE.

  The deterministic validator in 4.5 then checks each values position's `citations ⊆`
  this oracle — a body cannot forge a principle that is not in the owner's constitution.
  A values part for which NO verified oracle is produced (no position cited a real
  principle, or check-decision returned nothing that resolved) gets no `values_oracles`
  entry → the writer fail-closes that part (no oracle = no grounding = every position
  rejected). Records-grounded parts — including a `grounding: records` stance — skip this
  stage entirely; their citations ground in `read_records`. This runs inside the tick
  under the already-held `.roles.lock`; check-decision `--dry_run` writes nothing to
  `0_constitution/` and takes no pipeline lock, so it is safe within the tick (it is a
  read-only reasoning call, not a competitor). A stance never ACTS on its positions —
  the only outward effect of a stance is a bounded, dismissable `role-nudge`.

`--dry-run`: stop here — print the payload (including any `values_oracles` computed in
Stage 2.6, so the printed payload is faithful) for inspection, do NOT proceed to 4.5.

### 4.5 CONTROL BOUNDARY — hand the payload to `roles_persist.py`

**This is the only writer.** The skill and the body MUST NOT edit any
`parts/{part_id}.json`, `state.md`, `decisions.jsonl`, `roles-runs.jsonl`, or
`log_roles.md` directly.

**First, engine-author `read_records` (grounding-oracle hardening).** The
structurer echoed a `read_records` set, but the body must NOT be trusted to author
the grounding oracle: a body that fabricated both a stem and a matching provenance
would otherwise pass the ⊆-check by internal consistency alone, never touching
truth. So the runner OVERWRITES `payload["read_records"]` with the ACTUAL
zone-index stems resolved in 4.1 (the deterministic `minder_query --list` output)
before piping to the writer. The body's echoed copy is discarded; a fabricated
stem cannot survive, so the validator's ⊆-check runs against an engine-authored
oracle — a citation only passes when it names a note that is truly in the zone:

Also engine-author the **injection-firewall flag** `ingested_external_tool` from the
tick's tool ctx (Step 4.4) — the body cannot forge it. The writer HITL-gates an
inbox emission (and an act) on a tick that ingested external tool
content (INV-17). Reading only the own zone is NOT ingestion, so the flag is false
and the role writes freely.

```bash
PAYLOAD_FILE=$(mktemp)
printf '%s' "$PAYLOAD_JSON" > "$PAYLOAD_FILE"
python3 - "$INDEX" "$PAYLOAD_FILE" "$CTX" <<'PY' > "${PAYLOAD_FILE}.fixed"
import json
import sys
from pathlib import Path
sys.path.insert(0, "_system/scripts")
from roles_common import is_role_authored_source

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
ctx_path = Path(sys.argv[3])
try:
    ctx = json.loads(ctx_path.read_text(encoding="utf-8")) if ctx_path.is_file() else {}
    if not isinstance(ctx, dict):
        ctx = {}
except (OSError, ValueError):
    ctx = {}   # unreadable/empty ctx → treat as no-tool tick (fail-safe)

# Engine-authored grounding oracle: the zone-index stems from --list this tick,
# EXCLUDING self-authored records (INV-27 no-self-feed — matches BOTH source:role:{id}
# and the /ztn:process-derived .../roles/{id}--... path via is_role_authored_source),
# in list order, deduped. Replaces whatever the structurer wrote so the body cannot
# author the set the validator checks citations against. (roles_persist.
# _inject_read_records re-authors this identically as the FINAL oracle — this is the belt.)
rid = payload.get("role_id")
stems = []
for unit in (index.get("units") or []):
    path = unit.get("path")
    if not path:
        continue
    fm = unit.get("frontmatter_subset") or {}
    if is_role_authored_source(fm.get("source"), rid):
        continue  # self-feed excluded (INV-27)
    stem = Path(str(path)).stem
    if stem not in stems:
        stems.append(stem)
payload["read_records"] = stems
# Injection-firewall flag (INV-17) — engine-authored from the tool ctx, not the body.
payload["ingested_external_tool"] = bool(ctx.get("ingested_external", False))
# Body-cage flag (INV-15) — engine-authored FALSE in the shipped honor-system runtime.
# NOTE: this payload flag alone CANNOT relax the emission gate — the writer only honours
# `body_caged=true` when the out-of-band env marker `ZTN_ROLES_CAGE_VERIFIED=1` is ALSO
# set (the owner sets it once a REAL sandboxed no-FS body runtime exists — not buildable
# via the harness agent-type mechanism, where an empty `tools:` inherits ALL tools). So a
# body / a regression here can never forge autonomy; the env marker is the actual gate.
payload["body_caged"] = False
print(json.dumps(payload))
PY
PAYLOAD_JSON=$(cat "${PAYLOAD_FILE}.fixed")
rm -f "$PAYLOAD_FILE" "${PAYLOAD_FILE}.fixed"
```

The `values_oracles` map (if a stance part produced one in Stage 2.6) is likewise
ENGINE-AUTHORED — the SKILL already computed + verified it there and wrote it into the
payload, so it is handed to the writer unchanged (do NOT let the structurer author it;
the read_records hardening above overwrites only `read_records`). The writer reads
`payload["values_oracles"][{part_id}]` as each values part's grounding oracle and
fail-closes a values part that has none.

Then hand the corrected payload to the writer, passing the gate's `pending`
watermarks (from Step 4.25) via `--pending-watermarks` so the WRITER — not the SKILL —
owns the commit (INV-26, see Step 4.6):

```bash
printf '%s' "$PAYLOAD_JSON" | python3 _system/scripts/roles_persist.py --role {id} --payload - --tool-ctx "$CTX" --pending-watermarks "$PENDING_JSON"
```

`roles_persist.py`:
- loads the prior ledger, runs the archetype **validator FIRST**, and only then
  persists — grounding (a records part: citations ⊆ the engine-authored `read_records`;
  a values-grounded part / stance: `citations ⊆` the engine-verified `values_oracles`
  entry, fail-closed when absent), append-not-replace, churn-guard;
- on a **fresh** ledger with adds, freezes the draft into `staging` (cold-start),
  emits `role-cold-start`, and does NOT advance the watermark;
- on a pending cold-start, re-surfaces the frozen `role-cold-start` only — writes
  nothing, does not advance the watermark, discards the tick's proposed deltas
  (never re-drafts);
- routes unanchored new items through anchor-else-HITL (`role-new-key`);
- holds wholesale churn (`role-churn-guard`) without writing;
- on 3 consecutive validator rejects, auto-pauses the role (`role-auto-paused`)
  with an Archive-Contract reason;
- on forward progress, mints/carries keys, renders the `state.md` AUTO zone
  (preserving the owner portrait above the markers), appends `decisions.jsonl`,
  and — as the sole writer — appends the `roles-runs.jsonl` + `log_roles.md`
  entries itself;
- on a **mandate** role whose payload proposed `acts[]` (Phase 1): validates the
  mandate, captures the TOCTOU baseline (a READ), stages the acts + coupled inbox
  close-events + the `--pending-watermarks` into `_system/roles/{id}/pending_acts.json`,
  and emits ONE `role-act-confirm` — executing nothing, advancing no watermark (the
  owner runs `--approve-acts` for Phase 2). The Phase-1 inbox path is skipped so an
  emission never reaches the base before its act is confirmed;
- **commits the trigger watermarks it was handed** via `--pending-watermarks` (INV-26,
  §8): on a successful non-acting, non-cold-start tick it advances them now; on an
  acting tick it holds them, coupled to the confirmed act in Phase 2; on a cold-start /
  rejected / paused tick it advances nothing. The SKILL no longer commits them itself.

It prints a summary JSON on stdout: `outcome`, `run_status` (ok / empty /
rejected / paused), `counts` (added / advanced / clarifications / rejected),
`clarifications` (the `role-*` types it emitted, incl. `role-act-confirm`),
`state_flag`, `exit`.

### 4.6 Surface the outcome

Parse the summary. Because `roles_persist.py` already wrote the run + log + any
CLARIFICATION, the skill only **reports** — it does not re-write any of them:

- `outcome: progress|empty` → «{id}: {added} added, {advanced} advanced».
- `outcome: cold-start-staged` → «{id}: frozen draft ({N} items) awaiting
  approval — run `/ztn:roles --approve-coldstart {id}`».
- `outcome: cold-start-resurfaced` → «{id}: cold-start still pending — frozen
  draft re-surfaced, nothing written».
- `outcome: held` / `run_status: rejected` → «{id}: {reason} — see log_roles.md»
  (identity hold, churn hold, or grounding reject — all handled, not a skill error).
- `outcome: paused` → «{id}: auto-paused after 3 consecutive rejects — needs owner».
- `state_flag: auto-zone-edited|markers-missing` → note that `state.md` was
  preserved (the owner edited the AUTO zone) and not overwritten.
- `clarifications` includes `role-act-confirm` → «{id}: {N} act(s) staged for
  approval — run `/ztn:roles --approve-acts {id}`». The acts are staged in
  `pending_acts.json`; nothing was written to the external system this tick.

**The WRITER now owns the trigger-watermark commit (INV-26/28) — the SKILL passes,
never commits.** The gate's `pending` watermarks (`$PENDING_JSON` from Step 4.25) were
handed to `roles_persist.py` on the Step 4.5 call via `--pending-watermarks`. The
writer commits them itself: on a successful non-acting, non-cold-start tick it advances
them now; on an acting tick (a mandate role that staged `acts`) it holds them coupled
to the confirmed act and advances them only in Phase 2 (`--approve-acts`); on a
cold-start / `rejected` / `paused` / `error` tick it advances nothing — the external
change stays un-marked so it is re-processed next due (no silent
«processed-but-not-acted»). The SKILL runs no `commit_gate_pass` of its own. Then
remove the per-tick `$CTX` + `$INDEX` temp files.

> **Per-tick temp lifecycle.** `$INDEX` (4.1) and `$CTX` (a fresh `mktemp` per role,
> holding the tool call-counts + `ingested_external` flag) are created per role and
> removed in the role's finally — never shared across roles (per-role isolation).

A non-zero `exit` from `roles_persist.py` for one role is role-level: it already
logged an `error` run — surface it and continue to the next role.

---

## Step 5 — (folded into modes above)

Cold-start approval is **Mode: --approve-coldstart**, dispatched from Step 0.0.
No separate step body here.

---

## Step 6 — Log summary + cleanup + exit

The per-role run rows + log blocks are written by `roles_persist.py`. Step 6 is
the skill's own **sweep-level** summary and cleanup — it does not duplicate the
per-role writes.

Append one sweep block to `_system/state/log_roles.md` (skill-owned sweep header,
distinct from the per-role sections `roles_persist.py` writes):

```
## {YYYY-MM-DD HH:MM:SSZ} — roles sweep

Mode: --all-due | --role X | --dry-run
Roles considered: {count}
Roles run: {count}
  - {id}: {outcome} ({added} added, {advanced} advanced)
  - ...
Roles skipped (config error): {count}
Roles skipped (not activated): {count}
Roles skipped (gate): {count}   — with the {reason} per role (gate:skip:{reason})
CLARIFICATIONS surfaced: {list of role-* types or "none"}
Total duration: {seconds}
```

`--dry-run` prefixes the title with `[dry-run]` and adds «nothing persisted».

Cleanup:
- Delete `_sources/.roles.lock` (in the finally — guaranteed).
- Exit with a single-line status:
  - `success` — all due roles completed the pipeline cleanly (some may be empty /
    rejected / staged — those are completed outcomes, not errors)
  - `partial` — at least one role hit a role-level error (bad config, resolver /
    persist failure, LLM exhaustion)
  - `roles-locked` — aborted at Step 0.2 (a competitor lock was active)
  - `recent-run-blocked` — aborted at Step 0.3 without `--force`
  - `no-roles-due` — Step 0.1 found nothing due
  - `dry-run-complete` — `--dry-run` finished
  - `cold-start-approved` — `--approve-coldstart` adopted a draft
  - `acts-executed` — `--approve-acts` executed the staged acts cleanly (close-events
    fed to the base, watermark advanced)
  - `acts-partial` — `--approve-acts` hit drift / failure on at least one act
    (`role-act-drift` / `role-act-failed` surfaced; neither inbox nor watermark advanced)

---

## Skill-level invariants (doctrine §3.6)

- **Never write role state directly.** `parts/{part_id}.json`, `state.md`,
  `decisions.jsonl` are written ONLY by `roles_persist.py`. The skill and the
  body never edit them — the control boundary is the whole safety model.
- **Never edit a role's identity.** `config.yml` (persona / remit / cadence /
  status) is owner-sovereign. A role may only SUGGEST an identity change, surfaced
  as a `role-identity-suggest` CLARIFICATION — the skill never flips config
  (the one exception is `roles_persist.py`'s own best-effort auto-pause status
  flip on 3 rejects, which the skill does not perform).
- **Never auto-promote.** A role's ledger stays owner-visible in
  `_system/roles/{id}/`; nothing is promoted to constitution, knowledge, hub, or
  any owner-curated artefact.
- **Never touch the P2 emission substrate.** The skill raises no Action-Hint
  trailers into `_system/agent-lens/`; the only CLARIFICATIONS are the
  `role-*` types (registered in SYSTEM_CONFIG.md), emitted by `roles_persist.py`.
- **Never delete from `_sources/`.** The skill only creates + removes its own
  `.roles.lock` there.

---

## Files written

Per-role state + run + log + CLARIFICATION writes are performed by
`roles_persist.py` (the sole writer), not the skill. The skill's own write
surface is narrow:

- `_system/state/roles-runs.jsonl` — append: only the pre-flight `error` runs for
  roles that fail config-load before reaching `roles_persist.py` (Step 2). Every
  tick / cold-start / approval run row is written by `roles_persist.py`.
- `_system/state/log_roles.md` — append: the sweep-level summary block (Step 6).
  Per-role sections are written by `roles_persist.py`.
- `_sources/.roles.lock` — create + delete (concurrency lock).

Written by `roles_persist.py` when the skill routes a payload / approval to it:
`_system/roles/{id}/{parts/*.json, state.md (AUTO sub-zones), decisions.jsonl,
pending_acts.json (staged acts + TOCTOU baselines + coupled close-events + pending
watermarks), triggers.json (watermark commit)}`, `_system/state/roles-runs.jsonl`
(per-role rows), `_system/state/log_roles.md` (per-role sections),
`_system/state/CLARIFICATIONS.md` (the `role-*` types registered in SYSTEM_CONFIG.md,
incl. `role-act-confirm` / `role-act-drift` / `role-act-failed`), and the role's inbox
close-events under `_sources/inbox/roles/` on a confirmed act (Phase 2).

## Files read

The thinker (Stage 1) is a tool-restricted subagent — it decides what to open and
PROPOSES `read_requests`; the runner fulfils them via `minder_query --enforced
--role {id} --read` (remit-bound) and drives `tool_requests` through the TOOL STAGE.
The runner itself reads:
- `_system/roles/{id}/{config.yml, brief.md (optional STEER), parts/*.json, state.md, hooks/tick.md}` (`hooks/ask.md` is read by `/ztn:role:ask`, not the tick runner)
- `_system/roles/_frame.md`
- `_system/state/roles-runs.jsonl` (last_run + recent-run check)
- `_system/docs/ENGINE_DOCTRINE.md`, `SYSTEM_CONFIG.md` (context load)
- the `minder_query.py --list` zone index (per role, per tick), plus any
  `--enforced --read` fulfilments the runner performs for the body's read_requests
- `_system/registries/TOOLS.md` (the granted-tools manifest) + the tool audit
  `_system/state/roles-tool-audit.jsonl`; `_system/roles/{id}/{triggers.json, budget.json}`

---

## Boundary cases

Behaviour that follows directly from the steps (lock contention, config errors,
validator rejection, paused role) is described in place. Non-obvious cases:

| Case | Behaviour |
|---|---|
| Role due but nothing changed | Activation gate (4.2) is false → skipped silently, no run recorded — same as a not-due role. `by_elapsed_time` (if enabled) can still force a tick on a time floor. |
| Cold-start draft frozen, no new records | Activation compares against the draft's own coverage → not activated → skipped; the frozen `role-cold-start` CLARIFICATION stays open (deduped, not re-emitted). |
| Cold-start draft frozen, new record arrives | Activated → tick runs → `roles_persist.py` re-surfaces the frozen draft only (writes nothing, watermark unchanged); the new record is reviewed by the first tick after approval. |
| `--role X` on a paused role | Aborts with «role 'X' is paused; un-pause in config.yml to run». |
| Owner edited the `state.md` AUTO zone | `roles_persist.py` detects the hash drift, preserves the owner's edit, does not overwrite; the skill surfaces `state_flag: auto-zone-edited`. |
| Tick spans midnight | `run_at` is captured per role by `roles_persist.py`; cadence for the sweep uses the sweep-start date consistently. |
| Owner edits a `config.yml` mid-sweep | The config was loaded at Step 2; mid-sweep edits are picked up on the next tick, not this one. |
| First-ever tick of a role | `cold_start: true` → thinker synthesises the initial draft → `roles_persist.py` freezes it into `staging` and raises `role-cold-start`. |
| Mandate role proposes `acts` | Phase 1: `roles_persist.py` validates the mandate, captures the TOCTOU baseline, stages the acts (+ coupled close-events + pending watermarks) into `pending_acts.json`, and raises `role-act-confirm` — nothing written to the external system, watermark held. The owner runs `/ztn:roles --approve-acts {id}` for Phase 2. |
| `--approve-acts` hits target drift | The target changed since staging → the act is aborted (no write over someone else's change — TOCTOU), `role-act-drift` surfaced, pending cleared, watermark not advanced; the next tick re-reconciles from fresh state. |
| `--dry-run` | Runs Stages 1–2, prints the payload (incl. any proposed `acts`), never calls `roles_persist.py`; nothing persisted. |

---

## Coordination with other skills

- `/ztn:process`, `/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`, `/ztn:content`,
  `/ztn:resolve-clarifications` — mutually exclusive via the seven-lock matrix
  (Step 0.2). No data-path overlap: roles write only under `_system/roles/`,
  `_system/state/roles-runs.jsonl`, `_system/state/log_roles.md`, and the
  `role-*` CLARIFICATIONS.
- `/ztn:resolve-clarifications` — the owner resolves the `role-*`
  CLARIFICATIONS there (cold-start approval, new-key placement, churn holds,
  identity suggestions, auto-pause, proactive nudges, act-confirm / act-drift /
  act-failed). `--approve-coldstart` is the direct approval path for the cold-start
  case; `--approve-acts` is the direct approval path for a staged `role-act-confirm`.
- `/ztn:save` — sequential, never concurrent. In the autonomous tick, delivery is
  the scheduler's single commit (`finalize-tick.sh`); `/ztn:save` is forbidden
  in-tick.
- `/ztn:role:add` — the concierge that creates a role (`config.yml` + hooks +
  seed). This skill runs roles that already exist; it never creates one.

---

## Scheduler-safety contract

When this skill runs under the autonomous roles tick (the `roles-nightly`
scheduler prompt), it inherits the scheduler contract: **single commit + single
push per tick** (via `finalize-tick.sh`, never `/ztn:save`); best-effort (a role
error degrades to an `error` run, never aborts the tick); idempotent (re-running
matches by role id + run status and never re-drafts a frozen cold-start or
overwrites owner edits); and no direct `git` calls outside the helper scripts.
The skill never spawns a subagent (Step 3) — the tick holds `.roles.lock` and a
child would deadlock on it.
