"""
Lightweight, dependency-free, thread-safe metrics registry.

Captures the operational signals we previously had no way to observe in
production: LLM latency, PARE success rate & duration, how often we fall back
to mock/unavailable products, recommendation grounding rate, and the
distribution of measurement confidence scores.

This is intentionally tiny (no Prometheus dependency). The numbers are exposed
as JSON via GET /api/v1/health/metrics. Swap the backend later without touching
call sites — they only use record_*() helpers.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Deque, Dict, Iterator

# Keep the last N samples per latency/value series for percentile estimates.
_RESERVOIR_SIZE = 512


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = defaultdict(float)
        self._series: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=_RESERVOIR_SIZE)
        )

    # ---- counters ----
    def incr(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += value

    # ---- value/latency samples ----
    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._series[name].append(float(value))

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        """Context manager that records elapsed wall-clock seconds into a series."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - start)

    # ---- export ----
    @staticmethod
    def _percentile(sorted_vals: list[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
        return sorted_vals[k]

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
            series = {k: list(v) for k, v in self._series.items()}

        series_summary = {}
        for name, vals in series.items():
            if not vals:
                continue
            sv = sorted(vals)
            series_summary[name] = {
                "count": len(sv),
                "min": round(sv[0], 4),
                "max": round(sv[-1], 4),
                "mean": round(sum(sv) / len(sv), 4),
                "p50": round(self._percentile(sv, 50), 4),
                "p95": round(self._percentile(sv, 95), 4),
            }

        # Derived rates that the team actually asks about.
        derived = {}
        rec_total = counters.get("recommendations.total", 0)
        if rec_total:
            derived["mock_fallback_rate"] = round(
                counters.get("recommendations.source.mock", 0) / rec_total, 4
            )
            derived["unavailable_rate"] = round(
                counters.get("recommendations.source.unavailable", 0) / rec_total, 4
            )
            derived["llm_grounded_rate"] = round(
                counters.get("recommendations.llm_grounded", 0) / rec_total, 4
            )
        pare_total = counters.get("pare.total", 0)
        if pare_total:
            derived["pare_success_rate"] = round(
                counters.get("pare.success", 0) / pare_total, 4
            )

        return {
            "counters": {k: round(v, 4) for k, v in sorted(counters.items())},
            "series": series_summary,
            "derived": derived,
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._series.clear()


# Global singleton
metrics = _Metrics()
