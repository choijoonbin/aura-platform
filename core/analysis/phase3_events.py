"""
Phase3 Analysis Stream Events (PHASE3_SPEC §B)

started, step, agent, completed, failed
"""

from pydantic import BaseModel, Field


class Phase3StartedEvent(BaseModel):
    """started: runId, status"""
    runId: str
    status: str = "started"


class Phase3StepEvent(BaseModel):
    """step: label, detail, percent"""
    label: str
    detail: str = ""
    percent: int = Field(ge=0, le=100)


class Phase3AgentEvent(BaseModel):
    """agent: agent, message, percent"""
    agent: str
    message: str = ""
    percent: int = Field(ge=0, le=100)


class Phase3CompletedEvent(BaseModel):
    """completed: runId, status"""
    runId: str
    status: str = "completed"


class Phase3FailedEvent(BaseModel):
    """failed: runId, status, error, retryable"""
    runId: str
    status: str = "failed"
    error: str = ""
    retryable: bool = True
