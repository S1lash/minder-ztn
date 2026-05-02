# Agent Lenses Registry

**Last Updated:** 2026-05-02 (knowledge-emergence lens activated, weekly Saturday; energy-pattern + global-navigator cadence_anchor sun→mon for clean Mon-Sun calendar week; lint D.4 hub-stale-vs-material + A.6 INDEX heartbeat added)

Registry of agent-lens definitions. Each row points to a folder under
`_system/registries/lenses/{id}/` containing the lens prompt and any
companion files. To add a lens: create folder, add row, set status.
No skill-code changes required (same pattern as `SOURCES.md`).

## Concept

Agent lenses are **outside-view** observations the owner does not (yet)
make themselves. Each lens has a narrow intent (stalled threads,
stated-vs-lived gap, recurring reaction, etc.) and runs on its own
cadence under `/ztn:agent-lens`.

- Outputs land in `_system/agent-lens/{id}/{YYYY-MM-DD}.md` — one file
  per run, snapshot, never aggregated into a unified summary
- Each lens is independent — there is intentionally no cross-lens
  synthesis at the runner level. A meta-lens (`global-navigator`) reads
  other lenses' outputs but produces a digest of *pointers* (counts,
  ages, ids), not content
- All outputs are local to the owner

## Schema (lens frontmatter — required fields)

| Field | Values | Meaning |
|---|---|---|
| `id` | kebab-case slug | matches folder under `lenses/` and output dir |
| `name` | human title | shown in navigator |
| `type` | `mechanical` / `psyche` / `meta` | flavour — informs review cadence |
| `input_type` | `records` / `lens-outputs` | drives which frame variant wraps the prompt |
| `cadence` | `daily` / `weekly` / `biweekly` / `monthly` | scheduler runs it when due |
| `cadence_anchor` | `monday` / `sunday` / `1` (day-of-month) / `daily` | calendar anchor — see Cadence semantics below |
| `self_history` | `fresh-eyes` / `longitudinal` / `lens-decides` | NO default — must be explicit, lens fails registry validation otherwise |
| `status` | `draft` / `active` / `paused` | scheduler runs only `active` (unless `--include-draft`) |

Each lens folder MUST contain `prompt.md`. It MAY contain any number of
companion files (`what-counts.md`, `what-doesnt.md`, examples, anything).
The runner concatenates all `*.md` files in the folder, with `prompt.md`
first, the rest in alphabetical order. No fixed structure beyond
`prompt.md` being mandatory.

The lens prompt itself (in natural language) describes what to read,
what window to consider, and (if `self_history: lens-decides`) when to
look at past outputs. The runner does NOT constrain inputs — full read
access to the ZTN base is given.

## Cadence semantics

- `cadence: daily` → due every calendar day. `cadence_anchor` ignored
  (or set to `daily`).
- `cadence: weekly` → due on the day of week given by `cadence_anchor`
  (`monday`, `tuesday`, ...). If today matches anchor and last run was
  ≥6 days ago, run.
- `cadence: biweekly` → due every 14 calendar days, anchored to
  `cadence_anchor` day of week. First run defines the cycle.
- `cadence: monthly` → due on day-of-month given by `cadence_anchor`
  (`1`-`28`; values >28 clamp to 28).

**Catch-up policy:** if scheduler missed runs (laptop offline), the
runner does NOT replay missed days. It runs once for the current day
if due, and updates `last_run` to today. Missed days are gone — they
will be visible in `global-navigator` as gaps.

## Active Lenses

| ID | Name | Type | Input | Cadence | Self-history | Status |
|---|---|---|---|---|---|---|
| stalled-thread | Stalled Thread Detector | mechanical | records | weekly (mon) | fresh-eyes | active |
| stated-vs-lived | Stated vs Lived | psyche | records | biweekly (mon) | longitudinal | active |
| cross-domain-bridge | Cross-Domain Bridge | mechanical | records | weekly (thu) | longitudinal | active |
| decision-review | Decision Review | mechanical | records | monthly (1) | longitudinal | active |
| energy-pattern | Energy Pattern (records affect) | psyche | records | weekly (mon) | longitudinal | active |
| knowledge-emergence | Knowledge Emergence | mechanical | records | weekly (sat) | longitudinal | active |
| global-navigator | Global Navigator | meta | lens-outputs | weekly (mon) | longitudinal | active |

