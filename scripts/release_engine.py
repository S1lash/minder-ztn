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
import os
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


def _copy_symlink(src: Path, dst: Path, dry_run: bool, label: Path) -> None:
    """Preserve a symlink at the destination (relative target stored verbatim)."""
    target = os.readlink(src)
    if dry_run:
        print(f"  + {label} (symlink → {target})")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    os.symlink(target, dst)


# Lenses that ship `status: draft` to the skeleton even though the maintainer
# runs them `active` locally — for one of two reasons:
#   (1) prerequisite-gated: friends lack the source data (biometric records,
#       custom sources) and would otherwise burn LLM budget on empty runs;
#   (2) high-trust opt-in: a lens that proposes identity / values principles by
#       mining the owner's private reflections (cognitive-model) must be a
#       deliberate opt-in, not an auto-enrollment on first `/ztn:update`.
#
# Add to this list when releasing a lens that is either source-gated OR
# proposes constitution / identity-level candidates from private content.
DEMOTE_LENSES_ON_RELEASE: tuple[str, ...] = (
    "biometric-anomaly-narrator",
    "biometric-cross-domain",
    "training-load-trend",
    "biometric-life-synthesis",
    "cognitive-model",
)


def _demote_lens_status(skeleton_root: Path, *, lens_ids: tuple[str, ...]) -> int:
    """Demote each lens's `status: active` → `status: draft` in two
    places under the freshly-extracted skeleton:

      1. `_system/registries/lenses/<id>/prompt.md` frontmatter.
      2. `_system/registries/AGENT_LENSES.md` rows — moves them out of
         the `## Active Lenses` table into `## Draft Lenses`.

    Idempotent: if a lens row is already `draft` (or missing), no-op
    on that lens. Returns count of lenses demoted (across both files).
    """
    import re

    demoted = 0
    # 1) Per-prompt frontmatter
    for lens in lens_ids:
        prompt = skeleton_root / "zettelkasten" / "_system" / "registries" / "lenses" / lens / "prompt.md"
        if not prompt.exists():
            continue
        text = prompt.read_text(encoding="utf-8")
        new_text = re.sub(
            r"^(status:\s*)active\s*$", r"\1draft",
            text, count=1, flags=re.MULTILINE,
        )
        if new_text != text:
            prompt.write_text(new_text, encoding="utf-8")
            demoted += 1

    # 2) Registry table — move rows from Active Lenses → Draft Lenses
    registry = skeleton_root / "zettelkasten" / "_system" / "registries" / "AGENT_LENSES.md"
    if not registry.exists():
        return demoted
    text = registry.read_text(encoding="utf-8")
    moved_rows: list[str] = []
    new_lines: list[str] = []
    for line in text.splitlines():
        is_target_active_row = (
            line.startswith("|")
            and any(f"| {lid} " in line for lid in lens_ids)
            and line.rstrip().endswith("| active |")
        )
        if is_target_active_row:
            moved_rows.append(line.replace("| active |", "| draft |"))
            continue  # skip from output (will re-insert in Draft Lenses)
        new_lines.append(line)
    if not moved_rows:
        return demoted
    # Insert moved rows under `## Draft Lenses` (replacing the
    # `_(empty)_` placeholder if present, else appending under header).
    out: list[str] = []
    i = 0
    while i < len(new_lines):
        line = new_lines[i]
        out.append(line)
        if line.startswith("## Draft Lenses"):
            # Skip blank + `_(empty)_` placeholder if present
            j = i + 1
            while j < len(new_lines) and (new_lines[j].strip() == "" or new_lines[j].strip() == "_(empty)_"):
                j += 1
            # Emit blank + table header + moved rows
            out.append("")
            out.append("| ID | Name | Type | Input | Cadence | Self-history | Status |")
            out.append("|---|---|---|---|---|---|---|")
            out.extend(moved_rows)
            out.append("")
            i = j
            continue
        i += 1
    registry.write_text("\n".join(out) + "\n", encoding="utf-8")
    return demoted + len(moved_rows)


# Build artifacts and IDE / editor noise that locally git-ignores but
# physically lives under engine paths. Filtered at copy time so the
# skeleton stays clean.
_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    "node_modules",
})

_SKIP_SUFFIXES: tuple[str, ...] = (
    ".pyc", ".pyo", ".pyd",
)


def copy_path(src_root: Path, dst_root: Path, rel: str, *, strip_template: bool, dry_run: bool) -> int:
    """Copy a manifest entry. Returns count of files copied."""
    rel_clean = rel.rstrip("/")
    src = src_root / rel_clean

    # Top-level symlink — preserve as symlink (do not deref).
    if src.is_symlink():
        sub_rel = Path(rel_clean)
        _copy_symlink(src, dst_root / sub_rel, dry_run, sub_rel)
        return 1

    if not src.exists():
        print(f"  ! missing in source: {rel_clean}", file=sys.stderr)
        return 0

    count = 0
    if src.is_dir():
        for sub in src.rglob("*"):
            sub_rel = sub.relative_to(src_root)
            # Skip Python bytecode caches and other build artifacts that
            # are gitignored locally but rglob still finds on disk. They
            # would pollute the skeleton clone and cause permission /
            # ownership weirdness on friend's machines.
            if any(part in _SKIP_DIRS or part.endswith(_SKIP_SUFFIXES) for part in sub_rel.parts):
                continue
            dst = dst_root / sub_rel
            # Symlinks (to files OR directories) — preserve as symlinks.
            # Must be checked BEFORE is_dir(), since is_dir() follows symlinks
            # and rglob would otherwise either descend into them (duplicating
            # content under a different path) or skip them silently.
            if sub.is_symlink():
                _copy_symlink(sub, dst, dry_run, sub_rel)
                count += 1
                continue
            if sub.is_dir():
                continue
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

        # Skeleton-only post-process: demote owner-activated lenses
        # back to `status: draft` so friends don't auto-run lenses
        # against absent data. The maintainer's clone retains `active`
        # for the maintainer's own data; this hook only touches the
        # extracted skeleton tree.
        _demote_lens_status(target, lens_ids=DEMOTE_LENSES_ON_RELEASE)

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
