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
  for CI / power users. Closes with a short, personalized benefit-first
  digest — what the update actually delivers for THIS owner, aligned to
  how they read, honest about marginal / technical changes, with detail
  on request.
disable-model-invocation: false
---

# /ztn:update — Pull engine updates from upstream

Engine = code, prompts, scripts, spec docs. Friend's clone owns engine
paths in their `main`, but they flow upstream → friend via this skill.
Data (records, knowledge, registries, constitution principles) is never
touched.

`scripts/sync_engine.sh` does the same thing without prompts — use that
in CI or when scripting. This skill is the interactive default.

**Documentation convention:** on any edit to this SKILL, follow
`_system/docs/CONVENTIONS.md` — the file describes current behaviour,
no version / phase / rename-history narratives.

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
     https://github.com/<your-org>/minder-ztn.git
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

**`.claude/skills/` — pre-clean before checkout.** Upstream ships this path as
a real-file tree; a local clone may hold it as symlinks or, on a Windows clone
(`core.symlinks=false`), as text files masquerading as symlinks. A plain
`git checkout` then aborts on the file→dir type change. When `.claude/skills`
is among the overwrite paths, remove it first so the real-file tree lands
cleanly (it carries no owner data):
```
rm -rf .claude/skills
git checkout <remote>/<branch> -- .claude/skills
```

For each path marked keep — leave local copy.

For each path absent upstream (deleted in upstream) — leave local copy
and note «engine path removed upstream — review and delete locally if
appropriate».

### Step 6 — Apply migrations

If `--no-migrations` — skip.

Otherwise, run each pending migration in lexical order, **capturing its
combined stdout+stderr**:
```
out="$(bash scripts/migrations/<name>.sh 2>&1)"; rc=$?   # or python3 for .py
```

Append name to `.engine-migrations-applied` on success (`rc == 0`).

**Detection-only migrations (soft-nag) — MUST be surfaced, never let scroll past.**
A migration that exits 0 but prints recovery instructions (a `/ztn:...` command) is
NOT a failure — it detected a pre-existing backlog it cannot fix itself because
recovery needs the LLM pipeline (classification / repair), not a shell script.
Collect its captured message verbatim into a **Post-update recovery** list for
Step 8. `011`–`014` are exactly this kind: un-aggregated tasks (`011`) / events
(`012`), hub-index drift (`013`), misplaced note fences (`014`). If these are not
surfaced, the owner never runs the backfill and the recovered data stays hidden —
so surfacing them is load-bearing, not optional.

If a migration fails (`rc != 0`):
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
| A NEW file added under `integrations/claude-code/scheduler-prompts/**` (git status `A`) | «A new scheduled job shipped — set up a new `/schedule` routine for it (see `docs/scheduling.md` for the cron slot + prompt body). Nothing to re-paste; you don't have this routine yet.» |
| An EXISTING file under `integrations/claude-code/scheduler-prompts/**` changed (git status `M`) | «Re-paste the updated prompt body into the matching `/schedule` routine — Claude Code holds the prompt verbatim, so engine update does not propagate to running schedules automatically.» |

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

⚠ Post-update recovery — a migration detected a pre-existing backlog. Run these
  once to recover it (each command re-verifies itself when it finishes; if you
  defer, the nightly /ztn:lint keeps surfacing the same gap as a CLARIFICATION,
  so nothing is lost):
  • <verbatim recovery line captured from each soft-nag migration in Step 6, e.g.
    "011: 39 un-aggregated tasks → run /ztn:process --reconcile-tasks">
  (Omit this block entirely when no migration emitted a recovery nudge.)

