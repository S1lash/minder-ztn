---
schema_version: 2.0
last_updated: 2026-05-02
---

# Concept Naming Specification

Canonical format for concept names: in `concepts:` frontmatter, in
manifest concept fields (`concept_hints[]`, `member_concepts[]`,
`concept_ids[]`, `applies_in_concepts[]`, `concepts.upserts[].name`),
and anywhere else a concept is referred to by name.

---

## What a concept is

A concept is **a thing-in-the-world the knowledge base tracks** —
a person, a project, a topic, a recurring theme, a tool, a decision
class. The name is the handle for that thing. Two notes mentioning
the same thing must reach the same handle, otherwise links break,
hubs fragment, and the graph silently splits one entity into many
ghosts.

The whole purpose of canonical naming is **deduplication of identity
across re-spelling**. "Team Restructuring", "team-restructuring", and
"the team restructuring effort" are not three concepts — they are
one concept written three ways. Normalisation collapses them to one
identifier (`team_restructuring`) so every mention lands on the same
node.

This file is about the **format** of that identifier. Whether a
particular thing in the world deserves to be a concept, and which
concept it is, is editorial judgment exercised in `/ztn:process`.
Format rules apply uniformly once that judgment is made.

### A concept is more than just a name

Each concept carries five attributes:

| Attribute | What it is | Where it lives |
|---|---|---|
| `name` | The canonical identifier — the handle this file specifies | `concepts:` frontmatter; `concepts.upserts[].name` in manifest |
| `type` | One of a fixed enum of categories (theme, person, project, tool, decision, idea, event, organization, skill, location, emotion, goal, value, preference, constraint, algorithm, fact, other) | `concepts.upserts[].type` in manifest only — never embedded in `name` (rule 5) |
| `subtype` | Optional finer category within a type (e.g. type `tool` + subtype `database`) | `concepts.upserts[].subtype` in manifest only — never embedded in `name` |
| `related_concepts` | Names of other concepts this one is meaningfully connected to (peer relation, not subordinate) | `concepts.upserts[].related_concepts[]` in manifest only |
| `previous_slugs` | Past names this concept has been known by — alias chain for renames (rule 9) | `concepts.upserts[].previous_slugs[]` in manifest only |

**The format rules in this file apply to `name`, `subtype`, every
entry in `related_concepts`, and every entry in `previous_slugs`** —
all four are concept-name identifiers and follow the same
snake_case-ASCII shape. `type` is a closed enum, not a free-form
identifier; it is not subject to this spec.

The `concepts:` frontmatter field is **just a list of names**. Type
and subtype are determined at extraction time and ride alongside in
the manifest, not in the note frontmatter. Two notes that mention the
same concept by name will resolve to the same identity regardless of
which one happened to capture the type field.

### Concept vs tag vs domain — three axes, do not conflate

| Axis | Field | Question it answers | Cardinality |
|---|---|---|---|
| Concept | `concepts:` | "What things does this note touch?" | Open-ended; new concepts emerge as the world expands |
| Tag | `tags:` | "Which categorical buckets does this belong to?" | Closed registry of `category/value` labels |
| Domain | `domains:` / `domain:` | "Which life area is this in?" | Closed registry — see `DOMAINS.md` for canonical thirteen + extensions. |

If you can ask "is this note ABOUT X?" — X is probably a concept.
If you'd ask "is this note OF KIND X?" — X is probably a tag.
If you'd ask "is this note IN AREA X?" — X is a domain.

A note can carry all three. They do not duplicate each other.

### Why English only

One consistent surface for identifiers eliminates the dedup problem
across languages. If "ежедневник" and "daily-planner" both became
concept names, the same thing would split into two graph nodes and
every cross-reference would have to know both forms. ZTN holds a
single language at the identifier layer; non-English content is
translated upstream in `/ztn:process` before a name reaches a
manifest. A non-English string in `concepts:` is therefore a format
error — translation didn't happen, fix the upstream extraction.

---

## Format rules

| # | Rule | ✓ | ✗ |
|---|---|---|---|
| 1 | ASCII `[a-z0-9_]` only | `team_restructuring` | `тема`, `naïve_bayes` |
| 2 | Lowercase | `oauth` | `OAuth` |
| 3 | Underscore separator (no hyphens, spaces, camelCase) | `delivery_lead_role` | `delivery-lead-role` |
| 4 | No leading, trailing, or consecutive `_` | `team_restructuring` | `_team_`, `team__x` |
| 5 | No type prefix — type lives in a separate field | `queue_prioritization` | `theme_queue_prioritization` |
| 6 | No role suffix on people — role lives in their profile | `anna_smith` | `anna_smith_cto` |
| 7 | Length 1–64 after normalisation | `api_v2` | empty, 70-char string |
| 8 | Concrete enough — broad categories belong in `domains:` | `team_restructuring` | `work`, `team`, `general` |
| 9 | Stable — renames cost; chain via `previous_slugs[]` when unavoidable | — | — |

