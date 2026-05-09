#!/usr/bin/env bash
# 002-sources-family-column — Add `Family` column to SOURCES.md.
#
# Engine 0.22.0 introduces the `Family` column on SOURCES.md to drive
# /ztn:process branch routing (transcript / metric-day / recap). Existing
# rows are populated with `transcript` (the prior implicit default).
# Idempotent: re-running on an already-migrated file is a no-op.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCES_LIVE="$REPO_ROOT/zettelkasten/_system/registries/SOURCES.md"

if [[ ! -f "$SOURCES_LIVE" ]]; then
    echo "info: $SOURCES_LIVE not found — skipping (fresh clone or non-ZTN base)"
    exit 0
fi

# Idempotent guard: header already contains `| Family |` → no-op.
if grep -qE '^\|\s*ID\s*\|\s*Inbox Path\s*\|\s*Family\s*\|' "$SOURCES_LIVE"; then
    echo "info: SOURCES.md already has Family column — no-op"
    exit 0
fi

python3 - "$SOURCES_LIVE" <<'PY'
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")

# Header rewrite: insert `Family` column after `Inbox Path`.
header_old = re.compile(
    r"^\|\s*ID\s*\|\s*Inbox Path\s*\|\s*Layout\s*\|",
    re.MULTILINE,
)
text_new = header_old.sub(
    "| ID | Inbox Path | Family | Layout |",
    text,
)

# Separator rewrite — match the same column count under each header.
sep_old = re.compile(
    r"^\|---\|---\|---\|---\|---\|---\|---\|(---\|)?$",
    re.MULTILINE,
)


def _bump_sep(match: re.Match) -> str:
    s = match.group(0).rstrip("|")
    n = s.count("|")
    return ("|" + "---|" * (n + 1)).rstrip()


text_new = sep_old.sub(_bump_sep, text_new)

# Data rows: only rewrite rows that look like sources (not narrative).
# A source row begins with `| <kebab-id> | _sources/inbox/<id>/ |`.
row_re = re.compile(
    r"^(\|\s*([a-z0-9-]+)\s*\|\s*`_sources/inbox/[^`]+`\s*\|)\s*([a-z-]+)\s*\|",
    re.MULTILINE,
)


def _row(match: re.Match) -> str:
    head = match.group(1)
    layout = match.group(3)
    return f"{head} transcript | {layout} |"


text_new = row_re.sub(_row, text_new)

if text_new == text:
    print("info: no rewrite needed (table format unrecognised)")
    sys.exit(0)

p.write_text(text_new, encoding="utf-8")
print(f"migrated: {p} — Family column populated with `transcript` for existing rows")
PY

echo "002-sources-family-column: done"
