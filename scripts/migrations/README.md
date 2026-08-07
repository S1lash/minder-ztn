# Engine migrations

Migration scripts run by `scripts/run_migrations.py`, which both
`scripts/sync_engine.sh` and the `/ztn:update` skill call after a successful
fetch + checkout. One file per breaking engine change.

## Convention

- Filename: `NNN-short-slug.sh` (zero-padded order). NNN starts at `001`.
- Each script is idempotent. The runner records every attempt in the ledger at
  repo root and never re-runs a migration that succeeded.
- Scripts run from the repo root. They may rewrite files, move paths,
  or print upgrade instructions for the user. They MUST NOT touch
  user-data paths (records, knowledge, registries, SOUL, constitution).
- Keep migrations small and reversible.
- **Declared kind — `structural` vs `heal`.** Every migration states, in a
  header comment on the second line, what its failure means:

  ```bash
  #!/usr/bin/env bash
  # migration-kind: heal
  ```

  **Choose by ONE question: after this migration fails, is CONTINUING the update
  DANGEROUS — would the engine then read or write the wrong place?** Not "is this
  migration important"; every migration is important, and that question yields
  `structural` for all of them.

  - **`structural`** — yes, dangerous. A non-zero exit ABORTS the update and is
    deliberately NOT recorded, so the next update resumes at exactly that
    migration. Conservative default when the header is absent.
  - **`heal`** — no, merely incomplete. A non-zero exit is recorded as
    `partial`, the update CONTINUES, and the migration is retried on the next
    update — so an improved repair shipped later reaches the clone by itself.

  Worked examples on both sides, because the line is not "does it touch owner
  data":

  | Migration | Kind | Why |
  |---|---|---|
  | `008` skill rename | structural | a stale skill folder beside the new one leaves two skills answering one name |
  | `009` biometric namespace | structural | it MOVES owner data, and the new pipeline reads only the new location — half-moved means reading the wrong place |
  | `002` `Family` column | structural | a schema column `/ztn:process` branches on; conservative on schema, by default |
  | `018` roles hand-off | heal | it also moves owner data, but nothing reads the old location — un-run means invisible, not wrong |
  | `007` manifest retrofit | heal | historical data is repaired or it is not; the engine reads it either way |
  | `016`, `004`, `005`, `015` | heal | they only print |

  The distinction is not stylistic. A repair of historical data used to abort
  the whole update and stay unrecorded, so every future update re-ran it and
  re-aborted at the same point; a friend's clone was unable to update for weeks
  because of one. **A repair of old data must never be able to block a future
  engine update** — and neither may a notice.

  A detection-only migration still exits 0 and prints its recovery command to
  stderr, which `/ztn:update` surfaces in its Post-update recovery list. It must
  NOT coerce a failed detector run into a false "all clear" — if the detector
  produces no valid output, say so and point to a manual check.

- **The ledger, not a name list.** `scripts/run_migrations.py` runs the chain and
  records one JSONL line per attempt in `.engine-migrations.jsonl` — name, kind,
  rc, outcome, timestamp, note. A clone carrying the older flat
  `.engine-migrations-applied` has it folded in automatically on first read.
  Never write either file from a migration; the runner owns them.

- **Cross-platform — Windows + macOS + Linux (HARD RULE).** A migration runs on
  EVERY friend's machine, so it MUST work on all three. macOS ships **bash 3.2**
  (no `mapfile`/`readarray`/`declare -A`/`${x^^}`); Windows runs Git Bash. Use
  `python3` for logic; portable commands only (no `md5`/`md5sum` split, use
  `sed -i.bak` not `sed -i`/`sed -i ''`, no `readlink -f`); resolve paths from
  `BASH_SOURCE`/repo-root (never hardcode `/` or `C:\`); invoke helpers via
  `bash`/`python3` (no exec-bit reliance). `.sh` stays LF (`.gitattributes`
  enforces it — a CRLF migration breaks bash on a Windows checkout). Verify with
  `/bin/bash -n <migration>.sh` on macOS before shipping. Full rule:
  `_system/docs/ENGINE_DOCTRINE.md §3.9`.

## When to author one

Whenever an engine change requires friends to do something other than
"pull the new files". Examples:

- A skill is renamed (need to remove the old `~/.claude/skills/foo`
  symlink before re-installing).
- A state file changes shape (new column, renamed field).
- A path moves under `_system/` (needs `git mv` mirrored locally).

## When NOT to author one

- New skill / new doc / additive change — `sync_engine.sh` already
  pulls the new file in. No migration needed.
- Internal refactor of an engine script that doesn't change its
  contract — no migration needed.

## Template

```bash
#!/usr/bin/env bash
# migration-kind: structural
# 001-example-rename.sh
# Brief: explain the breaking change in one sentence.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ... idempotent migration steps here ...

echo "[migration 001] done"
```
