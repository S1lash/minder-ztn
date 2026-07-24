---
name: ztn:role:edit
description: >
  Change, improve, or retune one of the owner's ZTN roles — and run its lifecycle
  (pause / resume / retire). The expert counterpart to `ztn:role:add`, but over a
  role that already has HISTORY: it reads the role's decisions and run log and its
  tracked part state to propose GROUNDED improvements («Kitchen Reno ran eight weeks and
  never flagged a stale item — add a staleness instruction to its tick?»), then
  applies the owner-confirmed change validate-before-write — never leaving an invalid
  config on disk. Resolves a free-text role reference (display name / id /
  transliteration, STT-tolerant) the same way `ask` does — confirm on fuzzy, never
  guess. Ordinary edits (persona / cadence / name / hooks / activation / adding a new
  part) just validate and write. It also runs the **acting lifecycle**: renew / revoke
  / re-point a role's outward **mandate** (the act grant + scope + expiry), and **grant
  a tool** the role asked for via a `role-tool-request` (add a registered tool to a
  part, or hand off to `/ztn:role:add` to wire a new one) — human-gated, never a
  self-grant. A remit change stages a re-baseline instead of silently churning the
  tracked state; a parts-shape change that would strand state is refused in favour of a
  new role. Acquires `.roles.lock` before writing.
  Triggers: «давай улучшим Kitchen Reno», «переучи роль», «поменяй как звучит роль»,
  «расширь что она смотрит», «переименуй роль», «поставь роль на паузу», «верни
  роль», «убери роль», «дай роли доступ к…», «продли / отзови мандат», «improve my PM
  role», «retune / rename / widen / pause / resume / retire this role», «grant the role
  a tool», «renew / revoke its mandate».
disable-model-invocation: false
---

# /ztn:role:edit — change / retune a role + lifecycle (expert)

The owner says «let's make {role} better» / «change how it sounds» / «widen what it
watches» / «pause it» / «retire it». This skill resolves which role they mean, loads
it, understands the edit on the merits, and applies the owner-confirmed change to
`config.yml` + `hooks/*.md` (+ optional `brief.md`) — **validate-before-write, atomic,
never an invalid config left on disk**. It PRESERVES the role's tracked state
(`parts/*.json` / `state.md`) and its `brief.md` — an edit changes the role's identity
and instructions, not its accumulated memory.

It is the sibling of `ztn:role:add`, and it inherits that skill's whole stance — the
concierge tone, the honesty gates, the reader-alignment, the one-question-per-turn
discipline, the «fights for the owner» expert posture — with ONE defining difference:
**it operates over a role that already ran.** That history is the raw material of the
expert proposal (Step 3). The owner never sees `remit` axes, `persona` stances,
`cadence_anchor`, `parts`, or any config field — the skill handles all of it.

**What a role is** (same model the family shares): a standing steward of one
owner-declared zone, a **composition of ordered parts**, each a built part-kind — a
**ledger** (keyed workstreams with moving status + owner / priority / due / deps) and a
**narrative** (a purpose headline + a grounded, versioned reading of meaning /
alignment). Most real roles are composite. This skill retunes the composition; it does
not reshape it in a way that would strand a part's state (see «Parts-shape change»).

---

## Philosophy

- **Concierge over a role with history, not a form-editor.** The owner talks about
  THEIR role and what they want different; the skill talks back about their role, never
  about `remit` globs or `persona` axes. It reads the role's real track record and
  proposes the highest-leverage change — it does not just apply the literal words.
- **Fights for the owner (expert edit).** After loading the role AND its history, it
  asks «what change would actually serve this role best» — which may be more than the
  literal ask (a staleness instruction the role never had, a tightened alignment
  framing, a meeting-aware remit widening). It proposes, grounds each proposal in the
  role's real decisions / runs / tracked state, and pushes back when a different edit
  serves better. It never imposes. (See Step 3.)
- **Preserve accumulated memory.** An edit is not a reset. `parts/*.json`, `state.md`,
  `decisions.jsonl`, and `brief.md` survive every ordinary edit untouched. The only
  thing this skill rewrites is the role's identity + instructions (`config.yml` +
  `hooks/*.md`), and `brief.md` only when the owner explicitly changes their steer.
- **Validate-before-write, always.** The new config is generated in memory, validated
  via `load_role_config` against a temp copy, and only swapped into place on success.
  An invalid config is never left on disk. (See Step 6.)
- **A remit change stages a re-baseline, never a silent churn.** The tracked state was
  built against the OLD zone. Reshaping the remit and letting the next tick reconcile
  silently would orphan keys or trip the churn-guard. So the skill writes the new remit,
  emits a `role-remit-changed` CLARIFICATION, and tells the owner the next tick
  re-baselines. (See «Remit change».)
- **A parts-shape change that rewrites state is refused on a live role.** Removing a
  part, replacing a part, or changing a part's kind would strand that part's tracked
  state. On a role that already ran, this is disallowed — the honest answer is a NEW
  role (offer to hand off to `ztn:role:add`). Adding a NEW part is fine — it cold-starts
  like a fresh role. (See «Parts-shape change».)
- **Lifecycle is an explicit owner act.** pause / resume / retire / hard-delete are
  legitimate owner commands — distinct from the runner's FORBIDDEN silent auto-pause
  recovery. Retire captures an Archive-Contract reason; hard-delete of owner data needs
  a typed confirmation. (See «Lifecycle».)
- **Honest about limits.** An edit that would need an unbuilt part-kind, a schema
  change, or a state-stranding reshape is named plainly with the real options — never
  papered over, never faked.
- **Quality over speed.** A bad edit corrupts a role that was working. Better to push
  back («that would strand its memory — here's the honest path») than to ship a change
  that quietly breaks the role's state.

**Language convention (load-bearing).** Lock the user-facing language at the first
turn: detect from the owner's opening message (Russian → Russian for the whole session;
English → English; mixed / unclear → fall back to `_system/SOUL.md` body text, then
recent records, then English). Maintain it across every turn. When the skill rewrites a
hook body, it writes it in the role's ESTABLISHED hook language (read the current
`hooks/*.md`), not necessarily the conversation language — the `/ztn:roles` runner
reasons in the language the hooks establish, so a hook-language switch is itself an edit
the owner must ask for explicitly. Machine state — `id`, `part.id`s, `config.yml` keys
and enum values, file paths — English only, always. The `name:` display field MAY be
non-ASCII («Kitchen Reno»).

