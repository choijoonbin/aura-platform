"""
Case Trigger Routes

배치(DetectBatchService)가 케이스 생성/업데이트 후 호출하는 웹훅.
조건 충족 시 Finance Agent 자동 분석 시작.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from core.config import settings
from core.context import set_request_context
from core.memory.redis_store import get_redis_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/triggers", tags=["triggers"])

# 중복 트리거 방지 TTL (초)
TRIGGER_DEDUP_TTL = 300  # 5분

# severity 순서 (높을수록 심각)
SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# Auto-start 조건 (기본값)
AUTO_START_SEVERITY_MIN = getattr(settings, "trigger_auto_start_severity_min", "HIGH")
AUTO_START_STATUSES = getattr(settings, "trigger_auto_start_statuses", ["NEW", "ACTION_REQUIRED"])


def _should_auto_start(severity: str, status_val: str) -> bool:
    """Trigger 조건 평가"""
    severity_min = getattr(settings, "trigger_auto_start_severity_min", AUTO_START_SEVERITY_MIN)
    statuses = getattr(settings, "trigger_auto_start_statuses", AUTO_START_STATUSES)
    if isinstance(statuses, str):
        statuses = [s.strip() for s in statuses.split(",")]
    sev_ok = SEVERITY_ORDER.get(severity.upper(), -1) >= SEVERITY_ORDER.get(severity_min.upper(), 0)
    status_ok = status_val.upper() in [s.upper() for s in statuses]
    return sev_ok and status_ok


class CaseUpdatedPayload(BaseModel):
    """케이스 생성/업데이트 웹훅 페이로드"""
    model_config = {"populate_by_name": True}

    eventType: str = Field(..., description="case_created | case_updated")
    caseId: str = Field(..., description="케이스 ID")
    caseKey: str | None = Field(default=None, description="케이스 표시 키")
    tenantId: str = Field(..., description="테넌트 ID")
    severity: str = Field(default="MEDIUM", description="HIGH | MEDIUM | LOW | CRITICAL")
    status: str = Field(default="NEW", description="NEW | OPEN | ACTION_REQUIRED | RESOLVED")
    trace_id: str | None = Field(default=None, alias="traceId")
    timestamp: str | None = Field(default=None)
    updated_at: str | None = Field(default=None, alias="updatedAt", description="케이스 수정 시각 (중복 트리거 방지용)")


async def _run_finance_agent_background(
    case_id: str,
    case_key: str | None,
    tenant_id: str,
    trace_id: str,
) -> None:
    """Finance Agent를 백그라운드에서 실행 (SCAN_STARTED/COMPLETED audit 발행)"""
    try:
        from core.analysis.agent_factory import fetch_agent_config
        from core.memory.checkpointer_factory import get_finance_checkpointer
        from domains.finance.agents.finance_agent import FinanceAgent
        from domains.finance.agents.hooks import create_finance_sse_hook

        set_request_context(
            tenant_id=tenant_id,
            user_id="trigger_batch",
            auth_token=None,
            trace_id=trace_id,
            case_id=case_id,
            case_key=case_key,
        )
        config = await fetch_agent_config(agent_id="audit", tenant_id=tenant_id)
        agent = FinanceAgent(checkpointer=get_finance_checkpointer(), agent_config=config)
        hook = create_finance_sse_hook([])
        context = {"caseId": case_id, "caseKey": case_key}
        thread_id = f"trigger_{case_id}_{int(datetime.utcnow().timestamp())}"

        current_state: dict[str, Any] = {
            "messages": [],
            "thought_chain": [],
            "plan_steps": [],
            "execution_logs": [],
            "evidence": [],
        }

        async for graph_event in agent.stream(
            user_input=f"케이스 {case_id} 조사 및 조치 제안",
            user_id="trigger_batch",
            tenant_id=tenant_id,
            goal=f"케이스 {case_id} 조사",
            context=context,
            thread_id=thread_id,
        ):
            if isinstance(graph_event, tuple):
                mode, chunk = graph_event
                if mode == "values" and "__interrupt__" in chunk:
                    logger.info(f"Trigger run HITL interrupt (case={case_id}), stopping (no user for approval)")
                    break
                elif mode == "values" and "__interrupt__" not in chunk:
                    for k, v in chunk.items():
                        if k != "__interrupt__" and isinstance(v, (dict, list)):
                            current_state[k] = v
                elif mode == "updates":
                    for node_name, node_data in chunk.items():
                        if isinstance(node_data, dict):
                            current_state.update(node_data)
                        elif isinstance(node_data, list):
                            current_state["messages"] = node_data
                        else:
                            current_state["messages"] = [node_data]
                        state = {
                            **current_state,
                            "trace_id": trace_id,
                            "tenant_id": tenant_id,
                            "context": context,
                        }
                        await hook.on_node_start(node_name, state)
                        await hook.on_node_end(node_name, state)
    except Exception as e:
        logger.error(f"Trigger finance agent failed: {e}", exc_info=True)


@router.post("/case-updated")
async def case_updated_webhook(
    payload: CaseUpdatedPayload,
    x_trigger_secret: str | None = Header(None, alias="X-Trigger-Secret"),
):
    """
    케이스 생성/업데이트 웹훅 (배치 호출)

    BE 배치가 케이스 생성/업데이트 후 호출.
    조건 충족 시 Finance Agent 자동 분석 시작.
    """
    secret = getattr(settings, "trigger_webhook_secret", None)
    if secret and x_trigger_secret != secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid X-Trigger-Secret")

    case_id = payload.caseId
    tenant_id = payload.tenantId
    severity = payload.severity or "MEDIUM"
    status_val = payload.status or "NEW"
    trace_id = payload.trace_id or str(uuid.uuid4())

    # 중복 트리거 방지 (P1: caseId+updated_at 기반)
    updated_at_val = payload.updated_at or payload.timestamp
    dedup_suffix = updated_at_val or str(int(datetime.utcnow().timestamp()))
    try:
        store = await get_redis_store()
        dedup_key = f"trigger:case:{tenant_id}:{case_id}:{dedup_suffix}"
        if await store.client.get(dedup_key):
            logger.info(f"Trigger dedup: {case_id} (updated_at={dedup_suffix}) already triggered, skip")
            return {"status": "skipped", "reason": "duplicate", "caseId": case_id}
        await store.client.setex(dedup_key, TRIGGER_DEDUP_TTL, "1")
    except Exception as e:
        logger.warning(f"Trigger dedup check failed: {e}")

    if _should_auto_start(severity, status_val):
        asyncio.create_task(
            _run_finance_agent_background(
                case_id=case_id,
                case_key=payload.caseKey,
                tenant_id=tenant_id,
                trace_id=trace_id,
            )
        )
        logger.info(f"Trigger auto-start: case={case_id}, severity={severity}, status={status_val}")
        return {"status": "started", "caseId": case_id, "trace_id": trace_id}
    else:
        logger.info(f"Trigger waiting: case={case_id}, severity={severity}, status={status_val} (conditions not met)")
        return {"status": "waiting", "caseId": case_id, "reason": "conditions_not_met"}
