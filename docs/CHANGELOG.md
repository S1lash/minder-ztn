# What's new

User-readable release notes. For the engineering log, see git history.

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
