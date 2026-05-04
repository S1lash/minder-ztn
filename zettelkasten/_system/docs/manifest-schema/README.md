# ZTN engine output contract

`v2.json` (this directory) is the canonical **JSON Schema** that every
manifest written by a ZTN engine skill MUST validate against. Any
process that wants to consume ZTN output — Minder's ingest worker, a
fork running on someone's laptop, an experimental GraphRAG layer, a
notebook — reads this contract and nothing more.

This README is consumer-agnostic on purpose. ZTN is a standalone
engine; downstream is an open set.

---

## What is a manifest

After every persistent-state-changing run of `/ztn:process`,
`/ztn:maintain`, `/ztn:lint`, or `/ztn:agent-lens`, the engine writes
a single JSON file under `_system/state/batches/`:

```
_system/state/batches/{batch_id}-{skill}.json
```

`{batch_id}` is `YYYYMMDD-HHMMSS` UTC (sortable as string, monotone
non-decreasing per skill). `{skill}` is one of `process`, `maintain`,
`lint`, `agent-lens`. The same file is also written as a
human-narrative `{batch_id}-{skill}.md` next to it; the markdown is
informal and not part of the contract.

All four skills emit into one shape distinguished by the top-level
`processor` field. A consumer reads them uniformly.

> **Filename note.** A small history wart: until `2026-05-04`,
> `/ztn:process` wrote to `{batch_id}.json` (no skill suffix) while
> the other three already carried the suffix. Going forward all four
> follow `{batch_id}-{skill}.json`. Consumers built today should
> accept both forms — sort by leading timestamp prefix.

---

## Schema location and version evolution

- **Active schema:** `v2.json` in this directory. `$id` =
  `urn:ztn:manifest-schema:v2` (URN — no URL resolution, no domain
  commitment, consumer-agnostic). Draft 2020-12.
- **Past schemas** stay in this directory unchanged
  (`v2.json` → `v2.1.json` → `v3.json` …). Old batches keep
  validating against the version they were emitted with.
- **Version pinning per batch:** every manifest carries
  `format_version: "MAJOR.MINOR"`. Consumers pick the matching schema
  file by major (and minor when relevant).

### Evolution rules (SemVer per ARCHITECTURE.md §8.12.2)

| Change kind | Bump | Behaviour |
|---|---|---|
| Add new optional field | MINOR | Consumers accept; missing → use defaults. |
| Add new manifest section | MINOR | Process if known; ignore if not. |
| Add new entity type to existing section | MINOR | Route to handler; warn if not registered. |
| Remove deprecated field | MAJOR | Consumer rejects with loud error. |
| Change field semantics | MAJOR | Consumer rejects; explicit migration shim. |
| Restructure section | MAJOR | Consumer rejects. |

**Forward-compat slot.** Every section accepts `section_extras: jsonb`
for fields not yet promoted to schema. A top-level `section_extras`
covers entirely new sections. Consumers log unknown contents but do
not fail. This is what lets the engine ship new fields without
coordinating a major bump.

---

## What is in the manifest

Per ARCHITECTURE.md §4.5 (the long-form sample) and §8.11 (per-skill
mapping). Briefly:

| Top-level key | What it carries |
|---|---|
| `batch_id` / `timestamp` / `format_version` / `processor` | Identity. Always present. |
| `sources_processed` | Files consumed (transcripts under `_sources/processed/`). `/ztn:process` only. |
| `records` | Records created/updated under `_records/{meetings,observations}/`. |
| `knowledge_notes` | PARA notes created/updated under `1_projects/`…`4_archive/`. |
| `hubs` | Hub files created/updated under `5_meta/mocs/`. |
| `concepts.upserts[]` | Per-batch deduplicated concept registry. Names are conformant by construction. |
| `constitution.{principles,constitution_core_view,soul}` | Tier 0 surface — principles, the auto-rendered core view, SOUL fields. |
| `tier1_objects` | First-class typed objects: `tasks`, `ideas`, `events`, `decisions`, `people`, `projects`, `content`. |
| `tier2_objects` | Schema-registered structured objects: `inventory`, `wardrobe`, `content_candidates`, `lens_observation`, owner-extensible. |
| `sensitive_entities` | Per-batch summary of every entity emitted with `is_sensitive: true`. |
| `threads_opened` / `threads_resolved` | Slot for the deferred Tier 1 thread type. |
| `stats` | Per-skill counters. Schema accepts unknown keys (additive without bump). |
| `section_extras` | Forward-compat slot. |

