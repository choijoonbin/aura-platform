"""
Checkpointer Factory for LangGraph

Finance Agent용 Checkpointer (astream 호환).
- agent.stream()은 graph.astream() 사용 → async checkpointer 필요
- SqliteSaver는 async 미지원 → MemorySaver 사용 (aget_tuple 지원)
- 영속성 필요 시: AsyncSqliteSaver + aiosqlite (별도 구현)
"""

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_checkpointer_instance: Any = None


def get_finance_checkpointer() -> Any:
    """
    Finance Agent용 Checkpointer 반환 (싱글톤)
    
    astream(비동기 스트리밍) 호환을 위해 MemorySaver 사용.
    SqliteSaver는 async 미지원(aget_tuple → NotImplementedError).
    
    Returns:
        BaseCheckpointSaver 호환 체크포인터
    """
    global _checkpointer_instance
    if _checkpointer_instance is not None:
        return _checkpointer_instance
    _checkpointer_instance = MemorySaver()
    logger.info("Finance checkpointer: MemorySaver (async compatible)")
    return _checkpointer_instance
