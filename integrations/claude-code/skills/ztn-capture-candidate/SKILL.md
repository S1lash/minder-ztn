---
name: ztn:capture-candidate
description: >
  Append a principle candidate to _system/state/principle-candidates.jsonl —
  single, narrow, append-only capture for observations that look like a
  behavioural principle, a conscious trade-off, a non-obvious judgment,
  or an implicit pattern. Tags the entry with session origin (personal /
  work / external) based on CLAUDE_CONTEXT. No reasoning, no decisions —
  the buffer feeds /ztn:lint Scan F.3 weekly aggregation for the owner's
  batch review.
disable-model-invocation: false
---

# /ztn:capture-candidate — Append Principle Candidate to Buffer

Append-only write to the principle-candidates buffer. **No reasoning,
no review, no decisions** — that is `/ztn:lint` Scan F.3 and the owner's job.
The skill exists so that observations do not get lost between sessions.

**Documentation convention:** при любых edits этого SKILL соблюдай
`_system/docs/CONVENTIONS.md` — файл описывает current behavior без
version/phase/rename-history narratives.

## When to invoke (narrow triggers)

Capture when you observe one of these, and **only** these:

**(a) Explicit behavioural principle** — The owner says "I always ...", "my rule
is ...", "I never ..." with a reason (not just a factual statement, but
a principle).

**(b) Conscious trade-off** — explicit choice of X over Y with reasoning
why one priority outranks another in the specific situation. Example:
"here speed matters more than quality because rollback is cheap".

**(c) Non-obvious ethical / emotional / interpersonal judgment** — a
decision most people would make differently, with explanation why the owner
does not. Includes "по понятиям" moments.

**(d) Implicit pattern** — The owner does NOT name the principle, but makes
a choice that clearly follows from an internal logic. Capture the
**observation** (what you watched) plus your **hypothesis** about the
principle behind it. The owner decides on review whether it is real or noise.

## Do NOT capture

- Technical preferences (prefer postgres, use records not classes) —
  those are conventions, not principles.
- Stylistic preferences (commit-message phrasing, naming).
- Task-execution decisions without philosophical content.
- Facts about people — those go through `/ztn:process` → PEOPLE.md.
- The entire session content — that is `/ztn-recap`.

