# Onboarding — your first 30 minutes

After this guide you'll have:

- A vault opening cleanly in Obsidian (your daily UI) with a dashboard,
  graph view, hotkeys, bookmarks, and visual cues per note type.
- A populated `SOUL.md` (your identity, focus, working style) and
  registries (people, projects) seeded from your existing context.
- A clarifications queue you've walked through, resolving anything
  bootstrap was uncertain about.
- An autonomous nightly schedule (lint + agent-lens) catching drift
  while you sleep.

Two shell commands by hand: clone, then `install.sh`. Everything else
is Claude Code skills — `/ztn:bootstrap` first, then the daily flow.

If you only have 5 minutes: do steps 1–2, then `/ztn:bootstrap`.
You'll have a working system. The rest is enrichment.

## 1. Clone

```bash
gh repo create my-ztn --template <maintainer>/minder-ztn --private --clone
cd my-ztn
```

You'll need an `upstream` remote later to pull engine updates, but you
don't have to add it now — `/ztn:update` (step 8) will offer to add it
interactively the first time you run it. Manual:

```bash
git remote add upstream https://github.com/<maintainer>/minder-ztn.git
```

See `docs/upstream-sync.md` for the full engine-update flow.

> **Windows note.** Windows filesystems forbid colons (and a few other
> characters) in file names, and some recorder tools — Plaud in
> particular — name their export folders with ISO timestamps like
> `2026-04-29T14:09:30Z`. The engine handles this for you: any
> non-portable name dropped into `_sources/inbox/` is automatically
> renamed to a Windows-safe form (`2026-04-29T14-09-30Z`) when
> `/ztn:process` or `/ztn:save` runs, before any links to it are
> created. You don't need to rename anything by hand. If an export tool
> refuses to unpack a colon-named folder on Windows, let your unzip tool
> rename it however it wants — the engine normalises it on pickup.

## 2. Install the Claude Code integration

```bash
./integrations/claude-code/install.sh
```

Then add to `~/.claude/CLAUDE.md` if not already present:

```
## Constitution Capture — Global Hook
- @~/.claude/rules/constitution-capture.md

## Zettelkasten (ZTN) — Personal Knowledge Base
- @~/.claude/rules/ztn.md
```

## 3. (Optional but high-leverage) Drop your backlog and write a profile

If you have an existing corpus — voice-recorder transcripts, voice
notes, journal exports, past Zettelkasten dumps — copy them into the
matching subfolder of `_sources/inbox/`. The skeleton ships with a
universal starter set of sources defined in
`zettelkasten/_system/registries/SOURCES.md`:

- `plaud/` — Plaud voice-recorder transcripts (preferred summary +
  fallback transcript layout)
- `voice-notes/` — generic voice-note transcripts (any recorder)
- `claude-sessions/` — Claude Code session recaps captured via
  `/ztn-recap`
- `notes/` — plain Markdown notes you drop in by hand
- `crafted/` — hand-written long-form documents (also where
  `/ztn-recap --crafted` saves verbatim artifacts like toasts, letters,
  posts)

If your input does not match any of the starter sources, run
`/ztn:source-add` after install — it registers a new source-type
declaratively (one row in SOURCES.md + paired inbox/processed
folders). No code changes required.

If you want a high-quality identity seed, copy
`_sources/inbox/describe-me/PROFILE.template.md` to `PROFILE.md`
(same folder) and fill the copy — keep the template pristine. The
template suggests a workflow of pasting your transcripts into a
separate ChatGPT/Claude session and asking it to fill the template
for you.

Both steps are optional. If you skip them, bootstrap will detect that
and offer alternatives (interview-only path, or proceed with empty
backlog).

## 4. Run /ztn:bootstrap

In a Claude Code session opened in this repo:

```
/ztn:bootstrap
```

The skill is the actual orchestrator from here. It will:

- Run pre-flight checks (transcripts present? profile present? install
  sane?) and ask you what to do for any missing inputs.
