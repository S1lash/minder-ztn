---
name: ztn:update
description: >
  Pull engine updates from `upstream` (the public skeleton repo) into
  the owner's clone — interactive wrapper around `scripts/sync_engine.sh`.
  Reads `.engine-manifest.yml`, fetches upstream, computes VERSION
  delta, lists pending migrations from `scripts/migrations/`, detects
  local divergence on engine paths (where the owner customised), shows
  a per-path diff preview, asks for confirmation before overwriting,
  applies migrations in order, and surfaces follow-ups (re-run
  install.sh, regen constitution view). Never touches `template:` or
  data paths. Default UX for non-technical owners; bash script remains
  for CI / power users.
disable-model-invocation: false
---

# /ztn:update — Pull engine updates from upstream

Engine = code, prompts, scripts, spec docs. Friend's clone owns engine
paths in their `main`, but they flow upstream → friend via this skill.
Data (records, knowledge, registries, constitution principles) is never
touched.

`scripts/sync_engine.sh` does the same thing without prompts — use that
in CI or when scripting. This skill is the interactive default.

**Documentation convention:** при любых edits этого SKILL соблюдай
`_system/docs/CONVENTIONS.md`.

## Arguments

`$ARGUMENTS`:
- `--remote <name>` — default `upstream`
- `--branch <name>` — default `main`
- `--dry-run` — show plan, apply nothing
- `--yes` — skip per-path confirmations (still aborts on dirty engine
  paths or unknown migrations)
- `--no-migrations` — apply file overwrites only, skip running scripts
  under `scripts/migrations/`

## Preconditions

1. Repo root has `.engine-manifest.yml` and `integrations/VERSION`.
2. No producer-skill lock present (process / lint / maintain / resolve
   / save / sync-data). Abort if any.
3. Working tree clean on engine paths (script-style requirement —
   uncommitted engine edits would be lost).
4. `upstream` remote configured. If missing — offer to add it
   interactively:
   ```
   No `upstream` remote. Add it now? Default URL:
     https://github.com/S1lash/minder-ztn.git
   [y] add this URL   [u] enter custom URL   [n] abort
   ```

## Pipeline

### Step 1 — Fetch upstream

```
git fetch <remote> <branch>
```

### Step 2 — VERSION diff

Read `integrations/VERSION` from `HEAD` and from `<remote>/<branch>`.

| Local | Upstream | Action |
|---|---|---|
| same | same | print «engine already current», exit 0 |
| local > upstream | (impossible in friend clone) | warn, ask explicit confirm to proceed |
| local < upstream | upstream ahead | proceed |

### Step 3 — Migration inventory

List `scripts/migrations/*.sh` (and `*.py`) on `<remote>/<branch>` not
present locally — those between local VERSION and upstream VERSION are
candidates. Read each migration's first 30 lines (header comment) to
extract the human-readable summary.

Filter against `.engine-migrations-applied` marker — already-applied
migrations are skipped.

Render:
```
Engine update: 0.1.0 → 0.3.0

Pending migrations:
  • 0001-rename-state-files.sh
      Renames _system/state/CURRENT_CONTEXT.md → CONTEXT.md.
      Auto-apply: yes (idempotent file rename).

  • 0002-add-projects-frontmatter-field.py
      Adds `priority:` field to PROJECTS.md rows where missing.
      Auto-apply: yes (additive only).

[y] proceed with full update   [m] migrations only   [f] file copy only
[d] show full migration scripts   [n] abort
```

### Step 4 — Local divergence detection

For each path in `.engine-manifest.yml` `engine:` section, compute
`git diff --name-only HEAD <remote>/<branch> -- <path>`. Cross-check
against owner's local commits touching that path
(`git log <merge-base>..HEAD -- <path>`).

Three sub-cases per path:

| Local commits touch path | Upstream changed path | Meaning | Default |
|---|---|---|---|
| no | no | unchanged | skip silently |
| no | yes | clean upstream update | overwrite |
| yes | no | local-only customisation | keep local, no action |
| yes | yes | **DIVERGENCE** | ask owner |

For divergence cases — render per-path:
```
DIVERGENCE: integrations/claude-code/skills/ztn-process/SKILL.md
  Local commits:    2 (last: «tweak process step 4 wording»)
  Upstream commits: 5 (since 0.1.0)
  Diff stat (upstream vs local):  +47 -12

  [o] overwrite with upstream  (lose local edits)
  [k] keep local                (skip this file in update)
  [m] open merge tool           (manual three-way)
  [d] show full diff
```

