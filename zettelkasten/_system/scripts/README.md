# Engine scripts

Deterministic Python utilities for the engine — constitution layer,
concept and audience format autofix, batch JSON manifest emission,
shared frontmatter helpers. No LLM. PyYAML is the single external
dependency.

## Install

```bash
python3 -m pip install -r _system/scripts/requirements.txt
```

Works on any Python ≥ 3.9 with PyYAML ≥ 6.0.

## Scripts

All scripts support `--dry-run` and print to stderr on failure with a non-zero
exit code. Paths are resolved relative to the zettelkasten repo root; override
via the `ZTN_BASE` env var if running from outside the repo. All outputs live
inside the repo — scripts never write to `$HOME`. Consumers (Claude Code
harness) set up a symlink once per machine:
`ln -s $ZTN_BASE/_system/views/constitution-core.md ~/.claude/rules/constitution-core.md`.

| Script | Purpose | Writes |
|---|---|---|
| `gen_constitution_index.py` | Regenerate `_system/views/CONSTITUTION_INDEX.md` — full registry table with stats. | `_system/views/CONSTITUTION_INDEX.md` |
| `gen_constitution_core.py` | Regenerate `_system/views/constitution-core.md` — harness core view (all scopes, filtered by `applies_to: claude-code` and `status != placeholder`). | `_system/views/constitution-core.md` |
| `archive_buffer.py` | Generic archive + verify + clear for weekly-aggregation buffers. Used by `/ztn:lint` F.3 (`principle-candidates.jsonl`) and C.5 (`people-candidates.jsonl`). Exit 2 on verify failure (buffer preserved). Archive filename uses buffer stem as prefix. | `_system/state/lint-context/weekly/{YYYY-WW}-{buffer-stem}-archived.jsonl` |
| `append_person_candidate.py` | Append a bare-name mention to `_system/state/people-candidates.jsonl`. Invoked by `/ztn:process` Step 3.8 when a first name cannot be resolved to a `firstname-lastname` PEOPLE.md id. `/ztn:lint` Scan C.5 aggregates weekly. | `_system/state/people-candidates.jsonl` |
| `query_constitution.py` | Emit JSON of visible active principles filtered by consumer / domains. Consumed by `/ztn:check-decision` + `/ztn:lint`. | stdout |
| `append_candidate.py` | Append a principle candidate to `_system/state/principle-candidates.jsonl` with schema validation + advisory file lock. Backing for `/ztn:capture-candidate`. | `_system/state/principle-candidates.jsonl` |
| `emit_telemetry.py` | Append a `/ztn:check-decision` telemetry line (run or followup) to `_system/state/check-decision-runs.jsonl`. Atomic JSONL append under co-located `flock`; sensitive-redaction (omits situation_text + rationale, keeps situation_hash); per-class auto-commit (judgmental → path-specific commit; mechanical via `--from-pipeline` → skip, parent pipeline owns batch commit); graceful fallback if git fails (warn + return 0, JSONL is source of truth). Followup mode validates run_id format + existence in substrate, refuses orphan appends. | `_system/state/check-decision-runs.jsonl` |
| `render_soul_values.py` | Render the Values auto-zone inside `_system/SOUL.md`, bounded by markers. Detects manual drift. | `_system/SOUL.md` (only between markers) |
| `compact_evidence_trail.py` | Collapse Evidence Trail entries older than a cutoff into one `[compacted]` summary. Invoked only after the owner approves an `evidence-trail-compact` CLARIFICATION. | single `.md` file under `0_constitution/` |
| `lint_concept_audit.py` | Autonomous Scan A.7 + Step 1.D privacy-trio backfill for `/ztn:lint`. Walks frontmatter on records / knowledge notes / hubs / person and project profiles; normalises `concepts:` via `_common.py::normalize_concept_list`; filters `audience_tags:` against canonical 5 + AUDIENCES.md active extensions; backfills missing privacy trio fields with conservative defaults; coerces `is_sensitive` to bool, `origin` to enum. Emits JSONL fix events on stdout. NEVER raises CLARIFICATIONs — concept layer is fully autonomous (see ENGINE_DOCTRINE §3.1). Idempotent on a clean state. | frontmatter of in-scope `.md` files (in `--mode fix`) |
| `emit_batch_manifest.py` | Producer-side JSON manifest emitter for `/ztn:process` Step 5.5 and `/ztn:maintain` Step 6.6. Reads structured batch data (stdin or `--input`), recursively normalises every concept-list field (`concept_hints` / `member_concepts` / `applies_in_concepts` / `concept_ids` / `related_concepts` / `previous_slugs`), filters `audience_tags[]` against the whitelist, coerces privacy trio types, drops `concepts.upserts[]` entries with unnormalisable name. Writes conformant JSON to `_system/state/batches/{batch_id}.json`. Format contract: `minder-project/strategy/ARCHITECTURE.md` §4.5. | `_system/state/batches/{batch_id}.json` |
| `render_index.py` | Regenerate `_system/views/INDEX.md` — surface-line catalog of knowledge (`1_projects` / `2_areas` / `3_resources`) + archive (`4_archive`, marker `[archived]`) + constitution (`0_constitution/{axiom,principle,rule}`, marker `tier N`) + hubs (`5_meta/mocs`, with inbound count). Faceted by PARA + `domains:` + cross-domain. Records and posts intentionally out of scope. Atomic write via `.tmp` + rename. Invoked by `/ztn:bootstrap` Step 5.5, `/ztn:maintain` Step 7.6, and `regen_all.py`. | `_system/views/INDEX.md` |
| `render_hub_maps.py` | Regenerate `## Хронологическая карта` AUTO-GENERATED block inside hubs with `chronological_map_mode: derived`. Anchored insert / replace; honours `excluded_from_map[]`. Invoked by `/ztn:maintain` Step 7.7. | `5_meta/mocs/*.md` (only the marked block) |
| `regen_all.py` | Convenience runner that invokes the derived-views generators in dependency order: `gen_constitution_index` → `gen_constitution_core` → `render_index` → `render_soul_values`. Fail-fast on non-zero exit; SOUL step skipped (exit 3) if markers absent on a fresh base. | (delegates) |
| `build_concept_registry.py` | Build the canonical concept registry (`_system/registries/concepts.jsonl`) by walking notes/hubs frontmatter; aggregates type / mention counts / first-seen / last-seen. Invoked by `/ztn:lint` Scan A.7 / autonomous concept layer. | `_system/registries/concepts.jsonl` |
| `lint_hub_integrity.py` | Scan hub frontmatter and body for structural integrity (markers, member back-refs, derived-trio consistency). Read-only; emits findings as JSONL on stdout. Used by `/ztn:lint` Scan A.4. | stdout |
| `lint_projects_array.py` | Scan `projects:` arrays in records / knowledge notes / hubs for non-canonical project ids; cross-checks against `1_projects/PROJECTS.md`. Read-only; emits findings as JSONL. Used by `/ztn:lint` Scan A.5. | stdout |

