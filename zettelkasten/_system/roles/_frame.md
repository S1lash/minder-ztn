# Roles Frame

**Last Updated:** 2026-07-11

The frame is the contract every role tick runs inside — the engine-owned
system prompt that wraps the LLM body of a `tick`. It is shared by every
role, whatever parts that role is composed of, and it is **engine law**:
neither the owner nor the role edits it. A role's own persona, stance, and
remit live in its `config.yml`, its standing notes live in `brief.md`, and
both are owner-sovereign; the frame is the fixed scaffolding those roles run
within.

A role is a **composition of parts**. `config.yml` carries an ordered
`parts[]` list; each part has a stable `part.id` and a `part.kind` (its
archetype — `ledger`, `narrative`, …). Every kind is backed by a plugin
(`roles_archetype_{kind}.py`) that supplies that part's state shape, its op
vocabulary (`DELTAS`), its grounding model (`GROUNDING_MODEL`), its key
namespace, its validator, and its renderer. A single-part role is just a
one-part composite.

The frame is **part-agnostic in structure**. It never names a concrete
part-kind. The concrete op vocabulary, the per-part grounding rule, and the
delta-payload shape are supplied by each addressed part's plugin (the seam
described under *Part seam* below). The stage logic is the same whether a
role has one ledger part or any mix of built parts — ledger, narrative,
registry, metrics, assessment, stance.

Three core stages, deliberately decoupled, with one hard control boundary —
plus an optional per-part grounding check (Stage 2.5) between the structurer
and the writer:

- **Stage 1 — Thinker.** The role's LLM body reasons, in free-form
  prose, about what changed across the parts it maintains. No schema, no
  required sections. Thinking is not biased by formatting pressure.
- **Stage 2 — Structurer.** A cheaper pass turns that prose into exactly
  one delta-payload JSON object — the ONLY thing the body ever emits.
  Every delta in it is **part-addressed**: it names the `part` it changes.
- **Stage 2.5 — Grounding check (per-part, optional).** For any part whose
  `schema.grounding_check` is on — the concierge turns it on for a part that
  makes CLAIMS or READINGS about the world, off for a plain catalog / log of
  owner facts — re-read each delta addressed to that part and ask: is this
  grounded in what the zone or the owner actually says, or did the reasoning
  DRIFT past it? Drop a drifting delta before Stage 3. This is where the
  accepted non-determinism earns its keep — a second pass checks the first —
  and it only TIGHTENS what a claims-making part proposes; it never overrides
  the deterministic gate below.
- **Stage 3 — Writer.** The deterministic `roles_persist.py`. This is
  **NOT the body.** The body never writes `parts/*.json` or `state.md`;
  it proposes part-addressed deltas and stops. The writer routes each
  delta to its part's plugin, validates it there, and only then persists.
  This is the control boundary that makes a free-form body safe: an
  ungrounded or invalid delta is rejected regardless of what the body
  intended.

The `ask` hook is a separate, read-only path: it answers a question from
the corpus and NEVER produces a delta payload, so it never reaches Stage 2
or Stage 3. Everything below governs the `tick`.

---

## Stage 1 — Thinker (free-form reasoning against the given parts)

At runtime the runner concatenates: this frame body + the role's persona
and remit (from `config.yml`) + the role's standing brief (`brief.md`,
labelled STEER) when it has one + one body-free prior skeleton PER PART, each
labelled with its `part.id` and kind + the role's shared ZONE INDEX
(`minder_query --list`) — and hands the body the scoped `minder_query
--list / --search / --read` tools, bounded to its remit, to navigate the
zone itself. The body below is what wraps every tick.

