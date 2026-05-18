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

# Tier 2 subsection keys (per manifest-schema/v2.json
# tier2_objects_section): each is an object `{upserts: [...]}` of
# tier2_typed_object_entry / tier2_lens_observation_entry. The
# /ztn:process accumulator occasionally drops these to bare arrays
# (mirroring the tier1 shorthand bug). The normaliser coerces both
# empty and non-empty bare arrays to the canonical envelope.
TIER2_SUBSECTION_KEYS: frozenset[str] = frozenset({
    "inventory", "wardrobe", "content_candidates", "lens_observation",
    "tasks", "ideas", "events", "decisions", "content",
    "lens-observation",
})

# Legacy concept-type aliases — historical /ztn:process emissions used
# wider vocabulary than the schema's 17-value enum. Owner-confirmed
# mapping; original value is preserved under section_extras.legacy_type
# so the audit chain stays recoverable. Types NOT in this map and NOT
# in the enum pass through untouched — the schema validator will flag
# them so visibility is preserved (no silent re-mapping).
LEGACY_CONCEPT_TYPE_ALIASES: dict[str, str] = {
    "technical_concept": "technical",
    "pattern": "technical",
    "process": "theme",
    "concept": "theme",
    "technique": "skill",
    "system": "theme",
    "policy": "decision",
    "decision_pattern": "decision",
    "engineering_pattern": "technical",
    "engineering_task": "technical",
    "project_concept": "theme",
    "personal_insight": "idea",
    "career_pattern": "theme",
    "tech_component": "tool",
    "tech_concept": "technical",
    "tech_standard": "technical",
}

# Legacy tier2.tasks → tier1.tasks relocation. Owner tasks belong in
# tier1_objects.tasks (per ARCHITECTURE.md three-tier model). The
# /ztn:process accumulator historically misrouted them under
# tier2_objects.tasks (tier2 is for typed registries: inventory,
# wardrobe, lens-observation). Producer relocates with
# title-derivation from id and ownership mapping from legacy `type`.
TIER2_TO_TIER1_OWNERSHIP_MAP: dict[str, str] = {
    "action": "MINE",
    "delegate": "DELEGATED",
    "delegated": "DELEGATED",
    "waiting": "WAITING",
}

CONCEPT_TYPE_ENUM: frozenset[str] = frozenset({
    "theme", "tool", "decision", "idea", "event", "organization",
    "skill", "technical", "location", "emotion", "goal", "value",
    "preference", "constraint", "algorithm", "fact", "other",
})

# Folder-prefix → SOURCES.md source_type inference for the
# `sources_processed` coercion. Bare-string entries from the
# Claude-driven accumulator are wrapped into structured
# `source_entry` objects with source_type inferred from the path. Keys
# are checked longest-prefix first; unmatched paths fall through to
# `unknown` (counted in stats).
SOURCE_TYPE_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    ("_sources/processed/garmin/", "garmin-daily"),
    ("_sources/processed/plaud/", "plaud-transcript"),
    ("_sources/processed/claude-sessions/", "claude-session"),
)

# Privacy-trio defaults. Applied when any of origin / audience_tags /
# is_sensitive is missing on an entity-list entry (see
# ENTITY_LIST_PARENTS). Conservative-safe — per ENGINE_DOCTRINE §3.8.
PRIVACY_TRIO_DEFAULTS: dict = {
    "origin": "personal",
    "audience_tags": [],
    "is_sensitive": False,
}

