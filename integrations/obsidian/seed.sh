#!/usr/bin/env bash
# minder-ztn — Obsidian vault seeder.
#
# Idempotently seeds Obsidian configuration for the ZTN vault. Run by
# integrations/claude-code/install.sh after Claude integration is wired,
# but also safe to run standalone.
#
# Behaviour:
#   - If <vault>/.obsidian/ does not exist, copies vault-config/ there.
#   - If <vault>/minder-ztn.md does not exist, copies the dashboard
#     template there. A legacy <vault>/HOME.md (pre-rename) is migrated
#     to minder-ztn.md preserving any owner edits.
#   - Otherwise, leaves the file alone (friend's customisations are
#     preserved). To force-refresh, pass --force (overwrites both).
#
# Engine improvements to vault-config flow to friends via sync_engine.sh
# (the source under integrations/obsidian/ is engine-synced); the live
# .obsidian/ in the friend's vault stays the friend's own.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VAULT="${MINDER_ZTN_BASE:-$REPO_ROOT/zettelkasten}"

FORCE=0
RESET_GRAPH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --reset-graph) RESET_GRAPH=1 ;;
    --vault) VAULT="$2"; shift ;;
    -h|--help)
      sed -n '2,18p' "$0"
      echo
      echo "Usage: $0 [--force] [--reset-graph] [--vault PATH]"
      echo
      echo "  --force        wipe and re-seed everything (with backup)"
      echo "  --reset-graph  restore graph.json defaults only (color groups,"
      echo "                 forces, default filter) — useful after Obsidian"
      echo "                 erased your color groups when you tweaked filters"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { printf '[obsidian] %s\n' "$*"; }

if [ ! -d "$VAULT" ]; then
  echo "error: vault directory not found: $VAULT" >&2
  exit 2
fi

# --- Targeted reset: graph.json only ---
# Useful when Obsidian wiped color groups / forces during filter tweaks.
# Backs up the existing graph.json before overwrite.
if [ "$RESET_GRAPH" -eq 1 ]; then
  GRAPH_DST="$VAULT/.obsidian/graph.json"
  GRAPH_SRC="$SCRIPT_DIR/vault-config/graph.json"
  GRAPH_DEFAULTS="$VAULT/.obsidian/graph-defaults.json"
  if [ ! -f "$GRAPH_SRC" ]; then
    echo "error: source graph.json missing at $GRAPH_SRC" >&2
    exit 2
  fi
  if [ -f "$GRAPH_DST" ]; then
    cp "$GRAPH_DST" "$GRAPH_DST.bak-$(date +%Y%m%d-%H%M%S)"
    log "backed up current graph.json"
  fi
  cp "$GRAPH_SRC" "$GRAPH_DST"
  cp "$GRAPH_SRC" "$GRAPH_DEFAULTS"
  log "reset graph.json — color groups, forces, default filter restored"
  log "  reload Obsidian (Cmd+P → Reload app without saving) to pick up"
  log "  (in-vault Reset Graph button reads from .obsidian/graph-defaults.json)"
  exit 0
fi

OBS_DST="$VAULT/.obsidian"
OBS_SRC="$SCRIPT_DIR/vault-config"
DASHBOARD_DST="$VAULT/minder-ztn.md"
DASHBOARD_SRC="$SCRIPT_DIR/minder-ztn.template.md"
LEGACY_HOME="$VAULT/HOME.md"

# Migration: the dashboard was previously named HOME.md. If a legacy
# HOME.md exists and minder-ztn.md does not, rename it preserving owner
# edits.
if [ -f "$LEGACY_HOME" ] && [ ! -f "$DASHBOARD_DST" ]; then
  mv "$LEGACY_HOME" "$DASHBOARD_DST"
  log "migrated HOME.md -> minder-ztn.md (preserved your edits)"
fi

# --- .obsidian/ seed ---
if [ -d "$OBS_DST" ] && [ "$FORCE" -ne 1 ]; then
  log "skipped .obsidian/ — already exists at $OBS_DST"
  log "  (run with --force to overwrite — your customisations will be lost)"
