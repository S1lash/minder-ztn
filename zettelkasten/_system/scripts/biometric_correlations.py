"""Pearson + point-biserial correlation engine for biometric data.

Pure stdlib — no scipy / numpy dependency. The single-subject design
(n=1 owner, n_days for sample size) makes elaborate statistical machinery
unnecessary; effect-size + counter-evidence + lag is what we need.

Public API:
  compute_pairs(metric_series_dict, lag_max=3) -> list[CorrelationFinding]
  compute_cross(metric_series, affect_tags, lag_max=2) -> list[CrossDomainFinding]
  detect_anomaly_clusters(deviations_per_day, severity='medium') -> list
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from datetime import date as date_cls, timedelta
from typing import Any, Iterable


# Mathematically-tautological metric pairs — one is a definitional
# function of the other(s). Pearson r ≈ ±1 by construction; surfacing
# these as «findings» pollutes the lens output. Order-insensitive
# blacklist (frozenset of frozenset pairs).
TAUTOLOGY_PAIRS: frozenset[frozenset[str]] = frozenset({
    # sleep_efficiency = sleep_h / (sleep_h + awake_h)
    frozenset({"sleep_efficiency", "awake_h"}),
    frozenset({"sleep_efficiency", "sleep_h"}),
    # sleep stages sum to total
    frozenset({"deep_h", "sleep_h"}),
    frozenset({"light_h", "sleep_h"}),
    frozenset({"rem_h", "sleep_h"}),
    # sleep stages partially redundant pairwise
    frozenset({"deep_h", "light_h"}),
    frozenset({"deep_h", "rem_h"}),
    frozenset({"light_h", "rem_h"}),
    # awake derived from total − sleep
    frozenset({"awake_h", "sleep_h"}),
    # sleep_score is computed from stages + duration + awake count
    frozenset({"sleep_score", "sleep_h"}),
    frozenset({"sleep_score", "deep_h"}),
    frozenset({"sleep_score", "light_h"}),
    frozenset({"sleep_score", "rem_h"}),
    frozenset({"sleep_score", "awake_h"}),
    frozenset({"sleep_score", "sleep_efficiency"}),
    # body battery: closed-day mass balance: bb_end = bb_start + charged − drained
    frozenset({"bb_charged", "bb_drained"}),
    frozenset({"bb_charged", "bb_end"}),
    frozenset({"bb_charged", "bb_start"}),
    frozenset({"bb_drained", "bb_end"}),
    frozenset({"bb_drained", "bb_start"}),
    frozenset({"bb_start", "bb_end"}),
    # ACWR = acute_load / chronic_load
    frozenset({"acwr", "acute_load"}),
    frozenset({"acwr", "chronic_load"}),
    # readiness is computed by Garmin from sleep_score / hrv / acute_load /
    # stress_history factors — strong inter-derivation
    frozenset({"readiness", "sleep_score"}),
    frozenset({"readiness", "hrv_ms"}),
    frozenset({"readiness", "stress_avg"}),
    # respiration_waking ↔ respiration_sleeping — same noisy sensor / day
    frozenset({"respiration_waking", "respiration_sleeping"}),
    # stress_avg vs stress_max — same channel
    frozenset({"stress_avg", "stress_max"}),
    # intensity moderate vs vigorous — same workout-day flag
    frozenset({"intensity_moderate_min", "intensity_vigorous_min"}),
})


def is_tautological_pair(a: str, b: str) -> bool:
    return frozenset({a, b}) in TAUTOLOGY_PAIRS


@dataclass
class CorrelationFinding:
    a: str
    b: str
    lag: int                  # b lagged by `lag` days behind a (b on day t+lag, a on day t)
    r: float
    n: int
    direction: str            # 'positive' | 'negative'
    severity: str             # 'strong' | 'medium' | 'weak'
    counter_examples: list[dict[str, Any]]


@dataclass
class CrossDomainFinding:
    metric: str
    affect: str
    lag: int
    r_pb: float
    n_total: int
    n_positive: int
    severity: str             # 'strong' | 'medium' | 'weak'
    direction: str
    supporting_dates: list[str]
    counter_examples: list[dict[str, Any]]


@dataclass
class AnomalyCluster:
    date_start: str
    date_end: str
    metrics_involved: list[str]


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r over two equal-length lists. Returns None if undefined
    (n<3 or zero variance on either side)."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return num / math.sqrt(var_x * var_y)


def _classify(r: float) -> str:
    a = abs(r)
    if a >= 0.5:
        return "strong"
    if a >= 0.2:
        return "medium"
    return "weak"


def _date_range(dates: Iterable[str]) -> list[str]:
    """All ISO dates from min to max inclusive."""
    ds = sorted(set(dates))
    if not ds:
        return []
    start = date_cls.fromisoformat(ds[0])
    end = date_cls.fromisoformat(ds[-1])
    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur = cur + timedelta(days=1)
    return out


def _aligned(
    series_a: dict[str, float],
    series_b: dict[str, float],
    lag: int,
) -> tuple[list[float], list[float], list[str]]:
    """Align two date→value mappings at the given lag.

    For lag=k, pair value of `b` on date `d` with value of `a` on date
    `d - k` (so b 'follows' a by k days). Returns matched pairs + dates.
    """
    out_a, out_b, out_d = [], [], []
    for d_b, v_b in series_b.items():
        d_a = (date_cls.fromisoformat(d_b) - timedelta(days=lag)).isoformat()
        v_a = series_a.get(d_a)
        if v_a is None or v_b is None:
            continue
        out_a.append(float(v_a))
        out_b.append(float(v_b))
        out_d.append(d_b)
    return out_a, out_b, out_d


# ---------------------------------------------------------------------------
# Phase 1 — biometric × biometric
# ---------------------------------------------------------------------------

def compute_pairs(
    metric_series: dict[str, dict[str, float]],
    *,
    lag_max: int = 3,
    min_n: int = 14,
    min_severity: str = "medium",
) -> list[CorrelationFinding]:
    """Compute pairwise Pearson over all metric pairs with lags 0..lag_max.

    `metric_series`: {metric_name: {date: value}}. Skips pairs where either
    series has < min_n samples or zero variance.

    Returns ranked list (strongest |r| first) of findings at-or-above
    `min_severity`. Each finding records the lag at which the strongest
    correlation occurred for that ordered pair.
    """
    keys = sorted(metric_series.keys())
    findings: list[CorrelationFinding] = []
    severity_rank = {"weak": 1, "medium": 2, "strong": 3}
    min_rank = severity_rank.get(min_severity, 2)

    # Iterate unordered pairs only — symmetric Pearson over equal-length
    # paired data is the same on (a,b) and (b,a). Reporting both directions
    # was redundant noise; pick the direction that yields the strongest lag.
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if is_tautological_pair(a, b):
                continue
            # Search lag both directions: positive lag means b follows a;
            # negative lag means a follows b. We encode that by swapping
            # series for the "negative" half of the search.
            best: tuple[float, int, int, list[str], str, str] | None = None
            for swap, (lhs, rhs) in (
                (False, (a, b)),
                (True, (b, a)),
            ):
                for lag in range(0, lag_max + 1):
                    if swap and lag == 0:
                        continue  # lag 0 is symmetric — covered by False branch
                    xs, ys, dates = _aligned(metric_series[lhs], metric_series[rhs], lag)
                    n = len(xs)
                    if n < min_n:
                        continue
                    r = _pearson(xs, ys)
                    if r is None:
                        continue
                    if best is None or abs(r) > abs(best[0]):
                        best = (r, lag, n, dates, lhs, rhs)
            if best is None:
                continue
            r, lag, n, dates, lhs, rhs = best
            # Re-bind a, b for finding emission so the direction reflects
            # which side leads in the strongest lag.
            a_out, b_out = lhs, rhs
            sev = _classify(r)
            if severity_rank.get(sev, 0) < min_rank:
                continue
            counter = _counter_examples(metric_series[a_out], metric_series[b_out], lag, r)
            findings.append(CorrelationFinding(
                a=a_out, b=b_out, lag=lag, r=round(r, 3), n=n,
                direction="positive" if r > 0 else "negative",
                severity=sev,
                counter_examples=counter,
            ))

    findings.sort(key=lambda f: abs(f.r), reverse=True)
    return findings


def _counter_examples(
    a_series: dict[str, float],
    b_series: dict[str, float],
    lag: int,
    r: float,
    *,
    max_examples: int = 2,
) -> list[dict[str, Any]]:
    """Surface up to `max_examples` dates where the relationship breaks
    against the dominant direction."""
    pairs = []
    for d_b, v_b in b_series.items():
        d_a = (date_cls.fromisoformat(d_b) - timedelta(days=lag)).isoformat()
        v_a = a_series.get(d_a)
        if v_a is None:
            continue
        pairs.append((d_b, float(v_a), float(v_b)))
    if not pairs:
        return []
    mean_a = sum(p[1] for p in pairs) / len(pairs)
    mean_b = sum(p[2] for p in pairs) / len(pairs)
    counter = []
    for d, va, vb in pairs:
        # If r > 0, "above mean a but below mean b" or vice versa is a counter.
        # If r < 0, "above-above" or "below-below" is a counter.
        side_a = va > mean_a
        side_b = vb > mean_b
        if r > 0 and (side_a != side_b):
            counter.append((d, va, vb, abs((va - mean_a)) + abs((vb - mean_b))))
        elif r < 0 and (side_a == side_b):
            counter.append((d, va, vb, abs((va - mean_a)) + abs((vb - mean_b))))
    counter.sort(key=lambda x: x[3], reverse=True)
    return [
        {"date": d, "value_a": round(va, 2), "value_b": round(vb, 2)}
        for d, va, vb, _ in counter[:max_examples]
    ]


# ---------------------------------------------------------------------------
# Phase 2 — biometric × affect (point-biserial)
# ---------------------------------------------------------------------------

def compute_cross(
    metric_series: dict[str, dict[str, float]],
    affect_tags: dict[str, set[str]],
    *,
    lag_max: int = 2,
    min_total: int = 14,
    min_positive: int = 5,
    min_severity: str = "medium",
) -> list[CrossDomainFinding]:
    """Point-biserial correlation between numeric metric series and binary
    per-day affect tags.

    `affect_tags`: {date: {category, ...}}.
    """
    findings: list[CrossDomainFinding] = []
    severity_rank = {"weak": 1, "medium": 2, "strong": 3}
    min_rank = severity_rank.get(min_severity, 2)

    # collect all categories ever present
    all_cats = set()
    for tags in affect_tags.values():
        all_cats.update(tags)
    if not all_cats:
        return []

    for metric, series in metric_series.items():
        for cat in sorted(all_cats):
            best: tuple[float, int, int, int, list[str]] | None = None
            for lag in range(0, lag_max + 1):
                # binary on day d_metric: was category present on day d_metric - lag?
                xs_bin: list[float] = []
                ys_metric: list[float] = []
                positive_dates: list[str] = []
                for d_m, v_m in series.items():
                    affect_date = (
                        date_cls.fromisoformat(d_m) - timedelta(days=lag)
                    ).isoformat()
                    has = 1.0 if cat in affect_tags.get(affect_date, set()) else 0.0
                    xs_bin.append(has)
                    ys_metric.append(float(v_m))
                    if has:
                        positive_dates.append(d_m)
                n_total = len(xs_bin)
                n_pos = int(sum(xs_bin))
                if n_total < min_total or n_pos < min_positive:
                    continue
                r = _pearson(xs_bin, ys_metric)
                if r is None:
                    continue
                if best is None or abs(r) > abs(best[0]):
                    best = (r, lag, n_total, n_pos, positive_dates)
            if best is None:
                continue
            r, lag, n_total, n_pos, pos_dates = best
            sev = _classify(r)
            if severity_rank.get(sev, 0) < min_rank:
                continue
            findings.append(CrossDomainFinding(
                metric=metric,
                affect=cat,
                lag=lag,
                r_pb=round(r, 3),
                n_total=n_total,
                n_positive=n_pos,
                severity=sev,
                direction="positive" if r > 0 else "negative",
                supporting_dates=pos_dates[:5],
                counter_examples=[],
            ))

    findings.sort(key=lambda f: abs(f.r_pb), reverse=True)
    return findings


# ---------------------------------------------------------------------------
# Anomaly cluster detection
# ---------------------------------------------------------------------------

def detect_anomaly_clusters(
    deviations_per_day: dict[str, list[str]],
    *,
    min_metrics: int = 2,
    max_gap_days: int = 2,
) -> list[AnomalyCluster]:
    """Detect runs of dates where multiple metrics deviated simultaneously.

    `deviations_per_day`: {date: [metric, ...]}. Day qualifies when len ≥
    `min_metrics`. Cluster = consecutive qualifying dates with at most
    `max_gap_days` gap between them.
    """
    qualifying = sorted(d for d, ms in deviations_per_day.items() if len(ms) >= min_metrics)
    if not qualifying:
        return []
    clusters: list[AnomalyCluster] = []
    cur_start = qualifying[0]
    cur_end = qualifying[0]
    cur_metrics = set(deviations_per_day[qualifying[0]])
    for d in qualifying[1:]:
        gap = (date_cls.fromisoformat(d) - date_cls.fromisoformat(cur_end)).days
        if gap <= max_gap_days:
            cur_end = d
            cur_metrics.update(deviations_per_day[d])
        else:
            clusters.append(AnomalyCluster(
                date_start=cur_start, date_end=cur_end,
                metrics_involved=sorted(cur_metrics),
            ))
            cur_start = d
            cur_end = d
            cur_metrics = set(deviations_per_day[d])
    clusters.append(AnomalyCluster(
        date_start=cur_start, date_end=cur_end,
        metrics_involved=sorted(cur_metrics),
    ))
    return clusters


def finding_to_dict(f: CorrelationFinding | CrossDomainFinding | AnomalyCluster) -> dict[str, Any]:
    return asdict(f)
