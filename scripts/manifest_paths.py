#!/usr/bin/env python3
"""Emit one manifest section as LF-separated lines, for a shell caller.

Exists so `sync_engine.sh` no longer parses the manifest through an inline
`python3 - <<'PY'` heredoc. That heredoc printed with a bare `print()`, and
python's text-mode stdout writes CRLF on Git Bash — so every path the shell
read carried a trailing `\\r`, every `git cat-file` on it failed, and the script
reported each engine path as "not in upstream, kept local" before exiting 0.
A friend's `/ztn:update` silently applied nothing for weeks.

The fix is not "remember to reconfigure stdout in that heredoc": it is to stop
having ad-hoc heredocs on the boundary at all. This file is the boundary, and
it uses `lib.portable.emit_lines`, which the portability gate can verify.

Usage:
  python3 scripts/manifest_paths.py --section engine
  python3 scripts/manifest_paths.py --section template
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.manifest import LIST_SECTIONS, load_manifest, repo_root  # noqa: E402
from lib.portable import emit_lines  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Emit one manifest section, one path per line")
    ap.add_argument("--section", required=True, choices=LIST_SECTIONS)
    args = ap.parse_args(argv)

    manifest = load_manifest(repo_root())
    emit_lines(str(p).rstrip("/") for p in manifest.get(args.section, []) or [])
    return 0


if __name__ == "__main__":
    sys.exit(main())
