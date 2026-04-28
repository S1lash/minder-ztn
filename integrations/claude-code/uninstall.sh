#!/usr/bin/env bash
# minder-ztn — remove Claude Code integration symlinks.
#
# Removes only symlinks pointing into THIS repo. Untouched: any
# unrelated entries in ~/.claude/{rules,commands,skills}, including
# files backed up by install.sh (those live under ~/.claude/.minder-ztn-backup-*).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

remove_if_points_into_repo() {
  local p="$1"
  if [ -L "$p" ]; then
    local target
    target="$(readlink "$p")"
    case "$target" in
      "$REPO_ROOT"/*)
        rm "$p"
        echo "[uninstall] removed: $p"
        ;;
    esac
  fi
}

for d in "$CLAUDE_HOME/rules" "$CLAUDE_HOME/commands" "$CLAUDE_HOME/skills"; do
  [ -d "$d" ] || continue
  for entry in "$d"/*; do
    remove_if_points_into_repo "$entry"
  done
done

echo "[uninstall] done. Backups (if any) preserved at $CLAUDE_HOME/.minder-ztn-backup-*"
