"""
Agent Stream Event Schemas (Prompt C)

Dashboard "Agent Execution Stream"을 실제 에이전트/워크플로우 상태 이벤트로 채우기 위한 모델.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentStreamStage(str, Enum):
    """Agent Execution Stream stage (C1)"""
    SCAN = "SCAN"
    DETECT = "DETECT"
    ANALYZE = "ANALYZE"
    SIMULATE = "SIMULATE"
    EXECUTE = "EXECUTE"
    MATCH = "MATCH"


class AgentEvent(BaseModel):
    """Agent Stream 이벤트 (C1)"""

    tenantId: str = Field(..., description="테넌트 ID (숫자 문자열 권장)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="발생 시각")
    stage: str = Field(..., description="SCAN/DETECT/EXECUTE/SIMULATE/ANALYZE/MATCH")
    message: str = Field(..., description="운영자 이해 가능 문장")
    caseKey: str | None = Field(default=None, description="케이스 표시 키 (예: CS-2026-0001)")
    caseId: str | None = Field(default=None, description="케이스 ID")
    severity: str | None = Field(default="INFO", description="INFO/WARN/ERROR")
    traceId: str | None = Field(default=None, description="요청 추적 ID")
    actionId: str | None = Field(default=None, description="액션 ID (EXECUTE stage)")
    payload: dict[str, Any] = Field(default_factory=dict, description="추가 상세")
