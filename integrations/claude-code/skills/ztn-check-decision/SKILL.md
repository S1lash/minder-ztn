---
name: ztn:check-decision
description: >
  Check a pending decision or observed behaviour against the active
  constitution tree at 0_constitution/. Returns a verdict — aligned,
  violated, tradeoff, or no-match — with citations to specific principles
  and prose rationale. Opus-backed reasoning. Auto-appends Evidence Trail
  citations on every cited principle and bumps their last_applied field
  (L1 autonomous write — the one thing this skill modifies under
  0_constitution/, never the principle body).
disable-model-invocation: false
model: opus
---

# /ztn:check-decision — Decision Verdict Against Constitution

Opus-backed reasoning tool that checks a proposed decision, a recent
record, or an observed pattern against the active constitution tree.
Produces a structured verdict and leaves a durable citation on the
principles it leaned on.

**Documentation convention:** при любых edits этого SKILL соблюдай
`_system/docs/CONVENTIONS.md` — файл описывает current behavior без
version/phase/rename-history narratives.

## When to invoke

- Before acting on a non-trivial decision that touches identity, ethics,
  work philosophy, tech judgment, or life-domain trade-offs.
- Inside `/ztn:process` Step 3.x — for every record with `types:
  [decision]` in the current batch.
- When the user asks "is this aligned with my principles?" or surfaces
  a dilemma that mentions explicit trade-offs.
- Retroactively via `/ztn:lint --rescan-drift --days N` on historical
  records after a principle was edited.

Do **not** invoke for:
- Pure refactoring / syntax questions with no values-content.
- Task routing or "what should I work on next" questions.
- Any situation already categorised as a `people-*` or `thread-*`
  concern in ZTN vocabulary.

## Inputs

| Input | Required | Shape |
|---|---|---|
| `situation` | yes | 1–3 sentences describing the pending decision or observed behaviour |
| `domains` | no | comma-separated subset of the enum (`ethics,identity,tech,…`); narrows the candidate pool |
| `dry_run` | no | boolean; if true, skill only returns verdict, no Evidence Trail update |
| `record_ref` | no | `[[YYYYMMDD-meeting-...]]` or `[[YYYYMMDD-observation-...]]` (any record-id) to cite as the decision source; defaults to the calling session |

## Execution plan

1. **Regenerate derived views.** Invoke `/ztn:regen-constitution` (or run
   `python3 _system/scripts/regen_all.py`) first. Single consistency
   rule: every pipeline regenerates before reading.

2. **Load the filtered visible tree.** Call the helper:

   ```bash
   ZTN_BASE="$ZTN_BASE" python3 "$ZTN_BASE/_system/scripts/query_constitution.py" \
       ${DOMAINS:+--domains "$DOMAINS"} \
       --compact
   ```

   JSON array of visible active principles with full body, statement,
   metadata. Fields: `id`, `title`, `type`, `domain`, `priority_tier`,
   `core`, `scope`, `applies_to`, `binding`, `framing`, `confidence`,
   `status`, `last_reviewed`, `last_applied`, `derived_from`,
   `contradicts`, `statement`, `body`, `path`.

3. **Reason.** For the given situation, work the candidate list in
   priority-tier order (1 → 2 → 3). For each candidate match, classify
   the relation:

   | Relation | Meaning |
   |---|---|
   | `aligned` | The situation follows the principle — chose the path the principle recommends. |
   | `violated` | The situation breaks the principle — would degrade or ignore it. |
   | `tradeoff` | The situation trades one principle for another — surface both sides. |

   Conflict resolution inside a tier:
   - Explicit `contradicts: [other-id]` in either frontmatter → higher
     `confidence` wins (`proven > working > experimental`).
   - Otherwise → verdict is `tradeoff`; surface both principles.

   Cross-tier: tier 1 beats tier 2 beats tier 3 (see
   `0_constitution/CONSTITUTION.md` §6).

4. **Emit JSON verdict** on stdout:

   ```json
   {
     "verdict": "aligned | violated | tradeoff | no-match",
     "citations": [
       { "id": "axiom-identity-001", "relation": "aligned" }
     ],
     "tradeoffs": [
       { "between": ["axiom-id-001", "axiom-id-002"], "chosen": "axiom-id-001", "reason": "..." }
     ],
     "rationale": "prose explanation — 2–4 sentences max",
     "record_ref": "[[_records/...]] or session id"
   }
   ```

   - `verdict` is the overall call; `citations` list every principle the
     verdict leans on.
   - `tradeoffs` is empty unless `verdict == "tradeoff"`.
   - `no-match` = no candidate applies; still emit with `citations: []`.