**Reader alignment (load-bearing).** The owner reads every turn. Word the questions,
proposals, disclosures, and summaries to fit how THIS owner takes in information — the
presentation floor in `_system/docs/communication-baseline.md` (conclusion first, plain
language, high signal, no filler, no flattery), this owner's presentation-delta
principles in `_system/views/constitution-core.md` (ai-interaction), and their working
style in `_system/SOUL.md` (`## Context for Agents`, `## Working Style`). Read whichever
exist; a missing file is skipped silently → fall back to the communication-baseline
floor, then plain generic UX.

**HARD BOUNDARY: this shapes FORM only** — the wording, density, and ordering within the
fixed structure below. Decide the substance on the merits FIRST — which edit class the
ask really is, whether a remit change needs a re-baseline, whether a reshape would
strand state, what must be disclosed — and only then let the owner's profile shape how
it reads. It NEVER softens the state-stranding refusal, NEVER drops the remit-rebaseline
CLARIFICATION, NEVER skips a retire reason, NEVER waters down the validate-before-write
gate, and NEVER fabricates a capability that cannot run to please the owner. Per
`principle-ai-interaction-012`, adaptation to how the owner thinks must not become an
echo of what is pleasant to hear: stay critical, keep the gates intact.

**Documentation convention.** On any edit to this SKILL, follow
`_system/docs/CONVENTIONS.md` — describe current behaviour, no version / phase / rename
history, no personal names (placeholders like «Kitchen Reno», or read `SOUL.md` at runtime).

**Contracts:**
- `_system/scripts/roles_common.py` — config schema + loader / validator
  (`load_role_config`, `load_role_config_file`), `discover_role_ids`,
  `resolve_role_reference`, `emit_clarification`, cadence / persona semantics. The skill
  imports these for resolution, validation, and the re-baseline CLARIFICATION.
- `_system/scripts/minder_query.py` — remit resolver; the skill runs it to probe what a
  CHANGED remit would return before writing it.
- `_system/roles/_frame.md` — the shared three-stage frame every tick runs inside; a
  rewritten hook body must still fit it, never extend it.
- `_system/scripts/roles_archetype_*.py` — each built part-kind's plugin
  (`CONCIERGE_MANIFEST`); read when adding a new part, to compose it honestly.
- `_system/docs/ENGINE_DOCTRINE.md` §3.1.5 (Archive Contract), §3.6 (owner-LLM
  contract) — retire captures a reason; never seed part state, never extend schema,
  never silently mutate owner-curated state, never delete `_sources/`.

---

## Edit classes — the routing table (decide the class FIRST)

Every ask maps to exactly one class. The class decides the machinery; the reader-
alignment only shapes how it reads. Detect the class from the ask, confirm it if the
ask is ambiguous, then run its rule.

| The owner wants to… | Class | Machinery |
|---|---|---|
| change how it SOUNDS (voice / values / worldview / tempo; add or drop a counter-stance) | **persona edit** | ordinary config edit (Step 5); counter-stance ⇒ `mandate` mapping + Step 7 disclosure |
| change HOW OFTEN it looks (daily / weekly / biweekly / monthly, or the weekday / day-of-month) | **cadence edit** | ordinary config edit; `cadence_anchor` must match the cadence kind |
| change WHEN it updates (only-on-change vs a periodic floor) | **activation edit** | ordinary config edit |
| **rename** it (what the owner calls it) | **name edit** | ordinary config edit of the `name` display field (may be non-ASCII); the machine `id` / directory is stable — see «Rename» |
| change its INSTRUCTIONS — what «stewarding this zone» means, what to flag, its tone in the hook | **hook edit** | rewrite `hooks/tick.md` / `hooks/ask.md`; must still fit `_frame.md` |
| change / add its private STEER notes channel | **brief edit** | set / unset `brief: brief.md`; create an empty `brief.md` the owner fills — the engine never writes it |
| change whether / how long it can ACT on an external board (keep it going, stop it touching the board, point it at a different board) | **mandate edit** | rewrite or remove the `mandate:` block (see «Mandate lifecycle») — ordinary config edit, never a schema extension |
| GRANT a new tool the role asked for (it raised a `role-tool-request`) | **tool-grant** | add an existing registered tool to the relevant part's `tools:` grant, or hand off to `/ztn:role:add` to register a brand-new one — human-gated, never a self-grant (see «Tool-grant») |
| **ADD a new part** to the composite (e.g. add an alignment narrative to a ledger-only PM) | **add-part edit** | append to `parts[]`; it COLD-STARTS on the next tick (see «Add a part») |
| change WHAT ZONE it watches (widen / narrow / re-aim the remit) | **remit change** | write new remit + emit `role-remit-changed` re-baseline — NEVER a silent churn (see «Remit change») |
| REMOVE / REPLACE a part, or change a part's KIND | **parts-shape change** | **DISALLOWED on a live role** — offer a new role (see «Parts-shape change») |
| add a config field / a new cadence / persona stance / part-kind / hook | **schema extension** | **BLOCKED** — routes to the engine maintainer (see «Schema extension») |
| pause / resume / retire / hard-delete the role | **lifecycle** | flip `status` / archive with reason / typed-confirm delete (see «Lifecycle») |

When an ask bundles several classes («make it pushier AND widen it AND rename it»),
handle them one at a time, each on the merits — never batch. A remit change inside a
bundle still stages its own re-baseline.

**A cross-route beats every class.** If an «add a part» / «make it also …» ask is really
a passive observer (a lens) or raw daily-number intake (a metric source), it is not a
role edit at all — Step 2 names the better-fit primitive and hands off to
`/ztn:agent-lens-add` / `/ztn:source-add` before any class rule runs. A metrics PART
that tracks an EXISTING number toward a target is a legitimate add-part, not a
cross-route.

---

## Arguments

