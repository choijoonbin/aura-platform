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
    """step: {"label","detail","percent","total_steps?","thought_stream?"} — thought_stream: 인간 언어 사고(aura_auditor.yaml Internal Monologue)."""
    label: str
    detail: str
    percent: int = Field(ge=0, le=100)
    total_steps: int | None = Field(default=None, description="총 단계 수. BE injectStepCompletionRate에서 step_completion_rate 계산용.")
    thought_stream: str | None = Field(default=None, description="'왜 이 조항을 찾는지', '찾은 결과가 위반과 어떤 상관관계인지' 등 AI 고민이 느껴지는 문장. 기술 로그 대신 사용.")


class AnalysisEvidenceEvent(BaseModel):
    """evidence: {"type","items":[...],"thought_stream?"} — thought_stream: 찾은 증거가 위반 판단과 어떤 상관관계인지."""
    type: str  # DOC_HEADER, DOC_ITEMS, OPEN_ITEMS, LINEAGE 등
    items: list[dict[str, Any]] = Field(default_factory=list)
    thought_stream: str | None = Field(default=None, description="수집된 증거가 규정 위반·주의·정상 판단에 어떻게 쓰이는지 한 문장.")


class AnalysisConfidenceEvent(BaseModel):
    """confidence: {"anomalyScore","patternMatch","ruleCompliance","overall"}"""
    anomalyScore: float = 0.0
    patternMatch: float = 0.0
    ruleCompliance: float = 0.0
    overall: float = 0.0


class AnalysisProposalEvent(BaseModel):
    """proposal: {"type","riskLevel","rationale","requiresApproval", "payload"}"""
    type: str  # PAYMENT_BLOCK, REQUEST_INFO 등
    riskLevel: str = "MEDIUM"
    rationale: str = ""
    requiresApproval: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisCompletedEvent(BaseModel):
    """completed: {"status","runId","caseId","summary","score","severity"} — FE 정상 종료 인식용"""
    status: str = "completed"
    runId: str = ""
    caseId: str = ""
    summary: str = ""
    score: float = 0.0
    severity: str = "MEDIUM"


class AnalysisFailedEvent(BaseModel):
    """failed: {"error","stage"}"""
    error: str
    stage: str
