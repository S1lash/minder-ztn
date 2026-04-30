---
id: cross-domain-bridge
name: Cross-Domain Bridge
type: mechanical
input_type: records
cadence: weekly
cadence_anchor: thursday
self_history: longitudinal
status: active
---

# Cross-Domain Bridge

## Intent

Find concepts, entities, framings, or relational patterns that appear in records of two or more **distinct domains** but are NOT yet linked in the knowledge layer (`1_projects/`, `2_areas/`, `3_resources/`) or as bridges in `5_meta/mocs/`. The goal is NOT to claim "this is the insight." The goal is to **make the candidate visible** so the owner can decide if a real bridge exists, mark it as a watch-item, or dismiss it as ambient overlap.

Cross-domain insight is the engine doctrine's flagship value class (`ENGINE_DOCTRINE.md` §1.4 — "the highest-value insights live at domain boundaries"). This lens defends that property: humans are context-locked into one domain at a time and chronically miss connections their own records contain.

## What counts as a "bridge candidate" — the most important section

Not every shared word across two records is a bridge. Most aren't. A bridge candidate is a **structural connection** between distinct rule-systems, not a surface match. Use Gentner's structure-mapping discipline: shared **relational structure**, not shared attributes.

Four signals. A real bridge candidate carries **at least 2 of 4**:

1. **Relational-structure match (Gentner)** — both records express the same `subject–relation–object` schema or higher-order pattern, even if vocabulary differs. Example: a work-record framing "delegation as a control problem" + a therapy-record framing "trust as a release-of-control problem" share `agent–releases-control-of→object` schema. NOT just shared noun "delegation".

2. **Matrix independence (Koestler — bisociation)** — the two records sit inside vocabularies/frames the owner himself would consider distinct (work / personal / health / identity / relationships / learning). Higher independence → higher bridge value. Records both inside the same domain don't qualify; records crossing two work-areas may qualify if the areas use clearly different frames.

3. **Cluster disjointness (Granovetter / Burt — structural holes)** — the *other* concepts, people, and entities co-occurring in the two records barely overlap. The candidate concept is functioning as a path between two otherwise disconnected clusters. If the two records share many entities, the candidate is ambient context, not a bridge.

4. **Nameable claim (Luhmann / Matuschak)** — the connection can be stated in one sentence as a non-trivial proposition. "X and Y both treat Z as a constraint, not a goal." "P recurs as a control mechanism in domain A and as a coping mechanism in domain B." If you cannot name the claim in one sentence, it is not yet a bridge — it is a vague resonance.

## What to read

Decide for yourself. The frame's contract gives full base read access — use it. Useful starting points:

- `_records/observations/` and `_records/meetings/` over the recent few weeks. Bridges are statistically rare (Granovetter); you need volume across multiple domains to detect them above co-occurrence noise. Widen freely if a candidate's earliest mention seems older — there is no fixed limit.
- Frontmatter `domains: [...]` — the primary signal of which records sit in which frame.
- Existing wikilinks in record bodies (especially «Связи» / «See also» sections) — if owner already linked the two endpoints, the connection is already in the owner's awareness; skip.
- `1_projects/`, `2_areas/`, `3_resources/` — knowledge notes. For each candidate, check whether the connection is already named in either endpoint or in a third bridge-note.
- `5_meta/mocs/` and `_system/views/HUB_INDEX.md` — bridges that already exist as hubs. Don't duplicate.
- `3_resources/people/` (`PEOPLE.md`) — for person-mediated candidates, check whether the same person genuinely bridges two domains, or whether two different people share a name.

## What counts as a hit

A candidate where:

1. **Multiple records** appear on at least one side (a single-record-on-each-side with one shared word is too thin to support a structural claim).
2. **Domains are distinct** in the owner's vocabulary (per record frontmatter).
3. **At least 2 of the 4 signals** above hold (relational match, matrix independence, cluster disjointness, nameable claim).
4. **Not already linked** — neither knowledge-layer note states the connection, no bridge-hub names it, no wikilink connects them.

## Confidence calibration

State your confidence honestly:

- **high** = relational-structure match (Gentner) AND matrix independence (Koestler) AND nameable claim. Multiple records on both sides. Both endpoints already exist in the knowledge layer (the connection earns its place by linking mature material, not just raw records).
- **medium** = relational match OR strong matrix independence, with a tentative nameable claim. Endpoints may still be record-only.
- **low** = co-occurrence + a plausible-sounding claim, but the relational schema is weak or only one side has multiple records. Surface explicitly as "watching, not yet a bridge".

Low confidence is a normal output. Better to surface "watching" than to manufacture a connection from noise.

## Falsifiability test (apophenia guard)

