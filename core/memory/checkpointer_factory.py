"""
Checkpointer Factory for LangGraph

Finance Agent 등에서 사용할 BaseCheckpointSaver 호환 체크포인터를 생성합니다.
- SqliteSaver: 파일 기반 영속성 (langgraph-checkpoint-sqlite)
- MemorySaver: 인메모리 (폴백)
"""

import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

# SqliteSaver는 optional - 패키지 미설치 시 MemorySaver 사용
_SqliteSaver: Any = None

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    _SqliteSaver = SqliteSaver
except ImportError:
    pass


_checkpointer_instance: Any = None


def get_finance_checkpointer() -> Any:
    """
    Finance Agent용 Checkpointer 반환 (싱글톤)
    
    - langgraph-checkpoint-sqlite 설치 시: SqliteSaver (파일 기반 영속성)
    - 미설치 시: MemorySaver (인메모리, 단일 프로세스)
    
    Returns:
        BaseCheckpointSaver 호환 체크포인터
    """
    global _checkpointer_instance
    if _checkpointer_instance is not None:
        return _checkpointer_instance
    if _SqliteSaver is not None:
        db_path = Path("data/checkpoints/finance.sqlite")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn_str = str(db_path.absolute())
        try:
            _checkpointer_instance = _SqliteSaver.from_conn_string(conn_str)
            logger.info(f"Finance checkpointer: SqliteSaver ({conn_str})")
            return _checkpointer_instance
        except Exception as e:
            logger.warning(f"SqliteSaver init failed: {e}, falling back to MemorySaver")
    _checkpointer_instance = MemorySaver()
    logger.info("Finance checkpointer: MemorySaver (in-memory)")
    return _checkpointer_instance