## Lens summaries

Each active lens MUST have a summary block here — purpose / value / output format in 2-3 sentences each. This is what owner sees when scanning the registry; the full prompt lives in `lenses/{id}/prompt.md`.

### stalled-thread

Runs weekly on Monday. Surfaces topics the owner keeps returning to in records without resolution — what is rotating in his head but hasn't closed and hasn't graduated to a task / thread / hub. Output: list of threads with one-phrase framing + cited records + brooding-shape evidence + what is visible in the system as a next move (fix in OPEN_THREADS / open task / let go) + alternative reading + confidence.

### stated-vs-lived

Runs every other Monday. Compares what the owner declares (constitution + SOUL — values, goals, focus) against where attention actually goes in records over a window matched to the declaration's timescale. Output: declaration quote + multiple lived-side signals (count + completion + emotional energy etc) + three parallel readings (action gap / priority shift / stale declaration) with markers + confidence — owner judges which reading holds.

### cross-domain-bridge

Runs weekly on Thursday. Searches for connections the owner thought about independently in different life domains without noticing the structural overlap — defends ZTN's flagship value (highest-value insights at domain boundaries) by surfacing what context-lock makes the owner himself miss. Output: one-sentence claim + two endpoint records (path + cited framing each) + which of 4 signals fired (relational match / matrix independence / cluster disjointness / nameable claim) + a falsifier («this would NOT be a bridge if…») + confidence.

### decision-review

Runs monthly on the 1st. Takes substantive decisions 90-180 days old, extracts the assumptions / alternatives / expected outcome (from explicit sections OR embedded prose / TENTATIVE flags / Открытые вопросы), and checks whether records after the decision date confirm or disconfirm each assumption. Output: decision (path + date + one-line subject) + per-assumption verdict (confirmed / disconfirmed / open with cited records) + net call (held / drifted / mixed) + alternative reading + confidence. Top-3 most material per run; assumption-level scoring only — owner judges decision-quality. Edge case `hits: 0` differentiated by reason: «base too young», «present but not extractable», «extractable but no records-evidence».

### energy-pattern

Runs weekly on Monday. Surfaces verbatim affect-markers from owner's voice-note records over a 14-day window and compares them against the SOUL Working Style baseline («Заряжает / Истощает / Выводит из себя») and the previous window — targeting **shifts** in distribution, not absolute mood. Records-only by design; physiological (Garmin) and behavioral (ActivityWatch) data stay scoped to future sibling lenses. Hit requires ≥3 markers distributed across ≥2 different records (no single-session venting bursts) OR a polarity crossing relative to baseline. Output: pattern + verbatim quotes (path + date) + shift framing (vs prev / vs SOUL) + three readings (action gap / baseline shift / episode) + confidence (high requires 2+ consecutive windows confirming). «No shift, baseline confirmed» is a valid output, not failure.

### knowledge-emergence

Runs weekly on Saturday — primary input is the **knowledge layer** (`1_projects/`, `2_areas/`, `3_resources/`), not records. Surfaces themes / framings recurring across ≥3 knowledge notes that have no hub yet (or have a mismatched hub — too general / too narrow / split candidate). Defends Layer 3 (hubs) growth against passive owner-noticing: promotion knowledge → hub becomes an active observation, not a quiet drift. Output: one-sentence promotion claim + 3+ cited knowledge note paths + relational structure name + signal tally (recurrent / hub-absence / cross-PARA / independent-derivation, ≥2-of-4) + hub verdict (new-hub / split-existing / extend-existing / unclear) + falsifier + confidence + recurrence classification (new / stable / fading) + counter-evidence. Never recommends action — owner decides whether to promote.

### global-navigator

