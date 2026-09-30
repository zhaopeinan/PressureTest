from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.schemas import EndpointStat, MetricsSnapshot


def _percentile(stats_entry: dict[str, Any], ratio: float) -> float | None:
    """Read Locust StatsEntry.to_dict percentile fields (e.g. response_time_percentile_0.95)."""
    candidates = (
        f"response_time_percentile_{ratio}",
        f"response_time_percentile_{ratio:g}",
        # Older / alternate shapes
        f"response_time_percentile_{int(ratio * 100)}",
        str(int(ratio * 100)),
    )
    for candidate in candidates:
        if candidate in stats_entry and stats_entry[candidate] is not None:
            try:
                return float(stats_entry[candidate])
            except (TypeError, ValueError):
                pass

    # Top-level chart percentiles use the same naming under nested dicts.
    nested = stats_entry.get("current_response_time_percentiles") or {}
    for candidate in candidates:
        if candidate in nested and nested[candidate] is not None:
            try:
                return float(nested[candidate])
            except (TypeError, ValueError):
                pass

    # Fallback: median_response_time for p50
    if abs(ratio - 0.5) < 1e-9 and stats_entry.get("median_response_time") is not None:
        try:
            return float(stats_entry["median_response_time"])
        except (TypeError, ValueError):
            return None
    return None


def parse_locust_stats(payload: dict[str, Any], user_count: int = 0) -> MetricsSnapshot:
    stats = payload.get("stats") or []
    total = next((s for s in stats if s.get("name") == "Aggregated"), None)
    if total is None and stats:
        total = stats[-1]

    endpoints: list[EndpointStat] = []
    for entry in stats:
        name = entry.get("name") or ""
        if name in {"", "Aggregated"}:
            continue
        endpoints.append(
            EndpointStat(
                name=name,
                method=entry.get("method") or "GET",
                num_requests=int(entry.get("num_requests") or 0),
                num_failures=int(entry.get("num_failures") or 0),
                current_rps=float(entry.get("current_rps") or 0.0),
                avg_response_time=float(entry.get("avg_response_time") or 0.0),
                min_response_time=entry.get("min_response_time"),
                max_response_time=entry.get("max_response_time"),
                p50=_percentile(entry, 0.5),
                p95=_percentile(entry, 0.95),
                p99=_percentile(entry, 0.99),
            )
        )

    total = total or {}
    total_requests = int(total.get("num_requests") or 0)
    total_failures = int(total.get("num_failures") or 0)
    fail_ratio = float(payload.get("fail_ratio") if payload.get("fail_ratio") is not None else (
        (total_failures / total_requests) if total_requests else 0.0
    ))

    # Prefer aggregate row; fall back to top-level chart percentiles.
    p50 = _percentile(total, 0.5) or _percentile(payload, 0.5)
    p95 = _percentile(total, 0.95) or _percentile(payload, 0.95)
    p99 = _percentile(total, 0.99) or _percentile(payload, 0.99)

    return MetricsSnapshot(
        ts=datetime.now(timezone.utc),
        user_count=user_count,
        total_rps=float(payload.get("total_rps") or total.get("total_rps") or total.get("current_rps") or 0.0),
        fail_ratio=fail_ratio,
        total_requests=total_requests,
        total_failures=total_failures,
        p50=p50,
        p95=p95,
        p99=p99,
        endpoints=endpoints,
    )