### Privacy trio

Every Tier 0/1/2 entity entry carries:

- `origin` — provenance enum (`personal | work | external` plus the
  `bootstrap-*` and `sync-*` prefixes for synthetic origins).
- `audience_tags` — `text[]`, whitelist enforced by the engine
  (canonical 5 + per-tenant Extensions in `AUDIENCES.md`); schema
  enforces type only.
- `is_sensitive` — boolean modifier orthogonal to audience.

Defaults are conservative-safe (`personal` / `[]` / `false`). Defaults
are applied at emission, not at validation; the schema enforces
presence + type only.

### Per-skill emission semantics

| Skill | Role | What it emits |
|---|---|---|
| `/ztn:process` | Creator. Turns transcripts into records / knowledge / hubs / concepts / Tier 1 typed objects. | All sections; the densest manifest. |
| `/ztn:maintain` | Integrator. Reconciles drift, completes graph linkage, suggests tier shifts. | Diff-shaped: `hubs.updated[]`, `tier1_objects.people.upserts[]` with `tier_suggested`, etc. Suggests; never silently mutates ownership semantics. |
| `/ztn:lint` | Cleaner / promoter. Auto-fixes (concept names, audience tags, privacy-trio backfill), promotes principle candidates to Tier 0, surfaces dedup pairs as CLARIFICATIONs (does not auto-merge). | Stats + checksum updates for autofixed files; `constitution.principles.upserts[]` on F.5 promotion. |
| `/ztn:agent-lens` | Outside-view hypothesiser. Generates lens observations about owner state from accumulated content. | `tier2_objects.lens_observation.upserts[]` with `is_hypothesis: true`; references existing concepts (never creates new ones). |

Full per-skill mapping with anatomy tables: ARCHITECTURE.md §8.11.

---

## What is NOT in the manifest

Per ARCHITECTURE.md §4.5 + ENGINE_DOCTRINE.md §3.8 — these stay
inside the engine and never reach a consumer:

- **Candidate buffers** — `principle-candidates.jsonl`,
  `people-candidates.jsonl`. Pre-resolution staging; promotion gates
  on `/ztn:lint` F.5 (principles) or `/ztn:resolve-clarifications`
  (people).
- **Working memory** — `OPEN_THREADS.md`. Until the focus engine arrives.
- **HITL queues** — `_system/state/CLARIFICATIONS.md`. Owner-facing only.
- **Audit trails** — `log_process.md`, `log_maintain.md`, `log_lint.md`,
  `agent-lens-runs.jsonl`, `check-decision-runs.jsonl`. Substrate for
  lenses and future cross-source analysis; not consumer-routable.
- **Derived / regenerable views** — `CURRENT_CONTEXT.md`,
  `_system/views/INDEX.md`, `lint-context/{daily,monthly}/*`.

If a consumer needs any of these, the right answer is to derive them
itself from the manifests it does receive — not to reach into engine
internals.

---

## Consumer integration patterns

These are the rules a consumer is expected to follow to stay
compatible with the contract.

### Read order

1. List all `*.json` under `_system/state/batches/` that the consumer
   has not seen before (track by `batch_id` in your own bookkeeping).
2. Sort by **filename timestamp prefix** (the `YYYYMMDD-HHMMSS` part
   of the basename). Filename is canonical — do not rely on
   filesystem ctime, it churns on copy / git restore.
3. Process one at a time. No parallel reads — preserve causal order
   per ARCHITECTURE.md §8.11.2.

### Idempotency

Every batch carries a `batch_id` that the producer guarantees stable
across re-runs of the same logical batch (re-emit on a downstream
filesystem failure produces the same `batch_id`). Consumers MUST be
idempotent on `batch_id`: receiving the same batch twice yields the
same final state.

