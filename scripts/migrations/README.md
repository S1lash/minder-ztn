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
- Keep migrations small and reversible. If a change cannot be migrated
  automatically, the script should print clear manual steps and exit
  non-zero so the user notices.

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
