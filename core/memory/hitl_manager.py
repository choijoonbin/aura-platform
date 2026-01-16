"""
HITL (Human-In-The-Loop) Manager

Redis Pub/Sub을 사용하여 승인 신호를 수신하고 처리합니다.
"""

import json
import logging
import uuid
from typing import Any, Callable

import redis.asyncio as redis
from redis.asyncio import Redis

from core.config import settings
from core.memory.redis_store import get_redis_store

logger = logging.getLogger(__name__)


class HITLManager:
    """
    HITL 승인 신호 관리자
    
    Redis Pub/Sub을 통해 승인/거절 신호를 수신하고 처리합니다.
    """
    
    def __init__(self, redis_client: Redis | None = None):
        """
        HITLManager 초기화
        
        Args:
            redis_client: Redis 클라이언트 (None이면 새로 생성)
        """
        self.redis_client = redis_client
        self._pubsub: redis.client.PubSub | None = None
    
    async def _get_redis_client(self) -> Redis:
        """Redis 클라이언트 가져오기"""
        if self.redis_client is None:
            store = await get_redis_store()
            self.redis_client = store.client
        return self.redis_client
    
    async def save_approval_request(
        self,
        request_id: str,
        session_id: str,
        action_type: str,
        context: dict[str, Any],
        user_id: str,
        tenant_id: str,
    ) -> None:
        """
        승인 요청을 Redis에 저장
        
        Args:
            request_id: 요청 ID
            session_id: 세션 ID
            action_type: 액션 타입 (예: "send_email", "git_merge")
            context: 액션 컨텍스트
            user_id: 사용자 ID
            tenant_id: 테넌트 ID
        """
        redis_client = await self._get_redis_client()
        
        # 승인 요청 데이터
        request_data = {
            "requestId": request_id,
            "sessionId": session_id,
            "actionType": action_type,
            "context": context,
            "status": "pending",
            "userId": user_id,
            "tenantId": tenant_id,
            "createdAt": int(uuid.uuid4().int % (10 ** 10)),  # 임시 타임스탬프
        }
        
        # Redis에 저장 (TTL: 30분)
        key = f"hitl:request:{request_id}"
        await redis_client.setex(
            key,
            1800,  # 30분
            json.dumps(request_data, ensure_ascii=False)
        )
        
        # 세션 정보 저장 (TTL: 60분)
        session_key = f"hitl:session:{session_id}"
        session_data = {
            "sessionId": session_id,
            "requestId": request_id,
            "userId": user_id,
            "tenantId": tenant_id,
        }
        await redis_client.setex(
            session_key,
            3600,  # 60분
            json.dumps(session_data, ensure_ascii=False)
        )
        
        logger.info(f"HITL approval request saved: {request_id} (session: {session_id})")
    
    async def wait_for_approval_signal(
        self,
        session_id: str,
        timeout: int = 300,
    ) -> dict[str, Any] | None:
        """
        승인 신호 대기 (Redis Pub/Sub)
        
        Args:
            session_id: 세션 ID
            timeout: 타임아웃 (초), 기본 300초 (5분)
            
        Returns:
            승인 신호 딕셔너리 또는 None (타임아웃)
            
        예시 반환값:
            {
                "type": "approval",
                "requestId": "req-12345",
                "status": "approved",
                "timestamp": 1706152860
            }
        """
        redis_client = await self._get_redis_client()
        
        # Pub/Sub 구독
        self._pubsub = redis_client.pubsub()
        channel = f"hitl:channel:{session_id}"
        await self._pubsub.subscribe(channel)
        
        logger.info(f"Waiting for HITL signal on channel: {channel}")
        
        try:
            import asyncio
            
            # 타임아웃 설정
            async def wait_for_message():
                async for message in self._pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        signal = json.loads(data)
                        logger.info(f"Received HITL signal: {signal}")
                        return signal
                return None
            
            try:
                signal = await asyncio.wait_for(wait_for_message(), timeout=timeout)
                return signal
            except asyncio.TimeoutError:
                logger.warning(f"HITL signal timeout after {timeout} seconds")
                return None
                
        finally:
            if self._pubsub:
                await self._pubsub.unsubscribe(channel)
                await self._pubsub.close()
                self._pubsub = None
    
    async def get_approval_request(self, request_id: str) -> dict[str, Any] | None:
        """
        승인 요청 조회
        
        Args:
            request_id: 요청 ID
            
        Returns:
            승인 요청 데이터 또는 None
        """
        redis_client = await self._get_redis_client()
        key = f"hitl:request:{request_id}"
        
        data = await redis_client.get(key)
        if data is None:
            return None
        
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        
        return json.loads(data)
    
    async def get_signal(self, session_id: str) -> dict[str, Any] | None:
        """
        승인 신호 조회 (Redis Key 기반)
        
        Args:
            session_id: 세션 ID
            
        Returns:
            승인 신호 데이터 또는 None
        """
        redis_client = await self._get_redis_client()
        key = f"hitl:signal:{session_id}"
        
        data = await redis_client.get(key)
        if data is None:
            return None
        
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        
        return json.loads(data)


# 전역 HITL Manager 인스턴스
_hitl_manager: HITLManager | None = None


async def get_hitl_manager() -> HITLManager:
    """HITLManager 인스턴스 반환"""
    global _hitl_manager
    if _hitl_manager is None:
        _hitl_manager = HITLManager()
    return _hitl_manager