For finer-grained idempotency on individual entities, every entity
carries `path` (records / notes / hubs) or a stable `id` (Tier 1/2
objects). Re-applying an unchanged entity should be a no-op; the
`checksum_sha256` field (where present) tells the consumer when
content actually changed and graph reconciliation must run
(ARCHITECTURE.md §8.11.6 invariant 1).

### Forward compatibility

When a consumer encounters a key it does not know:

- Inside a known section → skip the key, log once at startup, do
  NOT fail. The producer is allowed to add MINOR-version optional
  fields without coordinating with consumers.
- A whole unknown section → same: skip + log + continue.
- An unknown entry in `section_extras` → same. That slot exists
  exactly to absorb pre-promotion fields.

When a consumer encounters an incompatible major version
(`format_version` major ≠ what the consumer speaks):

- Reject the batch with a loud error. Do not silently skip; the
  whole point of MAJOR is "your code needs updating".
- Recommended: pause subsequent newer batches until the operator
  resolves (ship an updated consumer or a migration shim).

### Graph reconciliation (consumers that maintain a graph)

When an entity's `checksum_sha256` changes between batches, the
consumer MUST diff the entity's relational arrays
(`people`, `concept_hints`, etc.) against its existing graph state
and reconcile edges (add new, remove obsolete). Re-applying based on
the new checksum alone, without diffing, accumulates stale edges.
This is invariant 1 in ARCHITECTURE.md §8.11.6 and applies uniformly
across all four skills' emissions.

### Status semantics

No skill ever causes a hard delete. Lifecycle uses `status`
(`active | archived | superseded | deprecated | dormant`). Consumers
preserve history; default queries can filter by status. This is
invariant 2 in §8.11.6.

### Epistemic markers

Two entity classes carry epistemic markers consumers should respect:

- **Tier 0 principles** drive prompt calibration in agent
  consumers — see ARCHITECTURE.md §8.9 for the calibration approach.
- **Tier 2 lens-observations** carry `is_hypothesis: true`. A
  consumer that retrieves them as evidence should preserve the flag
  end-to-end so downstream synthesis can frame them as "noticed, not
  confirmed". Never auto-inject into prompt context unconditionally.

---

## Validating a batch

```bash
python3 - << 'EOF'
import json, sys
from jsonschema import Draft202012Validator
schema = json.load(open('zettelkasten/_system/docs/manifest-schema/v2.json'))
v = Draft202012Validator(schema)
batch = json.load(open(sys.argv[1] if len(sys.argv) > 1 else '/dev/stdin'))
errs = list(v.iter_errors(batch))
if not errs:
    print('valid')
else:
    for e in errs[:20]:
        print(f'@ {list(e.absolute_path)}: {e.message[:200]}')
EOF
```

The same logic runs nightly inside `/ztn:lint` Scan G — see
`integrations/claude-code/skills/ztn-lint/SKILL.md`. Validator failures
surface as `manifest-schema-violation: <batch_id>` CLARIFICATIONs in
the engine, never silently.

---

## Examples — one specific consumer

`minder-project/strategy/ARCHITECTURE.md` §5+ describes one specific
downstream consumer (Minder backend). Other consumers — forks, custom
backends, experimental tooling — read the same contract. Nothing in
this directory is Minder-specific by design; the schema and the
patterns above are the whole interface.

---

## Adjacent docs

- `_system/docs/batch-format.md` — narrative about the
  human-readable `.md` summary that ships next to each `.json`.
- `_system/docs/SYSTEM_CONFIG.md` — engine contract (locks, append-only,
  per-entity field schemas).
- `_system/docs/ENGINE_DOCTRINE.md` §3.8 — the manifest emission
  doctrine across all skills.
- `_system/registries/CONCEPT_NAMING.md` — concept-name format spec.
- `_system/registries/AUDIENCES.md` — audience-tag whitelist.
- `_system/registries/DOMAINS.md` — domains whitelist.
- `fixtures/` — sanitized example manifests, one per skill, used as
  schema-evolution regression tests.
