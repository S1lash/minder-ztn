---
name: ztn:role:ask
description: >
  Ask one of the owner's ZTN roles a question — read-only, lock-free, never
  persists, remit-bounded. Resolves a free-text role reference (display name / id /
  transliteration, STT-tolerant) to a role, then answers in that role's persona
  voice via a 3-tier ladder: L0 its tracked state.md snapshot → L1 a bounded
  synthesis over its remit index → L2 a full remit-bounded investigation (search +
  read + follow the in-remit link graph), escalating only when a tier can't ground
  the answer. Triggers: "спроси у Kitchen Reno про…", "узнай у роли …", "ask my PM role
  about…", "что роль знает про…", "role, what's the status of…", "спроси kitchen-reno".
  For a generic reference ("узнай у роли") it enumerates the owner's roles and asks
  which. It NEVER edits a role — improvements go to `ztn:role:edit`, creation to
  `ztn:role:add`, listing to `ztn:role:list`.
disable-model-invocation: false
---

# /ztn:role:ask — ask a role a question (read-only, 3-tier ladder)

Answer a question a role can address from its own remit — the way you would ask a
standing steward "what's the status / history / why / what's blocked". It is
**read-only**: no lock, no write, it never reaches `roles_persist.py` or the tick
pipeline, and it never mutates any `parts/*.json`, `state.md`, run log, or
CLARIFICATIONS queue. The answer is grounded in the role's remit or it abstains —
it never invents.

This skill was extracted from the `/ztn:roles` runner: the runner is now
tick-only; every question goes here.

## Step 1 — Load context

Load, in order (top wins on conflict): `ENGINE_DOCTRINE.md` (auto-loaded), then —
once the role is resolved (Step 2) — its `_system/roles/{id}/config.yml` (persona /
remit / hooks), its `brief.md` (optional owner STEER — account for it, it is never
grounding), and its `state.md`. Read the role's `hooks/ask.md` body: it is the
role's own answering instruction and voice.

## Step 2 — Resolve the role reference (NEVER guess)

The owner names the role in free speech, often via STT — a display name, a
transliteration, or a slightly-garbled token, not the machine id. Resolve it
deterministically and surface rather than guess:

```bash
python3 - "<reference text>" <<'PY'
import sys
sys.path.insert(0, "_system/scripts")
from roles_common import resolve_role_reference, discover_role_ids, load_role_config
cands = resolve_role_reference(sys.argv[1])
for c in cands:
    print(f"{c.role_id}\t{c.name}\t{c.match}")
PY
```

Act on the result — this is the one place the skill decides, and it decides
conservatively:

| Candidates | Action |
|---|---|
| exactly one `id-exact` / `name-exact` | proceed to Step 3 with that role |
| exactly one `fuzzy` | **CONFIRM first** — "Did you mean **{name}** (`{id}`)?" — answer only after the owner confirms; never act on a fuzzy match unconfirmed |
| two or more | surface a short pick-list ("Which role: **Kitchen Reno** (`kitchen-reno`) or **Book Club** (`book-club`)?") and let the owner choose |
| none, and a name WAS given | "No role matches '{ref}'. Your roles: {list}." — list via `discover_role_ids` + each `config.yml → name` |
| none, generic reference ("узнай у роли", "ask a role") | enumerate the owner's roles and ask which one — a generic reference is not a role name |

Resolve the reference in the owner's language; the answer follows the role's
persona / remit language (its `config.yml` establishes it).

## Step 3 — Answer via the 3-tier ladder (escalate only as needed)

Three tiers, each grounded in the role's remit, escalating ONLY when the current
tier cannot ground the answer. A pure "what's the status" glance lands at L0; a
"details / history / connections / why" question is L2 by nature — jump straight to
the tier the question needs, do not climb needlessly.

