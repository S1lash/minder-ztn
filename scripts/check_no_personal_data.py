#!/usr/bin/env python3
"""
Personal-data linter.

Reads `.engine-manifest.yml` to learn which paths are engine + template
(those must contain no personal data identifying the owner of this
specific instance). Greps each path for blacklist patterns and reports.

Exit code:
  0 — no leaks found
  1 — leaks found (CI fails)

Usage:
  scripts/check_no_personal_data.py            # human report
  scripts/check_no_personal_data.py --quiet    # machine-readable, hits only
  scripts/check_no_personal_data.py --extra-pattern '\bAlice\b'

Manifest must be at repo root: `.engine-manifest.yml`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# Blacklist of regex patterns that must not appear in engine + template
# files. Word-boundary aware so `Iliya` doesn't match `Ilyaminate`.
DEFAULT_BLACKLIST: list[str] = [
    r"\bs1lash\b",
    r"\bIlya\b",
    r"\bИлья\b",
    r"\bИльи\b",
    r"\bИльёй\b",
    r"\bИлье\b",
    r"\bИльей\b",
    r"\bIlyas\b",
    r"\bKuzmichev\b",
    r"\bКузьмичев\b",
    r"\bКузьмичёв\b",
    r"\biliko\b",
    r"iliko\.from\.ge",
    r"\bTbilisi\b",
    r"\bТбилиси\b",
    r"\bBPC\b",
    r"\bRadar Payments\b",
    r"\bSilk Code\b",
    r"\bilya-kuzmichev\b",
    r"\bilya\.kuzmichev\b",
    # Ilya's coworker — used as illustrative example; replace with synthetic
    r"\bvasily-grigoryev\b",
    r"\bVasily Grigoryev\b",
    r"\bВасилий\b(?! Иванов)",  # allow synthetic «Василий Иванов» if introduced
]

# Filename suffixes considered text. Anything else skipped.
TEXT_SUFFIXES = {
    ".md", ".yml", ".yaml", ".sh", ".py", ".txt", ".json", ".toml", ".cfg", ".ini",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict:
    p = root / ".engine-manifest.yml"
    if not p.exists():
        print(f"error: manifest not found at {p}", file=sys.stderr)
        sys.exit(2)
    with p.open() as f:
        return yaml.safe_load(f)


def expand_paths(root: Path, raw: list[str]) -> list[Path]:
    """Expand manifest entries into concrete file paths."""
    out: list[Path] = []
    self_path = Path(__file__).resolve()
    for entry in raw or []:
        p = root / entry.rstrip("/")
        if p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file() and sub.suffix in TEXT_SUFFIXES and sub.resolve() != self_path:
                    out.append(sub)
        elif p.is_file():
            if p.suffix in TEXT_SUFFIXES and p.resolve() != self_path:
                out.append(p)
        else:
            # Path does not exist yet (e.g. integrations/VERSION before creation).
            # Skip silently — release tooling will error if a manifested path
            # is missing at extraction time.
            continue
    return sorted(set(out))


def scan_file(path: Path, patterns: list[re.Pattern[str]]) -> list[tuple[int, str, str]]:
    """Return list of (line_no, pattern, line_text) for each hit."""
    hits: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pat in patterns:
            if pat.search(line):
                hits.append((line_no, pat.pattern, line.rstrip()))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true", help="machine-readable, hits only")
    ap.add_argument(
        "--extra-pattern",
        action="append",
        default=[],
        help="add an extra regex to the blacklist (repeatable)",
    )
    args = ap.parse_args()

    root = repo_root()
    manifest = load_manifest(root)

    engine_paths = expand_paths(root, manifest.get("engine", []))
    template_paths = expand_paths(root, manifest.get("template", []))
    targets = sorted(set(engine_paths + template_paths))

    raw_patterns = DEFAULT_BLACKLIST + list(args.extra_pattern)
    patterns = [re.compile(p) for p in raw_patterns]

    total_hits = 0
    files_with_hits = 0
    for path in targets:
        hits = scan_file(path, patterns)
        if not hits:
            continue
        files_with_hits += 1
        rel = path.relative_to(root)
        for line_no, pat, line in hits:
            total_hits += 1
            if args.quiet:
                print(f"{rel}:{line_no}\t{pat}\t{line}")
            else:
                print(f"{rel}:{line_no}  [{pat}]")
                print(f"    {line}")

    if not args.quiet:
        print()
        print(f"scanned {len(targets)} files, {files_with_hits} with leaks, {total_hits} total hits")
        if total_hits == 0:
            print("✓ no personal data leaks found")
        else:
            print("✗ personal data leaks found — fix before extraction")

    return 1 if total_hits > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
