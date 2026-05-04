# `_system/state/batches/` — engine output directory

Canonical location for the ZTN engine's append-only manifest output.
Every persistent-state-changing run of `/ztn:process`, `/ztn:maintain`,
`/ztn:lint`, or `/ztn:agent-lens` writes one pair of files into this
directory: a machine-contract `.json` and a human-narrative `.md`.

This README documents the **directory's** contract — naming,
ordering, retention, the JSON / MD pair, archive convention, and
backup. The **schema** content of the JSON files is documented in
[`_system/docs/manifest-schema/README.md`](../../docs/manifest-schema/README.md)
and pinned by [`v2.json`](../../docs/manifest-schema/v2.json).

---

## 1. Purpose

One pair of files per batch:

- **`{ts}-{skill}.json`** — machine contract. Validated against
  `manifest-schema/v2.json` by `/ztn:lint` Scan H. Required for any
  consumer integration.
- **`{ts}-{skill}.md`** — human-facing narrative summary. Owner-
  oriented, not schema-validated, not consumed programmatically.

Both files share the same `{ts}-{skill}` stem. Consumers integrating
with the engine output read `.json` only; the `.md` is for manual
review of what a batch produced.

---

## 2. Naming convention

```
{ts}-{skill}.json
{ts}-{skill}.md
```

- `{ts}` — sortable string `YYYYMMDD-HHMMSS` UTC. Lexicographic sort
  on this prefix is monotone in time.
- `{skill}` — one of `process`, `maintain`, `lint`, `agent-lens`.
  Matches the manifest's top-level `processor` field with the
  `ztn:` prefix stripped.

### Legacy form

Pre-2026-05-04 `/ztn:process` emissions used `{ts}.json` (and the
paired `{ts}.md`) without a skill suffix. After Wave 1's filename
realignment (`A0-1.2`) `/ztn:process` writes `{ts}-process.json`
like the other three skills.

**Append-only — legacy filenames are never renamed retroactively.**
Consumers reading historic batches must match both patterns:

```
^[0-9]{8}-[0-9]{6}\.json$            # legacy /process
^[0-9]{8}-[0-9]{6}-[a-z-]+\.json$    # current contract
```

`/ztn:maintain` already implements this dual-match for `.md` files
per its `SKILL.md`; analogous fallback applies to JSON consumers.

**Footprint at time of writing:** 3 legacy `{ts}.json` files (all
`/ztn:process`) plus 8 even-older `{ts}.md`-only emissions that
predate JSON manifests entirely. The legacy footprint is small and
finite — it does not grow.

---

## 3. Ordering

Per ARCHITECTURE.md §8.11.2 (one specific downstream consumer's
ordering spec, in the minder-project repo) — *the canonical sort
key is the filename's timestamp prefix.* Consumers MUST NOT
rely on filesystem `ctime` / `mtime`: those change on copy, move,
`git restore`, clone-into-fresh-tree, or any rsync. Filename time
survives all of them.

Within the same `{ts}`, the cross-skill lock matrix
(ZTN doctrine §3.4) defines order:

```
process → maintain → lint → agent-lens
```

Skills cannot run in parallel under that matrix, so within any one
wall-clock second one and only one new batch lands. Equal-`{ts}`
ties between skill manifests are resolved by this skill order.

---

## 4. Idempotency

The manifest's top-level `batch_id` field is the **idempotency key**
for downstream consumers. Re-reading a manifest with a `batch_id`
already processed downstream MUST be a no-op.

- Reading the same `batch_id` twice is safe.
- Writing two different files with the same `batch_id` is a contract
  violation. The schema validator does not check this — the writer
  side (engine) and the reader side (consumer) are both expected to
  uphold it.
- `batch_id` uniqueness is preserved across archived batches too —
  if a consumer chooses to read the `archive/` subdirectory, replay
  remains safe.

---

## 5. The JSON / MD pair

| File | Purpose | Validated | Consumed by |
|---|---|---|---|
| `{ts}-{skill}.json` | Machine contract | Yes — `manifest-schema/v2.json` via `/ztn:lint` Scan H | Any downstream consumer |
| `{ts}-{skill}.md` | Owner-facing narrative | No | Humans only |