Before surfacing each candidate, ask: **what would falsify this connection?** What concrete observation would rule it out as coincidence? If you cannot articulate one, the candidate is probably apophenic — pattern-finders manufacture connections from noise, and falsifiability is the discipline that prevents this.

For each surfaced hit, include the falsifier in the output: *"this would NOT be a bridge if …"*.

## What does NOT count as a hit (anti-patterns)

1. **Lexical co-occurrence** — same word, different meanings ("model" the artefact vs "model" the role-model person; "scale" the metric vs "scale" the verb).
2. **Person-name overlap** — the same person mentioned in two records is one person, not a bridge — unless the *role they play* differs in a relational-structure-mapped way. Two different people sharing a first name is pure noise.
3. **Modifier-word bridges** — high-frequency abstract nouns ("balance", "context", "approach", "system", "energy", "growth", "strategy", "people"). Documented LLM false-positive class (~13% of false links in KG link-prediction studies). These connect everything to everything; reject unless paired with a strong relational-structure match.
4. **Ambient context overlap** — both records mention "the team", "the city", "this week" because that is the owner's environment. Environmental constants, not bridges.
5. **Temporal coincidence** — both records written the same day or week. Recency artefact, not structural pattern.
6. **Mood / state carryover** — "tired", "frustrated", "energised" appearing across domains is one emotional state spilling over, not a cross-domain pattern.
7. **Owner-tag transfer** — both records carry the same `domains: [...]` tag because the owner tags broadly. Tagging behaviour, not connection.
8. **Sloppy synthesis ("everything connects")** — three or more candidates per run, each opening with "interestingly, both…" — almost always confabulation. If you find 3+ candidates in one window, treat that itself as a noise signal and tighten your criteria before surfacing.
9. **Surface analogy without systematicity** — "both involve a decision", "both involve people". These satisfy no Gentner-style relational test. Reject.
10. **Bridge already named** — the connection is already in `5_meta/mocs/`, in a knowledge note's body, or as a wikilink. Verify before surfacing.

## Self-history

`longitudinal` — past outputs at `_system/agent-lens/cross-domain-bridge/{date}.md` are read for ONE purpose: **detect echo**. If a candidate appears identical to a past run with no new structural evidence, it is fading, not strengthening — surface as such, or drop.

Hard rule: **do not use past observations as evidence** for new ones. Past candidates are an age-trail, not a confirmation source. Each new observation rests on its own current structural evidence.

If you notice you are repeating a past candidate without new structural support, say so honestly: "this recurs in my outputs but no new structural evidence has emerged — may be my echo, not a real bridge."

## Tone

Descriptive, never prescriptive. The owner evaluates connection-quality; the lens does not.

- ❌ "Your work-delegation problem is really an attachment issue from therapy."
  ✅ "The word 'delegation' appears in `_records/meetings/2026-03-12.md` framed as a control problem and in `_records/observations/2026-04-02.md` framed as a trust problem — same operation, different rule-systems. Worth a look; could also be coincidence."

- ❌ "You keep avoiding the same theme across domains."
  ✅ "Concept X surfaced in two records four weeks apart, in domains that otherwise share little. Not currently linked in the knowledge layer."

- ❌ "This is clearly a bridge between work and identity."
  ✅ "If this is a bridge, the claim would be: '…'. If it isn't, the simplest alternative reading is: ambient overlap — both records were written in the same week and share a generic frame word."

- ❌ "Notice the parallel?" (rhetorical, leading)
  ✅ "Two records, same relational shape (`X constrains Y`), different domains. Does the shape feel real to you, or projected?"

- ❌ "You should make this a hub."
  ✅ "No hub currently holds this pair. Could become one, could stay as a watch-item, could be dismissed."

Pattern rules: cite path + date for both endpoints; name the candidate claim verbatim; include the falsifier; end with the owner-decides handoff.

## What to give back

For each hit, in free form:

- **Candidate concept / pattern** — name the bridge in one phrase.
- **The claim** — one sentence stating the non-trivial proposition the bridge makes.
- **Endpoint A** — record path, date, domain, short quote showing the framing.
- **Endpoint B** — same.
- **Which signals fire** — name the 2+ of {relational match, matrix independence, cluster disjointness, nameable claim} present, with concrete evidence for each.
- **Linkage status** — what already exists in the knowledge layer about either endpoint, and what is missing.
- **Falsifier** — what would rule this out as coincidence.
- **Confidence** — high / medium / low.
- **If recurring** — note recurrence with prior-output date (per Self-history echo guard).

If 0 hits — say so plainly: "Over the window I examined, no candidates met multi-signal criteria. Concepts I considered and rejected as ambient / surface / modifier-word: …" That is a healthy output, not a failure.
