"""
SSE Event Schemas

프론트엔드 명세 v1.0에 맞춘 SSE 이벤트 스키마를 정의합니다.
이벤트 페이로드에는 스키마 버전(version) 필드를 포함하여 호환성 관리를 지원합니다.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# SSE 페이로드 스키마 버전 (권장: 모든 이벤트에 version 포함)
SSE_EVENT_PAYLOAD_VERSION = "1.0"


class SSEEventPayloadBase(BaseModel):
    """SSE 이벤트 페이로드 공통 필드 (스키마 버전)"""
    version: str = Field(default=SSE_EVENT_PAYLOAD_VERSION, description="페이로드 스키마 버전")


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


class ThoughtEvent(SSEEventPayloadBase):
    """사고 과정 이벤트 (ThoughtChainUI: step/thought/evidence 규격)"""
    type: str = Field(default="thought", description="이벤트 타입")
    thoughtType: ThoughtType = Field(..., description="사고 타입")
    content: str = Field(..., description="사고 내용 (thought)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    sources: list[str] = Field(default_factory=list, description="참고 소스 (파일 경로, 대화 ID 등)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")
    # 감사 단계별 세분화 (ThoughtChainUI)
    step: str | None = Field(default=None, description="단계 식별자: INTERNAL_POLICY_LOOKUP, WEB_SEARCH, REGULATION_MATCH, FINAL_SYNTHESIS 등")
    evidence: str | None = Field(default=None, description="해당 단계에서 발견한 근거 요약 (예: 규정 제12조 발견)")


class PlanStepEvent(SSEEventPayloadBase):
    """계획 단계 이벤트"""
    type: str = Field(default="plan_step", description="이벤트 타입")
    stepId: str = Field(..., description="단계 ID")
    description: str = Field(..., description="단계 설명")
    status: PlanStepStatus = Field(..., description="단계 상태")
    confidence: float = Field(..., ge=0.0, le=1.0, description="신뢰도 점수 (0.0~1.0)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class PlanStepUpdateEvent(SSEEventPayloadBase):
    """계획 단계 업데이트 이벤트 (프론트엔드 요구사항)"""
    type: str = Field(default="plan_step_update", description="이벤트 타입")
    stepId: str = Field(..., description="단계 ID")
    status: PlanStepStatus = Field(..., description="업데이트된 상태")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="진행률 (0.0~1.0)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class TimelineStepUpdateEvent(SSEEventPayloadBase):
    """타임라인 단계 업데이트 이벤트 (프론트엔드 요구사항)"""
    type: str = Field(default="timeline_step_update", description="이벤트 타입")
    stepId: str = Field(..., description="단계 ID")
    title: str = Field(..., description="단계 제목")
    status: PlanStepStatus = Field(..., description="단계 상태")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="진행률 (0.0~1.0)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class ToolExecutionEvent(SSEEventPayloadBase):
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


class ContentEvent(SSEEventPayloadBase):
    """콘텐츠 이벤트 (최종 응답)"""
    type: str = Field(default="content", description="이벤트 타입")
    content: str = Field(..., description="콘텐츠 내용")
    chunk: bool = Field(default=False, description="청크 여부 (스트리밍 중)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class ErrorEvent(SSEEventPayloadBase):
    """에러 이벤트"""
    type: str = Field(default="error", description="이벤트 타입")
    error: str = Field(..., description="에러 메시지")
    errorType: str = Field(default="unknown", description="에러 타입")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")
    message: str | None = Field(default=None, description="에러 상세 메시지")


class FailedEvent(SSEEventPayloadBase):
    """작업 실패 이벤트 (HITL 타임아웃 등)"""
    type: str = Field(default="failed", description="이벤트 타입")
    message: str = Field(..., description="실패 메시지")
    error: str = Field(..., description="에러 메시지")
    errorType: str = Field(..., description="에러 타입")
    requestId: str | None = Field(default=None, description="요청 ID (HITL의 경우)")
    sessionId: str | None = Field(default=None, description="세션 ID (HITL의 경우)")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class StartEvent(SSEEventPayloadBase):
    """시작 이벤트"""
    type: str = Field(default="start", description="이벤트 타입")
    message: str = Field(default="Agent started", description="시작 메시지")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")


class EndEvent(SSEEventPayloadBase):
    """종료 이벤트"""
    type: str = Field(default="end", description="이벤트 타입")
    message: str = Field(default="Agent finished", description="종료 메시지")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="타임스탬프")


# 타입 유니온
SSEEvent = (
    ThoughtEvent | PlanStepEvent | PlanStepUpdateEvent | TimelineStepUpdateEvent |
    ToolExecutionEvent | ContentEvent | ErrorEvent | FailedEvent | StartEvent | EndEvent
)
