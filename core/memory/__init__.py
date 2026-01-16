"""
Memory Module

대화 히스토리 및 상태를 관리하는 메모리 시스템을 제공합니다.
LangGraph Checkpointer를 통해 에이전트 상태 저장 및 복원을 지원합니다.
"""

from core.memory.redis_store import (
    RedisStore,
    LangGraphCheckpointer,
    get_redis_store,
    get_checkpointer,
    cleanup_redis,
)
from core.memory.conversation import (
    ConversationHistory,
    Message,
    MessageRole,
    get_conversation_history,
    add_user_message,
    add_assistant_message,
    get_recent_context,
)
from core.memory.hitl_manager import (
    HITLManager,
    get_hitl_manager,
)

__all__ = [
    "RedisStore",
    "LangGraphCheckpointer",
    "get_redis_store",
    "get_checkpointer",
    "cleanup_redis",
    "ConversationHistory",
    "Message",
    "MessageRole",
    "get_conversation_history",
    "add_user_message",
    "add_assistant_message",
    "get_recent_context",
    "HITLManager",
    "get_hitl_manager",
]
