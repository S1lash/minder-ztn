#!/usr/bin/env bash
# minder-ztn — Claude Code integration installer.
#
# Sets up user-level Claude Code discoverability for ZTN rules / commands /
# skills under ~/.claude/. Two layers:
#
#   - rules + commands carry the {{MINDER_ZTN_BASE}} placeholder. The
#     installer renders them into integrations/claude-code/built/ with the
#     placeholder substituted by the absolute path to <repo>/zettelkasten,
#     then symlinks ~/.claude/{rules,commands}/ entries to the rendered
#     files. This path keeps the constitution-capture hook + ambient
#     /ztn:capture-candidate / /ztn:check-decision reachable from any CWD.
#   - skills use repo-relative `zettelkasten/...` paths in their source
#     and need no rendering. The installer symlinks ~/.claude/skills/ztn-*
#     directly to the source under integrations/claude-code/skills/. The
#     committed `.claude/skills/` symlinks at the repo root handle the
#     project-level + cloud-Routines discovery layer — see README.md.
#
# Existing entries that would be overwritten are moved to a timestamped
# backup directory under ~/.claude/.minder-ztn-backup-*.
#
# Idempotent: re-running the installer refreshes rendered files and
# replaces stale symlinks. Safe after `git pull` or after moving the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INTEGR_ROOT="$SCRIPT_DIR"
MINDER_ZTN_BASE="$REPO_ROOT/zettelkasten"

SRC_RULES="$INTEGR_ROOT/rules"
SRC_COMMANDS="$INTEGR_ROOT/commands"
SRC_SKILLS="$INTEGR_ROOT/skills"

BUILT="$INTEGR_ROOT/built"
BUILT_RULES="$BUILT/rules"
BUILT_COMMANDS="$BUILT/commands"

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
TARGET_RULES="$CLAUDE_HOME/rules"
TARGET_COMMANDS="$CLAUDE_HOME/commands"
TARGET_SKILLS="$CLAUDE_HOME/skills"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$CLAUDE_HOME/.minder-ztn-backup-$TIMESTAMP"

log() { printf '[install] %s\n' "$*"; }

render() {
  # render <src-file> <dst-file>
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  sed "s|{{MINDER_ZTN_BASE}}|$MINDER_ZTN_BASE|g" "$src" > "$dst"
}

backup_if_exists() {
  # backup_if_exists <path>
  local p="$1"
  [ -e "$p" ] || [ -L "$p" ] || return 0
  # If it is already a symlink to the desired target, nothing to back up.
  if [ -L "$p" ] && [ "$(readlink "$p")" = "$2" ]; then
    return 0
  fi
  mkdir -p "$BACKUP_DIR"
  local rel="${p#$CLAUDE_HOME/}"
  local backup_path="$BACKUP_DIR/$rel"
  mkdir -p "$(dirname "$backup_path")"
  mv "$p" "$backup_path"
  log "backed up: $p -> $backup_path"
}

link() {
  # link <src> <dst>
  local src="$1" dst="$2"
  backup_if_exists "$dst" "$src"
  mkdir -p "$(dirname "$dst")"
  ln -sfn "$src" "$dst"
  log "linked: $dst -> $src"
}

log "repo root: $REPO_ROOT"
log "MINDER_ZTN_BASE: $MINDER_ZTN_BASE"

# --- Render templated rules + commands into built/ ---
# Skills carry no {{MINDER_ZTN_BASE}} placeholder (sources use repo-relative
# `zettelkasten/...` paths) — they are NOT rendered into built/ and the
# user-level symlinks below point directly to the source tree.
log "rendering templates into $BUILT"
rm -rf "$BUILT"
mkdir -p "$BUILT_RULES" "$BUILT_COMMANDS"

for f in "$SRC_RULES"/*.md; do
  [ -f "$f" ] || continue
  render "$f" "$BUILT_RULES/$(basename "$f")"
done

for f in "$SRC_COMMANDS"/*.md; do
  [ -f "$f" ] || continue
  render "$f" "$BUILT_COMMANDS/$(basename "$f")"
done

# --- Symlinks ~/.claude/ -> rendered files ---
log "creating symlinks under $CLAUDE_HOME"
mkdir -p "$TARGET_RULES" "$TARGET_COMMANDS" "$TARGET_SKILLS"

# Rules: integration-managed (templated) + zettelkasten-internal (auto-loaded)
for f in "$BUILT_RULES"/*.md; do
  [ -f "$f" ] || continue
  link "$f" "$TARGET_RULES/$(basename "$f")"
done
link "$MINDER_ZTN_BASE/_system/docs/constitution-capture.md" "$TARGET_RULES/constitution-capture.md"
link "$MINDER_ZTN_BASE/_system/views/constitution-core.md" "$TARGET_RULES/constitution-core.md"
# Communication baseline — universal presentation spine, hot in every session.
# Owner's calibration layers on top: SOUL → Context for Agents + the long-form playbook.
link "$MINDER_ZTN_BASE/_system/docs/communication-baseline.md" "$TARGET_RULES/communication-baseline.md"
# Engine doctrine — operating philosophy auto-loaded in every session.
# Every /ztn:* skill reads it; the symlink ensures it flows into ad-hoc
# Claude Code sessions in this repo too (e.g. when owner is debugging
# without invoking a skill).
link "$MINDER_ZTN_BASE/_system/docs/ENGINE_DOCTRINE.md" "$TARGET_RULES/ztn-engine-doctrine.md"

# Commands
for f in "$BUILT_COMMANDS"/*.md; do
  [ -f "$f" ] || continue
  link "$f" "$TARGET_COMMANDS/$(basename "$f")"
done

# Skills (entire dir per skill) — symlink directly to source. No render
# step (sources are placeholder-free), so user-level symlinks resolve to
# the same content as project-level `.claude/skills/` symlinks at the
# repo root. Edits to a SKILL.md source are picked up immediately by
# both layers; install.sh re-run is not required after skill edits.
for skill_dir in "$SRC_SKILLS"/*/; do
  [ -d "$skill_dir" ] || continue
  skill_name="$(basename "$skill_dir")"
  link "${skill_dir%/}" "$TARGET_SKILLS/$skill_name"