Runs weekly on Monday — short status page for the **whole engine** over a trailing 7-day window ending the prior day (Mon-Sun calendar week): agent-lens layer (every active lens auto-discovered from this registry, including new ones), `/ztn:process` activity (batches + BATCH_LOG sums), `/ztn:lint` activity (F-codes + gaps), `/ztn:maintain` runs, candidate buffers (principle + people append counts by origin), CLARIFICATIONS state (new + open + by type), OPEN_THREADS delta. Output sections: stuck/failing → outstanding observations (by age) → lint → process → maintenance → candidates → clarifications → open-threads → productive lenses → silent lenses (only if non-empty) → aggregate counter; verbatim short titles, F-codes, batch-ids, type labels, counts only — no claims about the owner's life, no recommendations, no body-citation of any second-order content (observation bodies, candidate bodies, clarification quotes).

## Frameworks behind the calibration

Each lens prompt is calibrated against external frameworks (cited inline in the prompt body where applicable):

- **stalled-thread**: GTD open-loops + Nolen-Hoeksema brooding/pondering + Matuschak incubation
- **stated-vs-lived**: ACT VLQ + Higgins self-discrepancy + MI tone + Argyris-Schön espoused-vs-in-use
- **cross-domain-bridge**: Gentner structure-mapping + Koestler bisociation + Granovetter/Burt structural holes + Luhmann/Matuschak nameable-claim + apophenia falsifiability guard
- **decision-review**: Kahneman/Klein post-mortem discipline + Argyris double-loop learning + Tetlock superforecasting (assumption-level scoring, not overall decision-rightness)
- **energy-pattern**: ESM (Csikszentmihalyi) episode-level affect + Higgins ideal/ought self-discrepancy lexicon + ACT lived-vs-lived comparison
- **global-navigator**: SRE Four Golden Signals + USE method + Tufte data-ink + multi-doc summarisation hallucination research
- **knowledge-emergence**: Luhmann Folgezettel (thematic anchor on ≥3 sister-notes) + Matuschak evergreen promotion ladder + Weick retrospective sensemaking + apophenia falsifiability guard

## Operating principles

- Lenses are pure outside-view-of-life. System-health concerns (CLARIFICATIONS flow, lint context store, log audit) belong to `/ztn:lint` and `/ztn:maintain` and are deliberately not mixed in here.
- Numeric thresholds inside prompts are starting points, not hard limits. The thinker LLM has full base read access and license to widen windows when the pattern asks.
- Domain assumptions are owner-defined per `ENGINE_DOCTRINE.md` §1.5 — no hardcoded work/personal binary.
- The active lenses cover several observation flavours (within-records / records-vs-declarations / across-domains / decision-feedback-loop / affect-distribution / system-meta). They are not exhaustive; owners grow their own set via `/ztn:agent-lens-add`.
- Auto-pause safety net active: 3 consecutive validator rejections of any lens → runner flips status to `paused` (per `ztn-agent-lens/SKILL.md` §5.5).

## Draft Lenses

_(empty)_

## Output discipline

- One file per run, dated `{YYYY-MM-DD}.md` in `_system/agent-lens/{id}/`
- Empty result (`hits: 0`) → file IS written (with `## Reasons` section)
  to keep the run trail uniform; absence of file means the run never
  happened, not that it found nothing
- Every run (success / empty / rejected) appends one line to
  `_system/state/agent-lens-runs.jsonl`
- Rejected outputs are saved at
  `_system/state/agent-lens-rejected/{lens-id}/{run_at}.md` for owner
  inspection; not written to the canonical output dir
- Output schema is enforced by a **structurer pass** (separate cheap
  LLM call) and then validated structurally — see `lenses/_frame.md`.
  The thinker writes free-form

## `agent-lens-runs.jsonl` schema

One JSON object per line, append-only:

```json
{
  "lens_id": "stalled-thread",
  "run_at": "2026-04-30T06:00:00Z",
  "status": "ok | empty | rejected | error",
  "hits": 2,
  "output_path": "_system/agent-lens/stalled-thread/2026-04-30.md",
  "rejection_reason": null,
  "duration_seconds": 47.2
}
```

- `status: ok` → output written, `hits > 0`
- `status: empty` → output written, `hits == 0`
- `status: rejected` → validator rejected, output in `state/agent-lens-rejected/`
- `status: error` → runner couldn't even produce output (LLM error, file IO);
  `rejection_reason` carries cause

## Privacy

All lens outputs are owner-local. They live under `_system/agent-lens/`
and `_system/state/agent-lens-rejected/` and are committed to the same
private repo as the rest of the ZTN base.

