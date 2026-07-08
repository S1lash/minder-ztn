# minder-ztn — project guide for Claude Code

This repo holds two things side-by-side:

1. The **ZTN engine** — skills, scripts, system docs, integration tooling. Authored here, released to the public skeleton (`minder-ztn`) via `scripts/release_engine.py`, consumed by friends through `/ztn:update`.
2. **Owner data** under `zettelkasten/` — records, knowledge notes, constitution, registries, hubs. Owned by the human running this clone.

Different rules apply to each. This file is the project-local contract.

The global rule `~/.claude/rules/ztn.md` already covers HOW to USE the ZTN base from any session (search, recall, when to invoke skills). The global rule `~/.claude/rules/ztn-engine-doctrine.md` (symlink to `zettelkasten/_system/docs/ENGINE_DOCTRINE.md`) auto-loads the operating philosophy. **This file covers what those don't: how to WORK ON THIS REPO.**

## Authority order (top wins on conflict)

1. `zettelkasten/_system/docs/SYSTEM_CONFIG.md` — system contract; hard rules, schemas, lock matrix
2. `zettelkasten/_system/docs/CONVENTIONS.md` — documentation conventions; binding on every edit to engine docs and SKILLs
3. `zettelkasten/_system/docs/ENGINE_DOCTRINE.md` — operating philosophy; cross-skill principles (auto-loaded)
4. This file — project-local engine-development rules
5. Skill `SKILL.md` under `integrations/claude-code/skills/<name>/` — pipeline-specific spec
6. `zettelkasten/_system/SOUL.md` — owner identity calibration

When you find these in conflict, the higher one wins. When a rule is absent everywhere, surface a CLARIFICATION rather than silently choose.

## Engine vs data — the boundary

`.engine-manifest.yml` at the repo root is the **source of truth** for what is engine. Read it before touching any path you're unsure about.

### Engine paths (normal code edits land here)

- `integrations/claude-code/{rules,commands,skills}/` — Claude Code prompts and skills (sources)
- `integrations/claude-code/{install.sh,uninstall.sh,SETUP_PROMPT.md,scheduler-prompts/}` — installer + scheduler templates
- `integrations/minder-ztn-mcp/` — MCP integration guide
- `integrations/obsidian/` — Obsidian vault config seed (`.obsidian/` defaults + `HOME.template.md` dashboard, idempotently seeded by `seed.sh` from `claude-code/install.sh`)
- `scripts/` — release, sync, lint, migrations
- `zettelkasten/_system/docs/` — system spec
- `zettelkasten/_system/scripts/` — python pipeline + tests
- `zettelkasten/_system/registries/{FOLDERS.md,CONCEPT_NAMING.md,AGENT_LENSES.md,lenses/}` — engine registries (pure spec; sync upstream-to-downstream)
- `zettelkasten/_system/registries/AUDIENCES.template.md` — seed for `AUDIENCES.md` (spec + owner-mutable Extensions table; ships as template so owner extensions survive sync)
- `zettelkasten/5_meta/{CONCEPT.md,PROCESSING_PRINCIPLES.md,templates/,starter-pack/}`
- `zettelkasten/5_skills/` — engine quick-reference cards
- `zettelkasten/0_constitution/CONSTITUTION.md` — protocol spec (NOT the `axiom/principle/rule/` subdirs)
- `zettelkasten/{1_projects,2_areas,3_resources,_records}/README.md` — PARA explainers
- `.claude/CLAUDE.md`, `.claude/settings.json` — project-local engine-development guide and permissive command allowlist (this file and its sibling)
- Root meta: `.gitignore`, `LICENSE`, `integrations/VERSION`, `CONTRIBUTING.md`, `docs/{onboarding,upstream-sync,scheduling,obsidian,privacy,CHANGELOG}.md`

### Owner-data paths (NEVER edit by hand — route through ZTN skills)

