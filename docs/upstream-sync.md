# Pulling engine updates from upstream

Your data stays yours. Engine updates flow upstream → your repo.
Two entry points:

- **`/ztn:update`** — interactive Claude skill (recommended default).
  Detects local engine customisations, asks per-file before overwriting,
  applies migrations in order, surfaces follow-ups (re-run install.sh,
  regen constitution view, run tests).
- **`scripts/sync_engine.sh`** — non-interactive shell script (CI /
  power users). Same manifest, no prompts. See «Routine sync (script)»
  below.

## One-time setup

```bash
git remote add upstream https://github.com/<maintainer>/minder-ztn.git
```

Replace `<maintainer>/minder-ztn` with the actual upstream URL — the
repo you cloned the template from.

## Routine sync (skill — recommended)

In a Claude Code session:

```
/ztn:update
```

The skill walks you through VERSION delta, pending migrations,
divergence detection (per-file ask if you customised an engine path
locally), and proposes a commit. It does not push — run `/ztn:save`
afterwards.

## Routine sync (script — CI / power users)

```bash
scripts/sync_engine.sh           # fetch + apply
scripts/sync_engine.sh --dry-run # preview changes only
```

What the script does:

1. `git fetch upstream main`.
2. Reads `.engine-manifest.yml`. For each `engine:` path, runs
   `git checkout upstream/main -- <path>` to overwrite local engine
   files.
3. Skips `template:` paths — those seeded once at clone time and are
   now your data (e.g. your `SOUL.md`, your `PEOPLE.md`).
4. Runs any pending migrations under `scripts/migrations/`. The
   marker file `.engine-migrations-applied` records which scripts
   already ran (commit it).
5. Prints a recap.

If you have local changes inside any engine path, the script aborts
with `error: engine paths have uncommitted changes`. Commit or stash
first, then re-run.

## After a sync

- Re-install the Claude Code symlinks (some skills may have been
  renamed): `./integrations/claude-code/install.sh`.
- Run the test suite: `pytest zettelkasten/_system/scripts/tests/`.
- Review the diff: `git status` then `git diff`.
- Commit the engine update: `git add -A && git commit -m "engine sync"`.

## Customizing engine behaviour

If you want to override an engine prompt or script for your instance,
**don't edit the engine path directly** — the next sync will overwrite
your change. Instead:

- For Claude rules / commands / skills: edit your local
  `~/.claude/{rules,commands,skills}/` file after install. The
  installer respects existing files (it backs them up before
  symlinking, but you can replace the symlink with a real file).
- For system prompts that the engine reads from `_system/`: copy the
  engine file to a sibling path under `2_areas/personal/`, edit there,
  and update your `~/.claude/CLAUDE.md` to @-reference your version.
- For deeper changes you'd like everyone to benefit from: contribute
  upstream — see `CONTRIBUTING.md`.

## What is NOT pulled

`sync_engine.sh` deliberately leaves your data alone. It will never
touch:

- `_records/` — your meeting and observation logs.
- `_sources/` — your raw transcripts (inbox + processed).
- `1_projects/`, `2_areas/`, `3_resources/`, `4_archive/`,
  `6_posts/` — your knowledge notes (the PARA layout, except the
  README explainers).
- `0_constitution/{axiom,principle,rule}/` — your personal principles.
- `_system/SOUL.md`, `TASKS.md`, `CALENDAR.md`, `POSTS.md`, and the
  registries (`PEOPLE.md`, `PROJECTS.md`, `TAGS.md`, `SOURCES.md`).
- `_system/state/` and `_system/views/` — runtime state, regenerated
  by skills.

If you ever want to reset a `template:` file back to the upstream seed
(e.g. you blew up `SOUL.md`), do it manually:

```bash
git checkout upstream/main -- zettelkasten/_system/SOUL.template.md
mv zettelkasten/_system/SOUL.template.md zettelkasten/_system/SOUL.md
```