# Where in the manifest tree do we inject the privacy trio when it's
# missing? Only on entity-list entries: each tuple is
# (parent_dotted_path_suffix, child_key_under_parent). The
# walk_and_normalise function checks `path` against these to decide
# whether to inject. Top-level keys and non-entity dicts are skipped.
ENTITY_LIST_PARENT_PATHS: frozenset[str] = frozenset({
    # records / knowledge_notes / hubs entries
    "$.records.created", "$.records.updated",
    "$.knowledge_notes.created", "$.knowledge_notes.updated",
    "$.hubs.created", "$.hubs.updated",
    # tier1_objects.{type}.upserts / created / updated
    "$.tier1_objects.tasks.created", "$.tier1_objects.tasks.updated",
    "$.tier1_objects.ideas.created", "$.tier1_objects.ideas.updated",
    "$.tier1_objects.events.created", "$.tier1_objects.events.updated",
    "$.tier1_objects.decisions.created", "$.tier1_objects.decisions.updated",
    "$.tier1_objects.content.created", "$.tier1_objects.content.updated",
    "$.tier1_objects.people.upserts",
    "$.tier1_objects.people.created", "$.tier1_objects.people.updated",
    "$.tier1_objects.projects.upserts",
    "$.tier1_objects.projects.created", "$.tier1_objects.projects.updated",
})


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

        raw_type = entry.get("type")
        if isinstance(raw_type, str) and raw_type not in CONCEPT_TYPE_ENUM:
            mapped = LEGACY_CONCEPT_TYPE_ALIASES.get(raw_type)
            if mapped is not None:
                extras = entry.get("section_extras")
                if not isinstance(extras, dict):
                    extras = {}
                extras["legacy_type"] = raw_type
                entry["section_extras"] = extras
                entry["type"] = mapped
                events.append({
                    "fix_id": "concept-type-legacy-alias-autofix",
                    "field_path": f"{path_prefix}[{i}].type",
                    "before": raw_type, "after": mapped,
                })
            else:
                # Non-mutating: surfaces the unknown type but leaves
                # the value as-is. Tagged `mutation: false` so
                # idempotence tests can filter on `mutation: true`
                # without losing visibility across passes.
                events.append({
                    "fix_id": "concept-type-unknown-coercion-warning",
                    "field_path": f"{path_prefix}[{i}].type",
                    "before": raw_type, "after": raw_type,
                    "reason": "not-in-enum-and-no-alias",
                    "mutation": False,
                })

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


def infer_source_type(path: str) -> str | None:
    """Return the SOURCES.md source_type for a `_sources/processed/...`
    path, or None if no prefix matches. Conservative — callers map
    None to `unknown` and bump the stats counter.
    """
    if not isinstance(path, str):
        return None
    for prefix, source_type in SOURCE_TYPE_PREFIX_MAP:
        if path.startswith(prefix):
            return source_type
    return None


def coerce_sources_processed(
    data: dict, events: list[dict], stats: dict,
) -> None:
    """Coerce `sources_processed[i]` bare strings into `source_entry`
    objects with inferred `source_type`. Mixed lists of strings + dicts
    are handled in place — dict entries pass through untouched.

    Schema requirement: each item must be an object with `path`. Bare
    strings violate this; the producer accumulator occasionally emits
    raw paths instead of structured entries.
    """
    raw = data.get("sources_processed")
    if not isinstance(raw, list):
        return
    coerced: list = []
    unknown = 0
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            coerced.append(item)
            continue
        if isinstance(item, str):
            source_type = infer_source_type(item)
            if source_type is None:
                source_type = "unknown"
                unknown += 1
            new_entry = {
                "path": item,
                "source_type": source_type,
                "section_extras": {},
            }
            coerced.append(new_entry)
            events.append({
                "fix_id": "sources-processed-coerce-autofix",
                "field_path": f"$.sources_processed[{i}]",
                "before": item, "after": new_entry,
                "reason": "bare-string-wrapped",
            })
            continue
        # Unknown shape — record a coercion warning and skip.
        events.append({
            "fix_id": "sources-processed-drop-autofix",
            "field_path": f"$.sources_processed[{i}]",
            "before": item, "after": None,
            "reason": "unsupported-shape",
        })
        warnings = stats.setdefault("coercion_warnings", [])
        new_warning = {
            "field_path": f"$.sources_processed[{i}]",
            "shape": type(item).__name__,
        }
        if new_warning not in warnings:
            warnings.append(new_warning)
    data["sources_processed"] = coerced
    if unknown:
        stats["source_type_inferred_unknown"] = (
            stats.get("source_type_inferred_unknown", 0) + unknown
        )


