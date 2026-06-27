"""Field map for the `activitywatch` metric-day source.

Parses a daily computer-usage file produced by the activity collector
(`_sources/inbox/activitywatch/<date>.md`) into the canonical
`{date, status, summary_text, metrics, metric_failures}` shape consumed
by `process_metric_day.run`. Mirrors `biometric_extractor.extract` so the
orchestrator stays source-agnostic — the only difference is the metric
vocabulary (attention / focus rhythm, not physiology).

The source file carries a `## Detailed aggregates` fenced-JSON block whose
schema is owned by the collector (`minder-activity-collector`,
`docs/activitywatch-data-contract.md`, `schema_version: 3`). This module
translates that raw aggregate (seconds + counts) into the human-facing
Key-Number metrics (hours + counts) that get σ-baseline tracked. Seconds
are the collector's unit; hours are the record's unit — the conversion
lives here so the rest of the pipeline never sees raw seconds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml


def _round_hours(seconds: Any, ndigits: int = 2) -> Optional[float]:
    if not isinstance(seconds, (int, float)):
        return None
    return round(seconds / 3600.0, ndigits)


def _round_minutes(seconds: Any, ndigits: int = 0) -> Optional[float]:
    if not isinstance(seconds, (int, float)):
        return None
    val = round(seconds / 60.0, ndigits)
    return int(val) if ndigits == 0 else val


def _num(value: Any, ndigits: Optional[int] = None) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    return round(value, ndigits) if ndigits is not None else value


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    return yaml.safe_load(text[4:end]) or {}


def _extract_summary(text: str) -> str:
    """Return the verbatim `## Summary` section body (without the heading)."""
    marker = "\n## Summary\n"
    i = text.find(marker)
    if i < 0:
        return ""
    rest = text[i + len(marker):]
    nxt = rest.find("\n## ")
    body = rest if nxt < 0 else rest[:nxt]
    return body.strip()


def _extract_aggregate(text: str) -> dict[str, Any]:
    """Return the parsed `## Detailed aggregates` JSON object, or {}."""
    marker = "## Detailed aggregates"
    i = text.find(marker)
    if i < 0:
        return {}
    fence = text.find("```json", i)
    if fence < 0:
        return {}
    start = fence + len("```json")
    # Closing fence is always on its own line (the renderer emits `\n````);
    # anchor on the newline so a literal ``` inside a window title/URL value
    # cannot truncate the JSON early.
    end = text.find("\n```", start)
    if end < 0:
        return {}
    try:
        data = json.loads(text[start:end])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _top_app(agg: dict[str, Any]) -> Optional[str]:
    by_app = agg.get("active_seconds_by_app") or {}
    if not isinstance(by_app, dict) or not by_app:
        return None
    return max(by_app.items(), key=lambda kv: kv[1])[0]


def _map_metrics(agg: dict[str, Any]) -> dict[str, Any]:
    """Translate the collector's v2 aggregate into Key-Number metrics.

    Numeric metrics here are what the baseline engine σ-tracks; the
    *_h family is hours (collector emits seconds). Counts / ratios pass
    through. A missing aggregate key yields a missing metric (the
    pipeline simply omits absent keys), never a fabricated zero.
    """
    metrics: dict[str, Any] = {}

    metrics["active_h"] = _round_hours(agg.get("active_seconds"))
    metrics["context_switches"] = (
        int(agg["context_switches"]) if isinstance(agg.get("context_switches"), (int, float)) else None
    )
    metrics["switches_per_active_hour"] = _num(agg.get("switches_per_active_hour"), 1)
    metrics["longest_focus_block_min"] = _round_minutes(agg.get("longest_focus_block_seconds"))
    # Sustained uninterrupted focus blocks ≥25min (Newport "deep work" sense) —
    # named `sustained_focus_*` to NOT collide with the `deep_work` category
    # (time in IDE/Terminal/Claude apps). A heavy-coding day can have hours of
    # deep_work-category time yet zero sustained blocks — that contrast is signal.
    metrics["sustained_focus_h"] = _round_hours(agg.get("sustained_focus_seconds"))
    metrics["focus_blocks_ge_25min"] = (
        int(agg["focus_blocks_ge_25min"]) if isinstance(agg.get("focus_blocks_ge_25min"), (int, float)) else None
    )
    metrics["late_night_h"] = _round_hours(agg.get("late_night_active_seconds"))
    metrics["late_night_ratio"] = _num(agg.get("late_night_ratio"), 2)
    metrics["early_morning_h"] = _round_hours(agg.get("early_morning_active_seconds"))
    metrics["meeting_h"] = _round_hours(agg.get("meeting_seconds"))
    metrics["work_h"] = _round_hours(agg.get("work_seconds"))
    metrics["personal_h"] = _round_hours(agg.get("personal_seconds"))
    metrics["unclassified_h"] = _round_hours(agg.get("unclassified_seconds"))

    top = _top_app(agg)
    if top:
        metrics["top_app"] = top

    # --- v3 additions (schema_version 3): scores, AI-assisted split, loops ---
    # The AI-assisted split is the validity fix: `human_switches` excludes the
    # productive Browser↔Terminal churn of AI-coding sessions, so the σ-baseline
    # tracks GENUINE fragmentation, not Claude-Code/Codex deep-work. The raw
    # `context_switches` stays as a reference Key Number but is NOT baselined.
    metrics["productivity_score"] = _num(agg.get("productivity_score"), 0)
    metrics["focus_score"] = _num(agg.get("focus_score"), 0)
    metrics["combined_score"] = _num(agg.get("combined_score"), 0)
    metrics["human_switches"] = (
        int(agg["human_switches"]) if isinstance(agg.get("human_switches"), (int, float)) else None
    )
    metrics["human_switches_per_active_hour"] = _num(agg.get("human_switches_per_active_hour"), 1)
    metrics["ai_assisted_h"] = _round_hours(agg.get("ai_assisted_seconds"))

    # Share of switching that was AI-assisted — high share explains a high raw
    # switch count that is NOT fragmentation (context for the lens).
    ai_sw = agg.get("ai_assisted_switches")
    raw_sw = agg.get("context_switches")
    if isinstance(ai_sw, (int, float)) and isinstance(raw_sw, (int, float)) and raw_sw > 0:
        metrics["ai_assisted_switch_share"] = round(ai_sw / raw_sw, 2)

    top_cat = _top_category(agg)
    if top_cat:
        metrics["top_category"] = top_cat

    loop, distracting_loops, loops_str = _death_loop_summary(agg)
    if loop:
        metrics["top_death_loop"] = loop
    if loops_str:
        metrics["top_death_loops"] = loops_str   # top ≤3 leak pairs, for the lens
    metrics["distracting_loop_count"] = distracting_loops

    top_proj = _top_project(agg)
    if top_proj:
        metrics["top_project"] = top_proj        # presence signal (heartbeat-undercount)

    # Drop keys that came back None so the record omits truly-absent metrics
    # rather than rendering nulls.
    return {k: v for k, v in metrics.items() if v is not None}


def _top_category(agg: dict[str, Any]) -> Optional[str]:
    by_cat = agg.get("seconds_by_category") or {}
    if not isinstance(by_cat, dict) or not by_cat:
        return None
    # Ignore the catch-all buckets when naming the dominant *meaningful* category.
    ranked = [(k, v) for k, v in by_cat.items() if k not in {"uncategorized", "browser_idle", "system"}]
    pool = ranked or list(by_cat.items())
    return max(pool, key=lambda kv: kv[1])[0]


def _death_loop_summary(agg: dict[str, Any]) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Attention-leak loops (mixed/distracting, AI-assisted/productive excluded).

    Returns (top_loop_label, leak_count, top3_joined). AI-assisted loops are
    productive churn and deliberately skipped — they are not the death loop the
    owner targets. The top-3 string preserves the 2nd/3rd leak pairs the
    collector computes (otherwise discarded) so the lens sees more than #1.
    """
    loops = agg.get("death_loops")
    if not isinstance(loops, list):
        return None, None, None
    leaks = [lp for lp in loops if isinstance(lp, dict)
             and lp.get("verdict") in {"mixed", "distracting"}]
    if not leaks:
        return None, 0, None

    def _label(lp: dict[str, Any]) -> str:
        return f'{lp.get("pair")} ×{lp.get("count")} ({lp.get("verdict")})'

    top = _label(leaks[0])
    top3 = "; ".join(_label(lp) for lp in leaks[:3])
    return top, len(leaks), top3


