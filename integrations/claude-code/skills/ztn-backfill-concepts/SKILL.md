---
name: ztn-backfill-concepts
description: One-time-per-corpus historical backfill of `concepts:` frontmatter for notes processed before /ztn:process Step 3.4.5 existed. Idempotent — skips notes already populated. Writes to a feature branch, opens a PR for owner review, never auto-merges to main.
disable-model-invocation: false
---

# /ztn:backfill-concepts — Historical Concept Extraction

Backfills `concepts:` frontmatter on records and knowledge notes that
were authored before `/ztn:process` Step 3.4.5 (concept matcher
subagent) existed. Reuses the same Sonnet matcher contract per batch
of related notes; refreshes the canonical `CONCEPTS.md` registry
between batches so each subagent sees the growing vocabulary.

**Philosophy.**
- Quality over speed: prefer existing canonical names verbatim, coin
  only when no registry entry fits. Inter-batch registry refresh is
  the load-bearing mechanism preventing duplicate near-coinages.
- Owner-reviewed at the end. The SKILL writes a feature branch and
  opens a PR. Auto-merge is never enabled.
- Resumable. Per-batch checkpoint commits + a log file under
  `_system/state/log_backfill.md` let the owner interrupt and resume
  without losing progress.
- Non-destructive. Other frontmatter fields are preserved verbatim;
  body is never touched.

**Contracts:** `_system/docs/ENGINE_DOCTRINE.md` (operating philosophy
— load first; binding cross-skill rules: surface-don't-decide,
inclusion-bias-on-capture / curation-on-promotion, idempotency, the
owner-LLM contract), `_system/registries/CONCEPTS.md` (canonical
vocabulary), `_system/registries/CONCEPT_TYPES.md` (16-value emit
gate, never `person`/`project`), `_system/registries/DOMAINS.md`
(canonical 13 + extensions), `_system/scripts/_common.py`
(`normalize_concept_name`, `validate_concept_type`, `normalize_domain`).

**Documentation convention:** при edits соблюдай `_system/docs/CONVENTIONS.md`.

---

## Arguments

`$ARGUMENTS` supports:
- `--scope <records|knowledge|all>` — narrow what gets backfilled
  (default: `all`). `records` = `_records/{meetings,observations}/`;
  `knowledge` = PARA `1_projects/`, `2_areas/`, `3_resources/`.
- `--batch-size N` — notes per Sonnet subagent invocation (default 15).
  Reduce to 8–10 if Sonnet output truncation observed.
- `--limit N` — process only the first N batches (smoke-test mode).
- `--resume` — detect existing feature branch and skip already-
  processed batches (default behaviour when feature branch exists;
  flag is documentary).
- `--dry-run` — print scope + batch plan; do not spawn subagents,
  do not write frontmatter, do not commit.
- `--no-pr` — skip PR creation at the end (useful when owner intends
  to review locally before pushing).

---

## Step 0: Pre-flight checks