def coerce_sensitive_entities(
    data: dict, events: list[dict], stats: dict,
) -> None:
    """Coerce legacy `sensitive_entities[i]` shape `{note_id, reason}` →
    canonical `{id, kind, reason}`. The schema (manifest-schema/v2.json
    `sensitive_entity_entry`) requires `kind`; `note_id` was the
    historical synonym for `id` when the entity was always a knowledge
    note. Modern manifests carry mixed kinds (record / note / hub /
    task / event / ...), so `kind` is now explicit.

    Idempotent: items already in canonical shape pass through. Items
    with unknown legacy keys surface a coercion warning and are left
    in place so the validator can flag them downstream.
    """
    raw = data.get("sensitive_entities")
    if not isinstance(raw, list):
        return
    out: list = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            out.append(item)
            continue
        if "note_id" in item and "id" not in item:
            new_entry: dict = {
                "id": item["note_id"],
                "kind": "note",
            }
            if "reason" in item:
                new_entry["reason"] = item["reason"]
            for key, value in item.items():
                if key in ("note_id", "id", "kind", "reason"):
                    continue
                new_entry[key] = value
            extras = new_entry.get("section_extras")
            if not isinstance(extras, dict):
                extras = {}
            extras["legacy_note_id_field"] = True
            new_entry["section_extras"] = extras
            out.append(new_entry)
            events.append({
                "fix_id": "sensitive-entities-note-id-coerce-autofix",
                "field_path": f"$.sensitive_entities[{i}]",
                "before": item, "after": new_entry,
                "reason": "legacy-note-id-field",
            })
            continue
        if "id" not in item and "kind" not in item:
            # Unknown legacy shape — surface coercion warning, pass
            # through. The schema validator downstream will flag the
            # missing `kind`, preserving visibility.
            events.append({
                "fix_id": "sensitive-entities-unknown-shape-warning",
                "field_path": f"$.sensitive_entities[{i}]",
                "before": item, "after": item,
                "reason": "unknown-legacy-shape",
                "mutation": False,
            })
            warnings = stats.setdefault("coercion_warnings", [])
            new_warning = {
                "field_path": f"$.sensitive_entities[{i}]",
                "shape": "unknown-keys",
                "keys": sorted(item.keys()),
            }
            # Dedupe — re-running on the same input must not grow stats.
            if new_warning not in warnings:
                warnings.append(new_warning)
        out.append(item)
    data["sensitive_entities"] = out


def _derive_task_title_from_id(task_id: str) -> str:
    """`task-pay-by-bank-tink-communicate` → "Pay by bank tink communicate".

    Mirrors the hand-patch heuristic used to retrofit legacy batches:
    strip `task-` prefix, kebab → space, capitalise first letter only.
    The result is a human-readable placeholder; the owner can rename
    later via the task-manager surface. Conservative-safe — never
    fails, even on degenerate ids.
    """
    if not isinstance(task_id, str):
        return "Untitled task"
    stem = task_id
    if stem.startswith("task-"):
        stem = stem[len("task-"):]
    stem = stem.replace("-", " ").strip()
    if not stem:
        return "Untitled task"
    return stem.capitalize()


