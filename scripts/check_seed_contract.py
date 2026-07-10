#!/usr/bin/env python3
"""Seed-contract gate — enforce the three seeding conventions so they cannot drift.

The engine ships owner-facing files three ways (declared in `.engine-manifest.yml`):

  1. strip-seed  — `template:` minus `seed_skill:`; release renames
                   `X.template.<ext>` → `X.<ext>` (any extension). The stripped
                   file must exist in a fresh clone.
  2. skill-seed  — `template:` ∩ `seed_skill:`; ships verbatim (`.template` kept);
                   the owning skill copies it to the live name on first run.
  3. layered     — a `*.template.yaml` under the engine `_system/scripts/` dir,
                   read directly by the runtime loader; owner overrides live in
                   `*.local.yaml` (never shipped).

This gate proves an assembled skeleton honours the contract. It runs at release
time (inside `release_engine.py`, aborting a malformed release) and standalone in
CI. A mis-declared or leaked seed fails hard here — the contract cannot silently
rot.

Usage:
  scripts/check_seed_contract.py            # static checks + build a temp skeleton and scan it
  (imported)  scan_skeleton(target, manifest, repo_root) -> list[str]
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from release_engine import load_manifest, repo_root

# Engine `.template.*` files that legitimately ship verbatim (not seeds — their
# own installers/skills consume them at their `.template` name).
WHITELIST_TEMPLATE_BASENAMES = {
    "minder-ztn.template.md",  # obsidian vault dashboard seed (seed.sh renames it)
    "PROFILE.template.md",     # describe-me profile seed (excluded from /ztn:process by the *.template.md rule)
}


def _norm(paths: list[str]) -> set[str]:
    return {p.rstrip("/") for p in paths}


def static_checks(manifest: dict, repo: Path) -> list[str]:
    """Manifest-level invariants — no build needed."""
    v: list[str] = []
    template = _norm(manifest.get("template", []))
    engine = _norm(manifest.get("engine", []))
    seed_skill = _norm(manifest.get("seed_skill", []))

    for p in sorted(seed_skill - template):
        v.append(f"seed_skill entry not in template: {p}")

    # A template file must never sit under an engine directory — it would ship
    # twice (engine dir copy + template seed) and /ztn:update (engine-only) would
    # silently overwrite the seeded owner file. Exact overlap or dir-prefix.
    engine_dirs = [e for e in engine if (repo / e).is_dir()]
    for t in sorted(template):
        if t in engine:
            v.append(f"path declared in BOTH engine and template: {t}")
        for e in engine_dirs:
            if t.startswith(e + "/"):
                v.append(f"template seed under engine dir (double-ship): {t}  ⊂  {e}/")
    return v


def scan_skeleton(skeleton: Path, manifest: dict, repo: Path) -> list[str]:
    """Full gate: static manifest checks + scan of an assembled skeleton tree."""
    v = static_checks(manifest, repo)

    seed_skill_basenames = {Path(p.rstrip("/")).name for p in manifest.get("seed_skill", [])}

    # 1. No un-materialised template leaks. Every `*.template.*` in the skeleton
    #    must be an intended verbatim ship: a skill-seed, a layered baseline
    #    (`*.template.yaml`), or an explicit whitelist entry.
    for p in skeleton.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        name = p.name
        is_templatey = ".template." in name or name.endswith(".template")
        if not is_templatey:
            continue
        if name in seed_skill_basenames:
            continue
        if name.endswith(".template.yaml"):  # layered baseline, read directly
            continue
        if name in WHITELIST_TEMPLATE_BASENAMES:
            continue
        v.append(f"un-materialised template leaked into skeleton: {p.relative_to(skeleton)}")

    # 2. No owner override leaks — `*.local.yaml` is owner-private, never shipped.
    for p in skeleton.rglob("*.local.yaml"):
        v.append(f"owner override (.local.yaml) leaked into skeleton: {p.relative_to(skeleton)}")

    # 3. Layered baseline integrity — a plain `{base}.yaml` shipped next to a
    #    `{base}.template.yaml` must be byte-identical (owner tuning belongs in
    #    `.local.yaml`; a divergent plain `.yaml` means tuning leaked to friends).
    for tmpl in skeleton.rglob("*.template.yaml"):
        plain = tmpl.with_name(tmpl.name[: -len(".template.yaml")] + ".yaml")
        if plain.exists() and plain.read_bytes() != tmpl.read_bytes():
            v.append(f"baseline diverges from template (tuning leak): {plain.relative_to(skeleton)}")

    return v


def main() -> int:
    repo = repo_root()
    manifest = load_manifest(repo)

    # Build a throwaway skeleton and scan it — the most robust check is over the
    # ACTUAL release output, not a re-derivation of the naming logic.
    with tempfile.TemporaryDirectory(prefix="seed-contract-") as tmp:
        target = Path(tmp) / "skeleton"
        rc = subprocess.run(
            [sys.executable, str(repo / "scripts" / "release_engine.py"),
             "--target", str(target), "--skip-lint"],
            capture_output=True, text=True,
        )
        # release_engine runs scan_skeleton internally and returns 2 on violation.
        if rc.returncode == 0:
            print("seed-contract gate: OK")
            return 0
        sys.stderr.write(rc.stdout)
        sys.stderr.write(rc.stderr)
        print("seed-contract gate: FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