| Path | Skill that owns writes |
|---|---|
| `zettelkasten/_records/{meetings,observations}/` | `/ztn:process` |
| `zettelkasten/_records/{biometric,activity}/<source>/` + `_system/state/{biometric,activity}/`, `_system/views/{biometric,activity}/` | `/ztn:process` metric-day branch (records/baselines) + `/ztn:maintain` weekly workers (views) — deterministic, never hand-edit |
| `zettelkasten/_sources/inbox/` | `/ztn:process` consumes; `/ztn:source-add` registers new types |
| `zettelkasten/_sources/processed/` | `/ztn:process` (move-only); never delete |
| `zettelkasten/0_constitution/{axiom,principle,rule}/` | `/ztn:capture-candidate` → `/ztn:lint` F.5 promotion → `/ztn:regen-constitution` |
| `zettelkasten/{1_projects,2_areas,3_resources,4_archive}/` (excluding READMEs) | `/ztn:process`, `/ztn:maintain` |
| `zettelkasten/5_meta/mocs/`, `zettelkasten/6_posts/` | `/ztn:maintain` (incl. `hub-cognitive-model.md`: its `<!-- AUTO-GENERATED: cognitive-model-hub -->` zone is rendered by `render_cognitive_model_hub.py` Step 7.9 — never hand-edit the table; the prose «portrait» above the markers is owner-curated) |
| `zettelkasten/_system/{SOUL,POSTS,long-form-playbook}.md` | owner-curated; engine reads, surfaces clarifications, never silently overwrites |
| `zettelkasten/_system/{TASKS,CALENDAR}.md` | `/ztn:process` — derived aggregates over note `- [ ]` / `📅` items (owner owns only the TASKS `## Stale` section). Not hand-edited; completeness enforced by `reconcile_tasks.py` / `reconcile_calendar.py` |
| `zettelkasten/_system/registries/{TAGS,SOURCES}.md` | `/ztn:maintain`, `/ztn:lint` |
| `zettelkasten/3_resources/people/PEOPLE.md` | `/ztn:process` (rows + mentions), `/ztn:bootstrap`, `/ztn:lint` (dedup/audit); tier only via `/ztn:resolve-clarifications` |
| `zettelkasten/1_projects/PROJECTS.md` | `/ztn:bootstrap` (candidates); owner |
| `zettelkasten/_system/registries/AUDIENCES.md` (Extensions table only) | `/ztn:resolve-clarifications` (appends rows on owner approval); spec sections never edited by hand |
| `zettelkasten/_system/state/` | append-only logs, candidate buffers, clarifications queue — every skill writes its own files |
| `zettelkasten/_system/views/` | auto-generated by `/ztn:regen-constitution`, `/ztn:maintain` |

If a task tempts you to hand-edit any owner-data path, **stop and route through the right skill.** The append-only / idempotency / audit-trail guarantees of the engine depend on it. The CLARIFICATIONS queue exists precisely so you do not have to silently decide.

## Engine conventions — non-negotiable when editing engine docs and SKILLs

These are quoted from `_system/docs/CONVENTIONS.md` because they get violated otherwise. They apply to every contributor — friend or maintainer. Engine docs describe **current behaviour**, not history. A reader six months from now sees «how it works now», not «how it evolved».

1. **No version references.** Never write `v4.5`, `Version: 4.7`, `ZTN v3` in SKILL headers, descriptions, system docs. Components describe themselves by name. The single exception is `batch-format.md`, where `version: 1.0` IS the content of the spec.
2. **No phase references.** Never write `(Phase 4)`, `Phase 5+`, `per PHASE-4-SDD §Q8`. Phase narratives are git history, not doc content.
3. **No rename or migration history.** Don't write «previously this was called X», «moved from Y to Z», «renamed in vN». The file IS the contract; git log carries narrative.
4. **No personal names in engine code.** Engine prompts, system docs, SKILL examples use placeholders (`john-doe`, `ivan-petrov`, `<owner>`) or read from `zettelkasten/_system/SOUL.md → ## Identity → Name:` at runtime. The personal-data linter (`scripts/check-no-personal-data.sh`) enforces this in CI; PRs that fail it are blocked.
5. **Describe current behaviour.** Default mental check before committing any doc edit: *would this sentence still make sense after the v4.6→v4.7 narrative is forgotten?* If no, rephrase.
6. **Template-spec sync — both files or neither.** Several engine-spec docs ship as `*.template.md` (see `.engine-manifest.yml → template:`). `release_engine.py` strips the `.template` suffix when copying to the skeleton, and `sync_engine.sh` skips template paths so friend's owner-Extensions survive `/ztn:update`. Consequence: any **spec-portion edit** to a live file with a `.template.md` sibling MUST be backported to the template in the same change, otherwise friends never receive the spec update. Owner-mutable sections (Extensions tables, populated rows, owner data) naturally diverge — that is by design — but canonical sets, format rules, autofix tables, heuristic descriptions, and example values are spec and must stay byte-identical between live and template. Verify with `diff <live>.md <live>.template.md` before commit. The high-risk files today: `AUDIENCES.md` ↔ `AUDIENCES.template.md`, `DOMAINS.md` ↔ `DOMAINS.template.md`, `INDEX.md` ↔ `INDEX.template.md`, `TAGS.md` ↔ `TAGS.template.md`. CI does not enforce this; the discipline is on the editor.

These rules are aggressive on purpose. Engine docs are read cold by friends with no shared session history; drift here is the largest entropy risk in the system.

## Cross-platform — Windows + macOS + Linux (HARD RULE)

