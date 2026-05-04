#!/usr/bin/env bash
# Sync engine paths from upstream/main into this clone.
#
# For friends (and the personal instance) — pulls engine updates that
# the upstream maintainer has shipped, without touching local data
# (records, knowledge, registries, constitution principles, SOUL, etc).
#
# Reads .engine-manifest.yml. For each `engine:` path, fetches the
# upstream version and overwrites the local path. `template:` paths are
# DELIBERATELY skipped — they seed once at clone time and are then
# friend's data.
#
# Preconditions:
#   - git remote `upstream` configured and reachable
#   - working tree clean (script aborts if dirty in any engine path)
#   - python3 + PyYAML (used to parse the manifest)
#
# Usage:
#   scripts/sync_engine.sh                # fetch + apply
#   scripts/sync_engine.sh --dry-run      # show what would change
#   scripts/sync_engine.sh --remote name  # use a remote other than upstream

set -euo pipefail

REMOTE="upstream"
BRANCH="main"
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --remote) REMOTE="$2"; shift ;;
    --branch) BRANCH="$2"; shift ;;
    -h|--help)
      sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "error: remote '$REMOTE' not configured." >&2
  echo "  add it: git remote add $REMOTE <url-to-minder-ztn-skeleton>" >&2
  exit 2
fi

MANIFEST=".engine-manifest.yml"
if [ ! -f "$MANIFEST" ]; then
  echo "error: $MANIFEST not found at repo root" >&2
  exit 2
fi

echo "[sync] fetching $REMOTE/$BRANCH ..."
git fetch "$REMOTE" "$BRANCH"

# Read engine paths from manifest via python3 (yaml).
mapfile -t ENGINE_PATHS < <(
  python3 - "$MANIFEST" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    m = yaml.safe_load(f)
for p in m.get("engine", []):
    print(p.rstrip("/"))
PY
)

if [ ${#ENGINE_PATHS[@]} -eq 0 ]; then
  echo "error: no engine paths in $MANIFEST" >&2
  exit 2
fi

# Abort if any engine path has uncommitted local changes.
DIRTY=0
for p in "${ENGINE_PATHS[@]}"; do
  if ! git diff --quiet -- "$p" 2>/dev/null || \
     ! git diff --cached --quiet -- "$p" 2>/dev/null; then
    echo "  ! dirty: $p" >&2
    DIRTY=1
  fi
done
if [ $DIRTY -ne 0 ]; then
  echo "error: engine paths have uncommitted changes — commit or stash first." >&2
  exit 2
fi

if [ $DRY_RUN -eq 1 ]; then
  echo "[sync] dry-run: would overwrite the following paths from $REMOTE/$BRANCH:"
  for p in "${ENGINE_PATHS[@]}"; do
    echo "  - $p"
    git --no-pager diff --stat "$REMOTE/$BRANCH" -- "$p" 2>/dev/null || true
  done
  echo "[sync] (dry-run) done. no changes applied."
  exit 0
fi

echo "[sync] checking out engine paths from $REMOTE/$BRANCH ..."
for p in "${ENGINE_PATHS[@]}"; do
  # `git checkout <ref> -- <path>` works for both files and directories.
  if git cat-file -e "$REMOTE/$BRANCH:$p" 2>/dev/null; then
    git checkout "$REMOTE/$BRANCH" -- "$p"
    echo "  + $p"
  else
    # Path may have been removed upstream — leave local copy alone.
    echo "  · $p (not in upstream, kept local)"
  fi
done

echo
echo "[sync] applying migrations (if any) ..."
MIG_DIR="scripts/migrations"
if [ -d "$MIG_DIR" ]; then
  shopt -s nullglob
  ran=0
  for m in "$MIG_DIR"/*.sh; do
    name="$(basename "$m")"
    marker=".engine-migrations-applied"
    touch "$marker"
    if grep -qxF "$name" "$marker"; then
      continue
    fi
    echo "  > $name"
    bash "$m"
    echo "$name" >> "$marker"
    ran=$((ran + 1))
  done
  if [ $ran -eq 0 ]; then
    echo "  (none pending)"
  fi
fi

cat <<EOF

[sync] done.

Review the diff:    git status
Run tests:          (your test suite — engine ships pytest under zettelkasten/_system/scripts/tests/)
Re-install Claude:  ./integrations/claude-code/install.sh

If something looks wrong, revert with:  git restore --staged --worktree .
EOF