def _top_project(agg: dict[str, Any]) -> Optional[str]:
    """Most-touched IDE project (presence signal only — the editor watcher emits
    heartbeat pulses, so `seconds_by_project_raw` undercounts time massively; use
    as 'touched project X', never as effort)."""
    by_proj = agg.get("seconds_by_project_raw") or {}
    if not isinstance(by_proj, dict) or not by_proj:
        return None
    proj, sec = max(by_proj.items(), key=lambda kv: kv[1])
    return proj if sec > 0 else None


def extract(source_path: str | Path) -> dict[str, Any]:
    """Parse one activitywatch source file into the canonical shape.

    Returns `{date, status, summary_text, metrics, metric_failures}`.
    `metric_failures` lists metric keys the file was expected to carry
    but did not parse — surfaced on the record so silent gaps are visible.
    """
    p = Path(source_path)
    text = p.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)

    date = fm.get("date")
    if date is not None:
        date = str(date)
    status = (fm.get("status") or "ok")

    summary_text = _extract_summary(text)
    agg = _extract_aggregate(text)
    metrics = _map_metrics(agg)

    metric_failures: list[str] = []
    if status == "ok" and not agg:
        metric_failures.append("detailed_aggregates_unparsed")

    return {
        "date": date or p.stem,
        "status": status,
        "summary_text": summary_text,
        "metrics": metrics,
        "metric_failures": metric_failures,
    }
