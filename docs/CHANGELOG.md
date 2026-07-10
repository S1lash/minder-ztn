# What's new

User-readable release notes. For the engineering log, see git history.

## 0.45.1 — Seeded files can't silently drift (internal)

Nothing changes in how your Minder behaves — this hardens the machinery that
builds and ships releases, so a whole class of "your fresh clone was seeded
wrong" bugs is now impossible by construction rather than by luck.

- The three ways the engine seeds a starter file — rename-on-release, copy-on-
  first-run by a skill, and read-the-template-directly — used to be told apart by
  a filename coincidence (`.md` vs not). They are now **declared explicitly** and
  a release gate (`check_seed_contract.py`, run at release and in CI) refuses any
  release where a template would leak un-materialised, an owner's private tuning
  or `.local.yaml` override would leak upstream, or a file would be shipped twice
  and clobbered on update. If a future seed is mis-declared, the release fails
  loudly instead of shipping a broken skeleton.

## 0.45.0 — Minder now speaks the way you read

Everything Minder writes for you to read — lens observations, the questions it
asks you to resolve, and the update notes you are reading right now — is now
shaped to how you personally take in information, not a one-size-fits-all voice.

- **Lens observations read the way you do.** Every lens now aligns how it
  presents what it found to your presentation profile (your SOUL working style +
  your ai-interaction principles): conclusion first, your density, plain
  language. It only touches wording — the analysis, the findings, and the
  honesty never change, and it never softens a hard observation to read nicer.
  If your profile does not fit a given finding, the lens ignores it rather than
  forcing a smoother read.
- **The clarifications review meets you halfway.** When Minder asks you to
  resolve a batch of open questions, it now phrases them for how you read —
  same rigour, less friction.
- **Updates now tell you what you actually got.** `/ztn:update` closes with a
  short, personal digest of what the update gives you — new features written to
  make you want to try them, technical fixes kept plain, and you can ask for
  more detail on any point. It sells the real value and never hypes a marginal
  change.

## 0.44.0 — A weekly read on the opportunities you're not seeing

Minder gains a new lens that, once a week, shows you where your actual week
opened a door toward what you say you want — the leads, lucky connections, and
forks that are easy to miss while you are heads-down.

- **The `opportunity` lens runs every Friday.** It lines up what actually
  happened this week against your far-goals (your SOUL goals + constitution) and
  surfaces four things: new opportunities worth a look — each with a cheap
  one-week test, so "new" never means "new rabbit hole"; a weak-tie connection
  that just entered your orbit; what changed in the doors already open (advanced,
  decayed, or closed — a short delta, not a wall of notes); and the occasional
  fork worth choosing deliberately. It is informational — it surfaces, you
  decide. Every item reads cold, in plain language, so you do not need to
  remember the backstory. See this week's read now →
  `/ztn:agent-lens --lens opportunity`.

## 0.43.0 — The cognitive-model hub works for everyone, by default

Minder now learns how you think out of the box, and every new friend gets the
cognitive-model hub instead of an empty page.

- **The `cognitive-model` lens is on by default.** It used to ship disabled
  (`status: draft`), so unless you knew to flip it on, your cognitive-model hub
  stayed blank forever. Now it runs every other Monday out of the box: it reads
  your own reflections and proposes "you seem to want X" to a review buffer you
  control — it never changes your constitution on its own, which is why it is
  safe to run by default. To see your hub fill now, run
  `/ztn:agent-lens --lens cognitive-model`. To turn it off, set its row to
  `draft` in `_system/registries/AGENT_LENSES.md` (see `docs/privacy.md` for
  exactly what it reads and produces).
- **Fresh installs get the cognitive-model hub.** The hub's seed template was
  never shipped, so a brand-new base could never build the hub at all. It now
  ships with every install; existing bases already received it via an earlier
  migration.
- **New lenses are active by default.** The platform posture is now "a lens is
  on unless there is an explicit reason to gate it" — the only gated lenses are
  the biometric ones, which need health-data you have to provision first.

## 0.42.0 — Aggregates never silently drop; broken notes self-repair

Three integrity fixes so the pipeline can no longer quietly do less than it
claims. Each ships with a migration that DETECTS your existing backlog and points
you at a one-command recovery — the migrations never touch your data and never
fail the update.

- **Tasks & calendar no longer leak.** At scale, a processing tick could quietly
  stop aggregating every note's `- [ ]` tasks and `📅` events into `TASKS.md` /
  `CALENDAR.md`, so items accumulated un-aggregated. Now a deterministic
  reconciler (`reconcile_tasks.py` / `reconcile_calendar.py`) checks completeness
  every run, the nightly lint catches any gap, and `/ztn:process --reconcile-tasks`
  (or `--reconcile-calendar`) recovers what was missed. Nothing was ever lost —
  the tasks live in your notes; they just weren't indexed.
