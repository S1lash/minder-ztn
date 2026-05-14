#!/usr/bin/env python3
# Classify paths from `git status --porcelain` output as engine vs owner-data
# using `.engine-manifest.yml` as the single source of truth. Stdin: one path
# per line. Stdout: `ENGINE\t<path>` or `OWNER\t<path>` per line.
#
# Used by stage.sh so the engine-boundary definition lives in exactly one
# place (the manifest) rather than being duplicated as a hardcoded case
# statement.

import re
import sys
from pathlib import Path


def load_engine_patterns(manifest_path: Path) -> tuple[list[str], list[str]]:
    text = manifest_path.read_text(encoding="utf-8")
    dirs: list[str] = []
    files: list[str] = []
    section: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            head = line.split(":", 1)[0].strip()
            section = head if head in {"engine", "template", "exclude"} else None
            continue
        if section != "engine":
            continue
        m = re.match(r"^\s*-\s+(.+?)\s*$", line)
        if not m:
            continue
        path = m.group(1).strip().strip('"').strip("'")
        if path.endswith("/"):
            dirs.append(path)
        else:
            files.append(path)
    return dirs, files


# Conservative-safety prefixes. The manifest enumerates explicit engine
# subdirs (e.g. `integrations/claude-code/skills/`) but does not catch
# files dropped at the top of an engine-purpose directory tree (e.g. an
# ad-hoc `integrations/drift.md`). Owner files have no legitimate reason
# to live at these roots, so treat anything inside as engine even when
# not explicitly listed. This preserves the safety net the old hardcoded
# classifier provided, while the manifest stays the positive source of
# truth for what release_engine.py actually ships.
ENGINE_PREFIXES = (
    "integrations/",
    "scripts/",
    "docs/",
    ".claude/",
    ".github/",
)


def is_engine(path: str, dirs: list[str], files: list[str]) -> bool:
    if path in files:
        return True
    for d in dirs:
        if path.startswith(d):
            return True
    for prefix in ENGINE_PREFIXES:
        if path.startswith(prefix):
            return True
    if path.endswith((".template.md", ".template.yaml", ".template.yml", ".template")):
        return True
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = repo_root / ".engine-manifest.yml"
    if not manifest.exists():
        print(f"_classify_paths: {manifest} missing", file=sys.stderr)
        return 2

    dirs, files = load_engine_patterns(manifest)
    if not dirs and not files:
        print("_classify_paths: no engine entries parsed from manifest", file=sys.stderr)
        return 2

    for raw in sys.stdin:
        path = raw.strip()
        if not path:
            continue
        label = "ENGINE" if is_engine(path, dirs, files) else "OWNER"
        print(f"{label}\t{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