5. **Update Evidence Trail (L1 autonomous write).** For every principle
   in `citations`, use the `Edit` tool on its `.md` file to:

   a. Insert at the top of the `## Evidence Trail` section (newest-first,
      per `CONSTITUTION.md` §9) a line of the form:

      ```
      - **YYYY-MM-DD** | citation-{relation} | {record_ref or session id} — verdict: {verdict}; {short one-line reason}
      ```

      `{relation}` is one of `aligned`, `violated`, `tradeoff`.

   b. Bump the frontmatter `last_applied:` field to today's ISO date.
      Use a precise Edit: read the current value, then replace only that
      specific line. Patterns to handle:

      - `last_applied: null` → `last_applied: {today}`
      - `last_applied: {older-date}` → `last_applied: {today}`
      - `last_applied: {today}` → no-op (already today's date; skip the
        Edit to avoid spurious diffs and to keep the step idempotent)

      Never use a non-unique match like `last_applied:` alone — the word
      appears in other places. Always include the current value in the
      `old_string` so the match is unambiguous, and if multiple citations
      on the same principle fire in the same run, the second one is the
      no-op case above.

   **Skip step 5 entirely when `dry_run == true`.**

   **Never edit the body** of the principle outside `## Evidence Trail`
   and outside the `last_applied:` frontmatter field. This is the L1
   limit defined in `0_constitution/CONSTITUTION.md` §8.

## Invariants (do not break)

- Never create a new principle — that is `/ztn:capture-candidate`'s job.
- Never change any frontmatter field except `last_applied:`.
- Never write outside `0_constitution/` and the console.
- Fail loudly (non-zero-style error, explicit to the user) if
  `query_constitution.py` returns empty while the situation clearly
  needs a verdict — tell the user "no active principles available; the
  tree is empty, populate Stage 2 first". Do not fabricate principles.
- Only reason about principles actually present in the query output.
  Never cite a principle you did not load.

## Output contract — exact shape

The skill must produce exactly this JSON (pretty-printed for the user
is OK so long as the structure is unambiguous). Extra fields should not
appear. Missing fields should not appear — use empty arrays / `null`.

## Evidence Trail entry — canonical format

```
- **2026-04-20** | citation-aligned | [[20260420-meeting-deploy-check]] — verdict: aligned; chose to extend CI wait instead of force-merge
```

- Date: ISO-8601 YYYY-MM-DD.
- Event type: `citation-aligned`, `citation-violated`, or
  `citation-tradeoff` — matches the per-citation `relation` field.
- Reference: wiki-link to the record if available, otherwise the
  session identifier (`session-YYYY-MM-DD-NN`).
- Separator: ` — ` (em-dash with spaces).
- Tail: short one-line reason, ≤ 100 chars.

## Failure modes

| Condition | Skill behaviour |
|---|---|
| `regen_all.py` step fails | Return non-zero, surface the underlying stderr |
| `query_constitution.py` returns empty, situation cannot be classified | Emit `verdict: "no-match"` with explicit rationale |
| Two tier-1 principles conflict with equal `confidence` | Emit `verdict: "tradeoff"` with both in `between` |
| `Edit` cannot find `## Evidence Trail` in a cited principle | Skill errors out; the principle file is malformed per `CONSTITUTION.md` §4 — fix it, then re-run |
| User passes an empty `situation` | Skill asks the user to supply one sentence, then stops |

## Multi-environment notes

- `ZTN_BASE` env var must resolve to the zettelkasten root.
- Single-context model: no `CLAUDE_CONTEXT` filter applied. All scopes
  visible locally; consumer filter (`applies_to` includes `claude-code`)
  is the active narrowing.
- Works from any repo as long as `ZTN_BASE` is set. Scheduler tasks
  invoke the same way.
- Opus model selection is declared in the frontmatter (`model: opus`).
  Do not downgrade — the reasoning requires it.

## Examples (illustrative)

**A. Aligned.**
Situation: *"I'm about to extend the migration window from 2h to 6h so
we can run it during a low-traffic period instead of forcing it through
now."*

Expected verdict: `aligned` against `axiom-identity-001` (if it can be
better, should be better) — the extension chooses the higher-quality
path over speed.

**B. Violated.**
Situation: *"The commit message is embarrassing, I'll force-push to main
to overwrite it."*

Expected verdict: `violated` by `rule-tech-001` (never force-push to
main). No trade-off — rules are binary.

**C. No-match.**
Situation: *"Should I name this service billing-api or payments-api?"*

Expected verdict: `no-match`. Naming is not covered by any constitution
principle in the current tree; belongs to team conventions, not
identity-layer.
