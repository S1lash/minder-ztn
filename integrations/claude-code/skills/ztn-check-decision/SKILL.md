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

### Core (baseline contract — unchanged for any caller)

| Input | Required | Shape |
|---|---|---|
| `situation` | yes | 1–3 sentences describing the pending decision or observed behaviour |
| `domains` | no | comma-separated subset of the enum (`ethics,identity,tech,…`); narrows the candidate pool |
| `dry_run` | no | boolean; if true, skill only returns verdict, no Evidence Trail update |
| `record_ref` | no | `[[YYYYMMDD-meeting-...]]` or `[[YYYYMMDD-observation-...]]` (any record-id) to cite as the decision source; defaults to the calling session |
| `is_sensitive` | no | boolean; if true, telemetry emission omits situation text + rationale, keeps hash + verdict + citations only |

### Optional self-report (telemetry — best-effort, never blocks verdict)

These are **opportunistic**. A capable caller (Opus-class agent) can supply them
to enrich the audit substrate; a cheap caller (Haiku-class, weak local model)
should ignore them. **Skill never fails for missing self-report fields.**

| Input | Shape | Purpose |
|---|---|---|
| `intent` | 1-2 sentences | why the caller invoked the skill (counterfactual seed for autonomy analysis) |
| `pre_confidence` | `low \| medium \| high` | caller's certainty about the right action **before** the verdict |
| `expected_verdict` | `aligned \| violated \| tradeoff \| no-match \| unknown` | what the caller expected the skill to return |

### Pipeline integration flag

| Input | Shape | Purpose |
|---|---|---|
| `--from-pipeline <name>` | one of `/ztn:process`, `/ztn:lint`, `/ztn:maintain`, `/ztn:agent-lens`, `/ztn:bootstrap` | marks the call as `caller_class: mechanical` — pipelines pass it from their step that invokes check-decision; absence = `caller_class: judgmental` (ad-hoc agent in any repo). Mechanical calls skip the auto-commit step (parent pipeline owns batch-commit). |

### Followup mode (separate invocation, optional)

After acting on a verdict, the caller MAY invoke the skill in followup mode
to record post-action signal. Missing followups are themselves data — the
lens treats absence as observable, not as a contract violation.

