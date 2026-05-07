#!/usr/bin/env bash
# Last-resort save for autonomous scheduler ticks when /ztn:save is unavailable
# (skill-not-found in cloud-runner registry). Mirrors /ztn:save --auto behavior:
# stages owner-data, surfaces engine drift to CLARIFICATIONS as a note (does
# not block, does not commit engine paths). Pushes to origin/main.
#
# Usage:
#   scripts/scheduler-fallback-save.sh "<commit message>"
#
# Exit codes:
#   0 — committed + pushed (or no-op: nothing to commit)
#   2 — git operation failed (commit/push error; see stderr)
#
# Engine boundary mirrored from .engine-manifest.yml `engine:` + `template:`.
# Keep in sync when manifest changes (rare; engine layout is stable).

set -euo pipefail

MESSAGE="${1:-scheduler: fallback save}"
CLAR="zettelkasten/_system/state/CLARIFICATIONS.md"
TS="$(date -u +%Y-%m-%dT%H:%MZ)"

is_engine() {
  local p="$1"
  case "$p" in
    integrations/*|scripts/*|docs/*|.claude/*|.github/*) return 0 ;;
    .gitignore|.engine-manifest.yml|LICENSE|CONTRIBUTING.md|README.md) return 0 ;;
    zettelkasten/_system/docs/*) return 0 ;;
    zettelkasten/_system/scripts/*) return 0 ;;
    zettelkasten/_system/state/batches/README.md) return 0 ;;
    zettelkasten/_system/registries/FOLDERS.md) return 0 ;;
    zettelkasten/_system/registries/CONCEPT_NAMING.md) return 0 ;;
    zettelkasten/_system/registries/CONCEPT_TYPES.md) return 0 ;;
    zettelkasten/_system/registries/AGENT_LENSES.md) return 0 ;;
    zettelkasten/_system/registries/lenses/*) return 0 ;;
    zettelkasten/5_meta/CONCEPT.md) return 0 ;;
    zettelkasten/5_meta/PROCESSING_PRINCIPLES.md) return 0 ;;
    zettelkasten/5_meta/templates/*) return 0 ;;
    zettelkasten/5_meta/starter-pack/*) return 0 ;;
    zettelkasten/5_skills/*) return 0 ;;
    zettelkasten/0_constitution/CONSTITUTION.md) return 0 ;;
    zettelkasten/_records/README.md) return 0 ;;
    zettelkasten/1_projects/README.md) return 0 ;;
    zettelkasten/2_areas/README.md) return 0 ;;
    zettelkasten/3_resources/README.md) return 0 ;;
  esac
  case "$p" in
    *.template.md|*.template.yaml|*.template.yml|*.template) return 0 ;;
  esac
  return 1
}

declare -a ENGINE_DIRTY=()
declare -a OWNER_DIRTY=()

while IFS= read -r line; do
  [ -z "$line" ] && continue
  # Porcelain format: 'XY path' (status code is 2 chars, then space). For
  # renames the path field is 'old -> new' — take the new side.
  path="${line:3}"
  path="${path##* -> }"
  # Strip surrounding quotes if path had spaces (porcelain quotes those)
  path="${path#\"}"
  path="${path%\"}"
  if is_engine "$path"; then
    ENGINE_DIRTY+=("$path")
  else
    OWNER_DIRTY+=("$path")
  fi
done < <(git status --porcelain)

# Engine drift — log to CLARIFICATIONS, do not block. Matches /ztn:save --auto.
if [ ${#ENGINE_DIRTY[@]} -gt 0 ]; then
  mkdir -p "$(dirname "$CLAR")"
  touch "$CLAR"
  grep -q '^### Scheduler failures$' "$CLAR" || printf '\n### Scheduler failures\n' >> "$CLAR"
  printf -- '- %s scheduler-fallback: engine drift skipped from auto-commit: %s\n' \
    "$TS" "${ENGINE_DIRTY[*]}" >> "$CLAR"
  # Ensure CLARIFICATIONS itself is staged for this commit
  case " ${OWNER_DIRTY[*]:-} " in
    *" $CLAR "*) ;;
    *) OWNER_DIRTY+=("$CLAR") ;;
  esac
fi

if [ ${#OWNER_DIRTY[@]} -eq 0 ]; then
  echo "scheduler-fallback-save: nothing to commit"
  exit 0
fi

git add -- "${OWNER_DIRTY[@]}"

# Sanity: refuse if staging accidentally picked up an engine path
STAGED_ENGINE=()
while IFS= read -r p; do
  [ -z "$p" ] && continue
  if is_engine "$p"; then
    STAGED_ENGINE+=("$p")
  fi
done < <(git diff --cached --name-only)
if [ ${#STAGED_ENGINE[@]} -gt 0 ]; then
  echo "scheduler-fallback-save: aborting — engine path landed in stage despite filter:" >&2
  printf '  %s\n' "${STAGED_ENGINE[@]}" >&2
  git reset HEAD -- "${STAGED_ENGINE[@]}" >/dev/null 2>&1 || true
  exit 2
fi

if git diff --cached --quiet; then
  echo "scheduler-fallback-save: nothing staged after filter"
  exit 0
fi

git commit -m "$MESSAGE [scheduled, save-fallback]" || exit 2
git push origin main || exit 2
echo "scheduler-fallback-save: committed + pushed"
