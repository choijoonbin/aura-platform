"""
Audit Analysis Run Store

runId별 이벤트 큐. Trigger가 백그라운드 작업을 시작하고, Stream이 큐에서 이벤트를 읽어 SSE로 전송.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# runId -> asyncio.Queue[tuple[event_type, payload]]
_run_queues: dict[str, asyncio.Queue[tuple[str, dict[str, Any]]]] = {}


def get_or_create_queue(run_id: str) -> asyncio.Queue[tuple[str, dict[str, Any]]]:
    """runId에 대한 이벤트 큐 반환 (없으면 생성)"""
    if run_id not in _run_queues:
        _run_queues[run_id] = asyncio.Queue(maxsize=256)
    return _run_queues[run_id]


def put_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """이벤트 큐에 추가 (non-blocking)"""
    q = get_or_create_queue(run_id)
    try:
        q.put_nowait((event_type, payload))
    except asyncio.QueueFull:
        logger.warning(f"Run {run_id} event queue full, dropping event {event_type}")


def remove_queue(run_id: str) -> None:
    """완료 후 큐 제거 (메모리 정리). 스트림은 이후 get_event에서 None을 받아 종료."""
    _run_queues.pop(run_id, None)
    logger.info("run_store: queue removed run_id=%s", run_id)


async def get_event(run_id: str, timeout: float = 300.0) -> tuple[str, dict[str, Any]] | None:
    """큐에서 이벤트 조회 (timeout 초 대기)"""
    if run_id not in _run_queues:
        return None
    try:
        return await asyncio.wait_for(_run_queues[run_id].get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


def queue_exists(run_id: str) -> bool:
    """runId 큐 존재 여부"""
    return run_id in _run_queues
