# Scheduling — autonomous ZTN ticks

ZTN is designed to run **multiple times a day, every day**, without you
in the loop for the routine path. This doc describes the canonical
scheduling setup, the assumptions baked into it, and how to plug it in.

## The canonical loop

Four scheduled jobs.

| Job | Cadence | Skill chain | Prompt source |
|---|---|---|---|
| `ztn-process` | ≥ 3× per day | `/ztn:sync-data` → `/ztn:process` (maintain inline) → `finalize-tick.sh scheduler/process` | `integrations/claude-code/scheduler-prompts/process-scheduled.md` |
| `ztn-agent-lens` | 1× nightly (03:00) | `/ztn:sync-data` → `/ztn:agent-lens --all-due` → `finalize-tick.sh scheduler/agent-lens` | `integrations/claude-code/scheduler-prompts/agent-lens-nightly.md` |
| `ztn-lint` | 1× nightly (05:00) | `/ztn:sync-data` → `/ztn:lint` (Step 7.5 dispatches `/ztn:resolve-clarifications --auto-mode` inline) → `finalize-tick.sh scheduler/lint` | `integrations/claude-code/scheduler-prompts/lint-nightly.md` |
| `ztn-content` | 1× weekly (Tue 06:00) | `/ztn:sync-data` → `/ztn:content --maintain` → `finalize-tick.sh scheduler/content` | `integrations/claude-code/scheduler-prompts/content-tick.md` |

The content pipeline runs across two ticks a day apart: the `content-synthesis`
lens (the classifier) is a registered agent-lens (`weekly mon`), so the existing
`ztn-agent-lens` tick runs it on Mondays; the `ztn-content` maintainer drafts on
Tuesdays. Producer (lens) and consumer (maintainer) stay in separate scheduler
contexts on purpose — the maintainer must not be the same context that just
produced the lens verdict.

Two nightly ticks. Agent-lens runs first (03:00) in its own scheduler-
agent context — lens production isolated from resolve consumption,
prevents the agent that produces lens bodies from also voting on its
own proposals (confirmation bias). Lint runs later (05:00), invokes
its invariant scans, then Step 7.5 dispatches resolve --auto-mode
inline so the same tick consumes fresh lens hints + CLARIFICATIONS
that lint just emitted. The agent-lens skill filters lenses by per-
lens cadence — nightly fire ≠ nightly lens runs.

There is no `ztn-maintain` schedule — maintain runs inline as the tail
of `/ztn:process`. There is no `ztn-resolve-clarifications` schedule —
the owner reviews the queue manually; that is the human-in-loop hinge
of the whole system. There is no `ztn-agent-lens-add` schedule — lens
creation is owner-driven (wizard-style); see
`integrations/claude-code/skills/ztn-agent-lens-add/SKILL.md`.

## Single-commit guarantee

Every scheduler tick produces **exactly one commit on `origin/main`**.
The contract is enforced by `scripts/scheduler/finalize-tick.sh` — the
single point in the prompt that commits + delivers. Two helpers feed
into it:

- `scripts/scheduler/stage.sh` — staging-only (idempotent). Engine
  paths are filtered (defined in `.engine-manifest.yml` + a small
  conservative-prefix list in `_classify_paths.py`); only owner data
  is staged. May be called any number of times during a tick.
- `scripts/scheduler/finalize-tick.sh <tag>` — single commit + delivery.
  Folds any unpushed `[scheduled]` commits from a previous partial tick
  into one commit. Refuses to rewrite history if owner has manual
  non-scheduled commits ahead of `origin/main` (no force-push, ever).

`/ztn:save` is owner-interactive only. Scheduler prompts never invoke
it and never call `git commit` / `git push` / `git add` outside the
helper scripts (with one narrow exception below for the MCP fallback).

## Skill discovery — the Step 0 preflight

Every tick invokes `/ztn:*` skills as slash commands. The runtime discovers
them from `.claude/skills/<name>/SKILL.md` in the clone. If that layout is
broken, the tick dies at its first slash invocation — historically the most
common scheduler failure.

The layout is cross-platform by construction: the skeleton ships
`.claude/skills/<name>/SKILL.md` as **real files**, not symlinks. Git symlinks
do not survive a Windows clone (`core.symlinks=false` materialises the symlink
blob as a text file, so `.claude/skills/ztn-process` becomes a file and its
`SKILL.md` disappears). The owner repo keeps symlinks for the dev loop;
`scripts/release_engine.py` dereferences them into real files on release, and
`scripts/sync_engine.sh` replaces a broken local `.claude/skills/` with the
real-file tree on `/ztn:update`.

