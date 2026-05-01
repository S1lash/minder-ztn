# Contributing

Engine improvements — skills, slash commands, scripts, system docs —
are welcome. Personal data layers are not.

## What is "engine"

`.engine-manifest.yml` at the repo root is the source of truth. The
`engine:` and `template:` sections list every path that ships from the
upstream skeleton to friend clones. Anything outside those sections is
your own data and stays in your repo.

Engine paths in short:

- `integrations/claude-code/{rules,commands,skills}/` — Claude Code
  prompts and skills.
- `integrations/minder-ztn-mcp/` — MCP integration guide.
- `scripts/` — release, sync, lint tooling.
- `zettelkasten/_system/{docs,scripts,registries/{FOLDERS,CONCEPT_NAMING}.md}` —
  authoritative system spec.
- `zettelkasten/_system/registries/AUDIENCES.template.md` — seed for
  the `audience_tags` privacy whitelist (ships as template; owner
  extensions accumulate after install).
- `zettelkasten/5_meta/{CONCEPT.md,PROCESSING_PRINCIPLES.md,templates/}`
- `zettelkasten/5_skills/` — quick-reference cards.
- `zettelkasten/0_constitution/CONSTITUTION.md` — protocol spec
  (your `axiom/principle/rule/` files stay yours).
- `.claude/CLAUDE.md`, `.claude/settings.json` — project-local
  engine-development guide and permissive Bash allowlist for common
  dev/CI commands.
- `.github/workflows/`, `.gitignore`, `LICENSE`, `integrations/VERSION`.

Before opening an engine PR, read `.claude/CLAUDE.md` — it codifies
the boundary between engine paths and owner-data paths, the
documentation conventions enforced on every doc edit, and the
verification commands (linter, pytest, release dry-run) that gate
engine changes.

## Workflow

1. Fork the upstream skeleton (the public `minder-ztn` repo).
2. Branch off `main` (`feat/<short-slug>` or `fix/<short-slug>`).
3. Make engine changes only — never touch a `template:` path or any
   path outside the manifest. The personal-data linter guards this
   (`scripts/check-no-personal-data.sh`).
4. Bump `integrations/VERSION` (semver). Add a migration under
   `scripts/migrations/NNN-short-slug.sh` if your change is
   breaking — see `scripts/migrations/README.md`.
5. Open a pull request describing the user-visible behaviour change
   and the migration story.

## Style

- Engine docs follow `_system/docs/CONVENTIONS.md` — describe current
  behaviour, no version refs / phase narratives / rename history.
- Engine prompts never hardcode a person's name. When personal
  attribution is needed, read `_system/SOUL.md` `## Identity` `Name:`
  at runtime.
- Tests live under `zettelkasten/_system/scripts/tests/` (pytest).

## What does NOT belong upstream

- Anyone's `_records/`, `_sources/`, PARA notes, constitution
  principles, SOUL/PEOPLE/PROJECTS/TAGS values.
- Examples that name a real person. Use `john-doe` / `ivan-petrov`
  placeholders.
- Personal `~/.claude/` rules or memory files.
- Your `.engine-migrations-applied` marker file.

## Release process (maintainer)

The upstream maintainer authors engine changes in their personal
instance, then runs `scripts/release_engine.py --target <skeleton-tree>`
to publish to the public skeleton. Friends pick up the change via
`/ztn:update` (interactive Claude skill — default) or
`scripts/sync_engine.sh` (non-interactive shell, CI / power users).
