"""
Phase2 Analysis Stream Events (aura.txt §2)

started, step, evidence, confidence, proposal, completed, failed
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AnalysisStartedEvent(BaseModel):
    """started: {"runId","caseId","at"}"""
    runId: str
    caseId: str
    at: str  # ISO 8601


class AnalysisStepEvent(BaseModel):
    """step: {"label","detail","percent"}"""
    label: str
    detail: str
    percent: int = Field(ge=0, le=100)


class AnalysisEvidenceEvent(BaseModel):
    """evidence: {"type","items":[...]}"""
    type: str  # DOC_HEADER, DOC_ITEMS, OPEN_ITEMS, LINEAGE 등
    items: list[dict[str, Any]] = Field(default_factory=list)


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
