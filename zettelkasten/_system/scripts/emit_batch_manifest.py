#!/usr/bin/env python3
"""Emit a ZTN engine batch manifest as JSON.

Reads structured batch data from a file (or stdin), runs every
concept-name and audience-tag through the autonomous-resolution
helpers in `_common.py`, validates the manifest contract with
downstream Minder (top-level keys, processor enum, format_version
major, per-processor required sections), and writes the result to
`_system/state/batches/{batch_id}.json`.

Exit codes:
- 0 — manifest written (or printed in --dry-run)
- 2 — input is not parseable JSON or root is not an object
- 3 — manifest fails the structural contract (missing required key,
      unknown processor, incompatible major version, missing required
      section). Concept / audience format issues NEVER cause non-zero
      exit — they autofix or drop per the autonomous-pipeline contract.

The format contract is owned by `minder-project/strategy/ARCHITECTURE.md`
§4.5. ZTN-side guarantee: every concept name reaches Minder already
conformant per CONCEPT_NAMING.md; every audience tag is in canonical
5 ∪ active AUDIENCES.md extensions; every privacy trio field is
type-correct with conservative defaults.

This helper is the producer-side enforcement gate — the SAME normalisers
called by `lint_concept_audit.py` (post-write defence-in-depth) run
HERE at emission time. Clean batch in → conformant manifest out.

Usage:
    python3 emit_batch_manifest.py \\
        --input <path-to-batch-data.json> \\
        --output <path-to-batches/{batch_id}.json> \\
        [--audiences <AUDIENCES.md path>]

Or pipe via stdin:
    cat batch_data.json | python3 emit_batch_manifest.py \\
        --output _system/state/batches/{batch_id}.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from _common import (
    ALLOWED_DOMAINS,
    AUDIENCE_CANONICAL,
    expand_domain_entry,
    normalize_audience_tag,
    normalize_concept_list,
    normalize_concept_name,
    normalize_domain,
    parse_extensions_table,
    repo_root,
)


CONCEPT_LIST_FIELDS: frozenset[str] = frozenset({
    "concept_hints", "member_concepts", "applies_in_concepts",
    "concept_ids", "related_concepts", "previous_slugs",
})

ALLOWED_ORIGINS: frozenset[str] = frozenset({"personal", "work", "external"})

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "batch_id", "timestamp", "format_version", "processor",
)

ALLOWED_PROCESSORS: frozenset[str] = frozenset({
    "ztn:process", "ztn:maintain", "ztn:lint", "ztn:agent-lens",
})

# Major version this emitter / consumer pair speaks. Bump only on
# breaking schema changes (per ARCHITECTURE.md §8.12.2). Manifests
# with a different major are rejected — minor drift is forward-compat
# via section_extras.
SUPPORTED_FORMAT_MAJOR = 2

# Per-processor required sections (presence check; the helper does
# not enforce inner structure beyond walk_and_normalise). Keys are
# dotted paths into the manifest dict.
PROCESSOR_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "ztn:process": (
        "sources_processed", "records", "knowledge_notes",
        "concepts", "stats",
    ),
    "ztn:maintain": ("stats",),
    "ztn:lint": ("stats",),
    "ztn:agent-lens": ("stats",),
}

# Empty-shorthand reconciliation. The accumulator inside Claude-driven
# /ztn:process sometimes emits `tier1_objects.tasks: []` (and friends) as
# a literal empty list when no entities exist, instead of the canonical
# `{"created": [], "updated": []}` envelope from ARCHITECTURE.md §4.5.
# The schema (manifest-schema/v2.json) is strict on the sectioned shape,
# so this normaliser coerces empty `[]` to the proper empty-envelope
# form at write time. Future-conformant; existing legacy batches are
# excluded from validator coverage by the lint baseline marker.
TIER1_CREATE_UPDATE_KEYS: frozenset[str] = frozenset({
    "tasks", "ideas", "events", "decisions", "content",
})
TIER1_UPSERT_KEYS: frozenset[str] = frozenset({"people", "projects"})


class ManifestValidationError(Exception):
    """Raised on structural failures that the autonomous-resolution
    contract does NOT cover. The concept/audience layer is autonomous;
    the manifest contract with downstream Minder is NOT — missing
    `processor`, wrong major version, or missing section make the
    manifest unroutable. Surface, don't decide.
    """


def parse_audience_extensions(path: Path) -> set[str]:
    """Mirror of `lint_concept_audit.parse_audience_extensions`. Returns
    the set of active extension tags from AUDIENCES.md, or empty if the
    file is missing / malformed.
    """
    if not path.exists():
        return set()
    import re
    text = path.read_text(encoding="utf-8")
    m = re.search(
        r"<!-- BEGIN extensions -->(.*?)<!-- END extensions -->",
        text, re.DOTALL,
    )
    if not m:
        return set()
    extensions: set[str] = set()
    for line in m.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        tag, _added, status = cells[0], cells[1], cells[2]
        if not tag or tag.lower() == "tag":
            continue
        if tag.startswith("_(") or tag in {"—", "-"}:
            continue
        if status.lower().startswith("deprecated"):
            continue
        extensions.add(tag)
    return extensions


def normalise_domain_list(
    raw: list, accept_set: set[str], events: list[dict], path: str,
) -> list[str]:
    """Filter `domains:` array against canonical-13 ∪ extensions; normalise
    where possible. Slash-syntax (`work/learning`) splits into multiple
    independent values, each filtered separately. Emits per-entry
    `domain-normalise-autofix` / `domain-drop-autofix` events.
    """
    out: list[str] = []
    for value in raw or []:
        # Fast path: canonical / extension verbatim, no slash → keep.
        if isinstance(value, str) and "/" not in value and value in accept_set:
            if value not in out:
                out.append(value)
            continue
        if not isinstance(value, str):
            events.append({
                "fix_id": "domain-drop-autofix",
                "field_path": path, "before": value, "after": None,
                "reason": "format-unfixable",
            })
            continue
        expanded = expand_domain_entry(value)
        if not expanded:
            events.append({
                "fix_id": "domain-drop-autofix",
                "field_path": path, "before": value, "after": None,
                "reason": "format-unfixable",
            })
            continue
        kept_results: list[str] = []
        for part in expanded:
            if part in accept_set:
                if part not in out:
                    out.append(part)
                kept_results.append(part)
            else:
                events.append({
                    "fix_id": "domain-drop-autofix",
                    "field_path": path, "before": value, "after": None,
                    "reason": "not-in-whitelist", "part": part,
                })
        if kept_results and (len(expanded) > 1 or kept_results != [value]):
            events.append({
                "fix_id": "domain-normalise-autofix",
                "field_path": path, "before": value,
                "after": kept_results if len(kept_results) > 1
                         else kept_results[0],
            })
    return out


def coerce_domain_singular(
    value, accept_set: set[str], events: list[dict], path: str,
) -> str | None:
    """Singular `domain:` (constitution principles) → return value if in
    accept set, else None (caller decides what to do; `validate_manifest`
    will catch missing required fields). Emits autofix event on normalise
    success, drop event on failure.

    Reason for None-on-failure rather than fallback default: principle
    schema requires `domain` to match `ALLOWED_DOMAINS` at parse time,
    so a manifest reaching emission with an invalid domain has already
    drifted past the schema gate. Conservative-safe is to surface the
    drop, not to guess a default that would later contradict the
    principle's id-prefix (`{type}-{domain}-{NNN}`).
    """
    if isinstance(value, str) and value in accept_set:
        return value
    norm = normalize_domain(value) if isinstance(value, str) else None
    if norm is not None and norm in accept_set:
        events.append({
            "fix_id": "domain-normalise-autofix",
            "field_path": path, "before": value, "after": norm,
        })
        return norm
    events.append({
        "fix_id": "domain-drop-autofix",
        "field_path": path, "before": value, "after": None,
        "reason": "not-in-whitelist" if norm is not None
                  else "format-unfixable",
    })
    return None


def normalise_audience_list(
    raw: list, accept_set: set[str], events: list[dict], path: str,
) -> list[str]:
    out: list[str] = []
    for tag in raw or []:
        if isinstance(tag, str) and tag in accept_set:
            if tag not in out:
                out.append(tag)
            continue
        norm = normalize_audience_tag(tag) if isinstance(tag, str) else None
        if norm is not None and norm in accept_set:
            if norm not in out:
                out.append(norm)
            if norm != tag:
                events.append({
                    "fix_id": "audience-tag-normalise-autofix",
                    "field_path": path, "before": tag, "after": norm,
                })
        else:
            events.append({
                "fix_id": "audience-tag-drop-autofix",
                "field_path": path, "before": tag, "after": None,
                "reason": "not-in-whitelist" if norm is not None
                          else "format-unfixable",
            })
    return out


def coerce_origin(value, events: list[dict], path: str) -> str:
    if value in ALLOWED_ORIGINS:
        return value
    events.append({
        "fix_id": "origin-coerce-autofix",
        "field_path": path, "before": value, "after": "personal",
    })
    return "personal"


def coerce_is_sensitive(value, events: list[dict], path: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        coerced = value.strip().lower() == "true"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        coerced = bool(value)
    else:
        coerced = False
    events.append({
        "fix_id": "is-sensitive-coerce-autofix",
        "field_path": path, "before": value, "after": coerced,
    })
    return coerced


def process_concepts_upserts(
    upserts: list, events: list[dict], path_prefix: str,
) -> list:
    """Walk concepts.upserts[]: normalise name (drop unnormalisables),
    normalise subtype + related + previous lists.
    """
    kept: list[dict] = []
    for i, entry in enumerate(upserts or []):
        if not isinstance(entry, dict):
            events.append({
                "fix_id": "concept-drop-autofix",
                "field_path": f"{path_prefix}[{i}]",
                "before": entry, "after": None,
                "reason": "non-dict",
            })
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            events.append({
                "fix_id": "concept-drop-autofix",
                "field_path": f"{path_prefix}[{i}].name",
                "before": name, "after": None,
                "reason": "non-string",
            })
            continue
        norm_name = normalize_concept_name(name)
        if norm_name is None:
            events.append({
                "fix_id": "concept-drop-autofix",
                "field_path": f"{path_prefix}[{i}].name",
                "before": name, "after": None,
                "reason": "unnormalisable",
            })
            continue
        if norm_name != name:
            events.append({
                "fix_id": "concept-format-autofix",
                "field_path": f"{path_prefix}[{i}].name",
                "before": name, "after": norm_name,
            })
            entry["name"] = norm_name

        sub = entry.get("subtype")
        if sub is not None and sub != "":
            sub_norm = normalize_concept_name(sub) if isinstance(sub, str) else None
            if sub_norm is None:
                events.append({
                    "fix_id": "concept-drop-autofix",
                    "field_path": f"{path_prefix}[{i}].subtype",
                    "before": sub, "after": None,
                })
                entry["subtype"] = None
            elif sub_norm != sub:
                events.append({
                    "fix_id": "concept-format-autofix",
                    "field_path": f"{path_prefix}[{i}].subtype",
                    "before": sub, "after": sub_norm,
                })
                entry["subtype"] = sub_norm

        for fld in ("related_concepts", "previous_slugs"):
            if isinstance(entry.get(fld), list):
                normalised = normalize_concept_list(entry[fld])
                if normalised != entry[fld]:
                    events.append({
                        "fix_id": "concept-format-autofix",
                        "field_path": f"{path_prefix}[{i}].{fld}",
                        "before": entry[fld], "after": normalised,
                    })
                    entry[fld] = normalised

        kept.append(entry)
    return kept


def normalise_empty_section_shapes(data: dict, events: list[dict]) -> None:
    """Coerce empty-shorthand `[]` to canonical empty-envelope `{}` form
    on sections where the schema expects an object.

    Why this lives at the producer-side normaliser, not in the schema:
    the manifest schema (manifest-schema/v2.json) is the consumer-facing
    contract — keeping it strict means downstream consumers do not have
    to handle two equivalent representations of "nothing here". The
    /ztn:process accumulator (Claude-driven) sometimes drops to literal
    `[]` on empty sections; this helper rewrites them to the canonical
    `{"created": [], "updated": []}` (Tier 1 create-update sections),
    `{"upserts": []}` (people / projects / concepts / constitution
    principles), or `{}` (tier2_objects when no Tier 2 entities) before
    the schema validator runs.

    Forward-conformant; legacy batches predate the validator baseline
    and stay as-is (append-only).
    """
    tier1 = data.get("tier1_objects")
    if isinstance(tier1, dict):
        for key in TIER1_CREATE_UPDATE_KEYS:
            if isinstance(tier1.get(key), list) and len(tier1[key]) == 0:
                tier1[key] = {"created": [], "updated": []}
                events.append({
                    "fix_id": "tier1-empty-shape-autofix",
                    "field_path": f"$.tier1_objects.{key}",
                    "before": [], "after": {"created": [], "updated": []},
                })
        for key in TIER1_UPSERT_KEYS:
            if isinstance(tier1.get(key), list) and len(tier1[key]) == 0:
                tier1[key] = {"upserts": []}
                events.append({
                    "fix_id": "tier1-empty-shape-autofix",
                    "field_path": f"$.tier1_objects.{key}",
                    "before": [], "after": {"upserts": []},
                })

    tier2 = data.get("tier2_objects")
    if isinstance(tier2, list) and len(tier2) == 0:
        data["tier2_objects"] = {}
        events.append({
            "fix_id": "tier2-empty-shape-autofix",
            "field_path": "$.tier2_objects",
            "before": [], "after": {},
        })
    elif isinstance(tier2, dict):
        for type_key, value in list(tier2.items()):
            if isinstance(value, list) and len(value) == 0:
                tier2[type_key] = {"upserts": []}
                events.append({
                    "fix_id": "tier2-empty-shape-autofix",
                    "field_path": f"$.tier2_objects.{type_key}",
                    "before": [], "after": {"upserts": []},
                })

    constitution = data.get("constitution")
    if isinstance(constitution, dict):
        if isinstance(constitution.get("principles"), list) and len(constitution["principles"]) == 0:
            constitution["principles"] = {"upserts": [], "archived": [], "superseded": []}
            events.append({
                "fix_id": "constitution-principles-empty-shape-autofix",
                "field_path": "$.constitution.principles",
                "before": [],
                "after": {"upserts": [], "archived": [], "superseded": []},
            })

    concepts = data.get("concepts")
    if isinstance(concepts, list) and len(concepts) == 0:
        data["concepts"] = {"upserts": []}
        events.append({
            "fix_id": "concepts-empty-shape-autofix",
            "field_path": "$.concepts",
            "before": [], "after": {"upserts": []},
        })


def walk_and_normalise(
    node,
    audience_accept: set[str],
    domain_accept: set[str],
    events: list[dict],
    path: str = "$",
):
    """Recursively traverse the manifest structure, applying autonomous
    normalisation to known fields. Mutates in place.
    """
    if isinstance(node, dict):
        for key in list(node.keys()):
            child_path = f"{path}.{key}"
            value = node[key]

            if key in CONCEPT_LIST_FIELDS and isinstance(value, list):
                normalised = normalize_concept_list(value)
                if normalised != value:
                    events.append({
                        "fix_id": "concept-format-autofix",
                        "field_path": child_path,
                        "before": value, "after": normalised,
                    })
                node[key] = normalised
                continue

            if key == "audience_tags" and isinstance(value, list):
                node[key] = normalise_audience_list(
                    value, audience_accept, events, child_path,
                )
                continue

            if key == "domains" and isinstance(value, list):
                node[key] = normalise_domain_list(
                    value, domain_accept, events, child_path,
                )
                continue

            if key == "domain" and isinstance(value, str):
                # Singular `domain:` (constitution principles). Drop on
                # failure rather than silently default — see
                # coerce_domain_singular docstring.
                norm = coerce_domain_singular(
                    value, domain_accept, events, child_path,
                )
                if norm is None:
                    del node[key]
                else:
                    node[key] = norm
                continue

            if key == "origin":
                node[key] = coerce_origin(value, events, child_path)
                continue

            if key == "is_sensitive":
                node[key] = coerce_is_sensitive(value, events, child_path)
                continue

            if key == "concepts" and isinstance(value, dict):
                if isinstance(value.get("upserts"), list):
                    value["upserts"] = process_concepts_upserts(
                        value["upserts"], events,
                        f"{child_path}.upserts",
                    )
                continue

            walk_and_normalise(
                value, audience_accept, domain_accept, events, child_path,
            )

    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk_and_normalise(
                item, audience_accept, domain_accept, events,
                f"{path}[{i}]",
            )


def validate_manifest(data: dict) -> None:
    """Raise ManifestValidationError on structural contract violations.

    The contract with downstream Minder is non-negotiable — a manifest
    that lacks `processor`, has an incompatible major version, or omits
    a section the consumer requires is unroutable. Unlike concept /
    audience format issues (which autofix or drop), these are routing-
    layer faults: surface immediately, do not silently emit.
    """
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise ManifestValidationError(
            f"missing required top-level keys: {missing}"
        )

    processor = data["processor"]
    if processor not in ALLOWED_PROCESSORS:
        raise ManifestValidationError(
            f"processor {processor!r} not in {sorted(ALLOWED_PROCESSORS)}"
        )

    fv = data["format_version"]
    if not isinstance(fv, str) or "." not in fv:
        raise ManifestValidationError(
            f"format_version must be string 'MAJOR.MINOR', got {fv!r}"
        )
    try:
        major = int(fv.split(".", 1)[0])
    except ValueError as exc:
        raise ManifestValidationError(
            f"format_version major not parseable: {fv!r}"
        ) from exc
    if major != SUPPORTED_FORMAT_MAJOR:
        raise ManifestValidationError(
            f"format_version major {major} != supported "
            f"{SUPPORTED_FORMAT_MAJOR} (manifest {fv!r})"
        )

    required_sections = PROCESSOR_REQUIRED_SECTIONS.get(processor, ())
    missing_sections = [s for s in required_sections if s not in data]
    if missing_sections:
        raise ManifestValidationError(
            f"processor {processor!r} requires sections "
            f"{sorted(required_sections)}; missing: {missing_sections}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=None,
        help="Input JSON file. If omitted, read from stdin.",
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Output JSON path (typically "
             "_system/state/batches/{batch_id}.json).",
    )
    parser.add_argument(
        "--audiences", type=Path, default=None,
        help="AUDIENCES.md path (default: "
             "{repo_root}/_system/registries/AUDIENCES.md).",
    )
    parser.add_argument(
        "--domains", type=Path, default=None,
        help="DOMAINS.md path (default: "
             "{repo_root}/_system/registries/DOMAINS.md).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print normalised JSON to stdout without writing.",
    )
    args = parser.parse_args(argv)

    if args.input:
        raw_text = args.input.read_text(encoding="utf-8")
    else:
        raw_text = sys.stdin.read()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"emit_batch_manifest: invalid JSON input: {exc}\n")
        return 2
    if not isinstance(data, dict):
        sys.stderr.write("emit_batch_manifest: input root must be an object\n")
        return 2

    audiences_path = args.audiences or (
        repo_root() / "_system" / "registries" / "AUDIENCES.md"
    )
    if not audiences_path.exists():
        # AUDIENCES.md missing → accept_set collapses to canonical 5
        # only. Owner extensions are silently lost. This is recoverable
        # (just re-emit after fixing the path) but worth a stderr line
        # so the operator notices the regression.
        sys.stderr.write(
            f"emit_batch_manifest: warning: AUDIENCES.md not found at "
            f"{audiences_path} — extensions table not loaded; "
            f"accept_set limited to canonical 5\n"
        )
    audience_extensions = parse_audience_extensions(audiences_path)
    audience_accept = set(AUDIENCE_CANONICAL) | audience_extensions

    domains_path = args.domains or (
        repo_root() / "_system" / "registries" / "DOMAINS.md"
    )
    if not domains_path.exists():
        sys.stderr.write(
            f"emit_batch_manifest: warning: DOMAINS.md not found at "
            f"{domains_path} — extensions table not loaded; "
            f"accept_set limited to canonical 13\n"
        )
    domain_extensions = parse_extensions_table(
        domains_path, canonical_blacklist=ALLOWED_DOMAINS,
    )
    domain_accept = set(ALLOWED_DOMAINS) | domain_extensions

    events: list[dict] = []
    normalise_empty_section_shapes(data, events)
    walk_and_normalise(data, audience_accept, domain_accept, events)

    try:
        validate_manifest(data)
    except ManifestValidationError as exc:
        sys.stderr.write(f"emit_batch_manifest: validation error: {exc}\n")
        # Emit any normalisation events captured before the failure so
        # the caller can correlate.
        for ev in events:
            sys.stderr.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return 3

    if args.dry_run:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = args.output.with_suffix(args.output.suffix + ".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_path, args.output)
        except BaseException:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

    # Emit fix events on stderr so the caller can ingest them into
    # the batch's audit log without contaminating the JSON output.
    for ev in events:
        sys.stderr.write(json.dumps(ev, ensure_ascii=False) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
