---
name: ztn:roles
description: >
  Tick runner for the ZTN Roles subsystem. Discovers roles under
  _system/roles/{id}/, filters by cadence (is_due) and activation
  (by_change / by_elapsed_time), and for each due role assembles the shared
  frame (_system/roles/_frame.md) + persona/remit + standing brief + one
  body-free prior skeleton per composed part +
  the minder_query zone index (the body navigates its own zone via the scoped
  --list/--search/--read tools), runs thinker→structurer to a delta-payload
  JSON, and hands it to roles_persist.py — the SOLE writer and control boundary.
  The body never edits parts/*.json or state.md. `--approve-coldstart` adopts a
  frozen cold-start draft. Asking a role a question is a separate read-only skill,
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
- **Honor-system reading (lens-style, agentic).** A role NAVIGATES its own zone.
  It is handed the zone INDEX (`minder_query --list` — path / type / status / trio
  per in-remit note, no bodies) plus the scoped `minder_query --list / --search /
  --read` tools bounded to its `config.yml → remit`, and it decides what to open —
  exactly as a lens thinker decides what to read. `minder_query` is a thin scoped
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
| `--dry-run` | modifier | With `--all-due` / `--role`: run the frame stages and print the delta payload, but do NOT call `roles_persist.py` — nothing is persisted, no runs / logs / CLARIFICATIONS written. For prompt iteration. |
| `--force` | modifier | Bypass the Step-0.3 recent-run guard. The scheduled tick passes it implicitly via cron timing. |

Modes are mutually exclusive in spirit: `--role X` overrides `--all-due`;
`--approve-coldstart` is standalone. The scheduled tick uses `--all-due` (with
`--force` by cron alignment).

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
| **Owner-action-required** | `roles_persist.py` reports a `role-*` CLARIFICATION (e.g. `role-cold-start`, `role-new-key`, `role-churn-guard`, `role-auto-paused`, `role-schema-version`, `role-unroutable`, `role-identity-suggest`, `role-nudge`) in its summary | `roles_persist.py` owns the CLARIFICATION emission; the skill surfaces the count + a one-line pointer in the run summary. Continue. |

The `role-*` CLARIFICATION types (the canonical set is registered in
`SYSTEM_CONFIG.md`) are emitted by `roles_persist.py` on a tick — all except
`role-remit-changed`, which `/ztn:role:edit` emits on a remit change. This skill's
`roles_common` emitter refuses any non-`role-*` type. The skill itself does not
emit CLARIFICATIONS — engine-infra failures surface via the log + exit status
(+ the scheduler failure-note in autonomous mode).

---

## Step 0 — Mode dispatch + early exit + cross-skill lock awareness

**FIRST action. No context load, no work until passed.**

### 0.0 Mode dispatch

- `--approve-coldstart <role-id>` → continue through 0.2 + 0.5 (it writes), then
  run **Mode: --approve-coldstart** above.
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

## Step 3 — Per-role isolation contract (load-bearing)

Every role runs in isolation. The runner enforces it at three levels; violating
any one breaks the design.

- **Per-role isolation.** Role N's frame stages have zero visibility into role
  N-1's input, output, or intermediate state. The orchestrator keeps no
  cross-role LLM conversation and passes no «what other roles found» between
  roles. Each role gets its own thinker + structurer pair.
- **Fresh context per stage.** Each LLM call — Stage 1 thinker, Stage 2
  structurer — has **system prompt** = exactly the corresponding `_frame.md`
  stage body (nothing prepended / appended: no skill preamble, no CLAUDE.md, no
  environment block; suppress runtime auto-injection for these calls),
  **user message** = the assembled input for that stage, **conversation
  history** = empty. Stage 2 receives Stage 1's output as INPUT TEXT, not as a
  conversation continuation — the structurer must strictly reformat, not argue.
- **No subagent dispatch.** Stage 1 / Stage 2 are direct LLM calls. Do NOT use
  the Agent / Task tool: it carries a foreign «general-purpose agent» system
  prompt that biases the thinker, and the autonomous scheduler tick holds
  `.roles.lock` while a spawned child would poll for it — deadlock. Retries are
  also fresh-context (no «previous attempt» carried).

Roles are independent, so the Stage-1/Stage-2 LLM calls (thinker →
structurer) across roles are safe to run in parallel — they read only.
The Stage-3 PERSIST (Step 4.5, `roles_persist.py`) MUST stay sequential:
it read-modify-writes shared files (`CLARIFICATIONS.md`, the append-only
`roles-runs.jsonl` / `log_roles.md`), so two persists in flight could lose
a write. Default is **sequential, in sorted-id order** for the whole tick.

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
`counts`. This is the role's table of contents; the bodies are fetched on demand
by the thinker via the scoped `--search` / `--read` tools (4.4), not dumped here.
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
    parts.append((st, import_archetype(p.kind)))

# cold_start (role-level): ANY part is fresh (never advanced, no draft, no content)
# OR has a frozen draft pending → tell the thinker a first draft is due for it. A
# records-grounded part's watermark is an exact "never adopted" proxy; a values-grounded
# part (a stance) consumes no records, so its watermark can stay None even after it has
# adopted a live position — for such a kind, freshness falls back to its live content.
def is_fresh(st, plugin):
    if st.get("staging") is not None:
        return False
    if st.get("seen_watermark") is not None:
        return False
    if getattr(plugin, "GROUNDING_MODEL", "records") != "records":
        return not list(plugin.content_summary(st))
    return True
cold_start = (not parts) or any(
    is_fresh(st, plugin) or isinstance(st.get("staging"), dict) for st, plugin in parts
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
wms = [eff_wm(st, plugin) for st, plugin in parts] or [None]
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
print(json.dumps({"activated": activated, "cold_start": cold_start,
                  "by_change": by_change, "by_elapsed": by_elapsed}))
PY
```

The index is passed as the `$INDEX` file arg (the heredoc owns stdin). If
`activated` is false → the role is cadence-due but nothing changed and no elapsed
floor fired: **skip silently** (no run recorded, mirroring a not-due role),
`rm -f "$INDEX"`, and count it under «skipped: not activated» in the log
summary. If `activated` is true → proceed. `cold_start` selects the framing in
4.3. Remove `$INDEX` in the role's finally once the tick completes.

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
   `type` / `status` / `trio` per in-remit note, no bodies), PLUS the scoped-tool
   description: the body navigates its own zone via `minder_query --list /
   --search "<q>" / --read <path>` (all bounded to `--role {id}`) and decides what
   to open. This is the handed map, not a handed pile of bodies. It is SHARED
   across the role's parts (one remit → one index).
4. The role's `hooks/tick.md` body (its role-specific tick instruction / voice).

Render each part skeleton deterministically from its `parts/{part_id}.json`. A
body-free projection — never leak the withheld fields. The runner never names a
kind of its own invention: it projects the shape `_frame.md` documents for each
`part.kind` it finds.

### 4.4 Run the frame stages → delta payload

- **Stage 1 — Thinker** (primary LLM; system = `_frame.md` Stage-1 body; user =
  the 4.3 assembly — zone index + scoped-tool description; fresh context): the
  thinker navigates its own zone and reasons free-form about what changed against
  the given keys. Give it the scoped `minder_query` reads as direct read-only
  tools it may call itself — `--list` (re-list the zone), `--search "<q>"`
  (keyword-grep the zone), `--read <path>` (full body of a named in-remit note) —
  all bounded to the role's remit via `--role {id}`, so nothing out of zone is
  reachable (an out-of-remit `--read` is refused). These are direct tool calls in
  the thinker's OWN fresh context, NOT a spawned subagent — the no-subagent rule
  (Step 3) is intact. The thinker decides what to open; it is not handed
  pre-dumped bodies. Capture its reasoning verbatim. Up to 2 fresh-context
  retries on transient error; on exhaustion → role-level `error` run + skip.
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

```bash
PAYLOAD_FILE=$(mktemp)
printf '%s' "$PAYLOAD_JSON" > "$PAYLOAD_FILE"
python3 - "$INDEX" "$PAYLOAD_FILE" <<'PY' > "${PAYLOAD_FILE}.fixed"
import json
import sys
from pathlib import Path

index = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

# Engine-authored grounding oracle: the zone-index stems from --list this tick,
# in list order, deduped. Replaces whatever the structurer wrote into read_records
# so the body cannot author the set the validator checks citations against.
stems = []
for unit in (index.get("units") or []):
    path = unit.get("path")
    if not path:
        continue
    stem = Path(str(path)).stem
    if stem not in stems:
        stems.append(stem)
payload["read_records"] = stems
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

Then hand the corrected payload to the writer:

```bash
printf '%s' "$PAYLOAD_JSON" | python3 _system/scripts/roles_persist.py --role {id} --payload -
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
  entries itself.

It prints a summary JSON on stdout: `outcome`, `run_status` (ok / empty /
rejected / paused), `counts` (added / advanced / clarifications / rejected),
`clarifications` (the `role-*` types it emitted), `state_flag`, `exit`.

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
`_system/roles/{id}/{parts/*.json, state.md (AUTO sub-zones), decisions.jsonl}`,
`_system/state/roles-runs.jsonl` (per-role rows), `_system/state/log_roles.md`
(per-role sections), `_system/state/CLARIFICATIONS.md` (the `role-*` types registered in SYSTEM_CONFIG.md).

## Files read

The thinker (Stage 1) navigates its own zone via the scoped `minder_query` tools
(honor-system, remit-bounded) — it decides what to open. The runner itself reads:
- `_system/roles/{id}/{config.yml, brief.md (optional STEER), parts/*.json, state.md, hooks/tick.md}` (`hooks/ask.md` is read by `/ztn:role:ask`, not the tick runner)
- `_system/roles/_frame.md`
- `_system/state/roles-runs.jsonl` (last_run + recent-run check)
- `_system/docs/ENGINE_DOCTRINE.md`, `SYSTEM_CONFIG.md` (context load)
- the `minder_query.py --list` zone index (per role, per tick), plus any
  `--search` / `--read` calls the thinker issues within its remit

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
| `--dry-run` | Runs Stages 1–2, prints the payload, never calls `roles_persist.py`; nothing persisted. |

---

## Coordination with other skills

- `/ztn:process`, `/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`, `/ztn:content`,
  `/ztn:resolve-clarifications` — mutually exclusive via the seven-lock matrix
  (Step 0.2). No data-path overlap: roles write only under `_system/roles/`,
  `_system/state/roles-runs.jsonl`, `_system/state/log_roles.md`, and the
  `role-*` CLARIFICATIONS.
- `/ztn:resolve-clarifications` — the owner resolves the `role-*`
  CLARIFICATIONS there (cold-start approval, new-key placement, churn holds,
  identity suggestions, auto-pause, proactive nudges). `--approve-coldstart` is the direct approval
  path for the cold-start case.
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