If no `--yes`, owner answers each. With `--yes`, divergence files default
to `[k] keep local` (safe default — never silently lose work).

### Step 5 — Apply file overwrites

For each path marked overwrite:
```
git checkout <remote>/<branch> -- <path>
```

For each path marked keep — leave local copy.

For each path absent upstream (deleted in upstream) — leave local copy
and note «engine path removed upstream — review and delete locally if
appropriate».

### Step 6 — Apply migrations

If `--no-migrations` — skip.

Otherwise, run each pending migration in lexical order:
```
bash scripts/migrations/<name>.sh    # or python3 for .py
```

Append name to `.engine-migrations-applied` on success.

If a migration fails:
- Stop the chain.
- Print: «migration `<name>` failed. Engine files already overwritten;
  partial state. Inspect, fix, then re-run `/ztn:update --no-migrations`
  for now and resolve manually.»
- Exit non-zero.

### Step 7 — Follow-up detection

Inspect what changed:

| Pattern in changed files | Recommendation |
|---|---|
| `integrations/claude-code/{rules,commands,skills}/**` changed | «Re-run `./integrations/claude-code/install.sh` to refresh `~/.claude/` symlinks.» |
| Any file under `0_constitution/` engine paths or constitution tooling changed | «Run `/ztn:regen-constitution` to refresh views.» |
| `_system/scripts/**` changed | «Run tests: `pytest zettelkasten/_system/scripts/tests/`.» |
| `integrations/claude-code/scheduler-prompts/**` changed | «Re-paste updated prompt body into `/schedule` routine — Claude Code holds the prompt verbatim, so engine update does not propagate to running schedules automatically.» |

### Step 8 — Stage + propose commit

`git add` all overwritten paths + `.engine-migrations-applied` +
`integrations/VERSION` (if changed). Do NOT push — push is `/ztn:save`'s
job.

Render:
```
Engine updated locally.

Files:    <K> overwritten
Skipped:  <D> kept local (divergence)
Migrated: <M> migration(s) applied

Proposed commit:
  engine: update 0.1.0 → 0.3.0

  - <N> engine paths refreshed from upstream/main
  - migrations: 0001-rename-state-files, 0002-add-projects-frontmatter-field
  - kept local: integrations/claude-code/skills/ztn-process/SKILL.md

Follow-ups:
  • run ./integrations/claude-code/install.sh
  • run /ztn:regen-constitution
  • run pytest zettelkasten/_system/scripts/tests/

[y] commit now   [m] edit message   [s] stage only, I'll commit
[n] unstage and abort
```

After commit, suggest `/ztn:save` for push (skill itself never pushes).

## What this skill does NOT do

- **Touch data paths.** Records, knowledge notes, registries,
  constitution principles, SOUL/TASKS/CALENDAR/POSTS, `*.template.md` —
  all left alone.
- **Auto-resolve divergence.** Three-way merge of prompts is not safe;
  owner decides per file.
- **Push.** Hands off to `/ztn:save`.
- **Run install.sh / regen-constitution / tests automatically.**
  Suggests; owner runs explicitly.
- **Reset migrations marker.** If owner needs to re-run a migration,
  they edit `.engine-migrations-applied` manually — guarded territory.

## Idempotency

VERSION current and no pending migrations → no-op exit 0.
Re-run immediately after success → no-op.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| «engine paths dirty» | Uncommitted engine edits | `/ztn:save --include-engine`, or `git restore` engine paths |
| «migration failed» | Bug in migration script or unexpected local state | Inspect script, fix manually, mark applied |
| «remote not configured» | First-time use | Skill offers to add `upstream` interactively |
| «merge tool requested but `git mergetool` not configured» | No mergetool | Owner picks `o` or `k`; manual merge stays out of scope |
| Local VERSION ahead of upstream | Owner is the maintainer running this in the wrong repo | Skill warns, requires explicit confirm |

## Relationship to other skills

- `/ztn:sync-data` pulls **owner's data** from `origin` (multi-device).
- `/ztn:update` pulls **engine** from `upstream` (skeleton).
- `/ztn:save` commits + pushes whatever the owner currently has staged.

These three never run automatically from each other. Owner orchestrates.
