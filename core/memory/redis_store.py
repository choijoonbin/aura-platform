"""
Redis Store Module for LangGraph Checkpointer

LangGraph의 RedisSaver를 활용하여 에이전트의 상태를 저장하고 복원합니다.
이를 통해 에이전트가 중단되었다가 다시 시작할 때 이전 상태에서 재개할 수 있습니다.
"""

import json
import logging
from typing import Any, Optional
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio import Redis

from core.config import settings

logger = logging.getLogger(__name__)


class RedisStore:
    """
    Redis 기반 저장소 클래스
    
    LangGraph Checkpoint 및 일반 캐싱을 모두 지원합니다.
    """
    
    def __init__(self, redis_url: str | None = None) -> None:
        """
        RedisStore 초기화
        
        Args:
            redis_url: Redis 연결 URL (None이면 설정에서 로드)
        """
        self.redis_url = redis_url or settings.redis_url
        self._client: Redis | None = None
        self._pool: redis.ConnectionPool | None = None
    
    async def connect(self) -> None:
        """Redis 연결 생성"""
        if self._client is None:
            self._pool = redis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=settings.redis_max_connections,
                decode_responses=False,  # LangGraph는 bytes를 사용
            )
            self._client = redis.Redis(connection_pool=self._pool)
            logger.info("Redis connection established")
    
    async def disconnect(self) -> None:
        """Redis 연결 종료"""
        if self._client:
            await self._client.close()
            self._client = None
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
            logger.info("Redis connection closed")
    
    @property
    def client(self) -> Redis:
        """Redis 클라이언트 반환"""
        if self._client is None:
            raise RuntimeError("Redis client not connected. Call connect() first.")
        return self._client
    
    async def get(self, key: str) -> bytes | None:
        """
        키로 값 조회
        
        Args:
            key: Redis 키
            
        Returns:
            값 (bytes) 또는 None
        """
        return await self.client.get(key)
    
    async def set(
        self,
        key: str,
        value: bytes | str,
        ttl: int | None = None,
    ) -> None:
        """
        키-값 저장
        
        Args:
            key: Redis 키
            value: 저장할 값
            ttl: TTL (초), None이면 기본값 사용
        """
        expire_time = ttl or settings.redis_ttl
        await self.client.setex(key, expire_time, value)
    
    async def delete(self, key: str) -> None:
        """키 삭제"""
        await self.client.delete(key)
    
    async def exists(self, key: str) -> bool:
        """키 존재 여부 확인"""
        return bool(await self.client.exists(key))
    
    async def get_json(self, key: str) -> dict[str, Any] | None:
        """
        JSON 형태로 값 조회
        
        Args:
            key: Redis 키
            
        Returns:
            딕셔너리 또는 None
        """
        value = await self.get(key)
        if value is None:
            return None
        try:
            return json.loads(value.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to decode JSON for key {key}: {e}")
            return None
    
    async def set_json(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """
        JSON 형태로 값 저장
        
        Args:
            key: Redis 키
            value: 저장할 딕셔너리
            ttl: TTL (초)
        """
        json_str = json.dumps(value, ensure_ascii=False)
        await self.set(key, json_str.encode("utf-8"), ttl)
    
    async def get_keys(self, pattern: str = "*") -> list[str]:
        """
        패턴에 매칭되는 키 목록 조회
        
        Args:
            pattern: 검색 패턴 (예: "checkpoint:*")
            
        Returns:
            키 목록
        """
        keys = await self.client.keys(pattern)
        return [key.decode("utf-8") for key in keys]
    
    async def flush_pattern(self, pattern: str) -> int:
        """
        패턴에 매칭되는 모든 키 삭제
        
        Args:
            pattern: 삭제할 키 패턴
            
        Returns:
            삭제된 키 개수
        """
        keys = await self.get_keys(pattern)
        if keys:
            return await self.client.delete(*keys)
        return 0


class LangGraphCheckpointer:
    """
    LangGraph용 Checkpoint 관리자
    
    에이전트의 실행 상태를 저장하고 복원하여
    중단된 지점에서 재개할 수 있도록 합니다.
    """
    
    def __init__(self, redis_store: RedisStore) -> None:
        """
        LangGraphCheckpointer 초기화
        
        Args:
            redis_store: RedisStore 인스턴스
        """
        self.redis_store = redis_store
        self.checkpoint_prefix = "langgraph:checkpoint"
        self.ttl = settings.redis_checkpoint_ttl
    
    def _make_key(self, thread_id: str, checkpoint_id: str | None = None) -> str:
        """
        Checkpoint 키 생성
        
        Args:
            thread_id: 스레드(대화) ID
            checkpoint_id: 체크포인트 ID (None이면 latest)
            
        Returns:
            Redis 키
        """
        if checkpoint_id:
            return f"{self.checkpoint_prefix}:{thread_id}:{checkpoint_id}"
        return f"{self.checkpoint_prefix}:{thread_id}:latest"
    
    async def save_checkpoint(
        self,
        thread_id: str,
        checkpoint_data: dict[str, Any],
        checkpoint_id: str | None = None,
    ) -> str:
        """
        Checkpoint 저장
        
        Args:
            thread_id: 스레드 ID
            checkpoint_data: 저장할 상태 데이터
            checkpoint_id: 체크포인트 ID (None이면 자동 생성)
            
        Returns:
            저장된 checkpoint_id
        """
        if checkpoint_id is None:
            import time
            checkpoint_id = str(int(time.time() * 1000))
        
        key = self._make_key(thread_id, checkpoint_id)
        latest_key = self._make_key(thread_id)
        
        # 메타데이터 추가
        data_with_meta = {
            "checkpoint_id": checkpoint_id,
            "thread_id": thread_id,
            "timestamp": checkpoint_id,
            "data": checkpoint_data,
        }
        
        # 체크포인트 저장
        await self.redis_store.set_json(key, data_with_meta, self.ttl)
        
        # latest 포인터 업데이트
        await self.redis_store.set(latest_key, checkpoint_id.encode(), self.ttl)
        
        logger.info(f"Checkpoint saved: {thread_id}/{checkpoint_id}")
        return checkpoint_id
    
    async def load_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Checkpoint 로드
        
        Args:
            thread_id: 스레드 ID
            checkpoint_id: 체크포인트 ID (None이면 최신 로드)
            
        Returns:
            저장된 상태 데이터 또는 None
        """
        if checkpoint_id is None:
            # latest checkpoint ID 조회
            latest_key = self._make_key(thread_id)
            latest_id_bytes = await self.redis_store.get(latest_key)
            if latest_id_bytes is None:
                logger.warning(f"No checkpoint found for thread: {thread_id}")
                return None
            checkpoint_id = latest_id_bytes.decode("utf-8")
        
        key = self._make_key(thread_id, checkpoint_id)
        data = await self.redis_store.get_json(key)
        
        if data:
            logger.info(f"Checkpoint loaded: {thread_id}/{checkpoint_id}")
            return data.get("data")
        
        logger.warning(f"Checkpoint not found: {thread_id}/{checkpoint_id}")
        return None
    
    async def list_checkpoints(self, thread_id: str) -> list[dict[str, Any]]:
        """
        스레드의 모든 체크포인트 목록 조회
        
        Args:
            thread_id: 스레드 ID
            
        Returns:
            체크포인트 메타데이터 리스트
        """
        pattern = f"{self.checkpoint_prefix}:{thread_id}:*"
        keys = await self.redis_store.get_keys(pattern)
        
        checkpoints = []
        for key in keys:
            if key.endswith(":latest"):
                continue
            data = await self.redis_store.get_json(key)
            if data:
                checkpoints.append({
                    "checkpoint_id": data["checkpoint_id"],
                    "thread_id": data["thread_id"],
                    "timestamp": data["timestamp"],
                })
        
        # 타임스탬프 기준 정렬
        checkpoints.sort(key=lambda x: x["timestamp"], reverse=True)
        return checkpoints
    
    async def delete_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> bool:
        """
        Checkpoint 삭제
        
        Args:
            thread_id: 스레드 ID
            checkpoint_id: 체크포인트 ID (None이면 모든 체크포인트 삭제)
            
        Returns:
            삭제 성공 여부
        """
        if checkpoint_id is None:
            # 스레드의 모든 체크포인트 삭제
            pattern = f"{self.checkpoint_prefix}:{thread_id}:*"
            deleted = await self.redis_store.flush_pattern(pattern)
            logger.info(f"Deleted {deleted} checkpoints for thread: {thread_id}")
            return deleted > 0
        
        key = self._make_key(thread_id, checkpoint_id)
        await self.redis_store.delete(key)
        logger.info(f"Checkpoint deleted: {thread_id}/{checkpoint_id}")
        return True


# 전역 RedisStore 인스턴스
_redis_store: RedisStore | None = None


async def get_redis_store() -> RedisStore:
    """
    전역 RedisStore 인스턴스 반환
    
    Returns:
        RedisStore 인스턴스
    """
    global _redis_store
    if _redis_store is None:
        _redis_store = RedisStore()
        await _redis_store.connect()
    return _redis_store


async def get_checkpointer() -> LangGraphCheckpointer:
    """
    LangGraphCheckpointer 인스턴스 반환
    
    Returns:
        LangGraphCheckpointer 인스턴스
    """
    store = await get_redis_store()
    return LangGraphCheckpointer(store)


@asynccontextmanager
async def redis_store_context():
    """
    RedisStore 컨텍스트 매니저
    
    사용 예:
        async with redis_store_context() as store:
            await store.set("key", "value")
    """
    store = await get_redis_store()
    try:
        yield store
    finally:
        # 연결은 유지 (앱 종료 시에만 닫음)
        pass


async def cleanup_redis() -> None:
    """
    Redis 연결 정리 (앱 종료 시 호출)
    """
    global _redis_store
    if _redis_store:
        await _redis_store.disconnect()
        _redis_store = None
        logger.info("Redis store cleaned up")