`$ARGUMENTS` supports:
- `<reference text>` — a free-text role reference (display name / id / STT token);
  resolved at Step 1. May be followed by the plain-language ask.
- (no reference) — the skill asks which role, enumerating the owner's roles.
- `--pause <ref>` / `--resume <ref>` / `--retire <ref>` — lifecycle shortcuts (still
  resolved + confirmed; retire still captures a reason).
- `--dry-run` — full conversation + proposals + a printed preview of the exact config /
  hook diff that WOULD be written, no disk writes, no lock taken for the write.
- `--show-technical` — reveal the current + proposed `config.yml` / hook bodies before
  the write.

---

## Conversation discipline (hard rules)

1. **One question per turn.** Maximum two if tightly coupled. Never batch.
2. **Wait for response** before continuing with new content.
3. **Turn length cap.** Each non-preview turn ≤ 10 lines + the question; proposal and
   confirmation turns may run 15–25 lines.
4. **Acknowledge before pivoting.** One short acknowledgement before the next question.
5. **No system-mechanics jargon unprompted.** Plainness calibrated per «Reader
   alignment»; the floor holds even for a technical owner.
6. **No bait-and-switch.** If the class is really a state-stranding reshape or a schema
   extension, say so when it first appears — do not confirm an edit you cannot ship.
7. **Recoverable cancellation.** «cancel» / «start over» at any turn → «no problem —
   nothing is written yet» and exit. No partial state, and the lock (if held) is
   released.

---

## Step 0 — Pre-flight (silent, read-only)

The conversation runs lock-free; only the write step (Step 6) takes `.roles.lock`. But
if a tick is already running, an edit conversation would only collide — so pre-check:

1. **Competitor + runner lock check.** Read the pipeline lock files under `_sources/`,
   in order; if any is present and fresh (< 2h, parse the ISO timestamp): tell the owner
   plainly which pipeline is busy and exit.
   - `.processing.lock` → «/ztn:process is running — try again in a few minutes»
   - `.maintain.lock`, `.lint.lock`, `.agent-lens.lock`, `.content.lock`,
     `.resolve.lock` → same shape.
   - `.roles.lock` → «the roles system is mid-run — try again in a few minutes» (a tick
     or a cold-start approval is writing a role dir).
   A stale lock (> 2h) → warn, report the PID if present, do NOT auto-delete (a human
   may be inspecting a crash), and do not proceed.
2. **Load the reader-alignment set** (per «Reader alignment»): `communication-baseline.md`,
   `SOUL.md` (`## Context for Agents` + `## Working Style`), `constitution-core.md`. Read
   whichever exist; skip a missing file silently.
3. **Read `_system/roles/_frame.md`** — the contract a rewritten hook must fit.
4. If a required engine file is missing (`roles_common.py`, `minder_query.py`,
   `_frame.md`) → «the roles system isn't fully installed — {file} is missing» and exit.
   Do NOT try to bootstrap.

---

## Step 1 — Resolve the role reference (NEVER guess)

The owner names the role in free speech, often via STT — a display name, a
transliteration, a slightly-garbled token, not the machine id. Resolve it
deterministically and surface rather than guess — the SAME contract as `ztn:role:ask`:

```bash
python3 - "<reference text>" <<'PY'
import sys
sys.path.insert(0, "_system/scripts")
from roles_common import resolve_role_reference
for c in resolve_role_reference(sys.argv[1]):
    print(f"{c.role_id}\t{c.name}\t{c.match}")
PY
```

| Candidates | Action |
|---|---|
| exactly one `id-exact` / `name-exact` | proceed to Step 2 with that role |
| exactly one `fuzzy` | **CONFIRM first** — «Did you mean **{name}** (`{id}`)?» — proceed only after the owner confirms; never act on a fuzzy match unconfirmed |
| two or more | surface a short pick-list («Which role: **Kitchen Reno** (`kitchen-reno`) or **Book Club** (`book-club`)?») and let the owner choose |
| none, and a name WAS given | «No role matches ‘{ref}’. Your roles: {list}.» — list via `discover_role_ids` + each `config.yml → name` |
| none, generic reference («улучши роль», «edit a role») | enumerate the owner's roles and ask which one — a generic reference is not a role name |

Resolve in the owner's language. STT garbles names — verify, do not rename on an
uncertain token. Once resolved, load the role: `load_role_config(id)` for the validated
config, plus its `hooks/tick.md` / `hooks/ask.md`, its `state.md`, and its `brief.md` if
present. Everything the skill knows about the role comes from these.

---

## Step 2 — Understand the ask + classify the edit

1. **Acknowledge** the ask briefly (one line).
2. **Classify** the edit against the routing table (silent). If the ask is ambiguous
   about class, ask ONE clarifying question — «do you want it to SOUND different, or to
   watch a different zone?» — never guess the class.
3. **Cross-route check (a different primitive, not a role edit — mirrors `add` Step 2b).**
   An ask framed as «also add a part» / «make it also …» is sometimes not a role edit at
   all. Before any add-part or schema machinery, catch the two primitives that belong
   elsewhere and hand off:
   - a passive OBSERVER of a pattern over time («make it also just watch my mood»,
     «notice when I keep avoiding X») → a **lens**: «That's less a job for {role} and more
     a quiet observer that watches a pattern over time — that's what a lens is for. Want
     me to set that up? (`/ztn:agent-lens-add`)»
   - raw daily-NUMBER intake («also pull my daily weight», «ingest a number I log each
     day») → a **metric source**: «Pulling a raw daily number in is a metric source, not
     something a role does — `/ztn:source-add <name> --family metric-day` sets up the
     intake.» (A role CAN track that number toward a target once the source exists — that
     part I can add here; the cross-route is only for RAW intake with no source.)
   A wish can be BOTH (keep the role AND set up the lens / source) — offer each its own
   home. Only when the ask genuinely belongs in the role, continue.
4. If the class is **schema extension** → block now (see «Schema extension»), exit.
5. If the class is **parts-shape change** on a live role → name it now (see «Parts-shape
   change»), offer the new-role hand-off, exit unless the owner picks a different edit.