- **Notes with a misplaced YAML fence self-repair.** A note whose
  `## Evidence Trail` heading landed inside the frontmatter fence became
  unparseable to the whole system. The producer now structurally prevents it, and
  `/ztn:lint` deterministically moves the fence back (the note's body is preserved,
  never deleted).
- **Hub synthesis stops being overwritten.** A hub's "current understanding"
  section was being wholesale-rewritten from a single batch's view, discarding
  cross-batch synthesis. It's now updated additively; a from-scratch re-synthesis
  only happens through the existing owner-reviewed staleness path.

After `/ztn:update`, if a migration reports a backlog: run the command it prints
(`/ztn:process --reconcile-tasks`, `/ztn:lint`, or `/ztn:maintain`). If it reports
nothing, you're already clean.

## 0.41.2 — Non-ASCII filenames + no git improvisation, everywhere

Hardening pass so the two failure modes from 0.41.0/0.41.1 cannot recur through
any other path:

- **`/ztn:save`** now reads the working tree with `core.quotepath=false`, so
  the interactive "save my work" button stages Cyrillic (and any non-ASCII)
  filenames instead of failing the same way a scheduled tick did.
- **Scheduler prompts** now explicitly forbid every history-rewriting or
  work-discarding git command run by hand — `--amend`, `git reset` (any mode),
  `git checkout --force`, `git rebase`, and identity edits. Recovery is the
  helper scripts' job; a tick never does git surgery itself.

## 0.41.1 — Scheduled ticks commit non-ASCII (Cyrillic, etc.) filenames

A scheduled tick could process everything correctly and then fail at the very
last step — the single commit — if any changed file had a non-ASCII name (e.g.
a Russian-titled transcript). All processed records, notes, and people would be
stranded uncommitted.

Cause: `git status --porcelain` octal-escapes non-ASCII bytes by default, and
the staging helper passed those escaped strings straight to `git add`, which
never matched them. Fixed by reading paths with escaping disabled. Covered by a
regression test.

If a tick was failing this way, just re-run it after `/ztn:update` — no data was
lost (source transcripts stay in the inbox until a tick commits successfully).

## 0.41.0 — Scheduled ticks work on Windows clones

Scheduled runs discover the `/ztn:*` skills from `.claude/skills/<name>/SKILL.md`
in your clone. That layout was shipped as git symlinks — which **do not survive
a Windows clone** (`core.symlinks=false` turns each symlink into a text file, so
the skill folder vanishes). On such a clone every scheduled tick died at its
first step, and the agent could spiral into out-of-contract recovery.

### What you get

- **Cross-platform skills.** The skeleton now ships `.claude/skills/` as real
  files, not symlinks — they clone correctly on Windows, macOS, Linux, and in
  Cloud Routines. (The maintainer's own repo keeps symlinks for the dev loop;
  they are dereferenced to real files at release.)
- **Self-healing update.** `/ztn:update` now replaces a broken local
  `.claude/skills/` with the real-file layout.
- **A pre-flight guard.** Every tick verifies skills resolve before running and,
  if something is still wrong, ships a precise failure note instead of failing
  obscurely. Scheduler prompts also explicitly forbid rewriting commit identity
  (`git commit --amend` / `--reset-author`) — an "unverified" sandbox author is
  normal and never needs fixing.

### If a scheduled tick was already failing on Windows

An already-broken clone cannot self-heal on the first `/ztn:update` (the old
update path and a stale `.gitignore` block it). Run this once to repair and
push the fix so your Cloud Routines pick it up, then future updates self-heal:

```
git fetch upstream
rm -rf .claude/skills
git checkout upstream/main -- .gitignore .claude/skills
git add -A .gitignore .claude/skills
git commit -m "fix: cross-platform real-file skills layout"
git push
```

No personal data is affected — `.gitignore` and `.claude/skills/` hold only
engine files. If unsure, ask your Claude to run these for you.

## 0.40.0 — Scheduled processing self-drains a backlog

If your scheduler is off for a while, the inbox piles up. Previously the first
catch-up run tried to process the whole backlog at once — and on a cloud
schedule that single run could run past its time limit, get killed mid-way, and
strand its work (nothing saved, next run repeats the overload).

Now `/ztn:process` bounds how much it takes per run, so a backlog drains
steadily across successive runs instead of choking on one.

### What you get

- **A per-run transcript cap (default 12).** Each run processes the oldest
  transcripts up to the cap; the rest wait in the inbox and are picked up next
  run — nothing is lost, order is preserved. On a normal daily inflow the cap
  never binds.
- **Biometric days are never capped.** `metric-day` sources (Garmin, Oura,
  ActivityWatch, …) are deterministic and cheap — they always process in full,
  so no biometric gaps.
- **Manual escape hatch.** For a supervised local catch-up with no time
  pressure, `/ztn:process --limit all` drains the whole inbox in one run.
  `--limit N` sets a custom cap for a single run.