| Flag | Shape | Purpose |
|---|---|---|
| `--record-followup <run_id>` | run_id from a prior verdict's stdout | activates followup mode; no constitution reasoning happens |
| `--post-confidence` | `low \| medium \| high` | caller's certainty after acting |
| `--decision-taken` | 1-2 sentences | what caller actually did with the verdict |
| `--human-needed-after` | boolean | did caller escalate to a human after the verdict? |
| `--verdict-resolved` | boolean | did the verdict actually answer the question? |

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
     "record_ref": "[[_records/...]] or session id",
     "run_id": "2026-05-03T15:22:11Z-7c4a9f02",
     "followup_hint": "optional — after acting on this verdict, you MAY call /ztn:check-decision --record-followup 2026-05-03T15:22:11Z-7c4a9f02 with --post-confidence / --decision-taken / --human-needed-after / --verdict-resolved to enrich audit substrate. Skipping is fine."
   }
   ```

   - `verdict` is the overall call; `citations` list every principle the
     verdict leans on.
   - `tradeoffs` is empty unless `verdict == "tradeoff"`.
   - `no-match` = no candidate applies; still emit with `citations: []`.
   - `run_id` is the substrate join-key; deterministic for the
     invocation, present even on failed-status runs.
   - `followup_hint` is informational, not a contract — the caller
     decides whether to follow up.

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

6. **Emit telemetry (always — regardless of `dry_run` or `status`).**
   Append one JSON line to `_system/state/check-decision-runs.jsonl`
   via the helper:

   ```bash
   python3 "$ZTN_BASE/_system/scripts/emit_telemetry.py" \
       --kind run \
       --run-id "$RUN_ID" \
       --status "$STATUS" \
       --caller-class "$CALLER_CLASS" \
       --working-dir "$PWD" \
       --situation "$SITUATION" \
       --tree-size "$TREE_SIZE" \
       ${IS_SENSITIVE:+--is-sensitive} \
       ${DRY_RUN:+--dry-run-flag} \
       ${DOMAINS:+--domains "$DOMAINS"} \
       ${RECORD_REF:+--record-ref "$RECORD_REF"} \
       ${VERDICT:+--verdict "$VERDICT"} \
       ${CITATIONS_JSON:+--citations "$CITATIONS_JSON"} \
       ${TRADEOFFS_JSON:+--tradeoffs "$TRADEOFFS_JSON"} \
       ${RATIONALE:+--rationale "$RATIONALE"} \
       ${INTENT:+--intent "$INTENT"} \
       ${PRE_CONFIDENCE:+--pre-confidence "$PRE_CONFIDENCE"} \
       ${EXPECTED_VERDICT:+--expected-verdict "$EXPECTED_VERDICT"} \
       ${PIPELINE:+--from-pipeline "$PIPELINE"}
   ```

   `RUN_ID` format: `<run_at_ISO>-<uuid4[:8]>` — generated by skill at
   step 1 (before any reasoning), so failed-run telemetry shares the
   same shape as successful runs.

   The helper handles atomic append under `flock`, sensitive-redaction
   (omits `situation_text` + `rationale` when `--is-sensitive` is passed,
   keeps `situation_hash` + verdict labels), and per-class auto-commit
   (judgmental only). Failures of the commit step degrade gracefully —
   helper writes the JSONL line, prints a warning, exits 0.

   Telemetry is opportunistic substrate: the lens consumes whatever
   fields are present, treats missing optional fields as no-signal
   rather than as errors. Schema is append-only; never mutate prior
   lines, never aggregate or compact JSONL prematurely.

## Followup mode

When invoked with `--record-followup <run_id>`, the skill skips all
constitution reasoning and instead:

1. Validates that `<run_id>` matches the documented format
   (ISO-timestamp + 8-char uuid suffix). Reject loud on malformed input.
2. Scans `_system/state/check-decision-runs.jsonl` for a `kind: "run"`
   line with the matching `run_id`. If not found → fail loud (orphan
   followups must not pollute substrate).
3. Appends a `kind: "followup"` line to the same JSONL via the helper:

   ```bash
   python3 "$ZTN_BASE/_system/scripts/emit_telemetry.py" \
       --kind followup \
       --run-id "$RUN_ID" \
       --post-confidence "$POST_CONFIDENCE" \
       --decision-taken "$DECISION_TAKEN" \
       --human-needed-after "$HUMAN_NEEDED_AFTER" \
       --verdict-resolved "$VERDICT_RESOLVED"
   ```

4. Acquires the same `flock` and applies the same per-class auto-commit
   policy as the run-line emission. The `caller_class` for the followup
   inherits from the original run (helper looks it up).

Followups on `dry_run: true` runs are allowed (the helper marks the
followup line for the lens to filter); followups twice on the same
run are allowed (lens uses the latest).

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
| `regen_all.py` step fails | Telemetry line written with `status: "failed_regen"`, then return non-zero with stderr |
| `query_constitution.py` returns empty, situation cannot be classified | Emit `verdict: "no-match"` with explicit rationale; telemetry `status: "ok"`, `tree_size: 0` (signal: no principles available — the no-match is structural, not absent-coverage) |
| Two tier-1 principles conflict with equal `confidence` | Emit `verdict: "tradeoff"` with both in `between` |
| `Edit` cannot find `## Evidence Trail` in a cited principle | Telemetry line written with `status: "failed_edit"`, then skill errors out; the principle file is malformed per `CONSTITUTION.md` §4 — fix it, then re-run |
| User passes an empty `situation` | Skill asks the user to supply one sentence, then stops; no telemetry line written (no run actually started) |
| Auto-commit step fails (parallel session holds git lock, repo mid-rebase) | Helper writes the JSONL line, prints warning to stderr, returns 0 — JSONL is source of truth; commit picked up later by `/ztn:save` |
| `--record-followup` references unknown run_id | Reject loud; do not append orphan followup line |
| Concurrent invocation in another session | `flock` on `_system/state/.check-decision-telemetry.lock` serialises emission; advisory only — no deadlock |

## Telemetry substrate — append-only contract

The JSONL at `_system/state/check-decision-runs.jsonl` is **append-only
substrate** for both current consumers (decision-review lens — Layer A
joint enrichment + Layer B aggregate engine signals) and future
consumers (e.g. cross-source autonomy analysis joining JSONL with
processed records). Therefore:

- Never mutate existing lines (followups are SEPARATE lines with
  matching `run_id`, distinguished by `kind: "followup"`).
- Never aggregate / compact / summarise the file. Substrate value
  comes from preserved per-run granularity. Rotation by year is
  acceptable when file size warrants (`check-decision-runs.YYYY.jsonl`)
  — implement only when justified by volume.
- Schema is forward-additive: new optional fields may appear; lens
  consumers MUST treat unknown fields as no-signal rather than fail.
- Sensitive runs (`is_sensitive: true`) omit `situation_text` and
  `rationale`; `situation_hash` remains for join purposes. The hash
  alone is not sensitive (one-way) and preserves dedup capability.
- Pipeline-mode (mechanical) calls emit JSONL lines without
  auto-commit; the parent pipeline's batch commit picks them up.
  Judgmental calls auto-commit per-invocation (path-specific `git
  add`, no push). Both modes use the same `flock` for atomic emission.

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
