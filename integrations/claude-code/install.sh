#!/usr/bin/env bash
# minder-ztn — Claude Code integration installer.
#
# Renders templated paths in integrations/claude-code/{rules,commands,skills}/
# (placeholder {{MINDER_ZTN_BASE}}) into integrations/claude-code/built/,
# then symlinks ~/.claude/{rules,commands,skills}/ entries to the rendered
# files. Existing entries that would be overwritten are moved to a
# timestamped backup directory under ~/.claude/.minder-ztn-backup-*.
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
BUILT_SKILLS="$BUILT/skills"

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

# --- Render templates into built/ ---
log "rendering templates into $BUILT"
rm -rf "$BUILT"
mkdir -p "$BUILT_RULES" "$BUILT_COMMANDS" "$BUILT_SKILLS"

for f in "$SRC_RULES"/*.md; do
  [ -f "$f" ] || continue
  render "$f" "$BUILT_RULES/$(basename "$f")"
done

for f in "$SRC_COMMANDS"/*.md; do
  [ -f "$f" ] || continue
  render "$f" "$BUILT_COMMANDS/$(basename "$f")"
done

for skill_dir in "$SRC_SKILLS"/*/; do
  [ -d "$skill_dir" ] || continue
  skill_name="$(basename "$skill_dir")"
  mkdir -p "$BUILT_SKILLS/$skill_name"
  while IFS= read -r -d '' f; do
    rel="${f#$skill_dir}"
    out="$BUILT_SKILLS/$skill_name/$rel"
    if file --mime "$f" 2>/dev/null | grep -q "charset=binary"; then
      mkdir -p "$(dirname "$out")"
      cp "$f" "$out"
    else
      render "$f" "$out"
    fi
  done < <(find "$skill_dir" -type f -print0)
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

# Skills (entire dir per skill)
for skill_dir in "$BUILT_SKILLS"/*/; do
  [ -d "$skill_dir" ] || continue
  skill_name="$(basename "$skill_dir")"
  link "${skill_dir%/}" "$TARGET_SKILLS/$skill_name"
done

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
  awk -v begin="$BEGIN_MARK" -v end="$END_MARK" -v block="$(managed_block)" '
    $0 == begin { skip = 1; print block; next }
    $0 == end   { skip = 0; next }
    !skip       { print }
  ' "$CLAUDE_MD" > "$CLAUDE_MD.tmp" && mv "$CLAUDE_MD.tmp" "$CLAUDE_MD"
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

cat <<EOF

[install] done.

Wired into ~/.claude/CLAUDE.md (managed block):
  - @~/.claude/rules/ztn.md                    (search triggers, decision-check discovery)
  - @~/.claude/rules/constitution-capture.md   (global capture hook)
  - @~/.claude/rules/constitution-core.md      (axioms / principles / rules)

Restart Claude Code (open a new session) to pick up the rules.
Re-run this installer any time after a 'git pull' on minder-ztn — it is
idempotent and refreshes the managed block in place.

EOF