else
  if [ "$FORCE" -eq 1 ] && [ -d "$OBS_DST" ]; then
    BACKUP="$VAULT/.obsidian.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$OBS_DST" "$BACKUP"
    log "force: backed up existing .obsidian/ to $BACKUP"
  fi
  mkdir -p "$OBS_DST"
  # Copy entire vault-config tree (top-level *.json + snippets/, plugins/
  # if/when we add bundled plugin configs). Shell glob with `cp -R` mirrors
  # the directory structure under .obsidian/.
  for entry in "$OBS_SRC"/*; do
    [ -e "$entry" ] || continue
    cp -R "$entry" "$OBS_DST/"
  done
  log "seeded .obsidian/ at $OBS_DST"
fi

# --- Always-refresh: graph defaults snapshot ---
# minder-ztn.md ships a "Reset graph" button that reads this file and
# copies it to .obsidian/graph.json. Refresh on every seed run (not
# only on full reseed) so engine improvements to graph defaults reach
# the in-vault button without requiring --force.
if [ -f "$OBS_SRC/graph.json" ] && [ -d "$OBS_DST" ]; then
  cp "$OBS_SRC/graph.json" "$OBS_DST/graph-defaults.json"
fi

# --- minder-ztn.md seed ---
if [ -f "$DASHBOARD_DST" ] && [ "$FORCE" -ne 1 ]; then
  log "skipped minder-ztn.md — already exists at $DASHBOARD_DST"
else
  cp "$DASHBOARD_SRC" "$DASHBOARD_DST"
  log "seeded minder-ztn.md at $DASHBOARD_DST"
fi

# --- Help docs into the vault ---
# Obsidian resolves links relative to the vault root. Engine docs live
# outside the vault (in repo `docs/` and `integrations/obsidian/`), so
# we copy a curated subset into `<vault>/5_meta/help/` for HOME and
# bookmarks to link to. Idempotent: only copies when missing or --force.
HELP_DST="$VAULT/5_meta/help"
mkdir -p "$HELP_DST"
declare -a HELP_PAIRS=(
  "$SCRIPT_DIR/guide.md|$HELP_DST/guide.md"
  "$SCRIPT_DIR/views.md|$HELP_DST/views.md"
  "$REPO_ROOT/docs/privacy.md|$HELP_DST/privacy.md"
  "$REPO_ROOT/docs/CHANGELOG.md|$HELP_DST/CHANGELOG.md"
)
for pair in "${HELP_PAIRS[@]}"; do
  src="${pair%%|*}"
  dst="${pair##*|}"
  [ -f "$src" ] || continue
  if [ -f "$dst" ] && [ "$FORCE" -ne 1 ]; then
    log "skipped $(basename "$dst") — already exists"
  else
    cp "$src" "$dst"
    log "seeded $(basename "$dst")"
  fi
done

# --- Community plugins — detect missing and warn ---
# Plugin IDs in community-plugins.json auto-enable when their main.js lands
# under .obsidian/plugins/<id>/. Until then, the dashboard's [live] blocks
# in minder-ztn.md render as code.
RECOMMENDED_PLUGINS=("dataview" "obsidian-tasks-plugin" "obsidian-front-matter-title-plugin")
MISSING_PLUGINS=()
for pid in "${RECOMMENDED_PLUGINS[@]}"; do
  if [ ! -f "$OBS_DST/plugins/$pid/main.js" ]; then
    MISSING_PLUGINS+=("$pid")
  fi
done

cat <<EOF

[obsidian] done.

Open the vault in Obsidian:
  Obsidian → Open folder as vault → $VAULT

Start at minder-ztn.md (Cmd+O → "HOME").
EOF

if [ ${#MISSING_PLUGINS[@]} -gt 0 ]; then
  cat <<EOF

[obsidian] Recommended community plugins not yet installed:
EOF
  for pid in "${MISSING_PLUGINS[@]}"; do
    case "$pid" in
      dataview) desc='Browse → search "Dataview" by Michael Brenan (NB: Settings → Dataview → enable JavaScript Queries)' ;;
      obsidian-tasks-plugin) desc='Browse → search "Tasks" by Clare Macrae' ;;
      obsidian-front-matter-title-plugin) desc='Browse → search "Front Matter Title" by snezhig (NB: enable Features after install)' ;;
      *) desc="" ;;
    esac
    printf '  - %-25s %s\n' "$pid" "$desc"
  done
  cat <<EOF

Install them in one pass:
  Obsidian → Settings → Community plugins → Turn on community plugins
  → Browse → search by author/name above → Install + Enable

(Once installed, they auto-enable on next launch — your
community-plugins.json already lists their IDs.)

File explorer cleanup is handled by the shipped CSS snippet
"ztn-hide-engine-paths" — already enabled by the seeder via
appearance.json. No plugin needed.

Full guide: docs/obsidian.md
EOF
fi

cat <<EOF

Settings preserved on next sync; re-run with --force only if you want
to reset .obsidian/ and minder-ztn.md to engine defaults.
EOF