def relocate_tier2_misplaced_sections(
    data: dict, events: list[dict], stats: dict,
) -> None:
    """Three legacy patterns under `tier2_objects` get reshaped here:

    1. `tier2_objects.tasks.upserts[]` items without `name` (the tier2
       typed-object marker) but with `id` (the tier1 task marker) →
       relocate to `tier1_objects.tasks.created[]` with title
       derivation + ownership mapping. The whole `tier2_objects.tasks`
       subsection is removed once empty.
    2. `tier2_objects.events.upserts[]` items lacking the required
       tier2 typed-object trio (id + type + name) → drop into
       `section_extras.legacy_tier2_drop` on the manifest root to
       preserve audit. Genuine tier2 events (with the trio) stay.
    3. `tier2_objects.people_candidates` — deprecated section. Always
       preserved under `section_extras.legacy_tier2_drop` and removed
       from tier2_objects.

    Idempotent: re-running on already-relocated input produces no
    further events (the relocated tier1 items carry
    `section_extras.legacy_origin = "tier2_objects.tasks"`; the
    detector keys off the tier2 presence, not the tier1 marker).
    """
    tier2 = data.get("tier2_objects")
    if not isinstance(tier2, dict):
        return

    tasks_section = tier2.get("tasks")
    if isinstance(tasks_section, dict):
        upserts = tasks_section.get("upserts")
        if isinstance(upserts, list) and upserts:
            misplaced: list[dict] = []
            genuine: list = []
            for item in upserts:
                if (
                    isinstance(item, dict)
                    and "id" in item
                    and "name" not in item
                ):
                    misplaced.append(item)
                else:
                    genuine.append(item)
            if misplaced:
                created_entries: list[dict] = []
                for task in misplaced:
                    task_id = task.get("id", "unknown")
                    new_task: dict = {
                        "id": task_id,
                        "title": _derive_task_title_from_id(task_id),
                        "origin": PRIVACY_TRIO_DEFAULTS["origin"],
                        "audience_tags": list(
                            PRIVACY_TRIO_DEFAULTS["audience_tags"]
                        ),
                        "is_sensitive": PRIVACY_TRIO_DEFAULTS["is_sensitive"],
                    }
                    legacy_type = task.get("type")
                    if isinstance(legacy_type, str):
                        new_task["ownership"] = (
                            TIER2_TO_TIER1_OWNERSHIP_MAP.get(
                                legacy_type, "MINE",
                            )
                        )
                    else:
                        new_task["ownership"] = "MINE"
                    due = task.get("due")
                    if due is not None:
                        new_task["deadline"] = due
                    source_path = task.get("note") or task.get("source")
                    if isinstance(source_path, str) and source_path:
                        new_task["source_record_path"] = source_path
                    extras: dict = {
                        "legacy_origin": "tier2_objects.tasks",
                    }
                    if legacy_type is not None:
                        extras["legacy_type"] = legacy_type
                    assignee = task.get("assignee")
                    if assignee is not None:
                        extras["assignee"] = assignee
                    owner_field = task.get("owner")
                    if (
                        owner_field is not None
                        and owner_field != "owner"
                    ):
                        extras["legacy_owner"] = owner_field
                    new_task["section_extras"] = extras
                    created_entries.append(new_task)

                tier1 = data.setdefault("tier1_objects", {})
                if not isinstance(tier1, dict):
                    tier1 = {}
                    data["tier1_objects"] = tier1
                tier1_tasks = tier1.get("tasks")
                if not isinstance(tier1_tasks, dict):
                    tier1_tasks = {"created": [], "updated": []}
                    tier1["tasks"] = tier1_tasks
                created_list = tier1_tasks.setdefault("created", [])
                if not isinstance(created_list, list):
                    created_list = []
                    tier1_tasks["created"] = created_list
                tier1_tasks.setdefault("updated", [])
                created_list.extend(created_entries)
                events.append({
                    "fix_id": "tier2-tasks-relocated-to-tier1",
                    "field_path": "$.tier2_objects.tasks.upserts",
                    "before_len": len(misplaced),
                    "after": {
                        "tier1_created_added": len(created_entries),
                    },
                })

                if genuine:
                    tasks_section["upserts"] = genuine
                else:
                    tier2.pop("tasks", None)

    events_section = tier2.get("events")
    if isinstance(events_section, dict):
        ev_upserts = events_section.get("upserts")
        if isinstance(ev_upserts, list) and ev_upserts:
            unmappable: list = []
            genuine_events: list = []
            for item in ev_upserts:
                if (
                    isinstance(item, dict)
                    and "id" in item
                    and "type" in item
                    and "name" in item
                ):
                    genuine_events.append(item)
                else:
                    unmappable.append(item)
            if unmappable:
                extras_root = data.setdefault("section_extras", {})
                if not isinstance(extras_root, dict):
                    extras_root = {}
                    data["section_extras"] = extras_root
                legacy_drop = extras_root.setdefault(
                    "legacy_tier2_drop", {},
                )
                if not isinstance(legacy_drop, dict):
                    legacy_drop = {}
                    extras_root["legacy_tier2_drop"] = legacy_drop
                bucket = legacy_drop.setdefault("events", [])
                if not isinstance(bucket, list):
                    bucket = []
                    legacy_drop["events"] = bucket
                bucket.extend(unmappable)
                events.append({
                    "fix_id": "tier2-events-preserved-as-legacy",
                    "field_path": "$.tier2_objects.events.upserts",
                    "before_len": len(unmappable),
                    "after": {
                        "legacy_tier2_drop_added": len(unmappable),
                    },
                    "reason": "missing-id-type-name-triple",
                })
                if genuine_events:
                    events_section["upserts"] = genuine_events
                else:
                    tier2.pop("events", None)

    people_candidates = tier2.get("people_candidates")
    if people_candidates is not None:
        # Unwrap if normalise_empty_section_shapes already wrapped a
        # bare list into `{upserts: [...]}` — the deprecated section
        # has no internal envelope semantics, so we preserve the raw
        # items list under legacy_tier2_drop.
        if (
            isinstance(people_candidates, dict)
            and "upserts" in people_candidates
            and isinstance(people_candidates["upserts"], list)
        ):
            people_candidates = people_candidates["upserts"]
        extras_root = data.setdefault("section_extras", {})
        if not isinstance(extras_root, dict):
            extras_root = {}
            data["section_extras"] = extras_root
        legacy_drop = extras_root.setdefault("legacy_tier2_drop", {})
        if not isinstance(legacy_drop, dict):
            legacy_drop = {}
            extras_root["legacy_tier2_drop"] = legacy_drop
        legacy_drop["people_candidates"] = people_candidates
        tier2.pop("people_candidates", None)
        events.append({
            "fix_id": "tier2-people-candidates-preserved-as-legacy",
            "field_path": "$.tier2_objects.people_candidates",
            "before": "deprecated-section",
            "after": "$.section_extras.legacy_tier2_drop.people_candidates",
            "reason": "section-deprecated",
        })


