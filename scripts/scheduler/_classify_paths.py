#!/usr/bin/env python3
# Classify paths from `git status --porcelain` output as engine vs owner-data
# using `.engine-manifest.yml` as the single source of truth. Stdin: one path
# per line. Stdout: `ENGINE\t<path>` or `OWNER\t<path>` per line.
#
# Used by stage.sh so the engine-boundary definition lives in exactly one
# place (the manifest) rather than being duplicated as a hardcoded case
# statement.

import sys
from pathlib import Path

# `scripts/` on the path so the shared primitives are importable. Both modules
# used here are dependency-free on purpose: this helper runs inside the
# scheduler sandbox, where PyYAML is not guaranteed to be installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.manifest import read_section_lite  # noqa: E402
from lib.portable import configure_stdin, emit_lines  # noqa: E402


def load_engine_patterns(manifest_path: Path) -> tuple[list[str], list[str]]:
    dirs: list[str] = []
    files: list[str] = []
    for path in read_section_lite(manifest_path, "engine"):
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

    # Stdin carries owner filenames, which are not ASCII. Without this it is
    # decoded through the platform default and a Cyrillic path raises on
    # Windows, killing the tick's staging outright.
    configure_stdin()

    # `emit_lines` rather than `print`: stage.sh reads this stdout with
    # `while IFS=$'\t' read -r label path`, and python's text-mode stdout on Git
    # Bash would append a `\r` to every path — which then reaches `git add` as
    # part of the pathspec and fails, silently costing the tick its commit.
    emit_lines(
        f"{'ENGINE' if is_engine(path, dirs, files) else 'OWNER'}\t{path}"
        for path in (raw.strip() for raw in sys.stdin)
        if path
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
