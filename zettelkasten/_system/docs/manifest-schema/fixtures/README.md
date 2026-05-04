# Manifest schema fixtures

Sanitized batch manifests, one per ZTN engine skill, that MUST validate
against the version of `manifest-schema/v{N}.json` they are paired with.

## Files

- `process.json` — `/ztn:process` emission. Sanitized from a real
  reprocess-corpus batch: people, project, and source IDs replaced with
  realistic placeholders; record titles overwritten; concept hints kept
  where generic. Substantive — non-empty `records.updated[]`,
  `concepts.upserts[]`.
- `maintain.json` — `/ztn:maintain` emission. Real batch from the same
  pipeline; carries `stats` only because no graph-completion changes
  were emitted that run.
- `lint.json` — `/ztn:lint` emission. Real batch with non-zero
  `autofixes_applied` and the `autofixes_by_fix_id` breakdown.
- `agent-lens.json` — `/ztn:agent-lens` emission. **Synthesized** per
  ARCHITECTURE.md §8.11.5 + §6.4.2: at the time the schema and
  fixtures were authored, /ztn:agent-lens emitted only to
  `_system/state/agent-lens-runs.jsonl` and not to
  `_system/state/batches/{ts}-agent-lens.json`. Bringing agent-lens
  under the universal manifest contract (per SD007 / §8.11.1) is a
  follow-up — the synthetic fixture pins the expected shape so that
  the validator and downstream consumers have a stable contract from
  day one. When the first real agent-lens batch lands, swap this
  synthetic fixture for a sanitized real one.

## Why fixtures exist

Regression test for schema evolution. **Any future schema change MUST
keep these fixtures validating.** If a change breaks them, that is a
contract change — make the conscious decision: either adjust the
fixtures (if the change is intentional + non-breaking, MINOR bump per
§8.12.2) or treat it as a MAJOR bump (breaks consumers; ship a
migration shim).

The fixture set deliberately covers the four `processor` values so a
`oneOf`-style branch in the schema cannot silently regress one skill
while the others stay green.

## Sanitization rules

When replacing a real batch with a fixture:

1. People IDs → fictional kebab-case slugs (`alex-rivers`, `ben-marlow`).
2. Project IDs → fictional kebab-case slugs (`alpha-platform`).
3. Free-text titles / bodies → "Example {kind} (sanitized)" or a
   neutral paraphrase. Keep at least one substantive `body_markdown`
   for the lens-observation fixture so `searchable_fields` semantics
   are realistic.
4. Source paths under `_sources/processed/` → keep prefix structure
   but generalize the timestamp (`2026-01-01T0N:00:00Z`).
5. Concept names — keep when the term is generic
   (`technical_debt`, `delegation_pattern`); rename when the term
   reveals a tenant-specific project (`alterpay_integration` →
   `external_provider_integration`).
6. Checksums → `"a"*64` style placeholders (not real hashes — fixtures
   are meant to be byte-stable in git).
7. Privacy trio — preserve real values where they are non-default
   (`origin: work` carries semantic information about the producer
   pipeline branch; keeping it makes the fixture exercise the
   non-default code path).

## Running the validator locally

```bash
python3 - << 'EOF'
import json, glob
from jsonschema import Draft202012Validator
schema = json.load(open('zettelkasten/_system/docs/manifest-schema/v2.json'))
v = Draft202012Validator(schema)
for path in sorted(glob.glob('zettelkasten/_system/docs/manifest-schema/fixtures/*.json')):
    errs = list(v.iter_errors(json.load(open(path))))
    print(path, 'OK' if not errs else f'FAIL ({len(errs)} errors)')
EOF
```

The same logic runs in `/ztn:lint` Scan G (manifest schema validation
— see ztn-lint SKILL.md).