### Behaviour change

A bare `/ztn:process` now processes at most 12 transcripts per run (was:
unbounded). Pass `--limit all` to restore the old drain-everything behaviour
for a single run. Scheduled ticks need no change — they pick up the default
automatically.

## 0.39.0 — A visible model of how you think

The `cognitive-model` lens (0.38.0) proposed «you seem to want X» one candidate
at a time. Now those patterns have a **home you can see**: a single hub —
*«how you think, as Minder sees it»* — with one row per cognitive /
communication axis (how you structure thought, what evidence convinces you, what
feedback lands, how you want directness, how context should carry across
sessions, …), each showing what's understood, how confidently, and the
principle + the verbatim quote it rests on.

### What you get

- **The hub** at `5_meta/mocs/hub-cognitive-model.md` — a maintained map of the
  model across the cognitive axes, updated automatically by `/ztn:maintain`. The
  «portrait» at the top is yours to write; the table below is auto-rendered —
  don't hand-edit it. Blank/thin axes show the lens what to look at next.
- **Source quotes on learned principles.** A principle promoted from a reflection
  can carry the verbatim quote that grounds it (`source_quote:`) — so «why does
  Minder believe this about me?» is always answerable, and a future
  «Your Mind» screen can render principle + quote.
- **A nightly integrity check** keeps the axis tags honest (valid axis, no
  duplicates, sensitivity coherence) and surfaces issues for your review — it
  never edits your constitution on its own.

### To opt in / out

Nothing to do. The hub fills only from principles you've tagged and from the
`cognitive-model` lens — which still ships **OFF** (enable it deliberately in
`AGENT_LENSES.md`, same as before). With the lens off and no tagged principles,
the hub simply stays blank.

### Backward compatibility

Additive — nothing breaks. `cognitive_axes:` and `source_quote:` are optional
principle fields. A one-time migration (`010-cognitive-model-hub-seed.sh`, run
automatically on `/ztn:update`) creates the empty hub for existing installs; the
next `/ztn:maintain` fills it.

### For maintainers

New engine pieces: `render_cognitive_model_hub.py` (deterministic hub renderer,
`/ztn:maintain` Step 7.9), `lint_cognitive_axes.py` (lint Scan F.8), the axis SoT
block in `lenses/cognitive-model/prompt.md` (the single source for the axis set),
and the `source_quote`/`cognitive_axes` fields in the principle schema. The hub
is a pure projection of the constitution — it holds no truth of its own.

## 0.38.0 — The assistant learns how to talk to you

Two layers, plus a way the system keeps learning your style — without becoming
a yes-man.

### What changed

- **A communication baseline, loaded by default.** The assistant now answers
  you conclusion-first (the point before the play-by-play), leads with a ready
  result instead of an options menu, structures for scanning, cuts fluff — and
  stays critical: no flattery, it pushes back with reasons. This is the
  universal floor; your personal calibration layers on top.
- **Your own presentation preferences.** Put how you like praise and criticism
  in your `SOUL.md → ## Context for Agents`; put your recipe for long-form pieces
  (reports, audiobooks, debriefs) in its own `_system/long-form-playbook.md`
  (loaded on demand, never for normal answers). Both ship as templates with
  filled examples to copy.
- **A lens that learns your style from your reflections — opt-in, off by
  default.** A new `cognitive-model` lens can read your own voice-notes and
  reflections and propose "you seem to want X" as principles for you to approve
  or ignore. It ships OFF — enable it deliberately by setting its row to
  `active` in `AGENT_LENSES.md`. It never changes anything on its own:
  proposals land in your review queue, only highly-confident ones append
  without a click (tunable), and promotion into your constitution always needs
  your approval. See `docs/privacy.md` for exactly what it reads and produces.

### Why
The more the assistant adapts to how you think, the bigger the risk it just
tells you what you want to hear. The baseline's "no sycophancy" rule and the
lens's "don't mine for what comforts you" guard are deliberate: it learns your
thinking, it does not become your echo.

## 0.35.0 — Content becomes a living shelf, not a cold backlog

The content pipeline is rebuilt to be push-based and incremental like the rest of
the system, instead of one heavy session you have to start cold.

### What changed

- **`/ztn:check-content` → `/ztn:content`.** Three modes: default shows status
  from the new content map; `--draft <topic>` drafts one post on demand;
  `--maintain` is the scheduled draft-maintainer that keeps living drafts in
  `6_posts/drafts/` — creating, updating on new material, and archiving published
  ones, never rewriting a draft you've edited.
- **A weekly rhythm.** A new `content-synthesis` lens (Mondays) reads your whole
  content backlog from the outside, finds what's ripe and the cross-theme posts;
  the maintainer (Tuesdays) turns those into drafts. One autonomous run, a warm
  shelf of drafts waiting when you want them. Publishing stays your manual act.