---

## Normalisation algorithm

1. Lowercase the entire string.
2. Replace every separator with `_`. Separators: any whitespace; ASCII
   hyphen-minus and Unicode dashes U+2010…U+2015, U+2212; `/` `\` `.`
   `,` `;` `:` `!` `?`; round, square, and curly brackets; double and
   single quotes; and `~ % + @ # & * = < > ^ | ` `` ` ``.
3. Collapse runs of `_` into one.
4. Trim leading and trailing `_`.

Validate: `^[a-z0-9_]+$`, length in `[1, 64]`, does not start with a
forbidden type prefix.

Forbidden type prefixes (rule 5): `theme_`, `decision_`, `person_`,
`project_`, `tool_`, `idea_`, `event_`, `goal_`, `value_`, `fact_`,
`organization_`, `skill_`, `location_`, `emotion_`, `preference_`,
`constraint_`, `algorithm_`, `other_`.

---

## Why the rules exist — judgment behind the letter

Rules 1–4 and 7 are **mechanical** — they exist so the normalisation
algorithm produces one identifier for each thing-in-the-world, every
time, on any machine. Charset, case, separator, no double underscore,
length cap: all serve deterministic deduplication. There is no
judgment involved in applying them — run the algorithm.

Rules 5, 6, 8, 9 are **judgment-laden** — they protect specific
failure modes that aren't visible from the rule alone. Knowing the
failure mode is what lets you handle a case the table doesn't show.

### Rule 5 — no type prefix
The concept's type (theme, decision, project, person, …) is metadata
*about* the concept, not part of its identity. Reclassifying a
concept (e.g. a vague theme matures into a project) must not break
every reference to it. If the type is welded into the name
(`theme_queue_prioritization`), reclassifying means renaming, which
means cascading every link that ever pointed at the old name.
Identity stays in the name; type lives in a field that can change
freely.

### Rule 6 — no role suffix on people
Same principle, narrower case. Roles change (developer → lead → CTO);
identity does not. `anna_smith` is the same person across
twenty years of role changes, and every note that ever mentioned them
must continue to resolve.

### Rule 8 — concrete enough
A concept's value comes from selectivity. `work` matches half the
knowledge base; treating it as a concept means every "work" note
becomes "related" to every other "work" note, which is no
information at all. Broad classifiers belong in `domains:` (which is
designed to be set-membership, not connection). `team_restructuring`
is selective enough that a link between two notes carrying it
actually means something.

The inverse failure is also real: a concept so narrow it appears in
one note connects nothing. If you find yourself coining
`q3_2026_team_offsite_decision_meeting_notes`, you are making a
note title, not a concept.

### Rule 9 — stable identifiers
Every link, hub member, manifest reference, and historical mention is
a downstream debt against the name. Renaming pays that debt — sweep
the corpus, update wikilinks, chain `previous_slugs[]`, accept that
some references in archived material may go stale. So treat the
first naming with care, and only rename when the original name is
actually wrong (not merely suboptimal). "Could be cleaner" is not
grounds for a rename; "actively misleading" is.

---

## On violation — autonomous resolution (no CLARIFICATIONs)

The concept layer is fully autonomous — the engine resolves every
format issue with deterministic heuristics and never raises a
CLARIFICATION for owner action. The single source of truth is
`_system/scripts/_common.py::normalize_concept_name()`, which:

| Condition | Engine action |
|---|---|
| Raw value differs from its normalised form (case / hyphens / dashes / whitespace / punctuation / diacritics) | **Silent autofix** — rewrite to the canonical form. Fix-id `concept-format-autofix` logged in `log_lint.md`. |
| Starts with a forbidden type prefix (`theme_`, `decision_`, …) | **Silent autofix** — strip the prefix; if empty after strip, drop the entry. Fix-id `concept-format-autofix` or `concept-drop-autofix`. |
| Length > 64 after normalisation | **Silent autofix** — truncate at the last `_` boundary `≤ 64`; hard-cut otherwise. Fix-id `concept-format-autofix`. |
| Contains non-ASCII residue after diacritic-fold (e.g. Cyrillic) | **Silent drop** — entry not emitted. Fix-id `concept-drop-autofix` with reason `unnormalisable`. |
| Equals a bare type-enum word (`theme`, `decision`, …) — Rule 5 + 8 collapse | **Silent drop** (broad classifier belongs in `domains:`/tags). |
| Translation-impossible non-English term (Q15 fallback) | **Silent drop** at extraction time. Never transliterate. |