- Scan your raw corpus in chunks via parallel subagents — extracting
  people, projects, hub candidates, principle candidates, open threads.
- Seed `SOUL.md`, `PEOPLE.md`, `PROJECTS.md`, `OPEN_THREADS.md`,
  `CURRENT_CONTEXT.md`, `INDEX.md` (surface catalog of knowledge +
  archive + constitution + hubs), and the principle-candidates buffer.
- Surface decisions to `_system/state/CLARIFICATIONS.md` for your
  review.
- Print an exit summary with explicit next steps and timing
  expectations.

Follow the instructions in the exit summary. Bootstrap is idempotent —
re-run anytime as your inputs evolve.

## 5. Review the clarifications queue

After bootstrap (and after every `/ztn:process`, `/ztn:lint`, or
`/ztn:maintain` run that surfaces items), run:

```
/ztn:resolve-clarifications
```

The skill pre-syncs against `origin` (so a queue resolved on another
device doesn't waste your attention), clusters open items by theme,
presents one round at a time with full meeting context + verbatim
quotes inline, pre-forms hypotheses against your constitution, and
applies confirmed resolutions in place. After your rounds it
auto-refreshes derived views (`/ztn:regen-constitution` if you
accepted principle candidates; `/ztn:maintain` if you touched
registries / hubs) and reminds you to run `/ztn:save`. Designed for
offline-style review — you do not need to recall meeting context from
memory; the skill reminds you.

## 6. Save your work — `/ztn:save`

When you are done for now, run:

```
/ztn:save
```

The skill stages your changes by category (records, knowledge,
registries, state), proposes a commit message, shows a summary, asks
for confirmation, then commits and pushes to `origin`. No git plumbing
required.

## 7. Pull data on a second device — `/ztn:sync-data`

If you work from more than one machine (laptop ↔ desktop ↔ phone via
git push), run before any work session:

```
/ztn:sync-data
```

This pulls the latest from your `origin` with rebase, refusing to
auto-merge conflicting prose and handing off to you if anything is
ambiguous. Recommended before `/ztn:process`, `/ztn:lint`, and
`/ztn:maintain` on any non-canonical device.

## 8. Pull engine updates — `/ztn:update`

When the upstream skeleton (the public `minder-ztn` repo) ships new
engine code, prompts, or migrations, pull them:

```
/ztn:update
```

Different from `sync-data`: this targets the `upstream` remote (engine
maintainer) instead of `origin` (your data backup). It detects local
customisations on engine files, asks per-file what to do on
divergence, and runs migrations in order. Your data is never touched.

## 9. (Optional) Schedule autonomous processing

Five ready-made scheduler prompts ship in
`integrations/claude-code/scheduler-prompts/` (canonical cadence table +
exact cron in `docs/scheduling.md`):

- `process-scheduled.md` — pre-sync → `/ztn:process` →
  `finalize-tick.sh scheduler/process`.
  Recommended cadence: 3× per day (e.g. cron `0 9,14,19 * * *`).
- `agent-lens-nightly.md` — pre-sync → `/ztn:agent-lens --all-due` →
  `finalize-tick.sh scheduler/agent-lens`. Recommended cadence: 1× per
  night (e.g. cron `0 3 * * *`). The skill filters lenses by per-lens
  cadence — nightly tick ≠ nightly lens runs.
- `lint-nightly.md` — pre-sync → `/ztn:lint` (which dispatches
  `/ztn:resolve-clarifications --auto-mode` inline via Step 7.5)
  → `finalize-tick.sh scheduler/lint`. Recommended cadence: ~2 h after
  agent-lens (e.g. cron `0 5 * * *`).
- `roles-nightly.md` — pre-sync → `/ztn:roles --all-due` →
  `finalize-tick.sh scheduler/roles`. Recommended cadence: daily, after
  lint (e.g. cron `30 6 * * *`). The skill filters roles by per-role
  cadence — daily tick ≠ daily role runs.
- `content-tick.md` — pre-sync → `/ztn:content --maintain` →
  finalize. Recommended cadence: weekly (e.g. cron `0 6 * * 2`, Tuesday).

The daily ticks are offset from each other (lens production isolated from
lint+resolve consumption, roles reasoning over a quiesced base) — see
`docs/scheduling.md` for the offset rationale. To create new lenses use
`/ztn:agent-lens-add`, new roles `/ztn:role:add` (both owner-driven, not
scheduled).

Paste each body into your scheduler of choice (Claude Code `/schedule`,
GitHub Actions cron, host crontab calling `claude` headless — any
runner that can launch a Claude Code session works).

## 10. (Optional) Tune how the assistant talks to you

After install the assistant already answers you **conclusion-first, no fluff,
and stays critical** by default — the shipped *communication baseline*. You
don't have to do anything for it.

To make it yours: put how you like praise and criticism in
`zettelkasten/_system/SOUL.md → ## Context for Agents`, and your recipe for long
pieces (reports, audiobooks, debriefs) in
`zettelkasten/_system/long-form-playbook.md` (loaded on demand, only for an
actual long-form piece). Both ship with filled examples.

The assistant also *learns* your style over time through the `cognitive-model`
lens, which is **on by default**. Every other Monday it reads your own
reflections and proposes "you seem to want X" for you to approve via `/ztn:lint`
— it only appends to your review buffer and never changes your constitution on
its own. It fills your cognitive-model hub
(`5_meta/mocs/hub-cognitive-model.md`). To populate it now instead of waiting for
the next cycle, run `/ztn:agent-lens --lens cognitive-model`. To turn it off, set
its row to `draft` in `_system/registries/AGENT_LENSES.md` (note: a later
`/ztn:update` re-applies the platform default of `active`). See `docs/privacy.md`
for exactly what it reads and produces.

### Required GitHub repo setting — auto-delete head branches

Before relying on Cloud Routines (Claude Code `/schedule`), enable:

**GitHub repo → Settings → General → Pull Requests → ☑ Automatically
delete head branches**

In Routines mode `finalize-tick.sh` pushes each tick's commit to a
sandbox branch (the Routines git proxy refuses direct push to `main`),
then creates and squash-merges a PR. The Routines proxy also refuses
`git push origin --delete <branch>`, so deleting the sandbox branch
after merge must happen on GitHub's side via this setting. Without it
on, every Routines tick leaves a leftover `claude/*` branch on origin
and they accumulate.

This is a one-time toggle per repository. Local cron / launchd setups
do not strictly need it (LOCAL delivery mode pushes directly to `main`
with no PR involved), but enabling it does no harm.

### Push credentials

The scheduler runs in a non-interactive environment, so it cannot
prompt for SSH passphrases or 2FA. Set up one of:

- **SSH key without passphrase** stored on the scheduler host, added
  to your GitHub account.
- **Personal Access Token** with `repo` scope, configured as the
  remote URL:
  `git remote set-url origin https://<TOKEN>@github.com/<you>/my-ztn.git`.
- **Platform-managed credentials** — Claude Code cloud `/schedule`
  inherits your authenticated GitHub session (no extra setup).

Verify before relying on the schedule: run the prompt body manually
once in the scheduler environment and confirm:

1. The `[scheduled]` commit lands on `origin/main` (via direct push in
   LOCAL mode, or via squash-merged PR in ROUTINES mode).
2. The sandbox branch (Routines only) is gone from origin after the
   tick — proves the auto-delete setting is on and working.

Full design — `docs/scheduling.md`.

## 11. (Optional) Stand up a role

A **role** is a standing steward of one zone of your life — a project
manager for something you're shipping, a keeper of your open
workstreams, a coach for a habit you're building. Describe it in plain
language and the skill builds it for you:

```
/ztn:role:add
```

From then on the role ticks on its own cadence (nightly by default),
reads the slice of your base it owns, and keeps a live status ledger —
what moved, what's stuck, what needs a decision from you. Ask it
anything, anytime:

```
/ztn:role:ask <role> "what should I focus on this week?"
```

`/ztn:roles` on its own lists your roles and their latest status.
Create a role only when a zone is busy enough to deserve a standing
steward — you don't need any to start. To run the role tick on a
schedule, see `docs/scheduling.md`.

### Raise a role into an external system (a role with hands)

A role can also **reach out** — read an external board (a GitHub-issues board, a Jira
project, a Notion database) and, under your control, update it: create a missing task,
move a status, close a done one. You choose at creation whether it acts on its own or
waits for you (see «What autonomous means» below); by default it STAGES every change for
your approval and never writes hands-free until you opt into autonomy. Three one-time
steps, all walked by the concierge:

1. **Install the crypto dependency** (only needed for an authenticated tool):
   `pip install -r zettelkasten/_system/scripts/requirements.txt` (it declares
   `cryptography`). The secrets blob is encrypted with it.
2. **Wire the credential + the master key (once).** Tell `/ztn:role:add` you want a role
   that updates your board; when it needs auth it asks for the credential in plain
   language, stores it **encrypted** in a blob that is committed to your OWN private
   repo, and — the first time — prints a **master key**. Put that key into your
   scheduler routine's **env / secret config** as `ZTN_SECRET_MASTER_KEY=<key>`
   (per-instance, **never committed**). Where exactly depends on your scheduler: a Cloud
   Routine's env field, or the `env` of a local cron / GitHub-Actions job — see
   `scheduler-prompts/roles-nightly.md → §Secrets`. An in-prompt `export` does NOT work
   (it doesn't survive into the skill's Python subprocesses). Without the key in the
   routine env, the autonomous tick can't resolve the credential and the tool
   honest-degrades.
3. **Approve its acts** (a MANUAL role — the default). The role STAGES what it wants to do
   and surfaces a `role-act-confirm` showing the exact edits and the notes it will feed
   back to your memory; you run `/ztn:roles --approve-acts <role>` to execute (it re-checks
   the target for drift and never double-creates), or discard. (An AUTONOMOUS role you
   opted in skips this — it acts in the nightly run; see «What autonomous means» below.)
   Renew / revoke / re-point the mandate anytime via `/ztn:role:edit`.

**What "autonomous" means today — honestly.** You choose, per role, at creation:
- **Manual (the default):** the role STAGES every act and you approve it
  (`--approve-acts`). Nothing goes out without you. Safe, but hands-on.
- **Autonomous (your explicit opt-in):** dial the role `autonomous` AND set
  `ZTN_ROLES_AUTONOMOUS_ACK=1` in your roles scheduler's env — then it makes its board
  changes on its own on schedule, no per-act approval, including an irreversible surface
  if you granted one. The honest caveat: the runtime is not yet a verified sandbox, so an
  autonomous role acts on YOUR informed consent, not a proven-safe cage — a
  prompt-injection in content it reads could steer an act, bounded to the surface(s) your
  mandate scopes. The marker is off until you set it, so nothing acts hands-free by
  accident. A fully verified sandboxed runtime is a later, service-era capability that
  will remove even that caveat.

To see, in plain words, what any role has been doing and what's waiting on you, just ask
it: `/ztn:role:ask <role> "what did you do"`.

Your grounded notes stay the source of truth; the external board is a projection the
role reconciles toward them.

---

## Reference

- **`integrations/claude-code/skills/ztn-bootstrap/SKILL.md`** — the
  canonical playbook the skill executes. Read this if you want to
  understand exactly what bootstrap does and why.
- **`docs/upstream-sync.md`** — engine update flow, deeper details
  (`/ztn:update` is the friendly wrapper).
- **`docs/obsidian.md`** — opening the vault in Obsidian; what the
  ZTN-shipped `.obsidian/` config does and what to avoid.
- **`integrations/claude-code/skills/ztn-{save,sync-data,update}/SKILL.md`**
  — git-flow skills.
- **`zettelkasten/_system/docs/SYSTEM_CONFIG.md`** — full system spec.
- **`zettelkasten/5_skills/`** — engine reference cards for each skill.
