#!/usr/bin/env bash
# 006-describe-me-top-level-source — promote describe-me to a top-level source.
#
# Engine 0.30.0 registers `describe-me` as a first-class source row
# (`_sources/inbox/describe-me/`) instead of a `Skip Subdirs` exclusion
# nested under `crafted`. Owner self-descriptions added after bootstrap
# now flow through /ztn:process; `PROFILE.template.md` stays excluded
# via the engine-wide `*.template.md` rule.
#
# This script:
#   1. moves `_sources/inbox/crafted/describe-me/`    -> `_sources/inbox/describe-me/`
#   2. moves `_sources/processed/crafted/describe-me/` -> `_sources/processed/describe-me/`
#      (merge, never overwrite — collisions are left in place and reported)
#   3. renames a still-pristine (placeholder-heavy) `PROFILE.md` back to
#      `PROFILE.template.md` — older skeletons shipped the seed with the
#      suffix stripped; without the rename /ztn:process would ingest the
#      unfilled template as content
#   4. clears `describe-me` from the crafted row's Skip Subdirs cell in SOURCES.md
#   5. appends a `describe-me` row to SOURCES.md if absent
#
# Idempotent: re-running on a migrated repo is a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ZTN="$REPO_ROOT/zettelkasten"
SOURCES_LIVE="$ZTN/_system/registries/SOURCES.md"

merge_move() {
    # merge_move <src-dir> <dst-dir> — move contents, never overwrite.
    local src="$1" dst="$2"
    [[ -d "$src" ]] || return 0
    mkdir -p "$dst"
    ( cd "$src" && find . -type f -print0 ) | while IFS= read -r -d '' rel; do
        rel="${rel#./}"
        if [[ -e "$dst/$rel" ]]; then
            echo "warn: collision, left in place: $src/$rel"
        else
            mkdir -p "$dst/$(dirname "$rel")"
            mv "$src/$rel" "$dst/$rel"
        fi
    done
    # Remove the source dir only when fully drained.
    find "$src" -type d -empty -delete 2>/dev/null || true
    if [[ -d "$src" ]]; then
        echo "warn: $src not empty after merge — resolve collisions manually"
    fi
}

merge_move "$ZTN/_sources/inbox/crafted/describe-me" "$ZTN/_sources/inbox/describe-me"
merge_move "$ZTN/_sources/processed/crafted/describe-me" "$ZTN/_sources/processed/describe-me"
mkdir -p "$ZTN/_sources/inbox/describe-me" "$ZTN/_sources/processed/describe-me"
touch "$ZTN/_sources/inbox/describe-me/.gitkeep" "$ZTN/_sources/processed/describe-me/.gitkeep"

# Pristine-template guard: older skeletons shipped the profile seed as
# `PROFILE.md` (suffix stripped). If it is still placeholder-heavy
# (>= 5 `{LIKE THIS}` spans — same marker family /ztn:bootstrap detects),
# rename it to `PROFILE.template.md` so /ztn:process never ingests it.
PROFILE_MD="$ZTN/_sources/inbox/describe-me/PROFILE.md"
PROFILE_TMPL="$ZTN/_sources/inbox/describe-me/PROFILE.template.md"
PROFILE_OLD="$ZTN/_sources/inbox/describe-me/PROFILE.old.template.md"
if [[ -f "$PROFILE_MD" ]]; then
    placeholders=$(grep -coE '\{[A-Z][^{}]{4,}\}' "$PROFILE_MD" || true)
    if [[ "${placeholders:-0}" -ge 5 ]]; then
        if [[ ! -f "$PROFILE_TMPL" ]]; then
            mv "$PROFILE_MD" "$PROFILE_TMPL"
            echo "renamed pristine seed: PROFILE.md -> PROFILE.template.md (placeholder-heavy, $placeholders lines)"
        elif [[ ! -f "$PROFILE_OLD" ]]; then
            # Current template already synced in — park the stale seed under a
            # *.template.md name so /ztn:process never ingests the placeholders.
            mv "$PROFILE_MD" "$PROFILE_OLD"
            echo "renamed stale seed: PROFILE.md -> PROFILE.old.template.md (placeholder-heavy, $placeholders lines; review and delete)"
        else
            echo "warn: placeholder-heavy PROFILE.md left in place (PROFILE.template.md and PROFILE.old.template.md both exist) — rename or delete manually"
        fi
    fi
fi

if [[ ! -f "$SOURCES_LIVE" ]]; then
    echo "info: $SOURCES_LIVE not found — skipping registry rewrite (fresh clone or pre-bootstrap)"
    exit 0
fi

python3 - "$SOURCES_LIVE" <<'PY'
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
orig = text

# 1. Crafted row: drop `describe-me` from the Skip Subdirs cell.
#    Handles a bare cell and comma-separated lists.
def _crafted_row(match: re.Match) -> str:
    head, skip_cell, tail = match.group(1), match.group(2), match.group(3)
    entries = [e.strip() for e in skip_cell.split(",")]
    entries = [e for e in entries if e and e not in ("describe-me", "—", "-")]
    cell = ", ".join(entries) if entries else "—"
    return f"{head} {cell} {tail}"

crafted_re = re.compile(
    r"^(\|\s*crafted\s*\|[^\n]*?\|)\s*([^|\n]*describe-me[^|\n]*)\s*(\|[^\n]*)$",
    re.MULTILINE,
)
text = crafted_re.sub(_crafted_row, text)

# 2. Append describe-me row after the crafted row (if absent).
if not re.search(r"^\|\s*describe-me\s*\|", text, re.MULTILINE):
    row = (
        "| describe-me | `_sources/inbox/describe-me/` | transcript | flat-md | identity | — | "
        "Owner self-descriptions and identity reference material. Primary seed for `/ztn:bootstrap` "
        "SOUL.md draft; files added after bootstrap flow through `/ztn:process` as regular content. "
        "`PROFILE.template.md` is excluded by the engine-wide `*.template.md` rule. | active |"
    )
    crafted_line = re.search(r"^\|\s*crafted\s*\|[^\n]*$", text, re.MULTILINE)
    if crafted_line:
        end = crafted_line.end()
        text = text[:end] + "\n" + row + text[end:]
    else:
        # No crafted row (heavily customised registry) — append to Active Sources table.
        m = re.search(r"(## Active Sources\n.*?)(\n\n|\n---)", text, re.DOTALL)
        if m:
            text = text[: m.end(1)] + "\n" + row + text[m.end(1):]
        else:
            print("warn: could not locate Active Sources table — add the describe-me row manually")

if text != orig:
    p.write_text(text, encoding="utf-8")
    print(f"migrated: {p} — crafted Skip Subdirs cleared, describe-me row ensured")
else:
    print("info: SOURCES.md already migrated — no-op")
PY

echo "006-describe-me-top-level-source: done"