**Privacy trio on lens-observation entities** (per
`/ztn:agent-lens` SKILL Step 5.9). Every observation file carries:

- `origin: personal` — lens runs internal to the owner; never `work`
  (would risk leaking to a future work-team sync) or `external`.
- `audience_tags: []` — owner-only by construction. Engine never
  widens automatically; owner curates if a specific lens result is
  worth sharing.
- `is_sensitive: false` by default; `true` if the lens prompt
  explicitly surfaces sensitive patterns (relationship/conflict
  observations) — set via lens registry `output_sensitivity` field
  when added; default `false` otherwise.

If a lens output references concepts by name, the names are
normalised through `_common.py::normalize_concept_name()` at write
time — same autonomous-resolution contract as `/ztn:process` Q15
(silent autofix or silent drop; never raises CLARIFICATION).

**Search isolation is deferred.** A future phase will set up a separate
QMD index for lens outputs so they remain accessible to the owner via
`/ztn-search` but do not contaminate other skill sessions (e.g.
`/ztn:process` reading hypothesis-grade observations as if they were
records). For now: no search-side exclusion. Other skills that perform
content search (`/ztn:lint` Scan F.x, `/ztn:bootstrap`) MUST exclude
`_system/agent-lens/` and `_system/state/agent-lens-rejected/` paths
explicitly. This requirement is documented here and enforced by each
skill's own scope rules.

## Lock matrix

Doctrine for cross-skill lock matrix: `_system/docs/ENGINE_DOCTRINE.md`
§3.4. Implementation (which locks to read, in what order, abort
messages): `integrations/claude-code/skills/ztn-agent-lens/SKILL.md`
Step 0.2.

Lock file: `_sources/.agent-lens.lock` (consistent with other ZTN
skill locks).

## Registry validation

Loaded by `/ztn:agent-lens` at the start of each tick. Each lens row
must satisfy:

- Folder `_system/registries/lenses/{id}/` exists and contains `prompt.md`
- Frontmatter parses; all required fields present
- `id` matches folder name
- `id` is unique across registry
- `cadence` ∈ allowed set; `cadence_anchor` matches `cadence` (e.g.
  `weekly` requires day-of-week, `monthly` requires day-of-month)
- `self_history` is one of three explicit values (no default)
- `input_type` is one of two values

Failures: registry-level (table malformed) → abort tick, write
CLARIFICATION. Lens-level (one lens malformed) → skip that lens with
log entry, continue with remaining lenses.

## Lens lifecycle

- **draft** — under development; runs only via `--include-draft` or
  `--lens <id>` for manual dry-run
- **active** — included in scheduled `--all-due` runs
- **paused** — manually paused by owner, OR auto-paused by runner after
  3 consecutive validator rejections; not run until owner flips to
  `active`

To activate a draft lens: dry-run via `/ztn:agent-lens --lens <id>
--dry-run` until output is satisfactory, then change status to `active`
in this file.

## Adding a new lens

**Recommended:** use `/ztn:agent-lens-add` — Socratic interview wizard that
generates a complete lens (prompt + registry row) with validation and
push-back on vague intent / missing anti-examples / duplicate of
existing. See `integrations/claude-code/skills/ztn-agent-lens-add/SKILL.md`.

**Manual (if you want to skip the wizard):**

1. Create folder `_system/registries/lenses/{new-id}/`
2. Add `prompt.md` with required frontmatter (see Schema above)
3. Add row to `Draft Lenses` table in this file
4. Dry-run via `/ztn:agent-lens --lens {new-id} --dry-run`
5. Iterate prompt until output is good
6. Move row to `Active Lenses`, change frontmatter `status: active`
7. Add a 2-3 sentence summary block under `## Lens summaries` (purpose / value / output format) — required for every active lens

No skill code changes required either way.

## Open items

- QMD search-isolation deferred to a follow-up phase (see Privacy
  section). For now: `_system/agent-lens/` and
  `_system/state/agent-lens-rejected/` MUST be excluded explicitly
  by any other skill that performs full-base content scans
- Lens content calibration (per-lens prompt fine-tuning) — owner-driven
  iteration based on first real scheduled outputs. Auto-pause after
  3 consecutive validator rejections per lens is the safety net