6. Otherwise → continue to Step 3 (expert read) then the class's rule — EXCEPT pure
   lifecycle (pause / resume / retire) and rename, which SKIP Step 3 and go straight to
   their class rule (Step 4). Pausing or renaming has nothing to «improve»; an expert
   read there would surface proposals the owner didn't come for. (Retire still captures
   its Archive-Contract reason; hard-delete still needs its typed confirmation.)

---

## Step 3 — Expert read (fight for the role, grounded in its history)

This is where the skill earns «expert» over a role with a track record. Before applying
the literal ask, read the role's HISTORY and propose the highest-leverage change —
grounded in what actually happened, never invented. Surface 1–3 proposals, plainly, each
an OFFER the owner accepts or declines (never imposed).

**Skipped for a pure lifecycle edit (pause / resume / retire) or a rename** — those have
nothing to improve, so Step 2 routes them straight to their class rule (Step 4). The
grounded-proposal pass below is reserved for the substantive edits — persona / cadence /
activation / hook / remit / add-part / brief — where the role's history genuinely
informs a better shape.

Read the role's own record (all read-only):

```bash
# the role's decision audit — what it actually changed, tick by tick
python3 _system/scripts/minder_query.py --role {id} --list   # remit index (what its zone holds now)
```
- `_system/roles/{id}/decisions.jsonl` — the append-only audit of every delta it
  persisted (what it added / advanced / revised, with evidence + hook).
- `_system/state/roles-runs.jsonl` — its run history (when it ticked, empty vs
  productive runs, rejects, auto-pauses).
- `_system/roles/{id}/parts/*.json` + `state.md` — its current tracked state.

Grounded proposal shapes (only offer what the history genuinely supports):

- **A gap the history reveals.** «This role ran eight weeks and its ledger never once
  moved an item to `blocked`, though three workstreams stalled — want me to add a
  staleness instruction to its tick, so it flags a workstream that hasn't moved in N
  weeks?»
- **A stale part.** «Its narrative purpose hasn't been revised in a month, though the
  ledger churned through a dozen items — the reading has drifted from the work. Want me
  to tighten the alignment framing so it re-checks purpose against the current
  workstreams each tick?»
- **A remit that's half-blind.** «It has never cited a meeting — its zone can't see your
  calls. A PM that can't see the calls where decisions get made misses half the story.
  Want to widen the zone to the meetings tagged {project}?» (this is a **remit change** —
  it triggers the re-baseline path, Step «Remit change».)
- **Noise the runs show.** «Half its ticks were empty — the cadence is faster than the
  zone changes. Want to slow it to biweekly so every run has something to say?»

**Mandatory self-review gate (silent, before applying).** Ask: «is this the change that
actually serves the role — or am I just applying the literal words?» If the latter, go
back and propose the better shape. This gate NEVER fabricates a capability, NEVER
over-broadens the remit to seem useful, NEVER adds a part the owner declined — it only
ensures the offered edit is the best HONEST one (principle-ai-interaction-012).

Everything here is an OFFER. An owner who just wants the literal tweak gets exactly that
— the expert read proposes, it never forces richness on a plain ask.

---

## Step 4 — Apply the class rule

Run the rule for the classified edit. Each produces a proposed NEW `config.yml` (and / or
new hook bodies) IN MEMORY — nothing is written until Step 6.

### Persona / cadence / activation / name / hook / add-part / brief — ordinary edits

Map the plain ask to the config field(s), propose the concrete change WITH a reason, let
the owner accept or adjust. The owner never sees the field name.

- **Persona.** Map to the four axes (voice / values / worldview / tempo) as
  `inherit | own | counter`. A **counter** stance ⇒ attach `mandate` as a YAML **mapping**
  `{scope, expires, owner_consent_ref}` (never a bare string — the loader drops a bare
  string) and surface the counter disclosure at Step 7. Dropping a counter ⇒ remove the
  `mandate` with it.
- **Cadence.** `daily | weekly | biweekly | monthly`; `cadence_anchor` must match the
  kind (a weekday for weekly / biweekly, a day-of-month 1–28 for monthly, `daily` for
  daily). The owner says «Sundays» / «end of month»; the skill maps it.
- **Activation.** `by_change` on / off; offer the elapsed-time floor only if the owner
  wants a guaranteed periodic check even when nothing changed.
- **Name (rename).** Change the `name` display field — what the owner calls the role; may
  be non-ASCII. The machine `id` and the directory are STABLE (they anchor
  `parts/*.json`, `state.md`, `decisions.jsonl`, and every run-log reference) — renaming
  the machine id would strand all of that. If the owner insists the machine id itself is
  wrong, that is effectively a new role: offer the `ztn:role:add` hand-off, don't move
  the directory here.