- **Drafts are conceptual, in your language.** Each draft is the idea/argument, in
  your primary language (from SOUL) — platform and final language are your
  publish-time choices, not baked in.
- **Cleaner markup.** `content_type` drift is healed automatically; `content_angle`
  is always a list. A new `CONTENT_MAP.md` view + a small ledger track it all.

### Action needed

If you pinned the old `/ztn:check-content` command, switch to `/ztn:content`.
Migration `008` cleans up the old skill folder and seeds the new ledger on
`/ztn:update`; re-run `install.sh` afterwards.

## 0.33.0 — PROJECTS.md is the single source of truth for projects

### What changed

The nightly project check (Scan A.8) now treats `PROJECTS.md` as the one
authoritative list of your projects. Before, a project hub page could
silently stand in for a registry entry — so a project that had a hub but
was never written into `PROJECTS.md` (registry drift) passed unnoticed.
A hub is a view over your notes, not proof that a project exists; only the
registry is.

Each `projects:` entry on a note is now resolved against the registry and
gets a precise, actionable message instead of a generic "unknown":

- **registered project** → fine (with or without a hub yet);
- **a trajectory** used as a project → "use `tags: [trajectory/…]`";
- **a consolidated/retired ID** → "point at its successor";
- **a hub with no registry row** → "register it, or remove the hub";
- **a real typo** → "fix the slug or register it".

If `PROJECTS.md` is missing or empty (e.g. mid-setup), the check now stays
quiet instead of flagging every note — it has no source of truth to judge
against. Nothing to migrate; your existing notes are unaffected.

## 0.32.0 — Concept names kept verbatim + fewer false project warnings

### What changed

Two correctness fixes, nothing to migrate.

**Concept names that begin with a category-like word are no longer
mangled.** The engine used to strip a leading "type word" from concept
names — so `decision_making` silently became `making`, `value_chain`
became `chain`, and `skill_based_...` lost its `skill_`. That split one
concept into wrong pieces and quietly merged unrelated notes. The problem:
a bare name can't tell a redundant label (`skill_python`) from a compound
where the word belongs (`decision_making`), and guessing corrupts the very
thing the knowledge graph is built on — stable identity. So the engine now
keeps every concept name **exactly as written**. The "no type prefix in a
name" guideline is still honoured where it can be done safely — at
extraction, where the model knows the concept's type — never by a blind
rewrite. (A name that *is* nothing but a bare category word, like `theme`
or `skill` alone, is still dropped — that's too broad to be a concept.)

**The nightly check stopped false-alarming about real projects.** A record
tagged with a project that is registered in `PROJECTS.md` but doesn't have a
hub page yet was wrongly flagged as an "unknown project" every night
(hub pages only appear once a topic accumulates enough notes). The check
now treats a project as valid if it's in `PROJECTS.md` **or** has a hub —
so registered-but-young projects stop generating noise.

## 0.31.0 — Windows-safe filenames

### What changed

Some recorder tools — Plaud in particular — name their export folders
with ISO timestamps like `2026-04-29T14:09:30Z`. Colons are illegal in
file names on Windows, so such a folder couldn't be created in your
inbox on a Windows machine, and pulling it from another device (a Mac
or a phone) broke `git checkout` on the Windows clone.

The engine now keeps every new name Windows-safe automatically:

- **`/ztn:process`** renames non-portable inbox items before processing
  (`2026-04-29T14:09:30Z` → `2026-04-29T14-09-30Z`), so every link the
  engine writes is born with the safe name — nothing ever breaks.
- **`/ztn:save`** does the same rename before committing, so a raw inbox
  drop from one device never breaks checkout on your Windows device.
- **`/ztn:lint`** backstops both nightly.

Nothing to migrate and nothing to do by hand: your existing processed
files keep their names (old colon-named folders remain readable
forever), only new arrivals are normalised. Windows users can now
onboard without workarounds.

## 0.30.0 — `describe-me` is a first-class source

### What changed

Self-descriptions now have their own inbox: `_sources/inbox/describe-me/`
(previously a hidden subfolder under `crafted/` that `/ztn:process` skipped).

- **Drop identity material there anytime** — profile updates, "how I think"
  notes, AI-generated self-portraits. `/ztn:process` picks them up as
  regular content and they become knowledge notes like everything else.
- **`/ztn:bootstrap` still reads it first** as the primary seed for SOUL.md
  during onboarding; files it consumes are moved to
  `_sources/processed/describe-me/` so nothing is ingested twice.
- **`PROFILE.template.md` stays put** — files named `*.template.md` are now
  excluded from processing engine-wide, in every source. Templates are
  seed material, not content.

Migration `006-describe-me-top-level-source.sh` runs automatically on
`/ztn:update`: it moves the old `crafted/describe-me/` folders (inbox and
processed sides) to the new location and updates your SOURCES.md registry.

## 0.29.0 — `/ztn:recap` can save verbatim artifacts to `crafted/`

### What changed

`/ztn:recap` is now adaptive. Besides the usual session *summary* into
`_sources/inbox/claude-sessions/`, it can also save a **verbatim
artifact** — a self-contained piece you'll reuse as-is (a toast, speech,
letter, post, proposal, spec) — into `_sources/inbox/crafted/`, with the
exact wording preserved.

