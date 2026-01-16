"""
Conversation Memory Module

대화 히스토리를 관리하고 LangGraph와 통합합니다.
"""

import logging
from datetime import datetime
from typing import Any, Optional
from enum import Enum

from pydantic import BaseModel, Field

from core.memory.redis_store import RedisStore, get_redis_store

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    """메시지 역할"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """대화 메시지 모델"""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ConversationHistory:
    """
    대화 히스토리 관리 클래스
    
    Redis를 백엔드로 사용하여 대화 내용을 저장하고 조회합니다.
    """
    
    def __init__(self, redis_store: RedisStore) -> None:
        """
        ConversationHistory 초기화
        
        Args:
            redis_store: RedisStore 인스턴스
        """
        self.redis_store = redis_store
        self.prefix = "conversation"
    
    def _make_key(
        self,
        thread_id: str,
        tenant_id: str | None = None,
    ) -> str:
        """
        대화 키 생성
        
        Args:
            thread_id: 대화 스레드 ID
            tenant_id: 테넌트 ID (멀티테넌시)
            
        Returns:
            Redis 키
        """
        if tenant_id:
            return f"{self.prefix}:{tenant_id}:{thread_id}"
        return f"{self.prefix}:{thread_id}"
    
    async def add_message(
        self,
        thread_id: str,
        message: Message,
        tenant_id: str | None = None,
        max_messages: int = 100,
    ) -> None:
        """
        메시지 추가
        
        Args:
            thread_id: 대화 스레드 ID
            message: 추가할 메시지
            tenant_id: 테넌트 ID
            max_messages: 최대 메시지 개수 (초과 시 오래된 것 삭제)
        """
        key = self._make_key(thread_id, tenant_id)
        
        # 기존 히스토리 조회
        history = await self.redis_store.get_json(key)
        if history is None:
            history = {"messages": [], "created_at": datetime.utcnow().isoformat()}
        
        # 메시지 추가
        history["messages"].append(message.model_dump(mode="json"))
        history["updated_at"] = datetime.utcnow().isoformat()
        
        # 최대 개수 제한
        if len(history["messages"]) > max_messages:
            history["messages"] = history["messages"][-max_messages:]
        
        # 저장
        await self.redis_store.set_json(key, history)
        logger.debug(f"Message added to thread: {thread_id}")
    
    async def get_messages(
        self,
        thread_id: str,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        """
        메시지 목록 조회
        
        Args:
            thread_id: 대화 스레드 ID
            tenant_id: 테넌트 ID
            limit: 최대 조회 개수
            
        Returns:
            메시지 리스트
        """
        key = self._make_key(thread_id, tenant_id)
        history = await self.redis_store.get_json(key)
        
        if history is None:
            return []
        
        messages_data = history.get("messages", [])
        if limit:
            messages_data = messages_data[-limit:]
        
        return [Message(**msg) for msg in messages_data]
    
    async def get_messages_for_llm(
        self,
        thread_id: str,
        tenant_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        """
        LLM 입력용 메시지 형식으로 조회
        
        Args:
            thread_id: 대화 스레드 ID
            tenant_id: 테넌트 ID
            limit: 최대 조회 개수
            
        Returns:
            LLM 형식 메시지 리스트 [{"role": "user", "content": "..."}]
        """
        messages = await self.get_messages(thread_id, tenant_id, limit)
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
        ]
    
    async def clear_history(
        self,
        thread_id: str,
        tenant_id: str | None = None,
    ) -> None:
        """
        대화 히스토리 삭제
        
        Args:
            thread_id: 대화 스레드 ID
            tenant_id: 테넌트 ID
        """
        key = self._make_key(thread_id, tenant_id)
        await self.redis_store.delete(key)
        logger.info(f"Conversation history cleared: {thread_id}")
    
    async def get_thread_metadata(
        self,
        thread_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        대화 스레드 메타데이터 조회
        
        Args:
            thread_id: 대화 스레드 ID
            tenant_id: 테넌트 ID
            
        Returns:
            메타데이터 딕셔너리
        """
        key = self._make_key(thread_id, tenant_id)
        history = await self.redis_store.get_json(key)
        
        if history is None:
            return None
        
        return {
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "message_count": len(history.get("messages", [])),
            "created_at": history.get("created_at"),
            "updated_at": history.get("updated_at"),
        }
    
    async def list_threads(
        self,
        tenant_id: str | None = None,
    ) -> list[str]:
        """
        모든 대화 스레드 ID 목록 조회
        
        Args:
            tenant_id: 테넌트 ID (None이면 전체)
            
        Returns:
            스레드 ID 리스트
        """
        if tenant_id:
            pattern = f"{self.prefix}:{tenant_id}:*"
        else:
            pattern = f"{self.prefix}:*"
        
        keys = await self.redis_store.get_keys(pattern)
        
        # 키에서 thread_id 추출
        thread_ids = []
        for key in keys:
            parts = key.split(":")
            if tenant_id:
                # prefix:tenant_id:thread_id
                if len(parts) >= 3:
                    thread_ids.append(parts[2])
            else:
                # prefix:thread_id
                if len(parts) >= 2:
                    thread_ids.append(parts[1])
        
        return thread_ids


async def get_conversation_history() -> ConversationHistory:
    """
    ConversationHistory 인스턴스 반환
    
    Returns:
        ConversationHistory 인스턴스
    """
    redis_store = await get_redis_store()
    return ConversationHistory(redis_store)


# 편의 함수들
async def add_user_message(
    thread_id: str,
    content: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """사용자 메시지 추가"""
    history = await get_conversation_history()
    message = Message(
        role=MessageRole.USER,
        content=content,
        metadata=metadata or {},
    )
    await history.add_message(thread_id, message, tenant_id)


async def add_assistant_message(
    thread_id: str,
    content: str,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """어시스턴트 메시지 추가"""
    history = await get_conversation_history()
    message = Message(
        role=MessageRole.ASSISTANT,
        content=content,
        metadata=metadata or {},
    )
    await history.add_message(thread_id, message, tenant_id)


async def get_recent_context(
    thread_id: str,
    tenant_id: str | None = None,
    limit: int = 10,
) -> str:
    """
    최근 대화 컨텍스트를 문자열로 반환
    
    Args:
        thread_id: 대화 스레드 ID
        tenant_id: 테넌트 ID
        limit: 최대 메시지 개수
        
    Returns:
        대화 내용 문자열
    """
    history = await get_conversation_history()
    messages = await history.get_messages(thread_id, tenant_id, limit)
    
    context_parts = []
    for msg in messages:
        role = msg.role.value.capitalize()
        context_parts.append(f"{role}: {msg.content}")
    
    return "\n".join(context_parts)