def _coerce_hub_array(
    items: list, events: list[dict], path_prefix: str,
) -> dict:
    """Bucket a non-empty hubs array into `{created: [], updated: []}`.
    Items with `state: "created"` go to created; everything else
    (including no-state) goes to updated.
    """
    created: list = []
    updated: list = []
    for i, item in enumerate(items):
        if isinstance(item, dict) and item.get("state") == "created":
            created.append(item)
        else:
            updated.append(item)
    events.append({
        "fix_id": "hubs-nonempty-shape-autofix",
        "field_path": path_prefix,
        "before_len": len(items),
        "after": {"created_len": len(created), "updated_len": len(updated)},
    })
    return {"created": created, "updated": updated}


def _coerce_created_updated_array(
    items: list, events: list[dict], path_prefix: str, fix_id: str,
) -> dict:
    """Bucket a non-empty bare array of entries into `{created, updated}`.
    Items with `state: "created"` go to created; everything else
    (including no-state) goes to updated. Used for records /
    knowledge_notes when the producer emitted a flat array.
    """
    created: list = []
    updated: list = []
    for item in items:
        if isinstance(item, dict) and item.get("state") == "created":
            created.append(item)
        else:
            updated.append(item)
    events.append({
        "fix_id": fix_id,
        "field_path": path_prefix,
        "before_len": len(items),
        "after": {"created_len": len(created), "updated_len": len(updated)},
    })
    return {"created": created, "updated": updated}


def _coerce_tier2_subsection_array(
    items: list, events: list[dict], path_prefix: str,
) -> dict:
    """Wrap a non-empty Tier 2 subsection bare array into `{upserts: [...]}`.
    Items pass through unchanged — Tier 2 entries are owner-shaped; the
    schema only requires id/type/name at the entry level, and the
    surrounding envelope is the producer-side bug we are fixing here.
    """
    upserts: list = list(items)
    events.append({
        "fix_id": "tier2-nonempty-shape-autofix",
        "field_path": path_prefix,
        "before_len": len(items),
        "after": {"upserts_len": len(upserts)},
    })
    return {"upserts": upserts}


