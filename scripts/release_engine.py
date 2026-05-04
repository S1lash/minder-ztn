#!/usr/bin/env python3
"""
Release engine — copy engine + template paths into a target directory.

Reads `.engine-manifest.yml`. For each `engine` path, copies as-is. For
each `template` path with `.template.md` suffix, strips the `.template`
suffix in the destination filename. Anything not in `engine` or
`template` is excluded by default.

Used by the owner to assemble the public skeleton (`minder-ztn`) from
the personal instance.

Usage:
  scripts/release_engine.py --target /tmp/minder-ztn-skeleton
  scripts/release_engine.py --target /tmp/skeleton --dry-run

Verifies before write:
  - Linter passes (no personal data)
  - All manifested paths exist in the source

Does NOT initialize git in the target — that is the operator's job
(orphan-init recommended for the public repo).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML required. Install: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict:
    p = root / ".engine-manifest.yml"
    with p.open() as f:
        return yaml.safe_load(f)


def strip_template_suffix(name: str) -> str:
    """`SOUL.template.md` → `SOUL.md`."""
    if name.endswith(".template.md"):
        return name[: -len(".template.md")] + ".md"
    return name


def parse_source_ids_from_template(template_path: Path) -> list[str]:
    """Read SOURCES.template.md, return ordered list of IDs from the
    `## Active Sources` and `## Reserved Sources` tables. Skips
    `## Deprecated Sources`. ID is the first column of the markdown table.
    """
    if not template_path.exists():
        return []
    ids: list[str] = []
    section: str | None = None
    for raw in template_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            if heading.startswith("active sources") or heading.startswith("reserved sources"):
                section = heading
            else:
                section = None
            continue
        if section is None:
            continue
        # Table row: `| id | ... |` — skip header and separator rows.
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if not first or first.lower() == "id" or set(first) <= set("-: "):
            continue
        # Strip backticks/markdown around the ID if any.
        first = first.strip("`").strip()
        if first:
            ids.append(first)
    return ids


def copy_path(src_root: Path, dst_root: Path, rel: str, *, strip_template: bool, dry_run: bool) -> int:
    """Copy a manifest entry. Returns count of files copied."""
    rel_clean = rel.rstrip("/")
    src = src_root / rel_clean

    if not src.exists():
        print(f"  ! missing in source: {rel_clean}", file=sys.stderr)
        return 0

    count = 0
    if src.is_dir():
        for sub in src.rglob("*"):
            if sub.is_dir():
                continue
            sub_rel = sub.relative_to(src_root)
            dst = dst_root / sub_rel
            if dry_run:
                print(f"  + {sub_rel}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sub, dst)
            count += 1
    else:
        sub_rel = Path(rel_clean)
        dst_name = strip_template_suffix(sub_rel.name) if strip_template else sub_rel.name
        dst = dst_root / sub_rel.parent / dst_name
        if dry_run:
            print(f"  + {sub_rel.parent / dst_name}{' (renamed from template)' if dst_name != sub_rel.name else ''}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        count = 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", required=True, help="destination directory (must not exist or be empty)")
    ap.add_argument("--dry-run", action="store_true", help="list files without copying")
    ap.add_argument("--skip-lint", action="store_true", help="skip personal-data linter (NOT recommended)")
    args = ap.parse_args()

    root = repo_root()
    manifest = load_manifest(root)

    target = Path(args.target).resolve()
    if not args.dry_run:
        if target.exists() and any(target.iterdir()):
            print(f"error: target {target} exists and is not empty", file=sys.stderr)
            return 2
        target.mkdir(parents=True, exist_ok=True)

    if not args.skip_lint:
        import subprocess
        print("running personal-data linter...")
        rc = subprocess.run([str(root / "scripts" / "check-no-personal-data.sh")]).returncode
        if rc != 0:
            print("error: linter found leaks — fix before release", file=sys.stderr)
            return 2

    total = 0
    print(f"\nengine paths → {target}")
    for entry in manifest.get("engine", []):
        total += copy_path(root, target, entry, strip_template=False, dry_run=args.dry_run)

    print(f"\ntemplate paths → {target} (with .template suffix stripped)")
    for entry in manifest.get("template", []):
        total += copy_path(root, target, entry, strip_template=True, dry_run=args.dry_run)

    print(f"\n{'would copy' if args.dry_run else 'copied'} {total} files")

    if not args.dry_run:
        # Source folders are derived from SOURCES.template.md (single source
        # of truth). After release_engine copied templates and stripped the
        # `.template` suffix, the file lives at registries/SOURCES.md in
        # the target.
        sources_template = target / "zettelkasten/_system/registries/SOURCES.md"
        source_ids = parse_source_ids_from_template(sources_template)
        if not source_ids:
            print(
                "warning: no source IDs found in SOURCES.template — "
                "skeleton will ship without inbox/processed source folders",
                file=sys.stderr,
            )

        source_dirs: list[str] = []
        for sid in source_ids:
            source_dirs.append(f"zettelkasten/_sources/inbox/{sid}")
            source_dirs.append(f"zettelkasten/_sources/processed/{sid}")

        # Non-source layout dirs that always ship empty.
        layout_dirs = [
            "zettelkasten/_records/meetings",
            "zettelkasten/_records/observations",
            "zettelkasten/0_constitution/axiom",
            "zettelkasten/0_constitution/principle",
            "zettelkasten/0_constitution/rule",
            "zettelkasten/1_projects",
            "zettelkasten/2_areas",
            "zettelkasten/3_resources/people",
            "zettelkasten/3_resources/ideas",
            "zettelkasten/3_resources/tech",
            "zettelkasten/4_archive",
            "zettelkasten/5_meta/mocs",
            "zettelkasten/6_posts",
            "zettelkasten/_system/state/batches",
            "zettelkasten/_system/state/lint-context",
        ]
        empty_dirs = source_dirs + layout_dirs
        for d in empty_dirs:
            (target / d).mkdir(parents=True, exist_ok=True)
            keep = target / d / ".gitkeep"
            if not keep.exists():
                keep.touch()

        print(f"\nlayout ready at {target}")
        print("\nnext steps (operator):")
        print(f"  cd {target}")
        print("  git init")
        print("  git add .")
        print('  git commit -m "Initial skeleton release"')
        print("  gh repo create minder-ztn --public --source=. --remote=origin --push")
        print("  gh repo edit --enable-issues --enable-projects --template")

    return 0


if __name__ == "__main__":
    sys.exit(main())