Two files, same stem. They are written by the same skill in the
same run; absence of one does not invalidate the other. (See §6 for
why the producer does not need both to be atomically co-written.)

---

## 6. Append-only retention

ZTN never deletes batches. There is no automated cleanup, no
retention cron, no time-based pruning. The directory grows
monotonically; archival is an owner-driven move (§7), not a delete.

### Write semantics — current behaviour

`_system/scripts/emit_batch_manifest.py` writes manifests directly
to the output path via `Path.write_text(...)`. **This is not
`.tmp` + atomic-rename today.** A crash mid-write would leave a
partial JSON file. Two practical mitigations are in play:

1. The dominant emission path is short — manifests are small (a few
   kB to a few hundred kB) and Python's `write_text` issues a
   single `write(2)` on most filesystems. The crash window is
   narrow, but it is non-zero.
2. `/ztn:lint` Scan H runs nightly and would surface a corrupt JSON
   as a validation failure rather than letting it propagate
   silently to a consumer.

**Tracked as a follow-up improvement, not part of A0-ZTN scope.**
Migrating to `.tmp` + `os.replace()` is a small fix that would
remove the residual risk; the right place for it is a separate
hardening pass on the emitter, not folded into the docs wave.

### Validator baseline

Pre-validator-baseline batches (older than the timestamp recorded
in `_system/state/batches/.validator-baseline`) are skipped by
Scan H. Reason: legacy batches predate the schema's required
sections and would surface as false-positive failures. Append-only
philosophy applies — those batches are kept verbatim and excluded
from validation, never rewritten to fit the current shape.

The baseline file is created by `lint_manifest_schema.py
--init-baseline` on the first nightly run after Wave 1; once
written, it is itself append-only against retroactive edits.

---

## 7. Owner-archive convention

Path: `_system/state/batches/archive/{YYYY-MM}/`

- Move-to-archive is **owner-driven**, never automated. Trigger is
  disk pressure; nothing else.
- **Do NOT archive recent batches (< 30 days).** Downstream
  consumers may need a replay window. 30 days is a conservative
  floor; specific consumers may need longer in practice — they are
  expected to declare that need rather than discover it through a
  missing file.
- Archived batches stay valid and parseable. A consumer that
  *chooses* to read the archive can do so; the default expectation
  is that consumers ignore the `archive/` subdirectory.
- Idempotency persists across the move — `batch_id` keys are stable.

---

## 8. Backup

The ZTN repo has a GitHub remote. Every `git push` carries the
batches directory off the local box. There is no separate
batches-only backup mechanism in A0-ZTN scope, by design — the
engine's git repo is the unit of backup.

Per ARCHITECTURE.md §8.12.5 (one specific consumer's restore plan,
in the minder-project repo), this directory doubles as a disaster-
recovery source for downstream state: with the consumer's databases
lost but ZTN intact, re-processing every `*.json` here re-derives
the typed-object state. This is a major-incident fallback, not
routine restore.

For deeper protection (account loss, mirror failure), GitHub
mirroring or an off-site git remote is the owner's responsibility
and is out of A0-ZTN scope.

---

## 9. Pointers

- **Schema reference:**
  [`_system/docs/manifest-schema/README.md`](../../docs/manifest-schema/README.md)
  and [`v2.json`](../../docs/manifest-schema/v2.json)
- **Validator:** `/ztn:lint` Scan H, backed by
  [`_system/scripts/lint_manifest_schema.py`](../../scripts/lint_manifest_schema.py)
- **Per-skill manifest semantics:** ARCHITECTURE.md §8.11 in the
  minder-project repo (one specific downstream consumer's view of
  what each skill emits — the contract here is consumer-agnostic)
- **Engine doctrine on append-only / idempotency / lock matrix:**
  [`_system/docs/ENGINE_DOCTRINE.md`](../../docs/ENGINE_DOCTRINE.md)
  §3.3, §3.4, §3.8

---

## 10. Status reference

This file closes A0-ZTN deliverables **A0-5.2** (batches retention +
ordering policy) and **A0-5.4** (`.md` summary files documentation),
folded together per the plan. See
`minder-project/strategy/A0-ZTN-PLAN.md` §4 and
`minder-project/strategy/A0-ZTN-STATUS.md` for milestone context.
