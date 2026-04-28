# Constitution scripts

Deterministic Python utilities for the `0_constitution/` layer. No LLM. PyYAML
is the single external dependency.

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
| `render_soul_values.py` | Render the Values auto-zone inside `_system/SOUL.md`, bounded by markers. Detects manual drift. | `_system/SOUL.md` (only between markers) |
| `compact_evidence_trail.py` | Collapse Evidence Trail entries older than a cutoff into one `[compacted]` summary. Invoked only after the owner approves an `evidence-trail-compact` CLARIFICATION. | single `.md` file under `0_constitution/` |

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

See `0_constitution/CONSTITUTION.md` for the authoritative schema, scope
semantics, writeability matrix, and governance invariants. The scripts mirror
that spec; any discrepancy is a bug in the scripts.
