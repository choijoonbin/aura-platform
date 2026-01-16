"""
Aura Backend Integration Routes

dwp-backend와의 연동을 위한 엔드포인트입니다.
백엔드 요구사항에 맞춘 SSE 스트리밍 및 HITL 통신을 제공합니다.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, TenantId
from api.schemas.events import (
    ThoughtEvent,
    PlanStepEvent,
    ToolExecutionEvent,
    ContentEvent,
    StartEvent,
    EndEvent,
    ErrorEvent,
)
from api.schemas.hitl_events import HITLEvent
from core.memory.hitl_manager import get_hitl_manager
from domains.dev.agents.enhanced_agent import get_enhanced_agent
from domains.dev.agents.hooks import create_sse_hook
from core.memory import get_checkpointer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura", tags=["aura-backend"])


class BackendStreamRequest(BaseModel):
    """백엔드 스트리밍 요청 모델"""
    message: str = Field(..., min_length=1, description="사용자 메시지")
    context: dict[str, Any] = Field(default_factory=dict, description="추가 컨텍스트")
    thread_id: str | None = Field(default=None, description="스레드 ID")


def format_sse_event(event_type: str, data: dict[str, Any]) -> str:
    """
    SSE 이벤트 형식으로 변환 (백엔드 요구사항)
    
    백엔드 요구 형식:
        event: {event_type}
        data: {json_data}
    
    Args:
        event_type: 이벤트 타입 (thought, plan_step, tool_execution, hitl, content)
        data: 이벤트 데이터
        
    Returns:
        SSE 형식 문자열
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/test/stream")
async def backend_stream(
    message: str,
    user: CurrentUser,
    tenant_id: TenantId,
    x_dwp_source: str | None = Header(None, alias="X-DWP-Source"),
    x_dwp_caller_type: str | None = Header(None, alias="X-DWP-Caller-Type"),
):
    """
    백엔드 연동용 SSE 스트리밍 엔드포인트
    
    Gateway를 통한 접근: GET /api/aura/test/stream?message=...
    실제 경로: GET /aura/test/stream?message=...
    
    백엔드 요구사항:
    - SSE 이벤트 형식: `event: {type}\ndata: {json}`
    - 5가지 이벤트 타입: thought, plan_step, tool_execution, hitl, content
    - HITL 이벤트 전송 시 실행 중지 및 Redis Pub/Sub 대기
    """
    async def event_generator():
        """SSE 이벤트 생성기 (백엔드 요구사항 준수)"""
        event_queue: list[dict[str, Any]] = []
        session_id = f"session_{user.user_id}_{int(datetime.utcnow().timestamp())}"
        
        try:
            # 시작 이벤트
            start_data = {
                "type": "start",
                "message": "Agent started",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            yield format_sse_event("start", start_data)
            
            # Checkpointer 가져오기
            checkpointer = await get_checkpointer()
            
            # Enhanced Agent 가져오기
            agent = get_enhanced_agent(checkpointer=checkpointer)
            
            # SSE Hook 생성
            hook = create_sse_hook(event_queue)
            
            # Thread ID 생성
            thread_id = f"{user.user_id}_{tenant_id}_{int(datetime.utcnow().timestamp())}"
            
            # 현재 상태 추적
            current_state: dict[str, Any] = {
                "messages": [],
                "thought_chain": [],
                "plan_steps": [],
                "execution_logs": [],
                "sources": [],
            }
            
            # 에이전트 스트리밍 실행
            async for graph_event in agent.stream(
                user_input=message,
                user_id=user.user_id,
                tenant_id=tenant_id,
                context={"source": x_dwp_source, "caller_type": x_dwp_caller_type},
                thread_id=thread_id,
            ):
                # LangGraph 이벤트 처리
                for node_name, node_data in graph_event.items():
                    # 노드 데이터를 상태로 변환
                    if isinstance(node_data, dict):
                        current_state.update(node_data)
                        state = current_state.copy()
                    else:
                        if isinstance(node_data, list):
                            current_state["messages"] = node_data
                        else:
                            current_state["messages"] = [node_data]
                        state = current_state.copy()
                    
                    # 노드 시작 Hook 호출
                    await hook.on_node_start(node_name, state)
                    
                    # 노드 종료 Hook 호출
                    await hook.on_node_end(node_name, state)
                    
                    # HITL Interrupt 확인
                    if "pending_approvals" in state and state["pending_approvals"]:
                        # HITL 이벤트 발행
                        for approval in state["pending_approvals"]:
                            request_id = f"req_{uuid.uuid4().hex[:12]}"
                            
                            # HITL Manager에 승인 요청 저장
                            hitl_manager = await get_hitl_manager()
                            await hitl_manager.save_approval_request(
                                request_id=request_id,
                                session_id=session_id,
                                action_type=approval["toolName"],
                                context=approval["toolArgs"],
                                user_id=user.user_id,
                                tenant_id=tenant_id,
                            )
                            
                            # HITL 이벤트 발행 (백엔드 요구 형식)
                            hitl_event = HITLEvent.create(
                                request_id=request_id,
                                action_type=approval["toolName"],
                                message=f"{approval['toolName']} 실행을 승인하시겠습니까?",
                                context=approval["toolArgs"],
                            )
                            yield format_sse_event("hitl", hitl_event.model_dump())
                            
                            # 승인 신호 대기 (Redis Pub/Sub)
                            logger.info(f"HITL: Waiting for approval signal (session: {session_id})")
                            signal = await hitl_manager.wait_for_approval_signal(
                                session_id=session_id,
                                timeout=300,  # 5분
                            )
                            
                            if signal is None:
                                # 타임아웃
                                error_data = {
                                    "type": "error",
                                    "error": "HITL approval timeout",
                                    "errorType": "TimeoutError",
                                }
                                yield format_sse_event("error", error_data)
                                return
                            
                            if signal.get("type") == "rejection":
                                # 거절 처리
                                error_data = {
                                    "type": "error",
                                    "error": signal.get("reason", "Request rejected"),
                                    "errorType": "RejectionError",
                                }
                                yield format_sse_event("error", error_data)
                                return
                            
                            # 승인됨 - 실행 계속
                            logger.info(f"HITL: Request approved (request: {request_id})")
                
                # 큐에 쌓인 이벤트 발행 (백엔드 요구 형식으로 변환)
                while event_queue:
                    event = event_queue.pop(0)
                    event_type = event.get("type", "message")
                    
                    # 백엔드 요구 형식: {"type": "...", "data": {...}}
                    if "data" not in event:
                        formatted_data = {"type": event_type, "data": event}
                    else:
                        formatted_data = event
                    
                    yield format_sse_event(event_type, formatted_data)
            
            # 종료 이벤트
            end_data = {
                "type": "end",
                "message": "Agent finished",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            yield format_sse_event("end", end_data)
            
        except Exception as e:
            logger.error(f"Backend streaming failed: {e}", exc_info=True)
            error_data = {
                "type": "error",
                "error": str(e),
                "errorType": type(e).__name__,
            }
            yield format_sse_event("error", error_data)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/hitl/requests/{request_id}")
async def get_hitl_request(
    request_id: str,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    승인 요청 조회 (백엔드 연동)
    
    Gateway를 통한 접근: GET /api/aura/hitl/requests/{request_id}
    """
    hitl_manager = await get_hitl_manager()
    request_data = await hitl_manager.get_approval_request(request_id)
    
    if request_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval request not found",
        )
    
    # 백엔드 응답 형식 (ApiResponse)
    return {
        "status": "SUCCESS",
        "message": "Approval request retrieved",
        "data": json.dumps(request_data, ensure_ascii=False),
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/hitl/signals/{session_id}")
async def get_hitl_signal(
    session_id: str,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    승인 신호 조회 (백엔드 연동)
    
    Gateway를 통한 접근: GET /api/aura/hitl/signals/{session_id}
    """
    hitl_manager = await get_hitl_manager()
    signal_data = await hitl_manager.get_signal(session_id)
    
    if signal_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signal not found",
        )
    
    # 백엔드 응답 형식 (ApiResponse)
    return {
        "status": "SUCCESS",
        "message": "Signal retrieved",
        "data": json.dumps(signal_data, ensure_ascii=False),
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
    }
