"""Helper library for the /ztn:backfill-concepts SKILL.

Pure-Python deterministic substeps the SKILL orchestrator delegates to:
- batching: cluster scope files by origin_source / hub / domain, cap size
- verdict application: validate subagent JSON output and produce the
  frontmatter mutation set + per-note events
- log parsing: detect already-processed batches for resume

The SKILL itself owns the LLM subagent spawn loop, registry refresh
between batches, and PR creation — these are orchestration / harness
concerns, not pure-Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from _common import (
    EMITTED_CONCEPT_TYPES,
    normalize_concept_list,
    normalize_concept_name,
    normalize_domain,
    validate_concept_type,
)


# -----------------------------------------------------------------------------
# Batching
# -----------------------------------------------------------------------------

@dataclass
class Batch:
    """A unit of work for one Sonnet subagent invocation."""
    primary_key: str            # "origin_source=...", "hub=...", etc.
    primary_kind: str           # "origin_source" | "hub" | "domain-cluster" | "alphabetical"
    files: list[Path]


def _bucket_origin_source(
    fm_by_path: dict[Path, dict],
) -> tuple[dict[str, list[Path]], list[Path]]:
    """Return (buckets, residual). Bucket key is origin_source string."""
    buckets: dict[str, list[Path]] = {}
    residual: list[Path] = []
    for path, fm in fm_by_path.items():
        src = fm.get("origin_source") or fm.get("source")
        if isinstance(src, str) and src.strip():
            buckets.setdefault(src.strip(), []).append(path)
        else:
            residual.append(path)
    return buckets, residual


def _bucket_hub(
    fm_by_path: dict[Path, dict],
    paths: list[Path],
    hub_membership: dict[Path, str],
) -> tuple[dict[str, list[Path]], list[Path]]:
    buckets: dict[str, list[Path]] = {}
    residual: list[Path] = []
    for path in paths:
        hub = hub_membership.get(path)
        if hub:
            buckets.setdefault(hub, []).append(path)
        else:
            residual.append(path)
    return buckets, residual


def _bucket_domain_cluster(
    fm_by_path: dict[Path, dict],
    paths: list[Path],
) -> tuple[dict[str, list[Path]], list[Path]]:
    """Group by (primary_domain, year-month) using note's `created` date."""
    buckets: dict[str, list[Path]] = {}
    residual: list[Path] = []
    for path in paths:
        fm = fm_by_path.get(path) or {}
        domains = fm.get("domains") or []
        if not isinstance(domains, list) or not domains:
            residual.append(path)
            continue
        primary = next(
            (d for d in domains if normalize_domain(d) is not None), None
        )
        if primary is None:
            residual.append(path)
            continue
        created = fm.get("created") or fm.get("date")
        ym = _year_month(created)
        if ym is None:
            residual.append(path)
            continue
        key = f"{primary}@{ym}"
        buckets.setdefault(key, []).append(path)
    return buckets, residual


def _year_month(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw)[:7]
    if re.match(r"^\d{4}-\d{2}$", s):
        return s
    return None


def _split_oversize(
    cluster: list[Path], cap: int,
) -> list[list[Path]]:
    """Cap each cluster at `cap` files, preserving original order."""
    if cap <= 0:
        return [cluster] if cluster else []
    out: list[list[Path]] = []
    for i in range(0, len(cluster), cap):
        out.append(cluster[i: i + cap])
    return out


def compute_batches(
    fm_by_path: dict[Path, dict],
    batch_size: int = 15,
    hub_membership: dict[Path, str] | None = None,
) -> list[Batch]:
    """Apply primary → secondary → tertiary → fallback bucketing.

    `hub_membership` maps file path to its dominant hub id when available.
    Caller (SKILL orchestrator) computes this from MoC bodies — function
    is agnostic to derivation strategy.
    """
    hub_membership = hub_membership or {}
    batches: list[Batch] = []

    # Primary: origin_source
    src_buckets, residual = _bucket_origin_source(fm_by_path)
    for key, files in sorted(src_buckets.items()):
        for chunk in _split_oversize(files, batch_size):
            batches.append(Batch(
                primary_key=f"origin_source={key}",
                primary_kind="origin_source",
                files=chunk,
            ))

    if not residual:
        return batches

    residual_fm = {p: fm_by_path[p] for p in residual}

    # Secondary: hub
    hub_buckets, residual = _bucket_hub(residual_fm, residual, hub_membership)
    for key, files in sorted(hub_buckets.items()):
        for chunk in _split_oversize(files, batch_size):
            batches.append(Batch(
                primary_key=f"hub={key}",
                primary_kind="hub",
                files=chunk,
            ))

    if not residual:
        return batches
    residual_fm = {p: fm_by_path[p] for p in residual}

    # Tertiary: domain-temporal cluster
    dom_buckets, residual = _bucket_domain_cluster(residual_fm, residual)
    for key, files in sorted(dom_buckets.items()):
        for chunk in _split_oversize(files, batch_size):
            batches.append(Batch(
                primary_key=f"domain-cluster={key}",
                primary_kind="domain-cluster",
                files=chunk,
            ))

    if not residual:
        return batches

    # Fallback: alphabetical
    alpha = sorted(residual, key=lambda p: p.as_posix())
    for chunk in _split_oversize(alpha, batch_size):
        batches.append(Batch(
            primary_key="alphabetical",
            primary_kind="alphabetical",
            files=chunk,
        ))

    return batches