done

# Repair project-level `.claude/skills/` at the repo root. Cloud Routines and
# project-CWD sessions load skills from there, not from the user-level links
# above. On a clone where the committed symlinks did not survive (a Windows
# checkout with core.symlinks=false materialises them as text files), this
# heals the layout — symlink where supported, real-file copy as fallback.
ENSURE_SKILLS="$REPO_ROOT/scripts/scheduler/ensure-skills.sh"
if [ -f "$ENSURE_SKILLS" ]; then
  if ( cd "$REPO_ROOT" && bash "$ENSURE_SKILLS" --repair ); then
    log "verified project-level .claude/skills/ resolves"
  else
    log "WARNING: could not repair project-level .claude/skills/ — run 'bash scripts/sync_engine.sh' or re-clone"
  fi
fi

# --- Auto-wire @-imports into ~/.claude/CLAUDE.md ---
# Idempotent: managed block delimited by markers. Re-running install.sh
# rewrites the block in place. uninstall.sh strips it.
CLAUDE_MD="$CLAUDE_HOME/CLAUDE.md"
BEGIN_MARK="<!-- MINDER-ZTN BEGIN — managed by install.sh, do not edit by hand -->"
END_MARK="<!-- MINDER-ZTN END -->"

managed_block() {
  cat <<BLOCK
$BEGIN_MARK
## Zettelkasten (ZTN) — Personal Knowledge Base
- @~/.claude/rules/ztn.md

## Constitution Capture — Global Hook
- @~/.claude/rules/constitution-capture.md

## Communication baseline — how to present information
- @~/.claude/rules/communication-baseline.md

## Constitution — auto-loaded values & principles
- @~/.claude/rules/constitution-core.md
$END_MARK
BLOCK
}

if [ ! -f "$CLAUDE_MD" ]; then
  log "creating $CLAUDE_MD"
  mkdir -p "$CLAUDE_HOME"
  managed_block > "$CLAUDE_MD"
elif grep -qF "$BEGIN_MARK" "$CLAUDE_MD"; then
  log "refreshing managed block in $CLAUDE_MD"
  mkdir -p "$BACKUP_DIR"
  cp "$CLAUDE_MD" "$BACKUP_DIR/CLAUDE.md.before-refresh"
  # Splice the new block in via awk getline from a file. A multi-line
  # `-v block="$(managed_block)"` value is rejected by some awk builds
  # (macOS bwk awk: «awk: newline in string»), which silently no-ops the
  # refresh — so the block is read from a file, never from a var.
  managed_block > "$CLAUDE_MD.block"
  if awk -v begin="$BEGIN_MARK" -v end="$END_MARK" -v blockfile="$CLAUDE_MD.block" '
    $0 == begin { while ((getline line < blockfile) > 0) print line; close(blockfile); skip = 1; next }
    $0 == end   { skip = 0; next }
    !skip       { print }
  ' "$CLAUDE_MD" > "$CLAUDE_MD.tmp"; then
    mv "$CLAUDE_MD.tmp" "$CLAUDE_MD"
  fi
  # Clean temp files unconditionally — even if awk failed above (a failing
  # `awk && mv` under `set -e` would otherwise exit before cleanup).
  rm -f "$CLAUDE_MD.block" "$CLAUDE_MD.tmp"
else
  log "appending managed block to $CLAUDE_MD"
  mkdir -p "$BACKUP_DIR"
  cp "$CLAUDE_MD" "$BACKUP_DIR/CLAUDE.md.before-append"
  printf '\n' >> "$CLAUDE_MD"
  managed_block >> "$CLAUDE_MD"
fi

if [ -d "$BACKUP_DIR" ]; then
  log "previous entries backed up to: $BACKUP_DIR"
fi

# --- Obsidian vault seed (idempotent; skipped if .obsidian/ already exists) ---
OBSIDIAN_SEED="$REPO_ROOT/integrations/obsidian/seed.sh"
if [ -x "$OBSIDIAN_SEED" ]; then
  log "running Obsidian vault seeder"
  MINDER_ZTN_BASE="$MINDER_ZTN_BASE" "$OBSIDIAN_SEED" || log "obsidian seed failed (non-fatal)"
fi

cat <<EOF

[install] done.

Wired into ~/.claude/CLAUDE.md (managed block):
  - @~/.claude/rules/ztn.md                    (search triggers, decision-check discovery)
  - @~/.claude/rules/constitution-capture.md   (global capture hook)
  - @~/.claude/rules/communication-baseline.md (universal presentation spine)
  - @~/.claude/rules/constitution-core.md      (axioms / principles / rules)

Obsidian vault config:
  - Seeded into $MINDER_ZTN_BASE/.obsidian/ if not already present.
  - Open the vault: Obsidian → Open folder as vault → $MINDER_ZTN_BASE
  - Start at HOME.md (Cmd+O → "HOME").
  - Reset to engine defaults later: integrations/obsidian/seed.sh --force

Restart Claude Code (open a new session) to pick up the rules.
Re-run this installer any time after a 'git pull' on minder-ztn — it is
idempotent and refreshes the managed block in place.

EOF