Three modes, never forced on you:

- **recap** (default) — summary only. If a finished piece is detected,
  the skill *proposes* saving it; it never fabricates or drops one
  silently.
- **recap + crafted** (`--crafted`, "save the original too") — summary
  plus the verbatim artifact.
- **crafted-only** (`--crafted-only`, "just save the original") — the
  artifact alone, no recap.

When both are written they carry a **bidirectional link** (recap
`Crafted artifacts:` ↔ crafted `Source session:`), so `/ztn:process`
connects them even if they land in different batches. Verbatim text
lives only in `crafted/`; the recap stays a summary.

## 0.27.0 — Source naming tolerance (universal)

### What changed

The `/ztn:process` inbox scanner now treats folder names and contained
filenames as **best-effort hints**, not contracts. Across every source-
type (`plaud`, `garmin`, `claude-sessions`, manual drop-ins, …) the
processor accepts whatever the owner or producer drops in:

- Folder names that don't match the ISO / date / topic patterns fall
  back to file mtime silently — no CLARIFICATION.
- A subfolder containing a single `*.md` with a non-canonical filename
  is taken as-is (applies to `dir-per-item` and the new third
  fallback step in `dir-with-summary`).
- CLARIFICATIONs are reserved for cases where the engine would
  otherwise have to guess at the cost of correctness: multiple `*.md`
  files in one subfolder with no canonical name, missing summary-
  delimiter inside a file actually named `transcript_with_summary.md`,
  or a parsed folder-date that contradicts mtime in a way mtime can't
  resolve.

This removes friction for owner-driven flows (ad-hoc capture, manual
folder creation, `/ztn-recap` exports across Claude Code versions that
produce non-canonical filenames like `TECH-RECAP.md`) without weakening
the producer-drift signal (the right place to catch a producer suddenly
emitting weird names is `/ztn:lint` heuristics on the source itself,
not the inbox scanner).

### Affected files

- `integrations/claude-code/skills/ztn-process/SKILL.md` — §2.1
  «Naming tolerance» blockquote + relaxed `dir-per-item` /
  `dir-with-summary` scan rules; §2.3 folder-name parsing drops the
  CLARIFICATION on legacy / free-form names.
- `zettelkasten/_system/registries/SOURCES.template.md` — new spec
  section «Naming tolerance (universal across all source-types)»;
  `dir-per-item` / `dir-with-summary` Layout descriptions extended.

### Compatibility

Backward-compatible relaxation. Strict-canonical-name producers
(`plaud`, `garmin`) continue to emit canonical names — no change to
producer output. Friends running older `/ztn:process` will keep
seeing CLARIFICATIONs on free-form folder names until they sync
this version via `/ztn:update`.

## 0.25.0 — Scheduler single-commit + Cloud Routines delivery

### What changed

The autonomous scheduler protocol was producing dozens of commits per
tick (one per phase the agent felt like grouping) and accumulating
stranded `claude/*` branches on origin in Cloud Routines setups.
Replaced the old per-step `/ztn:save --auto` model with a strict
single-commit + adaptive-delivery design:

- **One commit per tick, guaranteed.** `scripts/scheduler/stage.sh`
  is staging-only (idempotent, may be called any number of times
  during a tick); `scripts/scheduler/finalize-tick.sh <tag>` is the
  sole commit + delivery point. Engine paths are filtered out via
  `.engine-manifest.yml` + a small conservative-prefix list.
- **Two delivery modes auto-detected.** LOCAL (start branch = main):
  direct `git push origin main`. ROUTINES (start branch = sandbox
  ref like `claude/<random>`): push to sandbox, `gh pr create
  --base main --head <sandbox>`, `gh pr merge --squash
  --delete-branch`. Cloud Routines' git proxy refuses direct push
  to main; this routes around it.
- **MCP fallback for gh-less sandboxes.** Cloud Routines sandboxes
  typically don't ship `gh`. When `finalize-tick.sh` exits 2 with
  «gh CLI not found in PATH», the scheduler prompts have a strict
  Step 5b that routes the create + merge through the `github` MCP
  server. The only authorized non-script git/MCP path in the
  prompts.
- **Partial-tick fold recovery.** If a previous tick committed
  locally but never pushed, the next tick's `finalize-tick.sh`
  folds it into the current commit via `git reset --soft
  origin/main`. Refuses to touch non-scheduled commits ahead of
  origin/main (no force-push, ever).

### Required repo setting