def _coerce_upserts_array(
    items: list, events: list[dict], path_prefix: str, stats: dict,
) -> dict:
    """Wrap a non-empty people/projects array into `{upserts: [...]}`.
    Bare-string items (`"maxim-goncharov"`) are wrapped as
    `{"id": <string>}` before being pushed into upserts. Dict items
    pass through. Anything else is logged as a coercion warning and
    dropped.
    """
    upserts: list = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            upserts.append(item)
        elif isinstance(item, str):
            upserts.append({"id": item})
            events.append({
                "fix_id": "tier1-bare-string-wrap-autofix",
                "field_path": f"{path_prefix}[{i}]",
                "before": item, "after": {"id": item},
            })
        else:
            events.append({
                "fix_id": "tier1-upserts-drop-autofix",
                "field_path": f"{path_prefix}[{i}]",
                "before": item, "after": None,
                "reason": "unsupported-shape",
            })
            warnings = stats.setdefault("coercion_warnings", [])
            new_warning = {
                "field_path": f"{path_prefix}[{i}]",
                "shape": type(item).__name__,
            }
            if new_warning not in warnings:
                warnings.append(new_warning)
    events.append({
        "fix_id": "tier1-nonempty-shape-autofix",
        "field_path": path_prefix,
        "before_len": len(items),
        "after": {"upserts_len": len(upserts)},
    })
    return {"upserts": upserts}


def normalise_empty_section_shapes(
    data: dict, events: list[dict], stats: dict | None = None,
) -> None:
    """Coerce array-shorthand to canonical envelope `{}` form on sections
    where the schema expects an object — empty AND non-empty.

    Why this lives at the producer-side normaliser, not in the schema:
    the manifest schema (manifest-schema/v2.json) is the consumer-facing
    contract — keeping it strict means downstream consumers do not have
    to handle two equivalent representations of "nothing here". The
    /ztn:process accumulator (Claude-driven) sometimes drops to literal
    `[]` (empty) or `[entity, ...]` (non-empty) on sections that the
    schema requires as objects. This helper rewrites both forms:
    - Tier 1 create-update sections → `{"created": [...], "updated": [...]}`
    - people / projects / concepts / constitution principles → `{"upserts": [...]}`
    - hubs (`hubs: []` or `hubs: [hub, ...]`) → `{"created": [...], "updated": [...]}`
    - tier2_objects empty → `{}`; inner empty arrays → `{"upserts": []}`

    For tier 1 create-update non-empty arrays, the bucketing rule is
    deferred to the owner — we leave them as-is at this layer, since
    splitting requires per-item create/update knowledge that only the
    upstream accumulator has (the field is rare in practice; emit it
    correctly upstream).

    Forward-conformant; legacy batches predate the validator baseline
    and stay as-is (append-only).
    """
    if stats is None:
        stats = {}
    tier1 = data.get("tier1_objects")
    if isinstance(tier1, list) and len(tier1) == 0:
        data["tier1_objects"] = {}
        events.append({
            "fix_id": "tier1-empty-shape-autofix",
            "field_path": "$.tier1_objects",
            "before": [], "after": {},
        })
        tier1 = data["tier1_objects"]
    if isinstance(tier1, dict):
        for key in TIER1_CREATE_UPDATE_KEYS:
            if key in tier1 and tier1[key] is None:
                tier1[key] = {"created": [], "updated": []}
                events.append({
                    "fix_id": "tier1-null-shape-autofix",
                    "field_path": f"$.tier1_objects.{key}",
                    "before": None,
                    "after": {"created": [], "updated": []},
                })
            elif isinstance(tier1.get(key), list) and len(tier1[key]) == 0:
                tier1[key] = {"created": [], "updated": []}
                events.append({
                    "fix_id": "tier1-empty-shape-autofix",
                    "field_path": f"$.tier1_objects.{key}",
                    "before": [], "after": {"created": [], "updated": []},
                })
        for key in TIER1_UPSERT_KEYS:
            if key in tier1 and tier1[key] is None:
                tier1[key] = {"upserts": []}
                events.append({
                    "fix_id": "tier1-null-shape-autofix",
                    "field_path": f"$.tier1_objects.{key}",
                    "before": None, "after": {"upserts": []},
                })
                continue
            value = tier1.get(key)
            if isinstance(value, list):
                if len(value) == 0:
                    tier1[key] = {"upserts": []}
                    events.append({
                        "fix_id": "tier1-empty-shape-autofix",
                        "field_path": f"$.tier1_objects.{key}",
                        "before": [], "after": {"upserts": []},
                    })
                else:
                    tier1[key] = _coerce_upserts_array(
                        value, events,
                        f"$.tier1_objects.{key}", stats,
                    )

    for section_key, fix_id in (
        ("records", "records-nonempty-shape-autofix"),
        ("knowledge_notes", "knowledge-notes-nonempty-shape-autofix"),
    ):
        value = data.get(section_key)
        if isinstance(value, list):
            if len(value) == 0:
                data[section_key] = {"created": [], "updated": []}
                events.append({
                    "fix_id": fix_id.replace("nonempty", "empty"),
                    "field_path": f"$.{section_key}",
                    "before": [], "after": {"created": [], "updated": []},
                })
            else:
                data[section_key] = _coerce_created_updated_array(
                    value, events, f"$.{section_key}", fix_id,
                )

    hubs = data.get("hubs")
    if isinstance(hubs, list):
        if len(hubs) == 0:
            data["hubs"] = {"created": [], "updated": []}
            events.append({
                "fix_id": "hubs-empty-shape-autofix",
                "field_path": "$.hubs",
                "before": [], "after": {"created": [], "updated": []},
            })
        else:
            data["hubs"] = _coerce_hub_array(hubs, events, "$.hubs")

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
            if isinstance(value, list):
                if len(value) == 0:
                    tier2[type_key] = {"upserts": []}
                    events.append({
                        "fix_id": "tier2-empty-shape-autofix",
                        "field_path": f"$.tier2_objects.{type_key}",
                        "before": [], "after": {"upserts": []},
                    })
                else:
                    tier2[type_key] = _coerce_tier2_subsection_array(
                        value, events,
                        f"$.tier2_objects.{type_key}",
                    )

    constitution = data.get("constitution")
    if isinstance(constitution, list) and len(constitution) == 0:
        data["constitution"] = {}
        events.append({
            "fix_id": "constitution-empty-shape-autofix",
            "field_path": "$.constitution",
            "before": [], "after": {},
        })
        constitution = data["constitution"]
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