**L0 — the tracked snapshot (`state.md`).** Read the role's `state.md`. The owner
portrait is above the markers; each part's rendered view is inside its
`<!-- AUTO: role-state/{part_id} -->` sub-zone (a role is a COMPOSITE — read every
part's zone, e.g. a `ledger` board and a `narrative` reading). Answer from what the
state actually records, in the role's persona voice. This is the status glance:
"what does the role currently track about X". If the tracked state answers the
question, stop here.

**L1 — bounded synthesis over the remit index.** When L0's snapshot doesn't cover
the question (the role hasn't ticked, its draft is still frozen in staging, or the
question is about the current corpus rather than the tracked view), synthesise from
the remit INDEX:

```bash
python3 _system/scripts/minder_query.py --role {id} --list
```

This is the table of contents of the role's remit — one lightweight entry per
in-remit note (path / type / status / trio, no bodies). Answer from the index
shape, and mark it **provisional** when the role has no tracked state yet ("I'm
answering from what's in your notes right now — {Name} hasn't built up its own picture
yet, so treat this as a first read."). Never persist this synthesis.

**L2 — full remit-bounded investigation.** When the question needs detail, history,
connections, or "why" — or L1's index shape can't ground it — investigate the
remit corpus, bounded to the role's zone the whole way:

```bash
python3 _system/scripts/minder_query.py --role {id} --search "<terms>"   # grep the zone → path + snippet
python3 _system/scripts/minder_query.py --role {id} --read <path> ...     # full body of named in-remit notes
```

`--search` matches across ALL in-remit note types the remit covers — knowledge
notes AND meetings AND calls / observations (`_records/` is in scope when the
remit's globs / tags / project-ids reach it). `--read` returns the full body of
named notes. Follow the in-remit **link graph**: when a note you `--read` cites a
`[[wikilink]]` that matters, `--read` that target too — every `--read` is
fail-closed to the remit, so an out-of-zone link is simply refused. Open what earns
opening (the notes the answer hinges on) and cite them; skip the rest. Produce a
grounded, **cited** answer — name the notes it rests on.

**Honor-system boundary (load-bearing).** Navigate FREELY within the remit; never
reach OUTSIDE it. `minder_query --role {id}` refuses any out-of-remit read, so the
tool bounds you — but this is honor-system in this stage (hard FS enforcement
arrives with friend-deploy), so read the zone only through `minder_query`, never a
raw file outside it. If the answer genuinely lives outside the role's remit, say so
plainly ("that's outside {role}'s zone") rather than reaching for it — then offer the
constructive next step: «want me to widen what it watches? (`/ztn:role:edit {name}`)»,
or point at another of the owner's roles whose zone DOES cover it. Read-only is
preserved — this hands off, it writes nothing.

## Step 3.5 — One caring nudge when the read reveals a struggling role

When (and only when) the answer itself exposed that the role isn't serving well, append
ONE plain, dismissable offer AFTER the answer — never instead of it, never on a clean
answer, at most once per session:

- **Answered provisional at L1** (no tracked state — the role has never ticked, or its
  draft is still frozen): «It answered from your notes, not its own tracking yet — want
  to run it? `/ztn:roles --role {id}`»
- **Its subject keeps landing outside its zone** (the question is squarely what the role
  is FOR, yet its zone can't see it — a recurring aim-too-narrow pattern, not a one-off):
  «Its own subject keeps falling outside what it watches — its aim may be too narrow.
  `/ztn:role:edit {name}` to widen it.»
- **Leaned on a stale snapshot** (its last run was long ago and the answer rested on a
  clearly outdated tracked view): «Its picture is from {when it last looked} — want to
  refresh it? `/ztn:roles --role {id}`»

This is a pointer, not an action — the skill stays read-only (writes nothing, runs
nothing; it only names the next step). If the honor-system boundary above already made
the widen offer inline for this same question, don't repeat it. Skip this entirely on a
healthy answer.

## Read-only invariants (the whole safety model)

- **No lock, no write, never persists.** The skill takes no `.roles.lock`, sends no
  payload to `roles_persist.py`, and never reaches the tick's Stage 2 / Stage 3.
  `roles_persist.py` itself refuses an `ask`-hook payload; the skill never sends one.
- **Remit-bounded.** Every corpus read goes through `minder_query --role {id}` —
  the engine-owned scope path. Nothing out of the role's zone is reachable.
- **Persona voice, grounded or abstain.** Answer as the role (its `hooks/ask.md` +
  `config.yml` persona establish the voice), grounded in what the remit records. If
  the remit does not cover the question, say so — never invent to seem complete.
- **Plain projection only.** Never surface `remit` / index / part-kind / tracked-state
  as jargon — answer in the role's plain voice or abstain. (Mirrors `role:list`'s
  read-only plainness floor.)
- **Owner-facing prose only.** No structured output, no state change. Exit status:
  `ask-answered`.

## Files read / written

Read: `_system/roles/{id}/{config.yml, brief.md, state.md, hooks/ask.md}`;
`_system/roles/` (to enumerate roles on a generic / unresolved reference); the
remit corpus via `minder_query --role {id}` (read-only). Reads no other role's
state — the answer is bounded to the addressed role.

**Written: nothing.** This skill is read-only by contract.

## Relationship to the rest of the family

- `ztn:role:add` — create a role (expert concierge).
- `ztn:role:edit` — change / improve / retune + pause / resume / retire.
- `ztn:role:list` — show the owner's roles.
- `ztn:roles` — the mechanical tick runner (scheduler-facing); no `ask` mode.

A question routes here; "improve / retune Kitchen Reno" routes to `edit`; "show my roles"
to `list`. When a request is really an edit ("Kitchen Reno should also watch X"), hand off
to `ztn:role:edit` rather than answering — this skill never changes a role.