**0.1 Cross-skill lock matrix** (per `SYSTEM_CONFIG.md` §"Cross-skill
exclusion"). Backfill is exclusive with `/ztn:process`,
`/ztn:maintain`, `/ztn:lint`, `/ztn:agent-lens`. Read all four
`.{skill}.lock` files in `_sources/`; abort if any exists. Acquire
`.backfill-concepts.lock` for the duration; release on completion or
failure.

**0.2 Registry must exist.** Check for
`_system/registries/CONCEPTS.md`. If absent or empty (header only),
STOP and surface:

```
CONCEPTS.md is missing or empty. Run /ztn:maintain (which invokes
build_concept_registry.py at Step 4.5) or build_concept_registry.py
directly before backfilling — even an empty schema-correct file is
required as the seed registry.
```

**0.3 Clean working tree on main.** Verify `git status` is clean and
the current branch is `main` (or whatever the project's default
trunk is — read from `git symbolic-ref refs/remotes/origin/HEAD`).
If not clean, surface and abort. Owner stages or commits before
re-running.

**0.4 GitHub CLI available.** `gh auth status` must succeed unless
`--no-pr` is set. If neither holds, abort with a one-line remediation
hint.

---

## Step 1: Scope resolution

Walk the engine-relevant corpus folders (per `--scope`):

```
default scope (--scope all):
  _records/meetings/
  _records/observations/
  1_projects/
  2_areas/
  3_resources/         (skip people/, ideas/ if owner stores raw drafts there;
                        SOULMD-style files are fine — concept extraction is safe)

skipped at every scope:
  4_archive/           (don't rewrite history)
  _system/             (engine state, never tagged)
  5_meta/              (templates, MoCs — MoCs handled by /ztn:maintain hubs)
  6_posts/             (output stage)
  0_constitution/      (principles use `domain:`, not `concepts:`)
```

Filter the walk to files where:
- `layer:` frontmatter ∈ {`record`, `knowledge`}
- `concepts:` field is absent OR is an empty list

Group results into a `scope.json` manifest in memory:

```json
{
  "total_files": 612,
  "by_layer": {"record": 125, "knowledge": 487},
  "by_dir": {"_records/meetings/": 89, "1_projects/": 230, ...}
}
```

Print to the owner:

```
Scope: 612 files (125 records, 487 knowledge notes)
Predicted batches: ~41 @ batch-size=15
Estimated subagent invocations: ~41
Proceed? [y/N]
```

Wait for explicit `y`. Anything else aborts.

---

## Step 2: Branch creation

```bash
today=$(date +%Y-%m-%d)
branch="feature/concept-backfill-${today}"
if git show-ref --verify --quiet "refs/heads/${branch}"; then
  echo "Resuming on existing branch ${branch}"
  git checkout "${branch}"
else
  git checkout -b "${branch}"
fi
```

If resuming and `_system/state/log_backfill.md` exists, parse it for
already-processed batch ids — those skip in Step 4.

---

## Step 3: Batching

Group scope files into batches. Size cap: `--batch-size` (default 15).

**Primary key — `origin_source`.** Notes derived from the same
transcript / source share extraction context; the matcher gives them
consistent canonical names. Read `source:` (records) and
`origin_source:` (knowledge — falls back to parent record's `source:`).

**Secondary key — linked hub.** Notes referenced from the same MoC
(parsed from `5_meta/mocs/*.md` body wikilinks) cluster well by
topic. Use this when origin_source is missing or under-populates a
batch.

**Tertiary key — `domains:` + temporal cluster.** Notes sharing a
primary domain and falling within a 14-day window. Heuristic for
solo-Plaud observations and freeform reflections without a strong
source/hub anchor.

**Fallback — alphabetical chunks of `--batch-size`.** Last resort
when no signal applies.

After grouping, split any cluster larger than `--batch-size` into
smaller batches preserving primary-key cohesion (e.g. one transcript
with 22 notes → two batches of 11 each, both labelled with the same
origin_source).

Print the batch plan as a numbered list with file counts per batch
and the dominant primary key per batch:

```
Batch 1/41 (origin_source=plaud/2026-04-23T...): 8 notes
Batch 2/41 (origin_source=plaud/2026-04-23T...): 12 notes
Batch 3/41 (hub=integration-architecture): 14 notes
Batch 4/41 (domains=[work,career] cluster 2026-03): 9 notes
...
```

---

## Step 4: Per-batch processing loop

For each batch (skipping those already in log_backfill.md when
resuming):

### 4.A Spawn Sonnet matcher subagent

Use the harness Agent tool:

```
Agent(
  description: "Backfill concepts for batch {N}/{M} ({primary-key})",
  subagent_type: "general-purpose",
  model: "sonnet",
  prompt: <see template below>
)
```

**Prompt template** (orchestrator interpolates):

```
You are the ZTN concept backfill matcher. Read the registry, the
type vocabulary, and the canonical domains. Then extract concepts
from each note in the batch. Prefer existing canonical names verbatim;
coin a new concept only when no registry entry fits.

REGISTRY (authoritative — prefer existing names verbatim):
<full text of _system/registries/CONCEPTS.md>

CONCEPT TYPES (assignable values — 16):
<full text of _system/registries/CONCEPT_TYPES.md plus the 16 emit
codes with descriptions; explicitly forbid `person` and `project`>

DOMAINS (canonical 13 + active extensions):
<full text of _system/registries/DOMAINS.md canonical + Extensions table>

BATCH (size = {N}):
For each note, you receive: path, current frontmatter (sans concepts),
truncated body excerpt (~3000 chars). Extract concepts per note.

[Per-note input block, repeated:]
=== NOTE: {path} ===
FRONTMATTER:
{yaml dump of fm without concepts}
BODY (truncated):
{first 3000 chars of body}
=== END NOTE ===

OUTPUT — strict JSON, no prose:
{
  "batch_results": [
    {
      "note_path": "...",
      "concepts": ["canonical_a", "canonical_b", ...],
      "new_concepts": [
        {"name": "...", "type": "<one of 16>",
         "subtype": "<optional>", "justification": "<one sentence>"}
      ],
      "domain_corrections": [
        {"raw": "...", "action": "remap" | "drop", "target": "<canonical>"}
      ]
    },
    ...
  ]
}

RULES:
- Prefer registry names verbatim. Coin new only when no entry fits.
- For new concepts, type from the 16 emit values. NEVER `person` or
  `project`.
- Concept names follow CONCEPT_NAMING.md (snake_case ASCII, length
  2-64). For non-English source terms, translate semantically.
- Aim for 3-7 concepts per note (the working range from the existing
  Q15 contract). Empty list valid for genuine fragments.
- Domain corrections are optional — only emit when you spot an
  obviously wrong domain in the note's existing frontmatter (rare).
- Do NOT include people or projects as concepts.
```

### 4.B Parse + validate

Parse the JSON. On parse failure, retry once. On second failure, log
`subagent-parse-failed` to log_backfill.md, skip the batch, continue.

For each `note_path` in `batch_results`:

1. Pass each entry of `concepts[]` through
   `_common.py::normalize_concept_name`. Drop None.
2. For each `new_concepts[].type` apply `validate_concept_type`. Drop
   the new-concept entry on miss (keep its name in `concepts[]` —
   it's still useful as a coined name; type rebinding happens on
   next maintain regen).
3. Apply `domain_corrections[]`:
   - `action: drop` → remove the value from the note's `domains:`.
   - `action: remap` + `target` ∈ canonical/extension → replace.
   - Other actions → ignore (log `domain-correction-unknown-action`).

### 4.C Frontmatter writeback

Read each note's frontmatter via `_common.py::read_frontmatter`,
inject the validated `concepts:` array (and updated `domains:` if
corrections applied), write via `write_frontmatter`. Body is
preserved verbatim.

### 4.D Per-batch checkpoint

```bash
git add -A   # only frontmatter changes; body is untouched
git commit -m "backfill: batch ${N}/${M} (${primary_key}) — ${file_count} files"
```

Append to `_system/state/log_backfill.md`:

```markdown
## Batch {N}/{M} — {YYYY-MM-DD HH:MM}

- Primary key: {origin_source | hub | domain-cluster | alphabetical}
- Files: {count}
- Concepts assigned (median per file): {N}
- Vocabulary hits (existing canonical reused): {N}
- New concepts coined: {N}
- Domain corrections applied: {N}
- Subagent: {success | retry-once | failed}
- Commit: {short_sha}
```

### 4.E Inter-batch registry refresh

After each successful batch commit, regenerate CONCEPTS.md from the
updated corpus so the next batch's subagent sees the growing
vocabulary:

```bash
python3 _system/scripts/build_concept_registry.py
git add _system/registries/CONCEPTS.md
if ! git diff --cached --quiet; then
  git commit -m "backfill: refresh CONCEPTS.md after batch ${N}/${M}"
fi
```

This is the load-bearing mechanism preventing parallel near-coinages
across batches: batch K coins `api_v2_design`, batch K+1 sees it in
the registry and reuses verbatim instead of coining `api_2_design`
or `api_v2`.

---

## Step 5: Post-completion quality gate

After the last batch commits:

**5.A Lint pass over the feature branch.**

```bash
python3 _system/scripts/lint_concept_audit.py --mode fix
```

This applies any final concept-name normalisations the subagent
missed and rewrites legacy aliases the registry might have grown.
Commit if changes:

```bash
git add -A
git commit -m "backfill: lint pass over backfilled corpus" || true
```

**5.B Diff sanity check.** Compare CONCEPTS.md before-vs-after the
backfill:

```
total_concepts: pre=N post=M (delta +K)
total_mentions: pre=A post=B (delta +C)
```

If post / pre > 10x, surface as a warning in the final report — owner
should spot-check that the subagents didn't hallucinate excessive
new-concept coinage.

**5.C Final summary block** (printed to stdout + appended to
log_backfill.md):

```
=== Backfill complete ===
Files processed: {N}
Files with concepts: now / before: {N} / 0
Concepts (canonical) reused from registry: {N}
New concepts coined: {N}
Reuse ratio: {pct}%
Subagent invocations: {N}
Subagent retries: {N}
Subagent failures: {N}
Commits on feature branch: {N}
```

---

## Step 6: PR creation

Unless `--no-pr` is set:

```bash
git push -u origin "${branch}"
gh pr create \
  --base main --head "${branch}" \
  --title "Concept backfill — historical corpus (${N} files)" \
  --body "$(cat <<'EOF'
## Summary

One-time backfill of \`concepts:\` frontmatter on the historical
corpus, produced by /ztn:backfill-concepts.

- Files touched: {N}
- New canonical concepts coined: {N}
- Existing-vocabulary reuse: {pct}%
- Subagent invocations: {N} (retries: {N}, failures: {N})

## Review path

- Spot-check 5–10 random files (suggested below) for concept
  appropriateness.
- Inspect CONCEPTS.md diff for any obviously bogus new-concept rows.
- Owner merges manually after review — no auto-merge.

## Suggested spot-check files

{5-10 random paths from the backfilled set}

## Test plan

- [ ] /ztn:lint scan over the merged branch is clean
- [ ] /ztn:process Step 3.4.5 on next fresh transcript reuses
      backfilled vocabulary
- [ ] Random file inspection confirms appropriate concept assignment
EOF
)"
```

Print the PR URL to stdout.

---

## Step 7: Cleanup

- Release `.backfill-concepts.lock`.
- Feature branch persists — owner merges or discards.
- log_backfill.md persists as the audit trail.

If `--dry-run` was active, no commits, no PR, no log. Just print the
batch plan and a count of files that would have been touched.

---

## Failure modes and resume contract

- **Subagent JSON parse failure (twice).** Skip the batch, log to
  log_backfill.md as `subagent-parse-failed`, continue with next
  batch. Owner re-runs `/ztn:backfill-concepts --resume` after
  investigation.
- **Validation strips all concepts for a note.** Note ends with
  empty `concepts: []`. Honest signal — the matcher couldn't
  produce conformant names. Owner reviews the note's source and
  manually assigns concepts via `/ztn:check-content` or direct
  edit.
- **Inter-batch registry refresh fails.** Surface the error, abort
  the current batch's processing, leave feature branch in a
  consistent state (last good commit). Owner debugs and re-runs
  `--resume`.
- **Network / gh auth failure on PR.** Skip PR creation, print the
  push command + suggested PR body for owner to file manually.
  Print remediation: `gh auth login`, then `--no-pr` to retry the
  full SKILL without re-spawning subagents.

---

## Why this is a one-time SKILL

The backfill is a corpus-historical operation. After it lands, every
new transcript flows through `/ztn:process` Step 3.4.5 and emerges
with `concepts:` populated by the matcher subagent at process time.
A second `/ztn:backfill-concepts` run finds zero candidates (the
filter `concepts: absent OR empty` matches nothing) and exits in
Step 1.

The SKILL stays in the engine for two reasons:
1. Friend instances can run it on their own historical corpora.
2. If the engine ever evolves a richer concept-extraction prompt and
   the owner wants to re-extract the corpus, the SKILL can be
   re-run with the existing `concepts:` field cleared by hand on
   targeted files.
