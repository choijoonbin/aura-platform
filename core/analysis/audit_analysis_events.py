"""
Case Audit Analysis — Stream Events

SSE 이벤트: started, step, evidence, confidence, proposal, completed, failed
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalysisStartedEvent(BaseModel):
    """started: {"runId","caseId","at","total_steps?"} — total_steps 있으면 SSE 시작 시점부터 진행률 계산 가능."""
    runId: str
    caseId: str
    at: str  # ISO 8601
    total_steps: int | None = Field(default=None, description="총 단계 수. 진행률(step_completion_rate) 계산용.")


class AnalysisStepEvent(BaseModel):
    """step: 실시간 스트림 시 '분석 진행률'만 전송. score/위험점수 미포함."""
    label: str
    detail: str
    percent: int = Field(ge=0, le=100, description="분석 진행률(0-100). 진행률용이며 위험 점수 아님.")
    total_steps: int | None = Field(default=None, description="총 단계 수. 진행률 계산용.")
    thought_stream: str | None = Field(default=None, description="AI 고민이 느껴지는 문장.")
    progress_type: str = Field(default="analysis_progress", description="이벤트 성격: 분석 진행률(스트림 전용).")


class AnalysisEvidenceEvent(BaseModel):
    """evidence: {"type","items":[...],"thought_stream?"} — thought_stream: 찾은 증거가 위반 판단과 어떤 상관관계인지."""
    type: str  # DOC_HEADER, DOC_ITEMS, OPEN_ITEMS, LINEAGE 등
    items: list[dict[str, Any]] = Field(default_factory=list)
    thought_stream: str | None = Field(default=None, description="수집된 증거가 규정 위반·주의·정상 판단에 어떻게 쓰이는지 한 문장.")


class AnalysisConfidenceEvent(BaseModel):
    """confidence: 스트림 중간 지표. 최종 '위험 점수'가 아님 — completed 시에만 위험 점수 전송."""
    anomalyScore: float = 0.0
    patternMatch: float = 0.0
    ruleCompliance: float = 0.0
    overall: float = 0.0
    score_type: str = Field(default="intermediate_breakdown", description="중간 지표용. 최종 위험 점수는 completed 이벤트에만 포함.")


class AnalysisProposalEvent(BaseModel):
    """proposal: {"type","riskLevel","rationale","requiresApproval", "payload"}"""
    type: str  # PAYMENT_BLOCK, REQUEST_INFO 등
    riskLevel: str = "MEDIUM"
    rationale: str = ""
    requiresApproval: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisCompletedEvent(BaseModel):
    """completed: 최종 완료 시에만 전송. '위험 점수(Score)' 및 구조화 데이터(violation_clauses, evidence_map_json) 필수 포함."""
    status: str = "completed"
    runId: str = ""
    caseId: str = ""
    summary: str = ""
    score: float = Field(default=0.0, description="위험 점수(0~1). 하위 호환용.")
    risk_score: int = Field(default=0, ge=0, le=100, description="위험 점수(Score) 0-100. 최종 완료 시에만 전송.")
    severity: str = "MEDIUM"
    score_type: str = Field(default="final_risk_score", description="최종 위험 점수. 스트림 진행률과 구분.")
    violation_clauses: list[str] = Field(default_factory=list, description="대조한 규정 조항 리스트. 절대 누락 금지.")
    evidence_map_json: list[dict[str, Any]] = Field(default_factory=list, description="전표 행(item_idx)↔근거 문장 매핑. 절대 누락 금지.")


class AnalysisFailedEvent(BaseModel):
    """failed: {"error","stage"}"""
    error: str
    stage: str