[y] commit now   [m] edit message   [s] stage only, I'll commit
[n] unstage and abort
```

After commit, suggest `/ztn:save` for push (skill itself never pushes).

### Step 9 — What arrived for you (personalized benefit digest)

The final, human step. Everything above is plumbing; here the owner
should walk away knowing **what this update gives them** and wanting to
try what is new — not reading a changelog. Minder is already adopted —
this step does not sell the product, it sells the *value that just
landed*.

**When it runs:**
- No-op (already current, nothing applied) → skip entirely.
- `--dry-run` → render as a PREVIEW ("here is what you'd get if you
  update"), present-tense-conditional instead of past-tense.
- `--yes` / non-interactive → still print the digest; only the
  interactive "ask more" prompt is skipped.

**Source — what changed (in this order):**
1. `git show <remote>/<branch>:docs/CHANGELOG.md` — the user-readable
   release notes. Take every `## <version>` entry in the delta range
   (local VERSION < version ≤ upstream VERSION). This is the primary,
   already-benefit-oriented source. Read it from `<remote>/<branch>`,
   not the working copy, so it is correct even if CHANGELOG was
   kept-local at Step 4.
2. Migration summaries from Step 3 + recovery nudges from Step 6 —
   technical detail and one-time actions.
3. Changed engine paths from Step 4 — fallback when a version has no
   CHANGELOG entry (infer feature vs internal from the path).

**Who reads it — align + personalize (reuses the lens reader-alignment
contract).** Read whichever of these exist; a missing file is not an
error, skip it silently:
- `_system/docs/communication-baseline.md` — presentation floor
  (conclusion first, plain language, short, no filler, no flattery).
- `_system/SOUL.md` → "Working Style", "Context for Agents", and
  "Active Goals" / "Current Focus" — how THIS owner reads AND what they
  currently care about (for honest personalization).
- `_system/views/constitution-core.md` — the owner's ai-interaction /
  cognitive principles.

This calibrates PRESENTATION only — it never changes which items you
report or invents value that isn't in the changelog. If a file is
absent or its profile doesn't fit, ignore it and use the floor.

**Stance — sell the benefit, honestly:**
- **New capability / owner-facing feature** → lead with the benefit,
  not the mechanism: "what you can do now" and why it matters. Make it
  vivid enough to want to try, and give the one action that starts it
  (the enable / try command from the CHANGELOG entry). Personalize when
  there is a REAL link to the owner's focus or goals ("you're deep in X
  right now — this is exactly about that") — never force a link that
  isn't there.
- **Technical / internal** (fix, refactor, perf, schema, plumbing) → no
  hype. One plain line on what it means for the owner *if* there is
  owner-relevant meaning ("faster", "more reliable", "no longer loses
  X"); if there is none, fold the rest into a single terse "under the
  hood" line, or omit. Depends on the update.
- **Recovery actions** (soft-nag migrations, Step 6) → frame as "do
  this once to reclaim X" — benefit-first but honest that it's a
  one-time chore.

**Honesty guard — load-bearing (this is `principle-ai-interaction-012`,
not marketing).** Sell REAL value vividly; never manufacture excitement
for a marginal change, never oversell a benefit that isn't there. A
minor update is stated as minor. Personalization is a true link to the
owner's context, never flattery or an echo of what's pleasant to hear.
Inspiration rides on truth — the moment it doesn't, it costs the
owner's trust in every future digest, and the whole digest stops being
read.

**Shape — rails, not a template.** Short by default: a one-line
headline of the release's essence, then a benefit blurb per feature
(most-valuable first), then at most one "under the hood" line for the
technical remainder. Write the digest in the owner's language — match
how their notes and SOUL read; a friend's clone writes in theirs (the
illustration below is in English as the engine-doc default). Plain
language, no jargon — a non-technical friend must get it. End with an
open door: the owner can ask "tell me more about X" and this step
expands that one item (how it works / how to enable / a concrete
example), pulling from the CHANGELOG entry, the relevant skill doc, and
`docs/privacy.md` when the feature reads owner-data. Do not pre-dump the
detail — default short, depth on request.

The block below is an ILLUSTRATION of the stance, not a required
layout — adapt freely per update:

```
Update 0.42.0 → 0.43.0 — Minder now learns how you think, out of the box.

✨ New for you:
  • The cognitive-model lens is on by default. Your "how I think" hub
    used to stay blank until you switched it on yourself. Now it reads
    your reflections every other week and proposes "you seem to want X"
    — into a buffer you control (it never edits your constitution on
    its own). Want to see it fill in now → `/ztn:agent-lens --lens
    cognitive-model`.

🔧 Under the hood: new lenses are active by default (except the
   biometric ones — those need your health data first).

Ask for more detail on any point?
```

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