## Shared `_common.py` helpers

Functions imported by the scripts above; consumers of the engine
SKILLs reference them as the single source of truth for autonomous
resolution.

| Helper | Purpose |
|---|---|
| `normalize_concept_name(raw) -> str \| None` | CONCEPT_NAMING.md normalisation: diacritic-fold, lowercase, separator→`_`, ASCII guard, type-prefix strip, reserved-word drop, length truncate. Returns `None` to signal silent drop. |
| `normalize_concept_list(raw_iter) -> list[str]` | Apply normalize_concept_name to each entry; drop Nones; dedupe preserving first-seen order. |
| `normalize_audience_tag(raw) -> str \| None` | AUDIENCES.md normalisation: kebab-case ASCII, length 2-32. Returns the well-formed value or `None` to drop. Caller checks against whitelist. |
| `recompute_hub_trio(hub_fm, member_trios) -> tuple[dict, list[dict]]` | Hub privacy derivation — dominant origin / audience intersection / sensitivity contagion. Owner-edit preservation: only fills missing fields; never overwrites. |
| `read_frontmatter(path) -> tuple[dict, str] \| None` | Generic YAML frontmatter reader, tolerant of read / parse errors (returns None). |
| `write_frontmatter(path, fm, body)` | Round-trip writer preserving body verbatim; sort_keys=False, allow_unicode=True. |

## CLI examples

```bash
# Dry-run: preview the index without writing anything
python3 _system/scripts/gen_constitution_index.py --dry-run

# Generate the harness core view
python3 _system/scripts/gen_constitution_core.py

# Render SOUL.Values, appending a drift CLARIFICATION if the auto-zone was
# edited by hand since last render
python3 _system/scripts/render_soul_values.py --write-clarification

# Compact old Evidence Trail entries (only after human approval in CLARIFICATIONS)
python3 _system/scripts/compact_evidence_trail.py \
    --file 0_constitution/axiom/identity/001-if-it-can-be-better.md \
    --cutoff 2025-04-20 \
    --summary "2024-04..2025-04 — cited 27 times; pattern: aligned on code-review trade-offs"
```

## Run from scheduled tasks (Claude platform)

The scripts are stateless and CLI-driven. To run from a scheduled agent:

1. `pip install -r _system/scripts/requirements.txt` (once).
2. Set `ZTN_BASE=/absolute/path/to/zettelkasten` so path resolution is
   independent of the agent's CWD.
3. Invoke the script by absolute path, e.g.
   `python3 $ZTN_BASE/_system/scripts/gen_constitution_index.py`.

All writes are idempotent (same inputs → same outputs) so safe to re-run.

## Tests

Stdlib `unittest` only — no pytest dependency.

```bash
cd _system/scripts
python3 -m unittest discover -s tests -v
```

## Schema & invariants

- `0_constitution/CONSTITUTION.md` — authoritative schema for the
  constitution layer; scope semantics; writeability matrix.
- `_system/registries/CONCEPT_NAMING.md` — concept-name format spec
  + autonomous-resolution table.
- `_system/registries/AUDIENCES.md` — audience-tag whitelist + spec
  + Extensions table.
- `_system/docs/batch-format.md` — batch format contract (markdown
  report + JSON manifest).
- `_system/docs/ENGINE_DOCTRINE.md` §3.1 — surface-don't-decide rule
  + concept layer autonomous-resolution exception.

The scripts mirror these specs; any discrepancy is a bug in the
scripts.