- **Hook.** Rewrite `hooks/tick.md` and / or `hooks/ask.md`. The new body must still fit
  `_frame.md` (name each part's job, keep grounding-in-real-notes, no schema invention).
  Written in the hook's established language (per the language convention).
- **Add a part.** Append a `{id, kind}` to `parts[]` — a plain English `part.id` naming
  its job, and a BUILT `kind` chosen the SAME way `ztn:role:add` composes (read the
  plugins' `CONCIERGE_MANIFEST`s, never hardcode a list): match a reference kind only when
  the wish fits its EXACT shape 1:1; a VARIATION adapts via `registry` (form-as-data
  capturing the owner's OWN states / fields), never bent into a reference. The new part
  carries NO state yet — it **cold-starts** on the next tick exactly like a fresh role's
  part (frozen draft → owner approval). Tell the owner: «the new tracker starts empty and
  builds a draft you approve on the next look; everything the role already tracks keeps
  its memory.» Do NOT seed its `parts/{id}.json` — the writer owns that.
- **Brief.** Set `brief: brief.md` and create an empty `brief.md` with a one-line header
  the owner fills, or unset `brief` to drop the channel (leave any existing `brief.md`
  file in place — it is owner data; only stop the config from pointing at it, and say
  so). The engine never writes `brief.md`.

Then go to Step 6 (validate-before-write).

### Mandate lifecycle — renew / revoke / re-point (owner language only)

A role with a `mandate:` block (`autonomy`, `scope: [{target, surface, mode, blast}]`,
`until`) is authorized to ACT on an external board (`_system/scripts/roles_common.py` →
`MandateSpec`; a real example is `_system/roles/minder-pm/config.yml`). The owner never
says «mandate» / «scope» / «blast» / «until» — they say things like «let it keep
updating my board» or «stop letting it touch my board». Map the plain ask to one of
three moves, then go to Step 6 like any other identity edit:

- **Renew.** «Let it keep going» / «extend it» / «don't let it stop acting» → update
  `until` to a later ISO date, or drop `until` entirely for open-ended. `until` is the
  date `roles_mandate.mandate_is_live` checks before authorizing any act — once it's
  past, every act is refused outright, not paused-and-resumable. A mandate that lapsed
  is the usual trigger for this edit (see the `role-act-failed` boundary case below) —
  this skill is the renewal path.
- **Revoke.** «Stop letting it touch my board» / «make it read-only again» → remove the
  whole `mandate:` block. `roles_mandate.authorize_act` refuses any act with no mandate,
  so the role reverts to read-only stewarding; its existing ledger / narrative state is
  untouched.
- **Re-point.** «Point it at a different board» / «it's watching the wrong page now» →
  change the scope target's `surface` (the specific board id), keeping the same
  `target` tool. Tell the owner plainly: the role's READ zone (`remit`) and its WRITE
  target (`mandate.scope[].surface`) are two separate settings (INV-16) — re-pointing
  one never silently moves the other.

**The two guards stay, always — state them for the owner plainly, never as jargon:**
1. Every act the role stages is still owner-confirmed in the harness, regardless of the
   `autonomy` dial — a mandate never grants a silent write.
2. An act tool that needs its own auth is `http` / `local` only, never `mcp` / `skill`.

A malformed mandate (missing `scope`, a `surface` that isn't a real id, a non-ISO
`until`) is refused and retried at Step 6 like any other identity edit — never left
invalid on disk.

### Tool-grant — grant a role's tool request (human-gated, never a self-grant)

A running role can ASK for a tool it would work better with — it raises a
`role-tool-request` CLARIFICATION (grounded in what its ticks actually needed, HITL, and
**never a self-grant**: a role cannot give itself a tool, by construction). This skill is
the human-gated grant path — the grant only ever happens here, on the owner's word. When
the owner decides to grant it, map to one of two moves, then go to Step 6 like any
ordinary identity edit:

- **The requested tool already exists** in the registry (`_system/registries/TOOLS.md`) —
  add its tool id to the relevant part's `tools:` grant (INV-19 per-part grant). Validate
  it in temp and swap atomically (Step 6) like any config edit; the loader refuses a grant
  naming a tool the registry doesn't hold, so a typo can't reach disk. Tell the owner
  plainly which part now holds the tool and what it can now read / do.
- **The requested tool is brand-new** (no registry row yet) — registering a tool needs its
  adapter kind, any credential + verify-at-creation, and its `TOOLS.md` row. That is the
  concierge's setup walk, not a config field this skill can conjure. Hand off: «Adding a
  tool the engine has never seen needs the setup walk — `/ztn:role:add` registers it
  (adapter, any login, a test that it works), then it's granted to the role.»

The two guards from a mandate edit hold here too: the role never grants itself, and an
ACT tool stays `http` / `local`, never `mcp` / `skill` (a harness-executed adapter has no
out-of-band runner to hand a secret to — CONTRACT §5). The owner later resolves the
open `role-tool-request` item in `/ztn:resolve-clarifications`.

### Remit change → `role-remit-changed` re-baseline (never a silent churn)

The remit is the allow-list the role reads. Changing it means the tracked state was built
against the OLD zone — the ledger keys, the narrative evidence, all anchored to notes that
may now be out of zone (or new notes are now in zone that the state never saw). Letting the
next tick reconcile that silently would **orphan keys or trip the churn-guard** (a mass of
items suddenly unreachable reads as a wholesale rewrite). So this class NEVER just writes
the remit and moves on. Instead:

1. **Probe the new remit before writing it** (calibration — same as `add` Step 4b). Run
   the resolver with the DRAFTED remit and show the owner what it lands on now:

   `--remit-json` is a dev/preview scope override gated behind `ZTN_DEV=1` (the hard
   read-lock refuses it otherwise — INV-15); the remit-preview probe is the sanctioned
   dev use, so set the marker:

   ```bash
   ZTN_DEV=1 python3 _system/scripts/minder_query.py \
     --remit-json '{"globs":["1_projects/x/**"],"project_ids":["x"],"decision_notes":false,"all":false}' \
     --no-body --compact
   ```
   Report the count + a few real note titles. If it lands on zero → block and re-aim
   (an empty remit is a dead role). If it reaches `all: true` → confirm it's deliberate
   and flag the broad-scope sensitivity disclosure now.

2. **Write the new remit** into the proposed config (Step 6 validates + writes it).

3. **Emit a `role-remit-changed` CLARIFICATION** so the re-baseline is staged, not silent:

   ```bash
   python3 - "{id}" <<'PY'
   import sys
   sys.path.insert(0, "_system/scripts")
   from roles_common import emit_clarification
   rid = sys.argv[1]
   emit_clarification(
       ctype="role-remit-changed",
       subject=rid,
       context=(
           f"The zone role '{rid}' watches was changed by an owner edit. Its tracked "
           "state (ledger keys / narrative evidence) was built against the previous "
           "zone, so the next tick must re-validate every tracked item against the new "
           "zone rather than churn-reconcile it. This item records that a re-baseline is "
           "pending; the owner does not need to act — the next tick handles it under the "
           "churn-guard, and only genuine drift surfaces further."
       ),
       source=f"ztn:role:edit — remit change on {rid}",
       suggested_action=(
           "review; the next tick re-validates tracked state against the new zone "
           "(re-baseline). No manual reshape needed."
       ),
       action_taken="remit updated; re-baseline pending",
   )
   PY
   ```

4. **Tell the owner plainly**: «I've re-aimed its zone. It keeps its current memory; on
   its next look it re-checks every tracked item against the new zone rather than
   reshuffling it all at once — so nothing gets orphaned. I've noted the re-baseline so
   the system expects it.»

This stages a re-validation; it never silently reshapes the tracked state.

### Parts-shape change → refuse on a live role, offer a new role

Removing a part, replacing a part with a different one, or changing a part's `kind`
would **strand that part's tracked state** (`parts/{id}.json` + its `state.md` sub-zone +
its `decisions.jsonl` rows anchor to the part id and kind). On a role that already ran,
this is DISALLOWED — there is no honest in-place path that preserves the contract. Say so
plainly and offer the real path:

> «Dropping the piece that tracks {its job} would lose everything it's remembered about
> that — its tracked items don't carry over to a different shape, and I won't quietly
> drop them. The honest move is a fresh role with the shape you want; this one keeps its
> history intact. Want me to hand off to role-creation to build the new one?
> (`/ztn:role:add`)»

If the owner agrees → point them at `/ztn:role:add` (this skill does not create roles).
**Adding** a new part is NOT a parts-shape change — it cold-starts cleanly and is handled
in the ordinary-edit path above. The line: append = fine (new state), remove / replace /
re-kind = refused (stranded state).

### Schema extension → block, route to the engine maintainer

The owner asks for a config field that doesn't exist, a cadence outside
`{daily, weekly, biweekly, monthly}`, a persona stance outside `{inherit, own, counter}`,
a part-kind that isn't built, or a hook beyond `{tick, ask}`:

> «That changes how roles work in general, not just this one — it needs an engine change,
> not this skill. Tell me what you want added and take it to whoever maintains the engine
> setup.»

Exit, no writes. Never extend the schema to please the ask.

### Lifecycle — pause / resume / retire / hard-delete

Lifecycle is an explicit owner command — legitimate, and DISTINCT from the runner's
forbidden silent auto-pause recovery. Each still resolves + confirms the role first.

- **Pause.** Flip `status: active → paused` (validate-before-write, Step 6). The role
  keeps all its state and stops being picked up by the tick runner. Tell the owner: «paused
  — it keeps everything and simply won't run until you resume it.»
- **Resume.** Flip `status: paused → active`. «resumed — it'll run on its next scheduled
  look.»
- **Retire.** Archive the role with an **Archive-Contract reason captured with the role**
  (doctrine §3.1.5) — keep it RECOVERABLE, do not delete. Set `status: paused` and record
  the reason in the config as an `archive_reason: "<owner's reason>"` field alongside
  status (owner-supplied — ask for one line: «why retire it?»). The role's dir, state, and
  history all remain on disk; it simply never runs. Tell the owner: «retired — it's stood
  down with the reason noted, and everything it built is kept. Say the word and I can bring
  it back.» (Retire is deliberately reversible; a true removal is the next, separate act.)
- **Hard-delete.** Removing the role's dir (owner data — state, history, everything) needs
  an **explicit typed confirmation**, never a soft yes:
  > «This deletes `{id}` and everything it built — its tracked state and full history — for
  > good. This can't be undone. Type the role's id exactly to confirm: `{id}`»
  Only on an exact-match reply → remove `_system/roles/{id}/`. Any other reply → «kept it —
  nothing deleted.» Default is always the safe path; a hard-delete is never inferred.

---

## Step 5 — Disclosures (mandatory before the write, when applicable)

Show the applicable groups as one block (they're short). Reader-alignment shapes the
prose; it NEVER drops a disclosure.

- **Counter persona (only if any axis is / becomes `counter`):** «You've given this role a
  deliberately opposing stance on {axis} — it'll push back on you there. That shapes how it
  TALKS and what it flags; it never changes what gets written to its state (still grounded
  and validated). It's advisory, scoped to {mandate scope}.»
- **Broad / whole-base remit (when a remit change reaches `all: true` or spans many
  projects):** «You've widened its zone to {plain description} — with a whole-base zone it
  can also see notes you've marked sensitive. Deliberate choice; you can narrow it any time
  by editing the zone again.»
- **Remit change (any):** «Its zone changed, so on its next look it re-baselines — it
  re-checks its tracked items against the new zone rather than reshuffling everything at
  once. Its memory is kept; only genuine drift will surface.»
- **Add-part:** «The new tracker starts empty and builds a draft you approve on its next
  look; everything the role already tracks keeps its memory.»

---

## Step 6 — Validate-before-write (atomic; never an invalid config on disk)

Disk writes happen here, and ONLY if the new config validates. The role dir already
exists with live state — so the write is a careful in-place swap, never a blind
overwrite.

1. **Acquire `.roles.lock`.** Re-read the competitor + runner locks (Step 0.1); if a tick
   started meanwhile, abort with «the roles system just started a run — try again in a few
   minutes» and do not write. Otherwise create `_sources/.roles.lock`:
   ```
   {ISO UTC timestamp} — role edit, PID {pid}, role: {id}, class: {edit class}
   ```
   Wrap Steps 6.2–6.6 in try/finally; **release the lock in finally on every exit path.**
2. **Snapshot the current config AND every hook body you will change** — read
   `config.yml` raw text AND the current raw text of each `hooks/*.md` (and `brief.md`)
   this edit will touch into memory as the rollback baseline. Snapshot the WHOLE set you
   will modify, not just the config — a rollback must restore config + hooks as one unit,
   so a config↔hook mismatch can never be left on disk. (State files are never touched.)
3. **Write the proposed config to a temp path** (`config.yml.tmp` in the role dir) and any
   changed hook bodies to their own temp paths.
4. **Validate the temp config:**
   ```bash
   python3 - "{id}" <<'PY'
   import sys
   from pathlib import Path
   sys.path.insert(0, "_system/scripts")
   from roles_common import load_role_config_file, RoleConfigError
   rid = sys.argv[1]
   tmp = Path("_system/roles")/rid/"config.yml.tmp"
   try:
       cfg = load_role_config_file(tmp)      # full schema validation
   except RoleConfigError as exc:
       print(f"INVALID: {exc}"); sys.exit(1)
   if cfg.id != rid:
       print(f"INVALID: id {cfg.id!r} != dir {rid!r}"); sys.exit(1)
   parts = ", ".join(f"{p.id}:{p.kind}" for p in cfg.parts)
   print(f"OK: {cfg.id} parts=[{parts}] cadence={cfg.cadence} status={cfg.status}")
   PY
   ```
   If it prints `INVALID` (or exits non-zero) → the proposed config is wrong. **Do NOT
   swap it in.** Fix the offending field (most often a `cadence_anchor` that doesn't match
   the cadence, or a persona / cadence value outside the allowed set, or a `mandate` that
   isn't a mapping), rewrite the temp, re-validate. Retry up to 3 times. Still failing →
   this is a skill bug: discard the temp files (the live `config.yml` was never touched),
   tell the owner «I hit an internal snag producing a valid change — nothing was written»,
   release the lock, stop.
5. **Atomic swap — config FIRST, hooks only after the config is confirmed live.** Only
   after `OK`: atomically move `config.yml.tmp` → `config.yml`, then run a final
   `load_role_config(id)` (the dir-match check) to confirm the LIVE config loads. Only when
   that final load succeeds, atomically move each hook temp → its real path. If the final
   load FAILS → restore the config snapshot (the hooks were NOT swapped yet, so nothing is
   mismatched), report the snag, write nothing else. If a hook move itself fails after that
   → restore config AND every hook body from the Step-6.2 snapshot, so the role is left
   exactly as it was. A rollback always restores config + hooks together — never a half-set.
6. **The remit-change CLARIFICATION** (Step 4 «Remit change») is emitted here, after the
   config is safely in place — so a pending re-baseline is only recorded once the new
   remit is actually live.

**Preserve, never reset.** Step 6 touches ONLY `config.yml`, changed `hooks/*.md`, and (on
a brief edit) `brief.md`. It NEVER writes `parts/*.json` or `state.md` (the writer
`roles_persist.py` owns those), NEVER touches `decisions.jsonl` or `roles-runs.jsonl`, and
a hard-delete is the sole path that removes anything — and only on typed confirmation.

**`--dry-run`:** skip the lock and all writes; print the exact before / after of every file
that would change, and state that the config would validate (run the temp-file validation
against a temp copy if feasible).

---

## Step 7 — Summary + next step

Final user-facing turn — conclusion first, per «Reader alignment»:

> «Done — `{id}` ({name}) updated: {plain one-line of what changed}.
>
> {If remit change:} Its zone re-baselines on the next look; its memory is kept.
> {If add-part:} The new part builds a draft you approve on the next look.
> {If pause/resume/retire:} {plain status line}.
>
> Files changed:
> - `_system/roles/{id}/config.yml`
> {- `_system/roles/{id}/hooks/tick.md` — only if the hook changed}
> {- `_system/roles/{id}/brief.md` — only if the steer channel changed}
>
> Nothing's saved to your history yet — say the word and I'll save it for you
> (`/ztn:save`). {technical owner: `git diff` shows the raw changes first.} To ask it
> anything: `/ztn:role:ask {name}`.»

The skill never auto-commits.

---

## Skill-level invariants (doctrine §3.6)

- **Never leave an invalid config on disk.** Every write is validate-in-temp →
  atomic-swap; a config that won't load is fixed-and-retried (≤3×) or discarded, never
  swapped in.
- **Never reset a role's memory on an ordinary edit.** `parts/*.json`, `state.md`,
  `decisions.jsonl`, `roles-runs.jsonl`, and `brief.md` survive every edit; only a
  typed-confirmed hard-delete removes them.
- **Never silently churn a remit change.** A remit edit stages a `role-remit-changed`
  re-baseline CLARIFICATION; it never lets the next tick reshape tracked state silently.
- **Never reshape parts in a way that strands state.** Remove / replace / re-kind on a live
  role is refused → new role. Only appending a part (which cold-starts) is allowed.
- **Never seed part state.** Adding a part writes only its `parts[]` entry; the writer
  cold-starts it.
- **Never extend the schema.** New field / cadence / stance / part-kind / hook → blocked,
  routed to the engine maintainer.
- **Never let a mandate edit bypass the owner-confirm gate or grant a disallowed tool
  kind.** Renew / revoke / re-point only ever touch `autonomy` / `scope` / `until` —
  every staged act still needs `/ztn:roles --approve-acts`, and an act tool stays
  `http` / `local`, never `mcp` / `skill`.
- **Never let a role grant itself a tool, and never grant a tool the registry doesn't
  hold.** A `role-tool-request` is granted only here, on the owner's word — an existing
  tool onto a part's `tools:`, or a hand-off to `/ztn:role:add` for a brand-new one; an
  act tool stays `http` / `local`.
- **Never rename the machine `id` / move the directory** in place (it anchors all state) —
  a genuine id change is a new role.
- **Never flip status except on an explicit owner command.** pause / resume / retire are
  owner acts; the skill never auto-pauses (that is the runner's forbidden path).
- **Never retire without a captured reason** (Archive Contract §3.1.5); never hard-delete
  without a typed confirmation of the id.
- **Never delete anything under `_sources/`** or any other owner-data path except the role
  dir on a confirmed hard-delete.
- **Never auto-run a tick.** Bringing a changed / resumed role to life is `/ztn:roles`'s
  job; this skill hands off, it never ticks.
- **Never auto-commit to git.**
- **Never batch questions** or skip an applicable Step 5 disclosure.
- **Never expose internal mechanics** unless asked (`--show-technical` or an explicit
  question).

---

## Files read by this skill

- `_system/roles/{id}/config.yml`, `hooks/tick.md`, `hooks/ask.md`, `brief.md`,
  `state.md`, `parts/*.json`, `decisions.jsonl` (the resolved role — identity + history).
- `_system/state/roles-runs.jsonl` (the role's run history — expert read, Step 3).
- `_system/roles/` (to enumerate roles on a generic / unresolved reference).
- `_system/roles/_frame.md` (the contract a rewritten hook must fit).
- `_system/registries/TOOLS.md` (to confirm a requested tool exists on a tool-grant).
- `_system/scripts/roles_archetype_*.py` `CONCIERGE_MANIFEST` (when adding a part).
- `_system/SOUL.md`, `_system/docs/communication-baseline.md`,
  `_system/views/constitution-core.md` (language + reader alignment).
- the `minder_query.py` probe output (remit-change calibration + expert read).

## Files written by this skill

- `_system/roles/{id}/config.yml` — the edited config (atomic swap after validation).
- `_system/roles/{id}/hooks/tick.md` / `hooks/ask.md` — only on a hook edit.
- `_system/roles/{id}/brief.md` — only on a brief edit (created empty for the owner; never
  populated by the engine).
- `_system/state/CLARIFICATIONS.md` — a `role-remit-changed` item, only on a remit change.
- `_sources/.roles.lock` — created + released around the write (concurrency lock).

**Never written:** `parts/*.json`, `state.md` (writer-owned), `decisions.jsonl`,
`roles-runs.jsonl` / `log_roles.md` (audit trails), `views/ROLES.md` (rendered by
`render_roles_registry.py` via `/ztn:maintain`). A hard-delete removes the whole role dir,
and only on typed confirmation.

## Relationship to the rest of the family

- `ztn:role:add` — create a role (expert concierge). This skill hands off to it for a
  parts-shape change or a machine-id change that is really a new role.
- `ztn:role:ask` — ask a role a question (read-only). When an ask is really a question
  («what's Kitchen Reno tracking?»), route there, don't edit.
- `ztn:role:list` — show the owner's roles.
- `ztn:roles` — the mechanical tick runner (scheduler-facing); brings a changed / resumed
  role to life on its next look, and owns the re-baseline after a remit change. Exclusive
  on a role dir via `.roles.lock` — this skill takes the same lock for its write.
- `/ztn:resolve-clarifications` — where the owner later resolves the `role-remit-changed`
  item this skill stages (and any `role-*` item a running role raises, including a
  `role-act-failed` pointing back here for a mandate renewal).
- `/ztn:save` — the owner's commit step; this skill never commits.

---

## Boundary cases

| Case | Behaviour |
|---|---|
| Reference is fuzzy / STT-garbled | Confirm on fuzzy, pick-list on multiple, never guess (Step 1). |
| Generic reference («улучши роль») | Enumerate roles, ask which. |
| Ask bundles several edit classes | Handle one at a time, each on the merits; a remit change still stages its own re-baseline. |
| Remit widened to `all: true` | Confirm deliberate; broad-scope disclosure (Step 5); re-baseline CLARIFICATION. |
| Remit change lands on 0 notes | Block, re-aim — an empty remit is a dead role. |
| Remove / replace / re-kind a part on a live role | Refuse; offer `/ztn:role:add` for a new role. |
| Add a new part | Allowed; it cold-starts on the next tick; existing parts keep memory. |
| A staged act can't run because its mandate expired (owner sees a `role-act-failed` CLARIFICATION pointing here) | Renew — update or drop `until`; see «Mandate lifecycle». |
| «Stop letting it touch my board» / «point it at a different board» | Revoke or re-point the `mandate:` block; see «Mandate lifecycle». |
| A role asked for a new tool (owner sees a `role-tool-request` CLARIFICATION) | Grant an existing registered tool onto the relevant part's `tools:`, or hand off to `/ztn:role:add` to register a brand-new one; human-gated, never a self-grant (see «Tool-grant»). |
| «Also watch / observe a pattern» or «also pull a raw daily number» | Cross-route at Step 2 — a lens (`/ztn:agent-lens-add`) or a metric source (`/ztn:source-add`), not a part; a metrics part tracking an EXISTING number stays a valid add-part. |
| Pure lifecycle (pause / resume / retire) or rename | Skips the Step 3 expert read — applies the class rule directly (Step 2 → Step 4); no unrequested improvement proposals. |
| Rename (display) | Edit `name`; machine id / dir stable. |
| Owner insists the machine id is wrong | That's a new role — hand off to `/ztn:role:add`; don't move the dir. |
| New config field / cadence / stance / part-kind / hook | Block at «Schema extension», route to the engine maintainer. |
| Counter persona added / dropped | Attach / remove the `mandate` mapping; counter disclosure at Step 5. |
| Pause / resume | Flip `status`, validate-before-write. |
| Retire | Archive with a captured reason; recoverable; nothing deleted. |
| Hard-delete | Typed id confirmation required; else kept. |
| Proposed config fails `load_role_config_file` | Fix-and-retry ≤3×; still failing → discard temp, live config untouched, report the snag. |
| A pipeline / `.roles.lock` is busy | «roles system busy, try again» and exit (Step 0 / Step 6 re-check). |
| `--dry-run` | Full conversation + proposals + exact before/after diff, no lock, no writes. |
| Owner says «cancel» / «start over» | No writes, lock released if held, friendly exit. |
| Owner asks «how do roles work?» mid-flow | Brief plain answer (3–4 lines), offer to continue. |
| Ask in a language other than English / Russian | Skill responds in the owner's language; hook rewrites stay in the hook's established language unless the owner asks to switch. |

---

## Anti-patterns the skill MUST avoid

- ❌ Guessing a fuzzy role reference instead of confirming.
- ❌ Overwriting `config.yml` in place without validating a temp copy first.
- ❌ Leaving an invalid `config.yml` on disk.
- ❌ Silently churning a remit change (orphaning keys / tripping the churn-guard) instead
  of staging the `role-remit-changed` re-baseline.
- ❌ Removing / replacing / re-kinding a part on a live role (stranding its state).
- ❌ Seeding a new part's `parts/{id}.json` (the writer cold-starts it).
- ❌ Resetting a role's tracked state / history on an ordinary edit.
- ❌ Extending the schema (new field / cadence / stance / part-kind / hook).
- ❌ Renaming the machine id / moving the dir in place.
- ❌ Auto-pausing (that is the runner's forbidden path) — pause only on owner command.
- ❌ Retiring without a captured reason, or hard-deleting without a typed confirmation.
- ❌ Auto-running a tick or holding `.roles.lock` beyond the write.
- ❌ Auto-committing to git.
- ❌ Batching questions or skipping an applicable disclosure.
- ❌ Lecturing about how roles work unless asked.