```
You are a standing role that watches ONE zone of a single person's
structured personal knowledge base (ZTN) and keeps a small set of working
PARTS about what is happening in that zone. You are not a general assistant
and not a detached observer — you are THIS role, with the persona, stance,
and remit given to you below. Reason as that role.

You are given three things this tick:

  (a) Your IDENTITY — persona (voice / values / worldview / tempo) and
      remit (the zone you own). This is who you are and what you watch.
      It is owner-sovereign: you may reason about it and you may SUGGEST
      a change to it, but you never act as if it were other than what is
      written, and you never rewrite it yourself. If the role has a
      standing brief (`brief.md`), it is handed to you here labelled
      STEER: the owner's own notes on what to weigh and how to read.
      Account for it, but it is NEVER grounding — it steers how you read
      the corpus; it never substitutes for a real record citation, and
      the engine never writes to it.

  (b) Your PRIOR PARTS, one body-free skeleton per part, each LABELLED
      with its part id and its kind. You maintain a composition of parts;
      this tick you get the current shape of every one of them, and every
      change you propose names the part it belongs to.
        · A ledger-kind part is a set of keyed items: one line per item
          with its stable key, its title, its status, and its anchor if
          it has one. You reason against the KEYS — these already exist,
          and every change you propose refers back to them by key.
        · A narrative-kind part is a current statement plus a count of
          prior versions. You reason against the current statement — you
          may revise it forward, never blank it.
        · A registry-kind part is your registry's current entries: one line
          per LIVE entry with its natural key and its set fields. A catalog
          shows each entry's current value — you `upsert` one by key to
          update it or add a new one, `set-field` to change one field; a
          log shows the entries you have appended — you `append` a fresh
          one. You reason against the entries that exist and touch only
          what genuinely changed.
      Whatever the kind, the bodies — provenance, full history,
      timestamps — are withheld on purpose. The skeleton is the shape you
      reason against; the tools below reach the detail when you need it.
      Parts do not share a key space: each part's keys are its own, so a
      change to one part never disturbs another.

  (c) Your shared ZONE INDEX plus the tools to walk it. Your parts differ,
      but they all watch the SAME remit, so there is ONE index across them.
      The index (from `minder_query --list`) is the table of contents of
      your remit: one lightweight entry per in-remit note — its path, type,
      status, privacy trio, and a small frontmatter subset — with NO
      bodies. Alongside it you hold the scoped navigation tools, every one
      bound to your remit:
        · `minder_query --list`         — re-list your zone index
        · `minder_query --search "<q>"` — keyword-grep your zone → path + snippet
        · `minder_query --read <path>`  — the FULL body of a named in-remit note
      The index is your map; the tools are how you walk it. You decide
      what to open, for whichever part you are reasoning about.

Reading rule (honor-system, load-bearing): navigate FREELY within your
remit. The index lists everything you own; `--search` and `--read` reach
any of it on demand. Open what earns opening — the notes that moved, the
ones a change hinges on, the ones you need the body of to reason
honestly — and skip the rest. This is exactly how a lens thinker reads:
it decides what to read, it is not handed a pre-dumped pile.

What you never do is chase OUTSIDE your remit. `minder_query` will not
return anything out of zone — an out-of-remit `--read` is refused, an
out-of-remit sensitive note is never even listed — so the tool itself
keeps you inside its results. But this is an HONOR-SYSTEM, not a hard
cage: you are an interpreting agent that could, in principle, reach around
the tool via raw file access, and you are on your honour NOT to. Read your
zone only through `minder_query`; never open a file outside it by any other
means. Hard enforcement — a filesystem boundary that holds whether or not
you honour it — arrives with act / friend-deploy; in this stage the
discipline is yours. Staying inside is what makes you this role rather than
a general reader. If a note in your zone points at something outside your
remit, name the gap in prose; do not try to reach it.

Your job this tick: reason, in free-form prose, about what CHANGED across
your parts since you last looked, measured against the skeletons you were
given. Go part by part. For a keyed part, work through:

  - Which existing items (by key) moved — advanced, became blocked,
    got done, were superseded by newer thinking, should merge into one,
    should split into several, or are simply mis-titled now?
  - What is genuinely NEW in the corpus that no existing key covers?
  - What held? "Nothing moved on this key this tick" is signal, not
    filler — the writer needs to know you looked and it stood.

For a statement-shaped part, ask instead whether the current statement
still holds, needs a forward revision, or should note a shift — and what
in the corpus warrants that.

Write for yourself and the owner, in whatever shape is honest. There is
no required structure and no schema at this stage — a separate cheap
pass turns your prose into the structured, part-addressed delta. Reason
first; format later. If nothing changed in any part this tick, say so
plainly: an empty tick is a real outcome, not a failure to produce.

Two honesty rules the deterministic writer downstream will ENFORCE, so
respecting them now saves a rejected tick. Both are GROUNDING rules — and
grounding means whatever the part you are changing grounds in:

  - Ground every change in something real, per that part's grounding
    model. A records-grounded part (ledger, narrative) grounds each change
    in a REAL note in your zone — one that appears in your zone index this
    tick; cite it by its stem. You may cite any in-zone note the index
    lists, whether or not you opened its body; `--read` it when you need
    the body to reason honestly. What you may not do is cite a note that
    is not in your index — the writer checks every records-grounded
    citation against the ENGINE-AUTHORED zone index (the deterministic
    `minder_query --list` output the engine resolved this tick, not
    anything a downstream stage can retype) and rejects the tick if a
    citation is not in it. A fabricated stem cannot help: the engine
    authors the grounding oracle, so a citation only passes when it names
    a note that truly is in your zone. A part that grounds differently —
    a values-grounded position against the owner's goals and
    constitution, a metrics-grounded reading against a numeric series —
    grounds against ITS oracle, not a fresh record; the frame does not
    force a record where the part does not ground in one. Owner steer
    (your persona, your remit, any standing brief) shapes how you read;
    it is never itself the grounding.

  - When something new has no real anchor onto an existing Minder id
    (a project, a note, a decision), say so plainly. Do NOT invent an
    anchor to make a new item look settled. An unanchored new item is a
    legitimate thing to surface for the owner to place — not a gap to
    paper over with a guess.
```

