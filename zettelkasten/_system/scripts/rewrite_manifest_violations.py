#!/usr/bin/env python3
"""One-shot retrofit utility — re-run historical manifests through the
fixed emit normaliser.

When the producer normaliser gains new coercions (e.g. bare-string
`sources_processed[]` → structured `source_entry`, non-empty
`tier1_objects.people: [...]` → `{upserts: [...]}`, privacy-trio
defaults on entity-list entries), historical manifests written before
the fix carry the broken shape. `/ztn:lint` Scan G surfaces them as
`manifest-schema-violation` CLARIFICATIONs; this utility fixes them in
place.

Idempotency: re-running over an already-fixed manifest yields the same
output (no events). Atomic write via tempfile + os.replace, matching
emit_batch_manifest's contract.

Usage:
    # Dry-run (default) — print per-batch diff summary, no writes.
    python3 rewrite_manifest_violations.py --batches-dir _system/state/batches

    # Apply — write back. NEVER bypass --apply; default is safe.
    python3 rewrite_manifest_violations.py --batches-dir _system/state/batches --apply

    # Single file mode for testing.
    python3 rewrite_manifest_violations.py --file path/to/batch.json --apply

Exit codes:
- 0 — all batches processed (with or without changes)
- 2 — invalid input (path missing, JSON parse failure on >0 files)
- 3 — at least one batch failed structural validation post-retrofit
      (the utility surfaces; never auto-repairs structural faults)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import emit_batch_manifest as e  # type: ignore
from _common import (  # type: ignore
    ALLOWED_DOMAINS,
    AUDIENCE_CANONICAL,
    parse_extensions_table,
    repo_root,
)


def _load_accept_sets(
    audiences_path: Path | None, domains_path: Path | None,
) -> tuple[set[str], set[str]]:
    audiences_path = audiences_path or (
        repo_root() / "_system" / "registries" / "AUDIENCES.md"
    )
    audience_extensions = e.parse_audience_extensions(audiences_path)
    audience_accept = set(AUDIENCE_CANONICAL) | audience_extensions

    domains_path = domains_path or (
        repo_root() / "_system" / "registries" / "DOMAINS.md"
    )
    domain_extensions = parse_extensions_table(
        domains_path, canonical_blacklist=ALLOWED_DOMAINS,
    )
    domain_accept = set(ALLOWED_DOMAINS) | domain_extensions
    return audience_accept, domain_accept


def retrofit_manifest(
    data: dict, audience_accept: set[str], domain_accept: set[str],
    filename: str | None = None,
) -> tuple[dict, list[dict]]:
    """Run the data dict through the emit normaliser pipeline. Returns
    (mutated_data, events). The data dict is mutated in place; the
    return is a convenience for the caller.

    Unlike live emission, the retrofit passes `fill_sections=True` to the
    identity/section synthesiser so structurally-incomplete historical
    manifests (missing timestamp / processor / required sections, or
    early-dialect key names) become schema-valid. The filename supplies
    the processor and batch_id when the manifest body lacks them.
    """
    events: list[dict] = []
    if not isinstance(data.get("stats"), dict):
        data["stats"] = {}
    stats = data["stats"]
    # Mirror of emit_batch_manifest.main() pipeline — keep in sync.
    e.synthesise_required_fields(
        data, events, filename=filename, fill_sections=True,
    )
    e.coerce_sources_processed(data, events, stats)
    e.normalise_empty_section_shapes(data, events, stats)
    e.relocate_tier2_misplaced_sections(data, events, stats)
    e.coerce_sensitive_entities(data, events, stats)
    e.walk_and_normalise(data, audience_accept, domain_accept, events)
    return data, events


def process_file(
    path: Path, audience_accept: set[str], domain_accept: set[str],
    apply: bool,
) -> tuple[bool, int, str | None]:
    """Process one manifest file. Returns (changed, event_count, error).

    On structural validation failure post-retrofit, returns
    (False, 0, "<error message>") and skips the write — the operator
    must resolve manually.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, 0, f"read error: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return False, 0, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return False, 0, "root is not an object"

    before_text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    _, events = retrofit_manifest(
        data, audience_accept, domain_accept, filename=str(path),
    )
    after_text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    changed = before_text != after_text

    try:
        e.validate_manifest(data)
        deep_errors = e.deep_validate_manifest(data)
        if deep_errors:
            raise e.ManifestValidationError(
                "deep schema validation failed: " + "; ".join(deep_errors)
            )
    except e.ManifestValidationError as exc:
        return False, len(events), f"post-retrofit validation error: {exc}"

    if changed and apply:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_path, path)
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    return changed, len(events), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--batches-dir", type=Path, default=None,
        help="Directory containing manifest JSON files to retrofit.",
    )
    group.add_argument(
        "--file", type=Path, default=None,
        help="Single manifest file to retrofit.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write changes back. Default is dry-run.",
    )
    parser.add_argument(
        "--audiences", type=Path, default=None,
        help="AUDIENCES.md path.",
    )
    parser.add_argument(
        "--domains", type=Path, default=None,
        help="DOMAINS.md path.",
    )
    args = parser.parse_args(argv)

    audience_accept, domain_accept = _load_accept_sets(
        args.audiences, args.domains,
    )

    if args.file:
        targets = [args.file]
    else:
        if not args.batches_dir.is_dir():
            sys.stderr.write(
                f"rewrite_manifest_violations: not a directory: "
                f"{args.batches_dir}\n"
            )
            return 2
        targets = sorted(args.batches_dir.glob("*.json"))

    total = 0
    changed_count = 0
    failed: list[tuple[Path, str]] = []
    for target in targets:
        if not target.is_file():
            continue
        total += 1
        changed, event_count, error = process_file(
            target, audience_accept, domain_accept, args.apply,
        )
        if error is not None:
            failed.append((target, error))
            sys.stderr.write(
                f"{target.name}: FAIL: {error}\n"
            )
            continue
        if changed:
            changed_count += 1
            mode = "would change" if not args.apply else "rewrote"
            sys.stdout.write(
                f"{target.name}: {mode} ({event_count} fix events)\n"
            )
        else:
            sys.stdout.write(f"{target.name}: clean\n")

    sys.stdout.write(
        f"\nSummary: {total} file(s) scanned, {changed_count} "
        f"{'would change' if not args.apply else 'rewritten'}, "
        f"{len(failed)} failed.\n"
    )
    if failed:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
