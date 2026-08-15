#!/usr/bin/env python3
"""Migration 025 — the identity report reaches the owner's queue.

Runs `_system/scripts/identity_audit.py` and writes what it finds into
`_system/state/CLARIFICATIONS.md`, one item per identity that still has live
residue.

**It changes no content, ever.** A friend's renames are their own history and
the engine has no standing to guess at them: which identifier survived a merge
is a decision, not a lookup. So this migration reports and stops. The owner
resolves each item through the ordinary interactive path —
`/ztn:resolve-clarifications`, which owns `entity-retire` and
`entity-reclassify` and gates every one of them on the same scan returning
zero.

Zero residue writes nothing at all: an empty finding is not news, and a queue
that fills up with «nothing to report» stops being read.

Usage: python3 _025_identity_report.py --repo-root <path>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _identity_migration_lib import (  # noqa: E402
    append_clarifications,
    clarification_anchor,
    configure_std_streams,
    report_no_library,
    import_common,
    resolve_base,
)

MIGRATION = "migration-025"

# How many example paths to name per identity. Enough for the owner to
# recognise the shape of the work; the audit itself is the full list, and the
# item says how to re-run it.
EXAMPLES_SHOWN = 5

BLOCK = """\
### {today} — identity residue: `{entity_id}` ({registry}) — {residue} live \
surface(s)

**Type:** identity-residue
**Subject:** {entity_id}
**Registry:** {registry_path}
**Source:** engine migration 025 (identity report)
**Suggested action:** {suggested}
**Action taken:** none — this migration reports and changes nothing. What \
happened to this identity, and what it became, is your decision and not \
something the engine may infer.
**Residue:** {surfaces}{derived}
**Registry says:** {registry_says}
**Where:**
{examples}
**Uncertainty:** {uncertainty}
**To resolve:** Run `/ztn:resolve-clarifications` — the `{suggested}` action \
takes {asks_for} from you, migrates every live surface in one unit of work, \
and refuses to finalise unless the scan afterwards returns zero. The full list \
is `python3 _system/scripts/identity_audit.py --report`.
"""

# What each action needs the owner to supply, per the Identity Contract's
# kind table. A reclassify has no successor at all — the identity stays alive.
ASKS_FOR = {
    "entity-retire": "the kind and, for a merge or a rename, the successor",
    "entity-reclassify": "the category this identity actually belongs to",
}


def run_audit(base: Path) -> dict | None:
    script = base / "_system" / "scripts" / "identity_audit.py"
    if not script.is_file():
        return None
    proc = subprocess.run(
        [sys.executable, str(script), "--report", "--json", "--root", str(base)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if proc.returncode not in (0, 2) or not proc.stdout.strip():
        sys.stderr.write(
            "025: the identity audit did not produce a report "
            f"(exit {proc.returncode}).\n"
            f"025: {proc.stderr.strip()[:400]}\n"
            "025: re-run it yourself with "
            "`python3 _system/scripts/identity_audit.py --report`.\n"
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(
            "025: the identity audit produced output this migration could not "
            "read. Re-run it yourself with "
            "`python3 _system/scripts/identity_audit.py --report`.\n"
        )
        return None


def _describe(ident: dict) -> tuple[str, str, str]:
    """`(suggested action, what the registry says, what is uncertain)`."""
    category = ident.get("category")
    kind = ident.get("kind")
    successor = ident.get("successor")
    if category == "consolidated":
        says = (
            f"retired as `{kind}`" if kind else "retired, kind not declared"
        ) + (f", successor `{successor}`" if successor else ", no successor named")
        uncertainty = (
            "The registry retired this identifier; these surfaces still name "
            "it. Whether each one moves to the successor or is left as history "
            "is a judgement about the sentence it sits in."
            if successor else
            "The registry retired this identifier without naming a successor, "
            "so these surfaces have nowhere to point until you say what "
            "replaced it — or that nothing did."
        )
        return "entity-retire", says, uncertainty
    says = f"classified as a {category}"
    uncertainty = (
        f"These surfaces treat `{ident['id']}` as something other than a "
        f"{category} — the axis it is carried on does not match the category "
        f"the registry declares. Either the registry's classification is stale "
        f"or the surfaces are."
    )
    return "entity-reclassify", says, uncertainty


def build_items(result: dict, today: str) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for ident in result.get("identities", []):
        if ident.get("excluded") or not ident.get("residue_count"):
            continue
        suggested, says, uncertainty = _describe(ident)
        surfaces = ", ".join(
            f"{name} {count}"
            for name, count in sorted(ident.get("by_surface", {}).items())
        ) or "—"
        derived = ident.get("derived_count") or 0
        live_findings = [
            f for f in ident.get("findings", [])
            if f.get("surface_class") == "live"
        ]
        shown = live_findings[:EXAMPLES_SHOWN]
        examples = "\n".join(
            "- `{path}`{line} — {surface}, {action}".format(
                path=f["path"],
                line=f":{f['line']}" if f.get("line") else "",
                surface=f["surface"], action=f["action"],
            )
            for f in shown
        ) or "- (the audit reported counts without paths)"
        if len(live_findings) > len(shown):
            examples += f"\n- … and {len(live_findings) - len(shown)} more"
        items.append((
            clarification_anchor(
                MIGRATION, f"{ident['registry']}/{ident['id']}",
            ),
            BLOCK.format(
                today=today,
                entity_id=ident["id"],
                registry=ident["registry"],
                registry_path=ident.get("registry_path", "—"),
                residue=ident["residue_count"],
                suggested=suggested,
                asks_for=ASKS_FOR[suggested],
                surfaces=surfaces,
                derived=(
                    f" · {derived} derived surface(s), regenerated not edited"
                    if derived else ""
                ),
                registry_says=says,
                examples=examples,
                uncertainty=uncertainty,
            ),
        ))
    return items


def main(argv: list[str] | None = None) -> int:
    # Owner text is not ASCII; std streams must not use the platform default.
    configure_std_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args(argv)

    base = resolve_base(args.repo_root)
    if base is None:
        print("025: no zettelkasten base on this clone — nothing to do")
        return 0

    # The library first: the audit imports it too, so without it the audit
    # would fail with a traceback about a module rather than a sentence about
    # a clone that is mid-update.
    common = import_common(base)
    if common is None:
        return report_no_library("025", base)

    result = run_audit(base)
    if result is None:
        # A detector that could not run must never be coerced into an
        # all-clear. `heal` kind: the update continues and this is retried.
        return 1

    items = build_items(result, common.today_iso())
    if not items:
        print("025: identity audit clean — nothing to surface")
        return 0

    written, skipped = append_clarifications(
        base, MIGRATION,
        f"migration 025 — identity report ({common.today_iso()})",
        items,
    )
    print(
        f"025: {result['residue_count']} live-surface residue across "
        f"{len(items)} identity(ies)"
    )
    print(f"025: {written} clarification(s) queued, {skipped} already known")
    if written:
        print(
            "025: nothing was changed — resolve them with "
            "`/ztn:resolve-clarifications`"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