**Every engine artifact MUST work on all three platforms friends run — no exceptions, ever.** Migrations, features, scripts, commands, hooks, paths, symlinks, doc instructions: anything the engine ships. A friend on Windows runs Git Bash + `python3`; a friend on macOS runs the system shell (**bash 3.2** — old) + `python3`. An artifact that only works on the author's Mac is a silent breakage that surfaces months later as "it doesn't work for me." This is non-negotiable and applies to every edit.

- **Shell must be bash-3.2-safe AND Git-Bash-safe.** macOS ships bash 3.2 — NO `mapfile`/`readarray`, NO associative arrays (`declare -A`), NO `${var^^}`/`${var,,}`. Prefer `python3` for any non-trivial logic. Portable commands only: no `md5`(mac)/`md5sum`(gnu) split, no `sed -i ''`(mac) vs `sed -i`(gnu) — use `sed -i.bak`, no `readlink -f`/`stat -f`/`stat -c`/`grep -P`. Invoke scripts via `bash x` / `python3 x` — never rely on the executable bit (Windows has none).
- **Line endings = LF, enforced by `.gitattributes`.** A CRLF `.sh`/`.py` (the Windows checkout default) breaks bash and python. `.gitattributes` at repo root forces LF; keep it shipped (it is in `.engine-manifest.yml`).
- **Paths portable.** Python: `pathlib`/`os.path`, never hardcode `/` or `C:\`; resolve from repo root (`git rev-parse` / `BASH_SOURCE`), never an absolute path.
- **Parity in lockstep.** A shell mechanism that has a Windows-equivalent (e.g. a future `install.ps1` beside `install.sh`) is edited in the SAME change, or the limitation is stated explicitly.
- **Readiness test before finalising:** «will this run **identically** on a friend's Windows machine and on a plain macOS bash 3.2?» "It works on my Mac" is NOT the bar. If unsure — verify (`/bin/bash -n script.sh` on macOS proves bash-3.2 syntax; check for CRLF; grep for the banned commands above).

The canonical statement of this rule lives in `_system/docs/ENGINE_DOCTRINE.md §3.9` (auto-loaded into every session); this section is its contributor-facing checklist.

## Where skills are authored

Skills live at `integrations/claude-code/skills/<name>/SKILL.md`. **That is the source of truth.** The full set lives under that path:

```
integrations/claude-code/skills/
  ztn-bootstrap/        ztn-process/         ztn-maintain/
  ztn-lint/             ztn-agent-lens/      ztn-agent-lens-add/
  ztn-capture-candidate/ ztn-content/        ztn-check-decision/
  ztn-regen-constitution/ ztn-resolve-clarifications/
  ztn-save/             ztn-sync-data/       ztn-source-add/
  ztn-update/