Cloud Routines also refuses `git push origin --delete <branch>`, and
the github MCP server has no `delete_branch` tool. Sandbox-branch
cleanup is therefore delegated to GitHub's repo setting:

**Settings → General → Pull Requests → ☑ Automatically delete head
branches**

Enable this once per repository. Without it, every Routines tick
leaves a sandbox branch on origin.

`docs/onboarding.md` §9 calls this out for new setups.
`docs/scheduling.md` documents the full delivery model.

### Migration

`scripts/migrations/005-scheduler-pr-merge-delivery.sh` prints a
re-paste reminder when run after `/ztn:update`. After this engine
update:

1. Enable the «Auto-delete head branches» repo setting (above).
2. Re-paste the three updated prompt bodies from
   `integrations/claude-code/scheduler-prompts/` into your
   `/schedule` Routines.
3. (Optional one-time) Delete any pre-existing `claude/*` sandbox
   branches accumulated before this update:
   `git push origin --delete <branch>` from a local clone.

### Removed

- `scripts/scheduler/save.sh` — replaced by `stage.sh` +
  `finalize-tick.sh`.
- `scripts/scheduler/cleanup-sandbox.sh` — replaced by GitHub's
  built-in auto-delete on PR merge.

## 0.22.0 — Biometric pipeline (metric-day source family)

### What landed

A complete biometric ingestion + analysis pipeline running on top of the
existing /ztn:process → /ztn:maintain → /ztn:agent-lens stack:

- **Tier I** — Per-day deterministic pipeline. New `metric-day` source
  family on SOURCES.md. /ztn:process metric-day branch parses
  `_sources/inbox/garmin/<date>.md` (Garmin daily snapshot) into
  `_records/biometric/<date>.md` with rolling 28-day baselines (42 for
  chronic_load), σ-deviation flags, categorical event detection (HRV /
  training / ACWR / readiness transitions), and streak state machine.
  No LLM in this branch — pure Python (~100 ms per file).

- **Tier II** — Weekly correlation worker, runs from /ztn:maintain
  after-batch with weekly idempotency gate (`last_weekly_run.txt`).
  Phase 1: Pearson over biometric × biometric metric pairs at lags
  0–3, anomaly cluster detection. Phase 2: lexicon-based affect tag
  extraction over `_records/observations/` + `_records/meetings/` +
  point-biserial correlation against biometric metrics. Calibration
  drift detection vs expected fire-rates surfaces
  `biometric-threshold-drift` CLARIFICATIONs. Backfill mode on
  first run iterates completed ISO weeks chronologically.

- **Tier III** — Four new agent-lenses ship under `status: draft`:
  - `biometric-anomaly-narrator` (daily) — narrates yesterday's
    biometric record when non-empty.
  - `biometric-cross-domain` (weekly thursday) — top 1–2 strongest
    cross-source findings from Tier II with cited journal evidence.
  - `training-load-trend` (weekly monday, conditional) —
    self-skips when `acute_load == 0` for 14 days.
  - `biometric-life-synthesis` (weekly monday, flagship) —
    multi-source synthesis bridging biometric pattern with life
    narrative; emits Memory note when strong tier reached.

- **Patches** to four existing lenses (`stated-vs-lived`,
  `energy-pattern`, `weekly-insights`, `global-navigator`) so they
  read biometric records / Tier II output / new biometric lens runs.

- **Ambient layer** — `## Health Snapshot` block (≤15 lines,
  life-connection focused) injected into `CURRENT_CONTEXT.md` after
  the Focus block, before Active Threads.

### Migration

`scripts/migrations/002-sources-family-column.sh` adds the `Family`
column to existing SOURCES.md; existing rows populate as `transcript`.
Idempotent — safe to re-run.

### Activation

The pipeline lies dormant until you wire a biometric source:

```
/ztn:source-add garmin --family metric-day
```