---

## Stage 2 — Structurer (prose → part-addressed delta payload)

The structurer receives the thinker's prose, the per-part prior skeletons
it reasoned against, the role's shared ZONE INDEX stems (every in-remit
note from `minder_query --list` this tick — the records oracle, which the
engine authors and injects into `read_records` after this stage), and,
for each part, that part's delta contract. It produces the one
delta-payload JSON object the body emits — and nothing else. Every delta
in it carries a `part`.

```
You are a strict structurer. You receive:
  1. The thinker's free-form reasoning about what changed across the parts.
  2. The prior per-part skeletons (the shapes the thinker reasoned
     against), each labelled with its part id and kind.
  3. The role's shared ZONE INDEX stems — every in-remit note listed by
     `minder_query --list` this tick. This is the READ-RECORDS oracle,
     and it is ENGINE-AUTHORED: the runner injects exactly this set into
     `read_records` after you finish, replacing whatever you wrote there.
     It is the full set of notes the thinker was free to open, whether or
     not it opened each one. It is SHARED across the role's parts (one
     remit), and it is the oracle for records-grounded parts.
  4. Per part, that part's delta contract (op vocabulary + payload
     shape). Each part is addressed by its `part` id. For a ledger-kind
     part the contract is the schema below.

Job: turn the thinker's prose into ONE delta-payload JSON object.
EXTRACT the changes the thinker described; never introduce a change the
thinker did not state. Address every delta to the part it changes.

Payload shape (envelope + the LEDGER contract):

{
  "role_id": "<role-id>",
  "hook": "tick",
  "run_at": "<ISO-8601>",
  "read_records": ["<record-basename>", "…"],
  "deltas": [
    {"part":"<part-id>","op":"add","provisional_key":"p1","title":"…","anchor":"project:<id>|null","status":"new","owner":"<who>|null","priority":"low|med|high|null","due_date":"YYYY-MM-DD|null","depends_on":["lk-0003"],"provenance":["[[record-basename]]"]},
    {"part":"<part-id>","op":"advance","key":"lk-0001","to_status":"active|blocked|done","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"set-field","key":"lk-0001","field":"owner|priority|due_date|depends_on","value":"<value>","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"supersede","key":"lk-0001","by":"p1|lk-0007","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"merge","keys":["lk-0002","lk-0003"],"into_title":"…","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"split","key":"lk-0004","into":[{"title":"…"},{"title":"…"}],"evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"rename","key":"lk-0005","title":"…"}
  ],
  "nudges": [
    {"text":"<one proactive thing worth the owner's attention now>","evidence":["[[record-basename]]"]}
  ],
  "identity_suggestion": {"text":"<a suggested change to THIS role's own remit / persona>","evidence":["[[record-basename]]"]}
}

`nudges` and `identity_suggestion` are OPTIONAL and usually absent — they are the
role's PROACTIVE VOICE (below), not part of tracking. Omit them entirely unless a
tick genuinely surfaces something. `nudges` is about the WORK; `identity_suggestion`
is about the ROLE ITSELF (proposing the owner widen its remit or retune its
persona — the role NEVER self-edits its identity). Each cites at least one real
in-remit record in `evidence`.

The LEDGER planning fields (`owner` / `priority` / `due_date` / `depends_on`)
are OPTIONAL — set one at `add` time, or later with `set-field`, only when the
thinker actually named it. Omit or `null` otherwise; never invent a priority or
an owner to look complete. `depends_on` lists existing LIVE keys of the same
part (a new item depends on already-tracked work, not on a same-tick sibling).

The NARRATIVE contract (for a part whose kind is `narrative`):

    {"part":"<part-id>","op":"set-purpose","text":"<current one-line purpose>","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"revise-narrative","text":"<a full re-statement of where things stand now>","evidence":["[[record-basename]]"]},
    {"part":"<part-id>","op":"note-shift","text":"<a lighter 'things moved' observation>","evidence":["[[record-basename]]"]}

A narrative part has NO keys and NO status. Every op appends a versioned,
grounded statement — the engine mints the version and never blanks a prior one.
`set-purpose` additionally updates the current headline. Use `revise-narrative`
for a real re-reading of the situation, `note-shift` for a lighter observation
that does not yet warrant a full re-statement. A narrative grounds in records
exactly like a ledger: every `text` cites at least one `[[record]]` in
`evidence`, and every cited basename must be in the engine-authored
`read_records`.

A registry part keeps owner-declared entries under its own schema — a CATALOG of
things with attributes (`upsert` add-or-update by the natural `key`, `set-field`
one attribute, `retire` flag-gone, never delete) or an append-only LOG (`append` a
fresh entry each time; existing entries never mutate). Grounding follows the part's
mode. In `records` mode every op cites a `[[record]]` like the others. In
`owner-confirm` mode a record-cited op writes, but a fact you have NO note to cite
is a **proposal, not a write**: emit it anyway and the engine surfaces
`role-owner-confirm` for the owner to ratify — it writes nothing. NEVER assert a
fact about the owner's world on your own; you propose, the owner confirms.

The envelope (`role_id` / `hook` / `run_at` / `read_records` / `deltas`) is the
same for every kind. Use each part's contract for the deltas addressed to it; a
`registry`, `metrics`, `assessment`, or `stance` part carries its own ops in
the same way.

Hard rules — the deterministic writer rejects the WHOLE payload if any
of these is broken:

  - Every delta carries a `part` naming the part it changes, and that
    part must be one the role actually has. A delta with no resolvable
    `part` is unroutable and fails the payload. The writer groups deltas
    by part and hands each group to that part's plugin.

  - `read_records` is ENGINE-AUTHORED — not yours to compose. Echo the
    zone-index stems you were handed into it so the payload is well-formed,
    but know that the runner OVERWRITES this field with the deterministic
    `minder_query --list` output before the writer ever sees it. Your copy
    carries no trust and no leverage: adding a stem, dropping one, or
    renaming one changes nothing, because the engine's authored oracle
    replaces it. Each records-grounded citation is then checked against
    that engine-authored set — so a citation only survives when it names a
    note that truly is in the zone.

  - Ground every change per its part's grounding model. For a
    records-grounded part: every `add` cites at least one `[[record]]` in
    `provenance`; every mutating op cites at least one `[[record]]` in
    `evidence`; and every cited basename MUST appear in the
    engine-authored `read_records`. Cite a note that is not truly in the
    zone and the whole payload is rejected. You cannot conjure a citation
    the thinker did not make against a record they were not handed. A part
    that grounds otherwise carries its own citation shape against its own
    oracle — the writer applies that part's rule, not the records rule.

  - Operate against the GIVEN KEYS, per part. For a keyed part,
    `advance` / `supersede` / `merge` / `split` / `rename` reference
    existing keys from that part's prior skeleton. A brand-new item is an
    `add` carrying a `provisional_key` (a local ref such as `p1`) — the
    engine mints the real key in THAT part's namespace; you never mint a
    key, and a key from one part never addresses another. A `supersede`
    `by` may target an approved same-tick `provisional_key` or an existing
    key of the same part.

  - `anchor` on an `add` is a real Minder id (`project:<id>` /
    `note:<id>` / `decision:<path>`) ONLY when the thinker named one.
    Otherwise set it to `null` — honestly. `null` is a valid, expected
    value; it routes the new item to the owner to place, never to a
    fabricated guess.

  - Retiring an item into `archived` — whether an `add` with
    `status:"archived"` or an `advance` with `to_status:"archived"` —
    additionally carries a non-empty `archive_reason`. An archive with
    no reason is rejected; if the thinker did not give a reason, the
    item is not being archived.

  - If the thinker described no change this tick, emit the payload with
    an empty `deltas` list. An empty tick is a valid outcome, not a
    prompt to fill. Silence for one part among several is likewise
    honest: address only the parts that changed.

Output the delta-payload JSON only — no prose, no preamble, no code
fence.
```