```

Skills are discovered through two paths:

1. **Project-level (Routines + interactive in repo CWD)** — `.claude/skills/ztn-*` symlinks at the repo root point into `integrations/claude-code/skills/<name>/`. Auto-discovered by Claude Code (interactive + Routines) when CWD is inside the repo. SKILL.md sources use repo-relative `zettelkasten/...` paths and need no rendering.

2. **User-level (interactive from any CWD)** — `./integrations/claude-code/install.sh` renders rules / commands templates (which still use `{{MINDER_ZTN_BASE}}`) into `integrations/claude-code/built/` (gitignored) and symlinks `~/.claude/{rules,commands,skills}/` so the constitution-capture hook + ambient `/ztn:capture-candidate` / `/ztn:check-decision` are reachable from sessions opened outside this repo. The skills loop in install.sh is a no-op pass for skills (no placeholder to render); kept for user-level symlink coverage.

**Never edit:**
- `integrations/claude-code/built/**` — generated output of install.sh
- `~/.claude/skills/<name>/SKILL.md` — symlink chain into the repo

After editing a SKILL source, no rebuild is required — both `.claude/skills/` and `~/.claude/skills/` resolve to the same source. After editing a rule or command source, re-run `./integrations/claude-code/install.sh` (idempotent) to refresh `built/`.

## Authoritative docs to keep current

When engine behaviour changes, these are the docs that must move with it. Drift between them is the engine's largest entropy risk.

| File | Purpose |
|---|---|
| `zettelkasten/_system/docs/SYSTEM_CONFIG.md` | System contract: schemas, hard rules, cross-skill lock matrix |
| `zettelkasten/_system/docs/CONVENTIONS.md` | Documentation style; binding on every edit listed in this table |
| `zettelkasten/_system/docs/ENGINE_DOCTRINE.md` | Operating philosophy; auto-loaded into every session via `~/.claude/rules/ztn-engine-doctrine.md` |
| `zettelkasten/_system/docs/ARCHITECTURE.md` | System design; multi-user planning |
| `zettelkasten/_system/docs/manifest-schema/v{N}.json` | Canonical JSON Schema for ZTN engine manifest (consumer-agnostic). New major = new file alongside; old majors retained for validating old batches |
| `zettelkasten/_system/docs/manifest-schema/README.md` | Reference doc for manifest contract: SemVer evolution rules, per-skill semantics, "what is NOT in the manifest", consumer integration patterns |
| `zettelkasten/_system/docs/manifest-schema/fixtures/` | Per-skill sanitized example manifests; regression test for schema evolution — schema changes MUST keep these validating |
| `zettelkasten/_system/docs/batch-format.md` | Markdown batch-summary format (`{ts}-{skill}.md` next to each JSON manifest); narrative side only — JSON contract canonical lives in `manifest-schema/` |
| `zettelkasten/_system/docs/constitution-capture.md` | In-the-moment capture trigger spec |
| `zettelkasten/_system/docs/communication-baseline.md` | Universal presentation spine; hot-loaded into every session (symlinked to `~/.claude/rules/`) |
| `zettelkasten/_system/docs/harness-setup.md` | Harness setup |
| `zettelkasten/5_meta/CONCEPT.md` | Three-layer model; long-form philosophy |
| `zettelkasten/5_meta/PROCESSING_PRINCIPLES.md` | The 8 processing principles |
| `zettelkasten/0_constitution/CONSTITUTION.md` | Constitution protocol spec (axiom / principle / rule schema, scope, evolution ladder) |
| `zettelkasten/_system/registries/FOLDERS.md` | Folder routing rules |
| `zettelkasten/_system/registries/CONCEPT_NAMING.md` | Canonical concept-name format (snake_case ASCII; rules + normalisation algorithm + heuristics) |
| `zettelkasten/_system/registries/AUDIENCES.md` | `audience_tags` privacy whitelist (canonical five + owner extensions + spec) |
| `zettelkasten/_system/registries/AGENT_LENSES.md` | Agent-lens registry + frame contract |
| `zettelkasten/5_skills/CLAUDE_ZETTELKASTEN.md`, `zettelkasten/5_skills/ztn-*.md` | Engine quick-reference cards |
| `.engine-manifest.yml` | Engine boundary; what ships to skeleton |
| `CONTRIBUTING.md` | Contribution rules |
| `docs/onboarding.md`, `docs/upstream-sync.md`, `docs/scheduling.md` | Friend-facing docs |

When you change a SKILL.md, ask: *does this affect anything in the table above?* If yes, update both in the same change. **Two-stage doc edits create drift; one-stage edits prevent it.**

## Verification — run before finalising engine changes

```bash
# Personal-data linter — engine code must not name any specific person.
# CI runs this; engine PRs fail otherwise.
scripts/check-no-personal-data.sh

# Python pipeline tests
pytest zettelkasten/_system/scripts/tests/

# Release dry-run — confirms the manifest is consistent and all engine
# paths exist. Run after touching `.engine-manifest.yml` or moving files.
python3 scripts/release_engine.py --target /tmp/skeleton-check --dry-run
```

If the change touches a SKILL contract, also bump `integrations/VERSION` (semver). For breaking changes add a migration under `scripts/migrations/NNN-short-slug.sh` (see `scripts/migrations/README.md`).

## Commit / save

- **Engine changes** (paths in the engine table above) — normal `git commit` + `git push`. English only, imperative mood, explain WHY not WHAT.
- **Owner-data changes** (records, knowledge, constitution, registries, hubs) — go through `/ztn:save`. The skill stages by category, drafts a message, commits and pushes after confirmation.

Never mix engine and owner-data in one commit — the boundary becomes muddled in history and `release_engine.py` cannot extract cleanly.

## Autonomous operation

Several skills run unattended via scheduler prompts (`integrations/claude-code/scheduler-prompts/`):

- `/ztn:process` — pre-sync → process → save (3× per day)
- `/ztn:lint` — pre-sync → lint → save (nightly)
- `/ztn:maintain` — after-batch integrator
- `/ztn:agent-lens --all-due` — pre-sync → lens runs → save (daily; runs the
  `content-synthesis` lens on Mondays)
- `/ztn:content --maintain` — pre-sync → draft-maintainer → finalize (weekly,
  Tuesday; the content pipeline's actor)
- `/ztn:sync-data` — pre-work pull on multi-device setups

They follow the cross-skill lock matrix in `SYSTEM_CONFIG.md` and write to append-only logs under `_system/state/log_*.md`. When debugging an autonomous run, **read the relevant log first** — the audit trail is designed to make every decision recoverable without re-running.

When proposing changes to skills that run autonomously, preserve the contract: never block on user input, always surface judgement to `CLARIFICATIONS.md` with a conservative default, never silently mutate owner-curated state.
