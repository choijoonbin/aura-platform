"""
Lightweight in-process metrics for Aura.

외부 모니터링 스택이 없더라도 핵심 카운터/지연시간을 기록할 수 있도록
프로세스 메모리 기반 집계를 제공합니다.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_latency_stats: dict[str, dict[str, float]] = {}


def incr(metric: str, value: int = 1) -> None:
    with _lock:
        _counters[metric] += value


def observe_ms(metric: str, duration_ms: float) -> None:
    with _lock:
        stat = _latency_stats.get(metric) or {
            "count": 0.0,
            "sum_ms": 0.0,
            "max_ms": 0.0,
            "last_ms": 0.0,
        }
        stat["count"] += 1
        stat["sum_ms"] += duration_ms
        stat["max_ms"] = max(stat["max_ms"], duration_ms)
        stat["last_ms"] = duration_ms
        _latency_stats[metric] = stat


def start_timer() -> float:
    return time.perf_counter()


def stop_timer(start: float, metric: str) -> float:
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    observe_ms(metric, elapsed_ms)
    return elapsed_ms


def snapshot() -> dict[str, Any]:
    with _lock:
        counters = dict(_counters)
        latency = {}
        for k, v in _latency_stats.items():
            count = max(v.get("count", 0.0), 1.0)
            latency[k] = {
                **v,
                "avg_ms": v.get("sum_ms", 0.0) / count,
            }
        return {"counters": counters, "latency_ms": latency}