# -----------------------------------------------------------------------------
# Verdict application
# -----------------------------------------------------------------------------

@dataclass
class NoteVerdict:
    """Validated mutation set for a single note."""
    path: Path
    concepts: list[str]
    new_concepts: list[dict]                # [{name,type,subtype?}]
    domain_corrections: list[dict]          # [{raw, action, target?}]
    events: list[dict] = field(default_factory=list)


def _validate_new_concept(entry) -> tuple[dict | None, dict | None]:
    """Return (kept_entry, event). `kept_entry` is None on drop."""
    if not isinstance(entry, dict):
        return None, {
            "fix_id": "backfill-new-concept-drop",
            "reason": "not-an-object", "raw": str(entry),
        }
    name = normalize_concept_name(entry.get("name"))
    if name is None:
        return None, {
            "fix_id": "backfill-new-concept-drop",
            "reason": "name-unnormalisable",
            "raw": str(entry.get("name")),
        }
    ctype = entry.get("type")
    if not validate_concept_type(ctype):
        return None, {
            "fix_id": "backfill-new-concept-drop",
            "reason": "type-invalid",
            "raw_type": str(ctype),
            "name": name,
        }
    subtype = entry.get("subtype") if isinstance(entry.get("subtype"), str) else None
    kept = {"name": name, "type": ctype}
    if subtype:
        kept["subtype"] = subtype
    if isinstance(entry.get("justification"), str):
        kept["justification"] = entry["justification"]
    return kept, None


def parse_subagent_verdict(
    payload: dict,
    fm_by_path: dict[Path, dict],
) -> list[NoteVerdict]:
    """Translate parsed subagent JSON → list[NoteVerdict].

    Drops malformed per-note entries silently (events captured for the
    log). The caller applies `verdict.concepts` to frontmatter via
    `write_frontmatter`.
    """
    out: list[NoteVerdict] = []
    raw_results = payload.get("batch_results")
    if not isinstance(raw_results, list):
        return out
    fm_by_str = {p.as_posix(): (p, fm) for p, fm in fm_by_path.items()}

    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        path_str = raw.get("note_path")
        if not isinstance(path_str, str):
            continue
        match = fm_by_str.get(path_str)
        if match is None:
            continue
        path, _fm = match

        events: list[dict] = []
        concepts = normalize_concept_list(raw.get("concepts") or [])

        new_concepts: list[dict] = []
        for entry in (raw.get("new_concepts") or []):
            kept, ev = _validate_new_concept(entry)
            if ev is not None:
                events.append(ev)
            if kept is not None:
                new_concepts.append(kept)
                if kept["name"] not in concepts:
                    concepts.append(kept["name"])

        domain_corrections: list[dict] = []
        for entry in (raw.get("domain_corrections") or []):
            if not isinstance(entry, dict):
                continue
            raw_value = entry.get("raw")
            action = entry.get("action")
            target = entry.get("target")
            if action not in ("remap", "drop"):
                events.append({
                    "fix_id": "backfill-domain-correction-unknown-action",
                    "raw": str(raw_value),
                    "action": str(action),
                })
                continue
            if action == "remap":
                target_norm = normalize_domain(target)
                if target_norm is None:
                    events.append({
                        "fix_id": "backfill-domain-correction-bad-target",
                        "raw": str(raw_value),
                        "target": str(target),
                    })
                    continue
                domain_corrections.append({
                    "raw": str(raw_value), "action": "remap",
                    "target": target_norm,
                })
            else:
                domain_corrections.append({
                    "raw": str(raw_value), "action": "drop",
                })

        out.append(NoteVerdict(
            path=path,
            concepts=concepts,
            new_concepts=new_concepts,
            domain_corrections=domain_corrections,
            events=events,
        ))
    return out


def apply_verdict_to_frontmatter(
    fm: dict, verdict: NoteVerdict,
) -> dict:
    """Inject the verdict's `concepts` (and optionally adjusted `domains`)
    into `fm` and return the new dict. Pure function.
    """
    new_fm = dict(fm)
    new_fm["concepts"] = list(verdict.concepts)

    if verdict.domain_corrections:
        existing = new_fm.get("domains") or []
        if isinstance(existing, list):
            keep: list[str] = list(existing)
            for corr in verdict.domain_corrections:
                if corr["action"] == "drop":
                    keep = [d for d in keep if d != corr["raw"]]
                elif corr["action"] == "remap":
                    keep = [
                        corr["target"] if d == corr["raw"] else d
                        for d in keep
                    ]
            seen: set[str] = set()
            dedup: list[str] = []
            for d in keep:
                if d not in seen:
                    seen.add(d)
                    dedup.append(d)
            new_fm["domains"] = dedup

    return new_fm


# -----------------------------------------------------------------------------
# Resume — log parsing
# -----------------------------------------------------------------------------

_BATCH_HEADER_RE = re.compile(r"^## Batch (\d+)/(\d+)\b")


def parse_processed_batches(log_text: str) -> set[int]:
    """Return set of batch indices already recorded as processed.

    Idempotent partial-progress detection: log entry written only on
    successful batch commit, so any header in the log = batch done.
    """
    out: set[int] = set()
    for line in log_text.splitlines():
        m = _BATCH_HEADER_RE.match(line)
        if m:
            out.add(int(m.group(1)))
    return out