def inject_privacy_trio_defaults(
    entry: dict, events: list[dict], path: str,
) -> None:
    """If any of the privacy-trio fields is missing on an entity-list
    entry, inject the conservative-safe default in place.

    Per ENGINE_DOCTRINE §3.8: every Tier 0/1/2 entity carries the trio
    with `personal / [] / false` defaults. Coercion functions normalise
    values when present; this fills in absent keys.
    """
    for key, default in PRIVACY_TRIO_DEFAULTS.items():
        if key not in entry:
            entry[key] = (
                list(default) if isinstance(default, list) else default
            )
            events.append({
                "fix_id": "privacy-trio-inject-autofix",
                "field_path": f"{path}.{key}",
                "before": None, "after": entry[key],
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
        inject_trio = path in ENTITY_LIST_PARENT_PATHS
        derive_hub_path = path in ("$.hubs.created", "$.hubs.updated")
        for i, item in enumerate(node):
            child_path = f"{path}[{i}]"
            if inject_trio and isinstance(item, dict):
                inject_privacy_trio_defaults(item, events, child_path)
            if (
                derive_hub_path
                and isinstance(item, dict)
                and "path" not in item
                and isinstance(item.get("id"), str)
            ):
                derived = f"5_meta/mocs/{item['id']}.md"
                item["path"] = derived
                events.append({
                    "fix_id": "hub-path-derive-autofix",
                    "field_path": f"{child_path}.path",
                    "before": None, "after": derived,
                })
            walk_and_normalise(
                item, audience_accept, domain_accept, events, child_path,
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
    if not isinstance(data.get("stats"), dict):
        data["stats"] = {}
    stats = data["stats"]
    coerce_sources_processed(data, events, stats)
    normalise_empty_section_shapes(data, events, stats)
    relocate_tier2_misplaced_sections(data, events, stats)
    coerce_sensitive_entities(data, events, stats)
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