As a fail-fast guard, **Step 0** of every tick runs
`scripts/scheduler/ensure-skills.sh` (check-only) and, if any skill does not
resolve, ships a precise failure note and exits `partial` instead of cascading
into confused recovery. The tick does **not** try to repair the layout
in-session: the runtime scans skills at clone time, so a mid-tick fix cannot
make the slash commands load, and a cloud sandbox is ephemeral so it cannot
persist either. Repair belongs to persistent local setups — `install.sh` runs
`ensure-skills.sh --repair` there (symlink where supported, real-file copy as
fallback). The durable fix for a broken clone is the real-file skeleton layout
delivered via `/ztn:update`.

## Delivery model — two modes with an MCP fallback

`finalize-tick.sh` auto-detects how to deliver the tick's commit:

**LOCAL mode** — start branch is `main` (local cron, launchd, GitHub
Actions running with full push rights to main). Single
`git push origin main`. No sandbox branch involved.

**ROUTINES mode** — start branch is a sandbox ref (`claude/...`).
Anthropic Cloud Routines' git proxy refuses direct push to `main` and
refuses `git push origin --delete <branch>` (both HTTP 403). The script
instead:

1. `git push origin HEAD:<sandbox-branch>` (proxy-allowed).
2. `gh pr create --base main --head <sandbox-branch>`.
3. `gh pr merge --squash --delete-branch`.

End state: `main` has one squash commit, sandbox branch deleted.

**MCP fallback** — Cloud Routines sandboxes typically don't ship `gh`.
When `finalize-tick.sh` exits 2 with `"gh CLI not found in PATH"`, the
scheduler prompts have an explicit Step 5b that routes through the
`github` MCP server: push HEAD to the sandbox branch via plain `git
push`, call MCP `create_pull_request`, call MCP `merge_pull_request`
with `merge_method: squash`. Branch cleanup falls to the repo setting
described in the next section. Step 5b is the **only** authorized
non-script git/MCP path in the prompts.

## ⚠️ Required repo setting — auto-delete head branches

The Routines proxy blocks `git push origin --delete <branch>`, and the
github MCP server does not currently have a `delete_branch` tool. The
scheduler therefore **cannot** delete its own sandbox branch from
within a Routines tick. The cleanup mechanism is GitHub itself:

**Settings → General → Pull Requests → ☑ Automatically delete head
branches**

Enable this **once per repository**. With it on, GitHub removes the
head branch the moment its PR is squash-merged. With it off, each
scheduler tick leaves a sandbox branch on origin and they accumulate.

This is the load-bearing assumption of the ROUTINES delivery path. The
new-repo onboarding checklist (`docs/onboarding.md` §9) calls it out
explicitly. Verify it is on before relying on cloud scheduling.

For LOCAL mode the setting is not required (no PR involved), but
enabling it does no harm.

## Opinionated assumptions

These are not configurable. If you need a different model, the
scheduler prompts are not for you yet.

- **Process at least daily, usually multiple times.** ZTN's value
  comes from cadence. Less than once a day means transcripts pile up
  and the macro picture lags reality.
- **Lint at night, after the day's last process tick.** Lint reads the
  day's accumulated state. Running it before processing is wasteful;
  running it concurrently with processing risks lock contention.
- **Every scheduled run autocommits and pushes.** Without push,
  multi-device use breaks. Without autocommit, the working tree
  accumulates uncommitted scheduler output and the next manual
  `/ztn:save` becomes ambiguous.
- **Ambiguity goes to CLARIFICATIONS, not to you.** The whole
  CLARIFICATIONS mechanism exists for this exact case. A scheduled
  run that pauses on a question is broken — it just hangs the agent
  until timeout. CLARIFICATIONS is the async hand-off.
- **Engine drift is never resolved by the scheduler.** `stage.sh` and
  `finalize-tick.sh` refuse engine paths. If you edited engine files
  locally, the scheduler will leave them dirty and surface a
  CLARIFICATIONS note. Run `/ztn:update` (or revert) yourself.

## What the scheduler will NEVER do

| Operation | Why not |
|---|---|
| `git push --force` (or `--force-with-lease`) | Data-loss risk. Push rejection means «sync next tick», not «overwrite remote». |
| Stage engine paths | Engine is owned upstream. Local edits to engine paths are an owner concern; engine drift is logged to CLARIFICATIONS instead. |
| `/ztn:resolve-clarifications` interactive | Resolution is the human-in-loop step by design. The auto-mode dispatch inside lint Step 7.5 is the exception. |
| `/ztn:update` | Engine sync needs owner attention (VERSION delta, migrations, divergence resolution). |
| Pause and ask the owner | No human in this loop. Anything that would be a question becomes a CLARIFICATIONS row. |
| Retry push on failure | The script makes exactly one delivery attempt per tick. A failed delivery surfaces as `partial`; next tick processes fresh state from inbox. |
| Skip commit on «small» changes | Every tick commits, even routine state-only churn. Predictability beats minimalism. |

## Partial-tick handling