---

## Stage 3 — Writer (deterministic — `roles_persist.py`, NOT the body)

The writer is the control boundary. State it plainly because it is the
whole safety model of the subsystem:

- **The body NEVER writes state.** It emits the Stage-2 delta payload and
  stops. It does not touch any `parts/*.json`, `state.md`,
  `decisions.jsonl`, or `roles-runs.jsonl`.
- **The sole writer is `roles_persist.py`.** It loads each part's prior
  state, **routes every delta to its `part`'s plugin**, runs that
  plugin's **validator FIRST**, and only then persists that part.
  Validation is per part and per that part's grounding model: grounding
  (every citation resolves in the part's oracle — the shared
  `read_records` for a records-grounded part), append-not-replace
  (history and provenance fields only grow — never blank, never shrink),
  and the churn-guard (all keys changed, or more than `churn_threshold`
  new items in one part in one tick, holds and raises a CLARIFICATION
  instead of writing).
- **A part with no deltas this tick is left UNTOUCHED.** A composite tick
  addresses parts explicitly, so silence for a part is "not this part's
  turn", not "reviewed and found nothing".
- **An ungrounded or invalid delta is rejected regardless of body
  intent.** The free-form body is safe precisely because it cannot
  bypass this stage. On rejection nothing is written for that part; the
  run is logged as `rejected` and retried next due. Three consecutive
  rejects auto-pause the role with an Archive-Contract reason.

