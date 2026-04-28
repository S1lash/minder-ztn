#!/usr/bin/env python3
"""Regenerate all derived views in one call.

Runs the generators in dependency order:
    1. gen_constitution_index   → _system/views/CONSTITUTION_INDEX.md
    2. gen_constitution_core    → _system/views/constitution-core.md
    3. render_soul_values       → _system/SOUL.md auto-zone (between markers)

Fail-fast: any step's non-zero exit propagates immediately — the remaining
steps are not run. All writes are idempotent (same inputs → same outputs
aside from the timestamp line).

Invocation:
    - Manually after editing `0_constitution/`
    - As the first step of every ZTN pipeline that reads derived views
      (`/ztn:process`, `/ztn:maintain`, `/ztn:lint`). This is the single
      consistent rule: every consumer regenerates before reading.
    - From scheduler tasks on the Claude platform

Usage:
    python3 regen_all.py [--dry-run]
                        [--strict-soul] [--write-soul-clarification]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def _run_step(script_name: str, extra_args: list[str], dry_run: bool) -> int:
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name)] + extra_args
    if dry_run and "--dry-run" not in extra_args:
        cmd.append("--dry-run")
    print(f"→ {script_name} " + " ".join(extra_args), file=sys.stderr)
    return subprocess.call(cmd)


def _soul_has_markers(soul_path: Path) -> bool:
    """SOUL marker presence is a prerequisite for render_soul_values.

    Until the SOUL integration step places the markers, render_soul_values
    would fail with a clear error. Skipping it keeps regen_all usable on
    fresh / pre-integration repos without manual flag juggling.
    """
    if not soul_path.exists():
        return False
    try:
        text = soul_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "<!-- AUTO-GENERATED FROM CONSTITUTION" in text
        and "<!-- END AUTO-GENERATED -->" in text
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="propagate --dry-run to every step (no writes)",
    )
    parser.add_argument(
        "--strict-soul", action="store_true",
        help="fail if SOUL.md is missing markers; default is to skip with "
             "an info message (exit code 3)",
    )
    parser.add_argument(
        "--write-soul-clarification", action="store_true",
        help="pass --write-clarification to render_soul_values",
    )
    args = parser.parse_args(argv)

    # Step 1: index
    rc = _run_step("gen_constitution_index.py", [], args.dry_run)
    if rc != 0:
        print("regen_all: gen_constitution_index failed", file=sys.stderr)
        return rc

    # Step 2: core (single file, all scopes visible)
    rc = _run_step("gen_constitution_core.py", [], args.dry_run)
    if rc != 0:
        print("regen_all: gen_constitution_core failed", file=sys.stderr)
        return rc

    # Step 3: SOUL — may be skipped if markers aren't in place yet
    from _common import system_dir  # local import — avoids polluting module load
    soul_path = system_dir() / "SOUL.md"
    if not _soul_has_markers(soul_path):
        if args.strict_soul:
            print(
                f"regen_all: SOUL.md at {soul_path} has no auto-zone markers "
                "(--strict-soul requires them)",
                file=sys.stderr,
            )
            return 2
        print(
            f"info: SOUL.md has no auto-zone markers yet — render_soul_values "
            "skipped. Add markers in the SOUL integration step.",
            file=sys.stderr,
        )
        # Distinct exit code so pipeline callers can notice partial completion
        # without mistaking it for a full run. Index + core are valid; SOUL is
        # the only view that was skipped.
        return 3

    soul_args: list[str] = []
    if args.write_soul_clarification:
        soul_args.append("--write-clarification")
    rc = _run_step("render_soul_values.py", soul_args, args.dry_run)
    if rc != 0:
        print("regen_all: render_soul_values failed", file=sys.stderr)
        return rc

    return 0


if __name__ == "__main__":
    sys.exit(main())
