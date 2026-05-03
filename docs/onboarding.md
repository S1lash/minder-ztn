# Onboarding — quickstart

You only need to do two shell commands by hand: clone, then run
`install.sh`. After that everything is orchestrated by Claude Code
skills — `/ztn:bootstrap` first, then the daily flow.

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
- `crafted/` — hand-written long-form documents

If your input does not match any of the starter sources, run
`/ztn:source-add` after install — it registers a new source-type
declaratively (one row in SOURCES.md + paired inbox/processed
folders). No code changes required.

If you want a high-quality identity seed, edit
`_sources/inbox/crafted/describe-me/PROFILE.template.md` in place. The
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

Three ready-made scheduler prompts ship in
`integrations/claude-code/scheduler-prompts/`:

- `process-scheduled.md` — pre-sync → `/ztn:process` → `/ztn:save --auto`.
  Recommended cadence: 3× per day (e.g. cron `0 9,14,19 * * *`).
- `lint-nightly.md` — pre-sync → `/ztn:lint` → `/ztn:save --auto`.
  Recommended cadence: 1× per night (e.g. cron `0 3 * * *`).
- `agent-lens-scheduled.md` — pre-sync → `/ztn:agent-lens --all-due` →
  `/ztn:save --auto`. Recommended cadence: 1× per day (e.g. cron
  `0 6 * * *`). The skill filters lenses by per-lens cadence — daily
  tick ≠ daily lens runs. To create new lenses, use the wizard:
  `/ztn:agent-lens-add` (owner-driven, not scheduled).

Paste each body into your scheduler of choice (Claude Code `/schedule`,
GitHub Actions cron, host crontab calling `claude` headless — any
runner that can launch a Claude Code session works).

**Important — push credentials.** `/ztn:save --auto` pushes to your
`origin` remote. The scheduler runs in a non-interactive environment,
so it cannot prompt for SSH passphrases or 2FA. Set up one of:

- **SSH key without passphrase** stored on the scheduler host, added
  to your GitHub account.
- **Personal Access Token** with `repo` scope, configured as the
  remote URL: `git remote set-url origin https://<TOKEN>@github.com/<you>/my-ztn.git`.
- **Platform-managed credentials** (Claude Code cloud `/schedule`
  inherits your authenticated session — no extra setup).

Verify before relying on the schedule: run the prompt body manually
once in the scheduler environment and confirm the `[scheduled]`
commit lands on `origin`.

Full design — `docs/scheduling.md`.

---

## Reference

- **`integrations/claude-code/skills/ztn-bootstrap/SKILL.md`** — the
  canonical playbook the skill executes. Read this if you want to
  understand exactly what bootstrap does and why.
- **`docs/upstream-sync.md`** — engine update flow, deeper details
  (`/ztn:update` is the friendly wrapper).
- **`integrations/claude-code/skills/ztn-{save,sync-data,update}/SKILL.md`**
  — git-flow skills.
- **`zettelkasten/_system/docs/SYSTEM_CONFIG.md`** — full system spec.
- **`zettelkasten/5_skills/`** — engine reference cards for each skill.
