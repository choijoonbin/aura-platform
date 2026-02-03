"""
Finance Agent Routes

Finance 도메인 에이전트 SSE 스트리밍 및 HITL 승인 API입니다.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, TenantId
from api.routes.aura_backend import format_sse_event
from api.schemas.hitl_events import HITLEvent
from core.config import settings
from core.context import set_request_context
from core.memory.hitl_manager import get_hitl_manager
from domains.finance.agents.finance_agent import get_finance_agent
from domains.finance.agents.hooks import create_finance_sse_hook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/finance", tags=["finance-agent"])

STREAMING_EVENT_DELAY = 0.05


class FinanceStreamRequest(BaseModel):
    """Finance 스트리밍 요청"""
    prompt: str = Field(..., min_length=1, description="사용자 프롬프트 (목표)")
    goal: str | None = Field(default=None, description="목표 (예: 중복송장 의심 케이스 조사 후 조치 제안)")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="caseId, documentIds, entityIds, openItemIds",
    )
    thread_id: str | None = Field(default=None, description="스레드 ID")


def _enrich_event_data(data: dict[str, Any], trace_id: str, case_id: str | None, tenant_id: str) -> dict[str, Any]:
    """이벤트 data에 trace_id, case_id, tenant_id 추가"""
    data["trace_id"] = trace_id
    data["tenant_id"] = tenant_id
    if case_id:
        data["case_id"] = case_id
    return data


@router.post("/stream")
async def finance_stream(
    request: FinanceStreamRequest,
    user: CurrentUser,
    tenant_id: TenantId,
    req: Request,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """
    Finance 에이전트 SSE 스트리밍
    
    이벤트 타입 및 순서: start → thought → plan_step → tool_execution → hitl(필요시) → content → end → done
    에러 시: ... → error → done. Last-Event-ID 지원(재연결, 중복 방지).
    각 이벤트 data에 trace_id, case_id, tenant_id 포함.
    """
    trace_id = str(uuid.uuid4())
    case_id = request.context.get("caseId") if request.context else None
    tenant_id_val = tenant_id or "default"
    
    # Synapse Tool API 호출 시 사용할 컨텍스트 설정 (tenant/user/trace headers)
    auth_header = req.headers.get("Authorization")
    set_request_context(
        tenant_id=tenant_id_val,
        user_id=user.user_id,
        auth_token=auth_header,
        trace_id=trace_id,
    )
    
    async def event_generator():
        event_queue: list[dict[str, Any]] = []
        session_id = f"finance_{user.user_id}_{int(datetime.utcnow().timestamp())}"
        
        event_id_counter = 0
        if last_event_id:
            try:
                last_id = int(last_event_id)
                event_id_counter = last_id + 1
                logger.info(f"Finance stream resuming from event ID: {last_event_id}")
            except (ValueError, TypeError):
                pass
        
        try:
            start_data = _enrich_event_data(
                {"type": "start", "message": "Finance agent started", "timestamp": int(datetime.utcnow().timestamp())},
                trace_id, case_id, tenant_id_val,
            )
            event_id_counter += 1
            yield format_sse_event("start", start_data, str(event_id_counter))
            
            agent = get_finance_agent()
            hook = create_finance_sse_hook(event_queue)
            thread_id = request.thread_id or f"finance_{user.user_id}_{tenant_id_val}_{int(datetime.utcnow().timestamp())}"
            
            current_state: dict[str, Any] = {
                "messages": [],
                "thought_chain": [],
                "plan_steps": [],
                "execution_logs": [],
                "evidence": [],
            }
            
            resume_value: Any = None
            stream_done = False
            hitl_manager = await get_hitl_manager()
            
            while not stream_done:
                async for graph_event in agent.stream(
                    user_input=request.prompt,
                    user_id=user.user_id,
                    tenant_id=tenant_id_val,
                    goal=request.goal or request.prompt,
                    context=request.context,
                    thread_id=thread_id,
                    resume_value=resume_value,
                ):
                    if isinstance(graph_event, tuple):
                        mode, chunk = graph_event
                        if mode == "values" and "__interrupt__" in chunk:
                            interrupt_list = chunk.get("__interrupt__", [])
                            for intr in interrupt_list:
                                payload = intr.value if hasattr(intr, "value") else intr
                                request_id = payload.get("requestId", f"req_{uuid.uuid4().hex[:12]}")
                                await hitl_manager.save_approval_request(
                                    request_id=request_id,
                                    session_id=session_id,
                                    action_type=payload.get("actionType", payload.get("toolName", "")),
                                    context=payload.get("context", {}),
                                    user_id=user.user_id,
                                    tenant_id=tenant_id_val,
                                )
                                hitl_event = HITLEvent.create(
                                    request_id=request_id,
                                    action_type=payload.get("actionType", payload.get("toolName", "")),
                                    message=payload.get("message", f"{payload.get('toolName', 'propose_action')} 실행을 승인하시겠습니까?"),
                                    context=payload.get("context", {}),
                                )
                                hitl_data = _enrich_event_data(
                                    hitl_event.model_dump(),
                                    trace_id, case_id, tenant_id_val,
                                )
                                event_id_counter += 1
                                yield format_sse_event("hitl", hitl_data, str(event_id_counter))
                                
                                signal = await hitl_manager.wait_for_approval_signal(
                                    session_id=session_id,
                                    timeout=settings.hitl_timeout_seconds,
                                )
                                
                                if signal is None:
                                    failed_data = _enrich_event_data({
                                        "type": "failed",
                                        "message": "사용자 응답 지연으로 작업이 취소되었습니다",
                                        "error": "HITL approval timeout",
                                        "errorType": "TimeoutError",
                                        "requestId": request_id,
                                        "sessionId": session_id,
                                        "timestamp": int(datetime.utcnow().timestamp()),
                                    }, trace_id, case_id, tenant_id_val)
                                    event_id_counter += 1
                                    yield format_sse_event("failed", failed_data, str(event_id_counter))
                                    error_data = _enrich_event_data({
                                        "type": "error",
                                        "error": f"HITL 승인 요청이 {settings.hitl_timeout_seconds}초 내에 응답되지 않아 작업이 중단되었습니다.",
                                        "errorType": "TimeoutError",
                                        "timestamp": int(datetime.utcnow().timestamp()),
                                    }, trace_id, case_id, tenant_id_val)
                                    event_id_counter += 1
                                    yield format_sse_event("error", error_data, str(event_id_counter))
                                    end_data = _enrich_event_data({
                                        "type": "end",
                                        "message": "작업이 타임아웃으로 인해 중단되었습니다",
                                        "status": "failed",
                                        "timestamp": int(datetime.utcnow().timestamp()),
                                    }, trace_id, case_id, tenant_id_val)
                                    event_id_counter += 1
                                    yield format_sse_event("end", end_data, str(event_id_counter))
                                    yield "data: [DONE]\n\n"
                                    return
                                
                                if signal.get("type") == "rejection":
                                    resume_value = {"approved": False}
                                else:
                                    resume_value = {"approved": signal.get("approved", True)}
                                logger.info(f"Finance HITL: {request_id} -> {resume_value}")
                                break
                            stream_done = False
                            break
                        elif mode == "values":
                            if "__interrupt__" not in chunk:
                                for k, v in chunk.items():
                                    if k != "__interrupt__" and isinstance(v, (dict, list)):
                                        current_state[k] = v
                        elif mode == "updates":
                            for node_name, node_data in chunk.items():
                                if isinstance(node_data, dict):
                                    current_state.update(node_data)
                                    state = current_state.copy()
                                else:
                                    if isinstance(node_data, list):
                                        current_state["messages"] = node_data
                                    else:
                                        current_state["messages"] = [node_data]
                                    state = current_state.copy()
                                await hook.on_node_start(node_name, state)
                                await hook.on_node_end(node_name, state)
                    else:
                        for node_name, node_data in graph_event.items():
                            if isinstance(node_data, dict):
                                current_state.update(node_data)
                                state = current_state.copy()
                            else:
                                if isinstance(node_data, list):
                                    current_state["messages"] = node_data
                                else:
                                    current_state["messages"] = [node_data]
                                state = current_state.copy()
                            await hook.on_node_start(node_name, state)
                            await hook.on_node_end(node_name, state)
                
                else:
                    stream_done = True
                
                while event_queue:
                    event = event_queue.pop(0)
                    event_type = event.get("type", "message")
                    enriched = _enrich_event_data(
                        event,
                        trace_id, case_id, tenant_id_val,
                    )
                    event_id_counter += 1
                    yield format_sse_event(event_type, enriched, str(event_id_counter))
                    await asyncio.sleep(STREAMING_EVENT_DELAY)
            
            end_data = _enrich_event_data({
                "type": "end",
                "message": "Finance agent finished",
                "timestamp": int(datetime.utcnow().timestamp()),
            }, trace_id, case_id, tenant_id_val)
            event_id_counter += 1
            yield format_sse_event("end", end_data, str(event_id_counter))
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Finance streaming failed: {e}", exc_info=True)
            error_data = _enrich_event_data({
                "type": "error",
                "error": str(e),
                "errorType": type(e).__name__,
                "timestamp": int(datetime.utcnow().timestamp()),
            }, trace_id, case_id, tenant_id_val)
            event_id_counter += 1
            yield format_sse_event("error", error_data, str(event_id_counter))
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/approve")
async def approve_finance_action(
    request_id: str,
    approved: bool,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    Finance HITL 액션 승인/거절
    
    기존 /agents/v2/approve 패턴과 동일.
    프론트 → Synapse 백엔드 → Redis Pub/Sub → Aura signal 처리.
    """
    return {
        "request_id": request_id,
        "approved": approved,
        "status": "processed",
        "message": "승인 신호는 Synapse 백엔드를 통해 Redis Pub/Sub으로 전달됩니다.",
    }
