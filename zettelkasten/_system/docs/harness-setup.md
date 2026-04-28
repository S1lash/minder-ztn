# Claude rules + cross-project skills — install

Two coupled install requirements per machine so that:

1. The global constitution-capture hook fires in every Claude Code session.
2. The skills the hook invokes (`/ztn:capture-candidate`,
   `/ztn:check-decision`, `/ztn:regen-constitution`) and the ambient ZTN
   commands (`/ztn:search`, `/ztn:recap`) are discoverable outside this
   repo too (radar sessions, HQ sessions, scheduler).

All install steps are automated by `integrations/claude-code/install.sh`
in the repo root. The script is idempotent and reads the absolute repo
path automatically — no manual env vars to set.

## What the installer does

The installer creates symlinks from `$HOME/.claude/` into the repo so
that the source stays version-controlled here while each machine sees a
stable local path:

| Symlink | Repo source |
|---|---|
| `~/.claude/rules/ztn.md` | `integrations/claude-code/built/rules/ztn.md` |
| `~/.claude/rules/constitution-capture.md` | `zettelkasten/_system/docs/constitution-capture.md` |
| `~/.claude/rules/constitution-core.md` | `zettelkasten/_system/views/constitution-core.md` |
| `~/.claude/skills/ztn-*` (8 dirs) | `integrations/claude-code/built/skills/ztn-*` |
| `~/.claude/commands/ztn-recap.md`, `ztn-search.md` | `integrations/claude-code/built/commands/*.md` |

`built/` is gitignored. The installer renders templates from
`integrations/claude-code/{rules,skills,commands}/` into `built/` by
substituting `{{MINDER_ZTN_BASE}}` with the absolute path to
`<repo>/zettelkasten`. Re-running the installer (after `git pull`, after
moving the repo) refreshes `built/` in place.

## Install (per machine)

```bash
cd <wherever-you-cloned>/minder-ztn
./integrations/claude-code/install.sh
```

After install, add the constitution-capture import to `~/.claude/CLAUDE.md`
once if not already present:

```markdown
## Constitution Capture — Global Hook
- @~/.claude/rules/constitution-capture.md
```

## Scheduler / headless environments

The installer is idempotent and non-interactive. In a fresh container:

1. `git clone <your-fork-url>` (or `gh repo create my-ztn --template <upstream>`)
2. `pip install -r minder-ztn/zettelkasten/_system/scripts/requirements.txt`
3. `./minder-ztn/integrations/claude-code/install.sh`

## Why symlinks via `built/` instead of direct symlinks

- The repo source uses `{{MINDER_ZTN_BASE}}` placeholders so that paths
  resolve against wherever the repo is cloned.
- Another user cloning the repo to a different path needs paths
  rendered against THEIR local clone — not hardcoded to one machine.
- `built/` is the rendered output, gitignored, machine-local.
- Symlinks point to `built/` so global `~/.claude/` consumers still get
  the path-resolved versions.

## Why not store directly in `~/.claude/rules/`?

- That path is outside the repo — updates cannot be tracked in git.
- Fresh machines and scheduler containers do not have it populated.
- Another user cloning the project would not get the hook.

Storing in the repo + symlinking + rendering keeps three properties:
version control, stable local path, and machine-portable paths.

## Add a new rule or skill

1. Drop the new file into the right `integrations/claude-code/{rules,skills,commands}/` subdir.
2. Use `{{MINDER_ZTN_BASE}}` for any reference to the data root.
3. Re-run `install.sh` — symlinks are picked up automatically (skills/commands by directory listing).
4. For new rules: add a row to the table above and the `@` import in `~/.claude/CLAUDE.md`.
