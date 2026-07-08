# Engine migrations

Migration scripts run by `scripts/sync_engine.sh` after a successful
fetch + checkout. One file per breaking engine change.

## Convention

- Filename: `NNN-short-slug.sh` (zero-padded order). NNN starts at `001`.
- Each script is idempotent. `sync_engine.sh` records applied
  migrations in `.engine-migrations-applied` at repo root and never
  re-runs the same name.
- Scripts run from the repo root. They may rewrite files, move paths,
  or print upgrade instructions for the user. They MUST NOT touch
  user-data paths (records, knowledge, registries, SOUL, constitution).
- Keep migrations small and reversible.
- **Exit-code convention — hard-fail vs soft-nag.** `sync_engine.sh` runs
  each migration with `bash "$m"` under `set -euo pipefail` and records the
  applied marker *after* the call. So a non-zero exit aborts the whole
  `/ztn:update`, leaves the migration unrecorded, and re-aborts on every
  future sync.
  - **Hard-fail (`exit 1`)** — only for a genuine tool-level failure that must
    stop the sync (a required helper missing, a retrofit that half-applied).
    `007`'s missing-script branch is the model.
  - **Soft-nag (`exit 0` + message to stderr)** — for a *detection-only*
    migration that cannot auto-fix because recovery needs the LLM pipeline or
    would touch owner-data. It detects the condition, prints the manual
    recovery command to stderr, and exits 0 so the sync completes and the
    migration is recorded. Owner runs the nudged pipeline command afterwards.
    `011`–`014` are the model. A soft-nag migration must NOT coerce a failed
    detector run into a false "all clear" — if the detector produces no valid
    output, say so and point to a manual check (still exit 0).
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
# 001-example-rename.sh
# Brief: explain the breaking change in one sentence.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# ... idempotent migration steps here ...

echo "[migration 001] done"
```