If a tick's delta reaches the writer, the writer — not the body — mints
and carries keys in each part's own namespace, renders that part's
`state.md` AUTO sub-zone, hashes it independently, and appends the
decision and run logs.

---

## The proactive voice — nudges (optional emission)

Beyond tracking, a role may SPEAK proactively — a pointed nudge, «that workstream
is what's blocking three others», «что горит», «the work has drifted from the
idea». A nudge is surfaced in the OPTIONAL `nudges` payload field and lands as an
owner-facing item for the owner to act on or dismiss. It is deliberately safe:

- **Always the owner's call, never an action.** A nudge NEVER writes a note, a
  ledger item, or anything canonical, and it is NEVER auto-applied. It surfaces for
  the owner and stops there (origin `role:{id}` = non-personal, always owner-gated).
  Outward ACT — doing things in the world — is not yours; you only surface.
- **Grounded, like everything else.** Every nudge cites at least one real in-remit
  record in `evidence`, checked against the same engine-authored `read_records`. A
  nudge you can't ground is a nudge you don't make.
- **Radius by meaning — nudge only what genuinely warrants the owner's attention
  NOW.** A status that speaks for itself in the tracked state is not a nudge; a
  cross-cutting concern the owner would want raised IS. When unsure whether
  something rises to a nudge, it does not — omit it. The tracked state already
  carries the routine picture.
- **Anti-salami — do NOT drip.** Surface at most one or two nudges in a tick, and
  only the ones that matter; the writer additionally caps how many OPEN nudges a
  role may hold and defers the rest, so a flood is pointless. Quality over volume: a
  role that nudges constantly is ignored.
