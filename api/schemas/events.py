"""
SSE Event Schemas

프론트엔드 명세 v1.0에 맞춘 SSE 이벤트 스키마를 정의합니다.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ThoughtType(str, Enum):
    """사고 과정 타입"""
    ANALYSIS = "analysis"
    PLANNING = "planning"
    REASONING = "reasoning"
    DECISION = "decision"
    REFLECTION = "reflection"


class PlanStepStatus(str, Enum):
    """계획 단계 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ToolExecutionStatus(str, Enum):
    """도구 실행 상태"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ThoughtEvent(BaseModel):
    """사고 과정 이벤트"""
    type: str = Field(default="thought", description="이벤트 타입")
    thoughtType: ThoughtType = Field(..., description="사고 타입")
    content: str = Field(..., description="사고 내용")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    sources: list[str] = Field(default_factory=list, description="참고 소스 (파일 경로, 대화 ID 등)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class PlanStepEvent(BaseModel):
    """계획 단계 이벤트"""
    type: str = Field(default="plan_step", description="이벤트 타입")
    stepId: str = Field(..., description="단계 ID")
    description: str = Field(..., description="단계 설명")
    status: PlanStepStatus = Field(..., description="단계 상태")
    confidence: float = Field(..., ge=0.0, le=1.0, description="신뢰도 점수 (0.0~1.0)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class ToolExecutionEvent(BaseModel):
    """도구 실행 이벤트"""
    type: str = Field(default="tool_execution", description="이벤트 타입")
    toolName: str = Field(..., description="도구 이름")
    toolArgs: dict[str, Any] = Field(..., description="도구 인자")
    status: ToolExecutionStatus = Field(..., description="실행 상태")
    result: Any = Field(default=None, description="실행 결과")
    error: str | None = Field(default=None, description="에러 메시지")
    requiresApproval: bool = Field(default=False, description="승인 필요 여부")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class ContentEvent(BaseModel):
    """콘텐츠 이벤트 (최종 응답)"""
    type: str = Field(default="content", description="이벤트 타입")
    content: str = Field(..., description="콘텐츠 내용")
    chunk: bool = Field(default=False, description="청크 여부 (스트리밍 중)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class ErrorEvent(BaseModel):
    """에러 이벤트"""
    type: str = Field(default="error", description="이벤트 타입")
    error: str = Field(..., description="에러 메시지")
    errorType: str = Field(default="unknown", description="에러 타입")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class StartEvent(BaseModel):
    """시작 이벤트"""
    type: str = Field(default="start", description="이벤트 타입")
    message: str = Field(default="Agent started", description="시작 메시지")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")


class EndEvent(BaseModel):
    """종료 이벤트"""
    type: str = Field(default="end", description="이벤트 타입")
    message: str = Field(default="Agent finished", description="종료 메시지")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")


# 타입 유니온
SSEEvent = ThoughtEvent | PlanStepEvent | ToolExecutionEvent | ContentEvent | ErrorEvent | StartEvent | EndEvent