**Better to miss 30% of real candidates than ingest 300% noise** — the
buffer should stay signal-heavy (`2_areas/...` CONSTITUTION.md §13
invariant #15 + rationale in the research note §5.5).

## Well-formed candidate — structural rules

These are **rules about form, not templates to mimic**. Do not echo their
phrasing, themes, or language style; the owner's principles must derive
from the owner's own corpus, not from this skill's prompt.

- `situation` — 1-2 sentences, concrete (one event, one decision), not
  a session summary.
- `observation` — verbatim if the owner spoke; otherwise empty string.
  Never paraphrase into the observation field; paraphrase belongs in
  `hypothesis`.
- `hypothesis` — at most one short sentence naming the rule the owner
  appears to be following. **Required to contain a reason or trade-off**,
  not just a preference. Empty/null only when (a) trigger fired and the
  owner stated the rule explicitly.
- `suggested_type` and `suggested_domain` — pick `unknown` over a forced
  guess. The owner re-classifies on review.
- No proper nouns of real people in any field except `record_ref`.
  Names belong to `/ztn:process` → PEOPLE.md.

## Boundary cases — what to reject

| Looks like | Why it's NOT a candidate |
|---|---|
| "The owner prefers tabs over spaces." | Stylistic preference. No reasoning, no trade-off. → ignore |
| "The owner picked option B because the meeting was running long." | Task-execution decision driven by external pressure, not internal logic. → ignore |
| "The owner said they like clean code." | Sentiment without specificity. No rule, no boundary. → ignore |
| "The owner used `RIGHT JOIN` instead of `LEFT JOIN`." | Technical convention. → ignore |
| "The owner declined a profitable deal because the counterparty had lied earlier, and explained why trust outranks revenue here." | Trade-off + reasoning + non-obvious judgment. → capture (type: principle, domain: ethics or work) |

## Execution plan

1. **No regeneration needed.** This skill does not read the constitution
   — it only writes to the buffer.

2. **Build the arguments** from the observation:
   - `situation` — 1-2 sentences of what was happening (required).
   - `observation` — verbatim quote if the owner said something; empty
     string otherwise.
   - `hypothesis` — one-line hypothesis of the principle; `null` if
     the owner stated it explicitly.
   - `suggested_type` — one of `axiom`, `principle`, `rule`, `unknown`.
     Prefer `unknown` over guessing wrong.
   - `suggested_domain` — one of the enum domains or `unknown`. Same
     principle: `unknown` beats a forced guess.
   - `record_ref` — link to a record or session if one exists.

3. **Invoke the helper:**

   ```bash
   ZTN_BASE="$ZTN_BASE" python3 "$ZTN_BASE/_system/scripts/append_candidate.py" \
       --situation "$SITUATION" \
       --observation "$OBSERVATION" \
       ${HYPOTHESIS:+--hypothesis "$HYPOTHESIS"} \
       --suggested-type "$SUGGESTED_TYPE" \
       --suggested-domain "$SUGGESTED_DOMAIN" \
       ${RECORD_REF:+--record-ref "$RECORD_REF"}
   ```

   `origin` is resolved automatically from `CLAUDE_CONTEXT`:
   - `personal` (or unset) → `personal`
   - `work` → `work`
   - `chatgpt` / `bootstrap` → `external`

   `session_id` is generated automatically from UTC timestamp if not
   provided.

4. **Do not ask permission.** The buffer is append-only and cheap to
   review. Silently appending is the correct behaviour.

5. **Do not attempt dedup.** That is Scan F.5's job (LLM-judge merge
   with the active tree). Your role is to ensure the observation is
   captured.

## Buffer entry schema (what lands in `_system/state/principle-candidates.jsonl`)

Each line is one JSON object:

```json
{
  "date": "2026-04-20",
  "situation": "The owner extended the migration window from 2h to 6h...",
  "observation": "«лучше 6 часов ночью чем 2 часа в прайм-тайм»",
  "hypothesis": "prefer-higher-quality-path",
  "suggested_type": "principle",
  "suggested_domain": "work",
  "origin": "personal",
  "session_id": "session-2026-04-20-154233-UTC",
  "record_ref": null,
  "captured_by": "ztn:capture-candidate"
}
```

## Invariants

- Single-line JSONL writes only. The file is append-only; never rewrite.
- Unicode preserved (Russian quotes round-trip cleanly).
- Work-origin candidates carry `"origin": "work"` and never qualify for
  L2 auto-merge in lint F.5 — they always require manual review.
- No dependency on the constitution tree state (empty tree is fine).

## Failure modes

| Condition | Skill behaviour |
|---|---|
| Empty `situation` | Helper fails, skill reports to user "capture needs a 1-2-sentence situation" |
| Bogus `suggested_type` or `suggested_domain` | Helper fails with a listing of allowed values; skill fixes and retries, or falls back to `unknown` |
| Buffer file write fails (permissions, disk full) | Helper errors; skill surfaces stderr — do not silently drop the observation |

## Multi-environment notes

- `ZTN_BASE` env var resolves the zettelkasten root.
- `CLAUDE_CONTEXT` drives origin tagging; unset → `personal`.
- The buffer lives inside the repo (`_system/state/principle-candidates.jsonl`)
  so scheduler tasks accumulate directly into the shared file.

## Relationship to `/ztn-recap`

Different concerns, no overlap:

| Skill | Target | When |
|---|---|---|
| `/ztn-recap` | `_sources/inbox/claude-sessions/...` — session-as-knowledge | End of a significant session |
| `/ztn:capture-candidate` | `_system/state/principle-candidates.jsonl` — one observation as candidate | At the moment of observation, by narrow trigger |

Both can fire independently in the same session. A recap summarises the
session for later processing into knowledge notes. A capture stores
one atomic observation that looks like a principle for lint F.3 review.