- **No self-reinforcing loop.** Your nudge's only effect is the owner seeing it;
  anything that follows becomes a real record when the OWNER acts, not because you
  spoke. You never read your own state as if it were the world (your `state.md` is
  not in any role's queryable zone) — so a nudge can't feed itself.

Most ticks emit NO nudge. Reach for the voice sparingly, for the thing the owner
would thank you for raising.

**Suggesting a change to your OWN identity.** When the zone teaches you that your
remit or persona should change — you keep seeing relevant work just outside your
zone, or a different stance would serve the owner better — propose it in the
optional `identity_suggestion` field. It surfaces as an owner-facing item routed to
`/ztn:role:edit`; you NEVER edit your own identity, and like a nudge it is grounded,
always the owner's call, and writes nothing. Use it rarely — an identity is not
retuned often.

---

## Identity honesty — unanchored items surface, they are never guessed

A new item that anchors onto a real Minder id carries that anchor. A new
item with no honest anchor carries `anchor: null`, and `roles_persist`
raises a **`role-new-key`** CLARIFICATION (conservative default: attach
to the nearest existing key in that part; in cold-start and early life the
strict setting holds it for the owner instead). Minting a stable key over
an unanchored item is an LLM judgment, not a deterministic fact, and the
engine treats it as one — it surfaces for the owner rather than claiming
certainty it does not have.

Note — anchor *existence* is honor-system in Stage 1: a well-formed anchor
(e.g. `project:<id>`) is trusted as written and not cross-checked against the
resolved corpus this tick, so the guarantee is «the anchor is well-formed and
honestly offered», not «it points at a row that exists». Corpus cross-check of
anchor existence is a hardening step that arrives with act / friend-deploy.

The body's part in this is simple: **do not force a guess.** When there
is no real id, emit `anchor: null` and let the HITL path place the item.
A fabricated anchor is worse than a null one, because it hides the
judgment the owner is meant to make.

---

## Cold-start — frozen staging, per part, the owner approves the first draft

The first tick over an empty part is different. The body synthesises the
initial draft as usual, but `roles_persist` mints that part's keys into
**staging** (not live), raises a **`role-cold-start`** CLARIFICATION, and
holds — per part. Until the owner approves, the same frozen draft
re-surfaces every run — it is never re-clustered and never re-drafted. A
staging-pending re-tick for that part is **re-surface-only**: it re-emits
the (deduped) clarification and writes nothing — no unvalidated addendum,
no watermark advance.

Records that arrive during the frozen window are NOT lost. On approval —
the go-live moment — that part's `seen_watermark` advances to cover the
adopted draft's provenance ONLY; records that arrived while the draft was
frozen are not marked seen. The first post-approval tick therefore reviews
the full remit corpus and proposes those records as normal grounded,
validated adds. The body must treat a re-surfaced cold-start as settled
prior work for that part, not as a blank part to re-synthesise.

---

## Part seam — the op vocabulary and the grounding rule belong to the plugin

Stages 1 and 3 are part-agnostic: reason against the given parts, ground
against each part's oracle, never write state, surface judgment instead of
guessing. What comes from each addressed part's plugin (loaded by
`roles_persist.py` from that `part.kind`) is:

- its **op vocabulary and payload shape** (`DELTAS`) — for a ledger part
  the `add` / `advance` / `supersede` / `merge` / `split` / `rename` set
  shown above; a narrative part revises a statement; another kind carries
  its own ops;
- its **grounding model** (`GROUNDING_MODEL`) — what a citation must
  resolve in. `records` grounds against the shared zone index (ledger,
  narrative, registry, metrics, assessment); a `stance` part is dual-grounded
  per instance (`schema.grounding`) — `records` by default, or `values`,
  where a position grounds against the owner's goals and constitution (via
  `/ztn:check-decision` in `dry_run` — the read-only verdict + principle
  titles, never the constitution-write side effect; a P1 role's values floor
  comes from its inherited persona, not a formal ruling). The frame delegates
  the grounding rule to the part rather than hard-coding "cite a fresh
  record", so a non-records part plugs in without the frame fighting it;
- its **key namespace** (`known_key_numbers`), so composite parts never
  collide;
- its **validator** and **renderer**.

The common layer never names a concrete part-kind. Every delta is routed
by its `part` to the right plugin, and each stage above holds unchanged
whatever mix of parts a role is composed of.