If a tick aborts between push and PR-merge (network glitch, MCP error,
PR creation failure), the sandbox branch on origin holds the unmerged
commit. There is **no automatic recovery sweep** — the new architecture
keeps the design minimal. The next tick processes fresh state from
`_sources/inbox/` and produces a new commit. The stranded sandbox
branch is harmless (work content is re-derivable from inputs) and can
be removed manually if it accumulates:

```bash
git push origin --delete <branch>   # from a local clone with push rights
```

Routines tick output ends with the contract status: `success <SHA>`,
`partial`, or `sync-blocked`. Owner sees the line in the Routine's
own log and can intervene if needed.

## How skills reach the scheduler agent

The scheduler agent is just a Claude Code session running your prompt
body. For the slash invocations (`/ztn:process`, `/ztn:lint`,
`/ztn:agent-lens --all-due`, `/ztn:sync-data`) to actually fire, ZTN
skills must be visible in the session's skill registry.

- **Cloud Routines / `/schedule`** — clone the repo fresh and look at
  `.claude/skills/<name>/SKILL.md` at the repo root. The repo ships
  committed symlinks there pointing into
  `integrations/claude-code/skills/<name>/`, so all skills load
  automatically. Nothing to configure.
- **Local cron / launchd / GitHub Actions** — same `.claude/skills/`
  symlinks load when the runner has the repo as CWD. If the runner
  invokes `claude` from a different CWD, also run
  `./integrations/claude-code/install.sh` once on the runner so
  user-level `~/.claude/skills/` symlinks cover the case.

The bash helpers under `scripts/scheduler/` (`pin-main.sh`,
`lock-check.sh`, `stage.sh`, `finalize-tick.sh`, `ship-failure-note.sh`)
are repo-local — every prompt body invokes them via
`bash scripts/scheduler/<name>.sh`. They handle git plumbing +
cross-skill lock detection + single-commit delivery so the prompt
bodies stay thin and identical across the three ticks.

## Plug-in — Claude Code `/schedule`

The recommended path. Three routines:

```
/schedule
  name: ztn-process
  cron: 0 9,14,19 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/process-scheduled.md>
```

```
/schedule
  name: ztn-agent-lens
  cron: 0 3 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/agent-lens-nightly.md>
```

```
/schedule
  name: ztn-lint
  cron: 0 5 * * *
  prompt: <paste body of integrations/claude-code/scheduler-prompts/lint-nightly.md>
```

Each routine runs in a fresh agent — the prompt body is fully
self-contained, no extra context required.

After a `/ztn:update` that changed any prompt body in
`integrations/claude-code/scheduler-prompts/`, re-paste the updated
body into `/schedule`. Claude Code holds the prompt verbatim; engine
updates do not propagate to running schedules automatically.

## Plug-in — non-Claude-Code schedulers

cron + `claude --print`, launchd, GitHub Actions on a private fork:
same prompt bodies. Ensure:

- Filesystem access to the ZTN repo working tree.
- Configured git identity for autonomous push.
- Authentication to `origin` (SSH key in the runner / token in env).
  Concrete setup options (passphrase-less SSH, PAT-baked remote URL,
  platform-managed credentials) — see `docs/onboarding.md` §9.
- A way to surface non-zero exit (logs, email, pager) — the prompt
  bodies exit non-zero on sync-blocked / partial.

Local cron starts on the `main` branch by default, so LOCAL mode in
`finalize-tick.sh` applies — no PR ceremony, just direct push.

## Owner morning routine

The other half of the loop. Whatever happened overnight + during the
day lands in CLARIFICATIONS by morning.

1. `/ztn:resolve-clarifications` — pre-syncs against `origin`, walks
   you through the queue one theme at a time, refreshes derived views
   (`/ztn:regen-constitution`, `/ztn:maintain`) when your resolutions
   touched constitution / registries, and reminds you to save.
2. `/ztn:save` (interactive, not `--auto`) — commit + push your
   resolutions when the skill prompts you.

That's it. The scheduler covers ingestion + slop-catching; you cover
judgement + resolution.

## Why this shape (instead of N tiny jobs or one big one)

- **One big nightly job.** Tried mentally: would mean transcripts
  dropped at 10am don't surface until 03:00 the next day. ZTN is a
  thinking aid; latency >12h kills the feedback loop.
- **Per-skill schedules (process, maintain, lint, resolve, agent-lens,
  agent-lens-add).** Tried mentally: maintain has no independent
  cadence (it tails process); resolve and agent-lens-add must not be
  autonomous (owner judgement / wizard interview); process / lint /
  agent-lens cover the autonomous surface area entirely. Three jobs
  is the right minimum.
- **Process every hour.** Wasteful for typical input rates and burns
  Claude Code budget; revisit only if you start dropping transcripts
  faster than the recommended 3× cadence drains them.
