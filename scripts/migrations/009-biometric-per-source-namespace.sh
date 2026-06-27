#!/usr/bin/env bash
# 009-biometric-per-source-namespace — namespace the biometric layer per device.
#
# The metric-day pipeline now stores records + derived state per wearable
# source so a user wearing two devices (e.g. garmin + oura) keeps each
# device's records and σ-baselines isolated (a shared store would collide
# same-date records and pool two sensors into one baseline). Existing
# single-source data was implicitly Garmin, so it moves under `garmin/`.
#
# Scope note: this touches the AUTO-EMITTED biometric layer only — records
# under `_records/biometric/` are machine-generated and regenerable from the
# processed sources (see `_records/biometric/README.md` "Never hand-edit"),
# plus the derived state/views. It does NOT touch the hand-authored knowledge,
# constitution, or registry layers the migration contract protects.
#
# Idempotent: re-running after the `garmin/` subdir exists is a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZK="$REPO_ROOT/zettelkasten"

# (dir, keep-pattern) — move every top-level FILE except names matching keep.
migrate_dir() {
    local dir="$1" keep="$2"
    [[ -d "$dir" ]] || { echo "info: $dir absent — skip"; return 0; }
    if [[ -d "$dir/garmin" ]]; then
        echo "info: $dir/garmin already exists — no-op"
        return 0
    fi
    local moved=0
    mkdir -p "$dir/garmin"
    shopt -s nullglob
    for f in "$dir"/*; do
        [[ -f "$f" ]] || continue                 # skip subdirs
        local base; base="$(basename "$f")"
        [[ -n "$keep" && "$base" == $keep ]] && continue
        mv "$f" "$dir/garmin/$base"
        moved=$((moved + 1))
    done
    shopt -u nullglob
    echo "moved $moved file(s) into $dir/garmin/"
}

migrate_dir "$ZK/_records/biometric"        "README.md"
migrate_dir "$ZK/_system/state/biometric"   ""
migrate_dir "$ZK/_system/views/biometric"   ""

# Bring already-emitted records up to the namespaced schema. Two idempotent
# rewrites, each anchored on the OLD form so re-runs are no-ops:
#   1. `## Source` backlink gains one `../` (records moved one level deeper).
#   2. Frontmatter `garmin_estimate: true` → `device: <id>` + `device_estimate:
#      true`, and `garmin_metric_failures:` → `metric_failures:`, so historical
#      records match what the current emitter writes (lenses key on `device:`).
NL=$'\n'
fix_records() {
    local recdir="$ZK/_records/biometric"
    [[ -d "$recdir" ]] || return 0
    local links=0 schema=0 f sid
    shopt -s nullglob
    for f in "$recdir"/*/*.md; do
        sid="$(basename "$(dirname "$f")")"
        if grep -q '\[\[\.\./\.\./_sources/processed/' "$f" 2>/dev/null; then
            sed -i.bak 's#\[\[\.\./\.\./_sources/processed/#[[../../../_sources/processed/#g' "$f"
            rm -f "$f.bak"; links=$((links + 1))
        fi
        if grep -q '^garmin_estimate: true$' "$f" 2>/dev/null; then
            sed -i.bak "s/^garmin_estimate: true\$/device: ${sid}\\${NL}device_estimate: true/" "$f"
            sed -i.bak 's/^garmin_metric_failures:/metric_failures:/' "$f"
            rm -f "$f.bak"; schema=$((schema + 1))
        fi
    done
    shopt -u nullglob
    echo "repaired $links backlink(s) + $schema record schema(s)"
}

fix_records

echo "009-biometric-per-source-namespace: done"