Then drop daily Garmin snapshots into `_sources/inbox/garmin/<date>.md`
(your collector's responsibility). After ≥14 days of records, Tier II
worker activates. Activate biometric lenses by flipping
`status: draft` → `active` in `AGENT_LENSES.md`.

### Notes for friends

- Universal: thresholds are σ-based (auto-adapt per-user baseline);
  affect lexicon ships RU+EN seeds, owner extends via
  `affect_lexicon.local.yaml`. Non-RU users in the cohort can drop RU
  entries via the local overlay.
- Privacy hard-set: `is_sensitive: true`, `audience_tags: []`,
  `origin: personal` on every biometric record + derived view.
  Owner-only by construction.
- Lens prompt patches reset precedent calibration in
  `lens-resolution-history.jsonl` for the four patched lenses; first
  interactive resolve session post-update will recalibrate naturally.

## 0.21.0 — Skills work in cloud Routines + thin scheduler prompts

### Cloud Routines now discover ZTN skills

Cloud Claude Code Routines (the cron-like scheduler that runs an
autonomous agent against your repo) clone the repo fresh and look for
skills only at the canonical `.claude/skills/<name>/SKILL.md` path. ZTN
skills lived only at `integrations/claude-code/skills/`, so slash
invocations like `/ztn:process` and `/ztn:lint` were inert in
Routines — they fell back to a fragile pattern of "open the SKILL.md
yourself and execute its steps", which broke in different ways every
night.

This release commits `.claude/skills/ztn-*` symlinks at the repo root
that point into `integrations/claude-code/skills/<name>/`. Routines
now load all 15 ZTN skills automatically; slash invocations work
identically in cloud and local sessions. SKILL.md sources were
de-templatized in the same change (`{{MINDER_ZTN_BASE}}/...` →
`zettelkasten/...`) so paths resolve from the repo CWD without a
render step.

### Scheduler prompts shrank by 65%

The three scheduler prompts (`process-scheduled.md`,
`lint-nightly.md`, `agent-lens-nightly.md`) were rewritten to ~92
lines each (down from ~250). They now invoke `/ztn:process` /
`/ztn:lint` / `/ztn:agent-lens --all-due` directly via slash and
delegate shared plumbing to five new bash helpers under
`scripts/scheduler/`:

- `pin-main.sh` — fetch + checkout fresh `origin/main` (with safe
  rebase if local commits exist), capture the sandbox branch
  for cleanup, and GC any leftover sandbox branches from prior ticks
- `lock-check.sh` — abort if any cross-skill pipeline lock is recent
  (<2h); auto-clean stale (>2h) locks
- `save.sh` — engine-aware commit + push (renamed from the old
  `scripts/scheduler-fallback-save.sh`)
- `cleanup-sandbox.sh` — first-attempt delete of the sandbox branch
  the Routine cloned onto, with diagnostic surfacing when the
  platform holds the active session ref
- `ship-failure-note.sh` — append a one-line cause to
  CLARIFICATIONS.md and ship via save.sh, so failures surface in
  the next interactive resolve session

### Scheduler-tagged commit messages

`/ztn:save` now accepts a `--tag <text>` flag that prefixes the commit
message before the `[scheduled]` suffix. Each scheduler prompt passes
its tick name (`--tag scheduler/process`, `--tag scheduler/lint`,
`--tag scheduler/agent-lens`) so every autonomous commit makes the
producing tick visible at a glance:

```
scheduler/lint: routine save: 25 file(s) across 6 areas [scheduled]
scheduler/process: process batch: 8 sources → 9 records + 6 notes [scheduled]
```

Idempotent: if the message already starts with the tag, no second
prefix is added. The bash fallback `save.sh` produces the same shape
when invoked with `"scheduler/<tick>: ..."` style messages.

### Sandbox branch cleanup

When a Routine clones the repo onto its session branch (e.g.
`claude/admiring-shannon-ETCE3`), the platform holds the branch ref
for the duration of the run, so end-of-tick `git push --delete` is
often rejected. Pin-main now runs a GC pass at the start of every
tick that lists `claude/*` branches on origin (excluding the current
session's own ref) and deletes any leftover from prior ticks. Net
effect: the previous tick's sandbox branch goes away when the next
tick fires, instead of accumulating on origin indefinitely.

### After `/ztn:update`

No manual migration required for friends pulling this release —
`git pull` brings the new `.claude/skills/` symlinks; re-running
`./integrations/claude-code/install.sh` (already part of the
`/ztn:update` follow-up reminder) refreshes user-level symlinks.
If you have scheduled prompts pasted into Claude Code's `/schedule`,
re-paste the bodies of the three updated files in
`integrations/claude-code/scheduler-prompts/` — `/schedule` holds
prompt text verbatim and does not auto-update on `/ztn:update`.

## 0.20.0 — Lens output upgraded for Obsidian + in-vault graph reset

### In-vault Reset Graph button

`minder-ztn.md` now ships a `## ⚙️ Maintenance` section with a
DataviewJS button: «🔄 Reset graph view to defaults». One click
restores `graph.json` (color groups, forces, default filter) from
the engine snapshot at `.obsidian/graph-defaults.json`, with an
auto-backup of your current state. No CLI needed for the common
recovery case after Obsidian wipes color groups during filter
tweaks. Requires Dataview JS Queries enabled (already part of the
Dataview setup checklist).

The CLI path stays available for power users:
`./integrations/obsidian/seed.sh --reset-graph`.

### Lens output upgraded for Obsidian


Lens output files now carry a human-readable `title:` and reference
cited files via `[[wikilinks]]` instead of paths in backticks. Two
practical effects:

- **Lens nodes in the graph have real names.** Instead of seeing
  `2026-05-04` as a node label, you see «🔭 stalled-thread —
  2026-05-04» (with Front Matter Title plugin enabled). Files become
  scannable in the file tree, Quick Switcher, and graph view.
- **Lens nodes connect to the records they observe.** Each Evidence
  bullet is now `[[basename]]` so Obsidian draws an edge between the
  lens output and the record / hub / principle it cites. The
  `🔭 Lens observations` graph preset becomes meaningful — you see
  «what the AI noticed about which records», not a cluster of
  disconnected dates.

**To opt in:**

1. Run `/ztn:update` (or `scripts/sync_engine.sh`) — pulls the new
   `_frame.md` Stage 2 schema.
2. The next `/ztn:agent-lens` run emits the new format automatically.
   No action needed for friends without prior lens output.

**For pre-existing lens output:** if you happen to have lens files
from before this version (rare — most friends adopt lenses fresh),
they remain valid in their original form per the grandfathering
clause in `_frame.md` Stage 3. The validator never rewrites files
already on disk. New emissions from this version forward use the new
format.

**For maintainers:** `_frame.md` Stage 2 prompt schema and Stage 3
validator updated in lockstep. Wikilink basename resolution replaces
ZTN-path resolution. Legacy outputs grandfathered.

---

## 0.19.0 — Obsidian vault integration

The first proper UI for ZTN. Until now you read your records as files
and your registries as markdown tables; now there's a vault config
that opens cleanly in Obsidian, a dashboard, graph presets, hotkeys,
bookmarks, and visual cues per note type.

**What you get after `/ztn:update` + re-running `install.sh`:**

- **`minder-ztn.md` dashboard** at the vault root. Live blocks (powered by
  Dataview) for recent meetings, observations, active projects, people,
  open tasks. Static links to Current Context, Open Threads,
  Clarifications, SOUL.
- **Bookmarks pane** (left sidebar, `Cmd+Shift+B`) — pre-pinned
  navigation: Now, Identity, Registries, Browse, Obsidian docs.
- **Graph view tuned for ZTN** — colour-coded by PARA layer (people
  orange, meetings green, observations teal, constitution purple, hubs
  gold, projects blue, archive grey). Engine internals and flat
  aggregator nodes (INDEX, registries) hidden by default.
- **6 graph presets** documented in `integrations/obsidian/views.md` —
  copy-paste filters for People web, Decision lineage, Project
  landscape, Hub network, Knowledge distillation, Sensitive zone.
- **Hotkeys** — `Cmd+Shift+G` graph, `Cmd+Shift+L` local graph,
  `Cmd+Shift+B` bookmarks, `Cmd+Shift+O` outline, `Cmd+Shift+K` tag
  pane, `Cmd+Shift+Y` insert template.
- **Visual cues** — coloured left border on the editor pane plus
  emoji prefix in tab headers and file explorer per note type
  (👤 person, 🤝 meeting, 👁 observation, ⚖️ axiom, 🧭 principle,
  📏 rule, 🌟 hub, 🚀 project).
- **Engine paths hidden** — `_system/state/`, `_system/scripts/`,
  `_system/docs/`, `_sources/processed/`, `*.template.md`,
  `integrations/`, `__pycache__/`, README files. Two layers: a CSS
  snippet hides them from the file tree, `userIgnoreFilters` hides
  them from search and graph.
- **Comprehensive guide** at `integrations/obsidian/guide.md` —
  hotkeys reference, daily/weekly/monthly recipes, frontmatter rules,
  reset-to-defaults procedure.

**To opt in:**

1. Run `/ztn:update` (or `scripts/sync_engine.sh`)
2. Run `./integrations/claude-code/install.sh` — it now seeds
   `<vault>/.obsidian/` and `<vault>/minder-ztn.md` if they don't exist.
3. Open Obsidian → "Open folder as vault" → select `zettelkasten/`
4. Install three community plugins (instructions print on first run):
   - **Dataview** by Michael Brenan — powers HOME's live blocks
   - **Tasks** by Clare Macrae — global task view across the vault
   - **Front Matter Title** by snezhig — shows `title:` from
     frontmatter instead of snake-case file IDs in graph, file tree,
     tab headers, Quick Switcher

**To opt out:** delete `<vault>/.obsidian/` and `<vault>/minder-ztn.md`. The
ZTN engine itself doesn't depend on Obsidian — skills work the same
whether you have the vault open or not.

**Backward compatibility:** purely additive. All earlier skills,
manifests, and engine internals unchanged.

**For maintainers:** new engine paths under `integrations/obsidian/`
ship via `release_engine.py`. The seeder is idempotent and never
overwrites a friend's live `.obsidian/` (only `--force` does, with
auto-backup). See `integrations/obsidian/README.md`.

---

## How to read this changelog

Each release has:

- **What you get** — concrete features after running `/ztn:update`
- **To opt in / out** — what you actively need to do
- **Backward compatibility** — whether anything broke
- **For maintainers** — engine-level notes (skip if you're a user)

Versions before 0.19.0 are not documented here in user-readable form;
see git log + integration commit messages for the engineering history.
