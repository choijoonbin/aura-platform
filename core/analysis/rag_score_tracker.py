"""
RAG Score Tracker — 진짜 피드백 루프 (Phase 3 P2)

retrieve_rag_pgvector 검색마다 doc_id별 유사도 점수를 Redis에 누적.
롤링 평균이 임계값 아래로 내려간 문서를 재청킹 큐에 적재.
백그라운드 워커가 큐를 소비하여 v2 재청킹 자동 실행.

Redis 키 구조:
  rag:score_stats:{doc_id}       Hash  → count, total_score, file_path, doc_type, last_queued_at
  rag:reindex_queue              List  → JSON { doc_id, file_path, doc_type, avg_score, reason }
  rag:reindex_in_progress:{doc_id}  String (TTL 1h) → 중복 실행 방지
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_SCORE_STATS_PREFIX = "rag:score_stats:"
_REINDEX_QUEUE_KEY = "rag:reindex_queue"
_IN_PROGRESS_PREFIX = "rag:reindex_in_progress:"

_IN_PROGRESS_TTL_SECONDS = 3600  # 1시간 이내 동일 문서 중복 재청킹 방지

_redis_sync_client: Any = None


def _get_sync_redis() -> Any:
    """동기 Redis 클라이언트 (redis.Redis). 싱글톤."""
    global _redis_sync_client
    if _redis_sync_client is not None:
        return _redis_sync_client
    try:
        import redis as redis_lib
        from core.config import get_settings
        url = get_settings().redis_url or "redis://localhost:6379/0"
        _redis_sync_client = redis_lib.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        return _redis_sync_client
    except Exception as e:
        logger.warning("rag_score_tracker: Redis 연결 실패 — 점수 추적 비활성화 (%s)", e)
        return None


def record_search_scores(search_results: list[dict[str, Any]]) -> None:
    """
    검색 결과에서 doc_id별 score를 Redis Hash에 누적.
    rag:score_stats:{doc_id} = { count, total_score, file_path, doc_type }

    rag.py의 retrieve_rag_pgvector 결과 직후 호출 (동기).
    """
    from core.config import get_settings
    settings = get_settings()
    if not bool(getattr(settings, "rag_score_tracking_enabled", True)):
        return
    if not search_results:
        return

    r = _get_sync_redis()
    if r is None:
        return

    # doc_id별 score 집계
    doc_scores: dict[str, list[float]] = {}
    doc_meta: dict[str, dict[str, Any]] = {}

    for item in search_results:
        doc_id = str(item.get("doc_id") or item.get("rag_document_id") or "")
        score = item.get("score")
        if not doc_id or score is None:
            continue
        doc_scores.setdefault(doc_id, []).append(float(score))

        if doc_id not in doc_meta:
            meta = item.get("metadata_json") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            doc_meta[doc_id] = {
                "file_path": meta.get("file_path") or "",
                "doc_type": meta.get("doc_type") or "",
            }

    if not doc_scores:
        return

    try:
        pipe = r.pipeline()
        for doc_id, scores in doc_scores.items():
            key = f"{_SCORE_STATS_PREFIX}{doc_id}"
            avg_this_search = sum(scores) / len(scores)
            pipe.hincrbyfloat(key, "total_score", avg_this_search)
            pipe.hincrby(key, "count", 1)
            # file_path / doc_type는 처음 한 번만 기록 (없으면 set)
            meta = doc_meta.get(doc_id, {})
            if meta.get("file_path"):
                pipe.hsetnx(key, "file_path", meta["file_path"])
            if meta.get("doc_type"):
                pipe.hsetnx(key, "doc_type", meta["doc_type"])
        pipe.execute()
    except Exception as e:
        logger.debug("rag_score_tracker: Redis 파이프라인 실패 (%s)", e)
        return

    # 기준 미달 여부 확인 → 재청킹 큐 적재
    for doc_id in doc_scores:
        _check_and_enqueue(r, doc_id, settings)


def _check_and_enqueue(r: Any, doc_id: str, settings: Any) -> None:
    """
    누적 통계를 조회하여 재청킹 필요 여부를 판단하고 큐에 적재.
    """
    min_searches = int(getattr(settings, "rag_score_min_searches_before_reindex", 5))
    avg_threshold = float(getattr(settings, "rag_score_avg_threshold", 0.65))

    key = f"{_SCORE_STATS_PREFIX}{doc_id}"
    in_progress_key = f"{_IN_PROGRESS_PREFIX}{doc_id}"

    try:
        stats = r.hgetall(key)
        if not stats:
            return

        count = int(stats.get("count", 0))
        total_score = float(stats.get("total_score", 0.0))

        if count < min_searches:
            return  # 데이터 충분하지 않음

        avg_score = total_score / count

        if avg_score >= avg_threshold:
            return  # 품질 양호

        # 이미 재청킹 진행 중이면 스킵
        if r.exists(in_progress_key):
            logger.debug(
                "rag_score_tracker: 재청킹 이미 진행 중 doc_id=%s", doc_id,
            )
            return

        file_path = stats.get("file_path", "")
        doc_type = stats.get("doc_type", "")
        last_queued_at = float(stats.get("last_queued_at", 0.0))

        # 마지막 재청킹 큐 적재 후 최소 1시간 간격 (중복 방지)
        if time.time() - last_queued_at < _IN_PROGRESS_TTL_SECONDS:
            return

        if not file_path:
            logger.debug(
                "rag_score_tracker: file_path 없음 — 재청킹 불가 doc_id=%s", doc_id,
            )
            return

        task = {
            "doc_id": doc_id,
            "file_path": file_path,
            "doc_type": doc_type or "HIERARCHICAL",
            "avg_score": round(avg_score, 4),
            "search_count": count,
            "reason": f"avg_score={avg_score:.3f} < {avg_threshold} (searches={count})",
        }
        r.rpush(_REINDEX_QUEUE_KEY, json.dumps(task, ensure_ascii=False))
        r.hset(key, "last_queued_at", time.time())

        logger.info(
            "rag_score_tracker: 재청킹 큐 적재 doc_id=%s avg_score=%.3f searches=%s",
            doc_id, avg_score, count,
        )
    except Exception as e:
        logger.debug("rag_score_tracker: 통계 확인 실패 doc_id=%s (%s)", doc_id, e)


def pop_reindex_task() -> dict[str, Any] | None:
    """
    재청킹 큐에서 태스크 1개를 꺼냄 (BLPOP 비블로킹 방식).
    없으면 None 반환.
    """
    r = _get_sync_redis()
    if r is None:
        return None
    try:
        raw = r.lpop(_REINDEX_QUEUE_KEY)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("rag_score_tracker: 큐 팝 실패 (%s)", e)
        return None


def mark_reindex_in_progress(doc_id: str) -> None:
    """재청킹 시작 마킹 — TTL 1시간 (중복 방지)."""
    r = _get_sync_redis()
    if r is None:
        return
    try:
        r.set(f"{_IN_PROGRESS_PREFIX}{doc_id}", "1", ex=_IN_PROGRESS_TTL_SECONDS)
    except Exception:
        pass


def mark_reindex_done(doc_id: str) -> None:
    """재청킹 완료 후 진행 중 마킹 해제 + 통계 초기화."""
    r = _get_sync_redis()
    if r is None:
        return
    try:
        r.delete(f"{_IN_PROGRESS_PREFIX}{doc_id}")
        # 통계 초기화 (재청킹 이후 새로운 기준으로 측정 시작)
        r.delete(f"{_SCORE_STATS_PREFIX}{doc_id}")
        logger.info("rag_score_tracker: 통계 초기화 doc_id=%s (재청킹 완료)", doc_id)
    except Exception:
        pass


def get_score_stats(doc_id: str) -> dict[str, Any] | None:
    """doc_id의 누적 score 통계 반환 (모니터링/디버깅용)."""
    r = _get_sync_redis()
    if r is None:
        return None
    try:
        stats = r.hgetall(f"{_SCORE_STATS_PREFIX}{doc_id}")
        if not stats:
            return None
        count = int(stats.get("count", 0))
        total = float(stats.get("total_score", 0.0))
        return {
            "doc_id": doc_id,
            "search_count": count,
            "avg_score": round(total / count, 4) if count > 0 else None,
            "total_score": round(total, 4),
            "file_path": stats.get("file_path"),
            "doc_type": stats.get("doc_type"),
            "last_queued_at": float(stats.get("last_queued_at", 0.0)) or None,
        }
    except Exception as e:
        logger.debug("rag_score_tracker: 통계 조회 실패 (%s)", e)
        return None


def get_queue_length() -> int:
    """재청킹 대기 큐 길이 반환."""
    r = _get_sync_redis()
    if r is None:
        return 0
    try:
        return int(r.llen(_REINDEX_QUEUE_KEY) or 0)
    except Exception:
        return 0