The normaliser is invoked at every emission point: capture-candidate
helper (write-time), `/ztn:process` Step 3.4 Q15 + Step 3.6
structural verification + Step 4.7 producer-side guard, `/ztn:lint`
Scan A.7 `lint_concept_audit.py` (post-write defence-in-depth),
`/ztn:lint` F.5 promotion (`applies_in_concepts[]` propagation).
Across all paths, format violations resolve mechanically; owner
sees no queue, takes no action.

**Why no CLARIFICATIONs here.** Concept-name normalisation is
deterministic mechanical work, not judgment. Surfacing per-decision
would drown the queue (every transcript can produce dozens of
concept names) without giving owner anything to actually decide —
the algorithm is fully specified. ENGINE_DOCTRINE §3.1 ("surface,
don't decide silently") applies to judgment-uncertain decisions;
mechanical normalisation is a layer-specific exception scoped to
the concept and audience surfaces.

A well-formed name that doesn't match any existing concept is **not**
a violation — vocabulary is open. New concepts emerge naturally; the
registry validates shape, not membership.

---

## Heuristics for novel cases

When a case isn't in the examples and the rules feel ambiguous, fall
back to these.

- **Is this a concept or a tag?** Could you imagine asking "show me
  every note ABOUT this"? → concept. Could you imagine filtering
  ("show me every note OF KIND this")? → tag.

- **Is this concrete enough (rule 8)?** Every concept starts at
  mention=1 — that's not a problem; vocabulary grows. The question is
  the **projected lifetime**: would this name plausibly recur across
  multiple future notes that the owner would want to link? If yes,
  proceed. If the name reads as a sentence-fragment that can only
  describe one specific moment (`q3_2026_team_offsite_notes`),
  it's a note title, not a concept — extract the load-bearing noun
  (`team_restructuring`) and use that. The opposite failure: a
  name that would match half the corpus (`work`, `general`,
  `meetings`) — that's a domain or a tag, not a concept.

- **Should I split a long compound?** If the parts mean meaningfully
  different things that you'd separately want to query, split. If the
  long form is just a context-sentence dressed as an identifier,
  pick the load-bearing noun and discard the framing.

- **Is this a rename or a new concept?** Ask: would someone who knew
  the old name and someone who knows the new name agree they are
  pointing at the same thing-in-the-world? Yes → rename (chain via
  `previous_slugs[]`). No → new concept; the old one stays where it
  was.

- **Person name with disambiguation?** If two people share a first
  name, the disambiguator goes inside the identifier
  (`anna_smith` vs `anna_petrova`), never as a role tag. If two
  people share both first and last name, use the next stable
  distinguisher available — middle initial (`anna_m_smith`),
  organisation (`anna_smith_acme`), or a numeric suffix as a last
  resort (`anna_smith_2`). Pick whatever the owner would naturally
  use to tell them apart in conversation. If the ambiguity emerges
  later (a second `anna_smith` joins), rename via rule 9 with the
  original `previous_slugs[]` chain.

- **Acronyms vs words?** Lowercase wins (rule 2). `oauth`, not
  `o_auth`. `p2p`, not `p_2_p`. Treat the acronym as a single
  segment.

- **Numbers and versions?** Allowed inside any segment (`api_v2`,
  `mastercard_2024`). Don't split them out into separate underscore
  segments unless that's how they read in prose.

- **Ambiguous because the source is non-English?** That's a signal
  the upstream extraction failed to translate. The engine silently
  drops the entry (graph identity stays clean); do not transliterate
  to "fix" it. No CLARIFICATION — autonomous drop is the contract.

- **Should this be a subtype or a separate concept?** Subtype lives
  inside one identity (`name=qdrant, type=tool, subtype=database`) —
  the parent concept *is* the subtype-bearer. If the would-be
  subtype could exist independently and be referenced on its own
  (`vector_database` as its own concept), make it a separate concept
  with a `related_concepts` link instead. Subtype is for "this
  particular tool happens to be a database", not for "databases in
  general".

---

## Examples

| Input | Normalised | Engine action |
|---|---|---|
| `team_restructuring` | `team_restructuring` | pass-through |
| `Team Restructuring` | `team_restructuring` | autofix (`concept-format-autofix`) |
| `team-restructuring` | `team_restructuring` | autofix |
| `Node.js (v18)` | `node_js_v18` | autofix |
| `team — restructuring` (em dash) | `team_restructuring` | autofix |
| `theme_queue_prioritization` | `queue_prioritization` | autofix — type prefix stripped |
| `тема` | — | drop (`concept-drop-autofix`, reason `unnormalisable`) |
| 70-char string | truncated at last `_` ≤ 64 | autofix |

---

Sibling axes: `tags:` → `TAGS.md`, `audience_tags:` → `AUDIENCES.md`.
