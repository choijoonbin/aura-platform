"""
Aura Backend Integration Routes

dwp-backend와의 연동을 위한 엔드포인트입니다.
백엔드 요구사항에 맞춘 SSE 스트리밍 및 HITL 통신을 제공합니다.
"""

import asyncio
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
    PlanStepUpdateEvent,
    TimelineStepUpdateEvent,
    ToolExecutionEvent,
    ContentEvent,
    StartEvent,
    EndEvent,
    ErrorEvent,
    FailedEvent,
)
from api.schemas.hitl_events import HITLEvent
from core.memory.hitl_manager import get_hitl_manager
from domains.dev.agents.enhanced_agent import get_enhanced_agent
from domains.dev.agents.hooks import create_sse_hook
from core.memory import get_checkpointer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura", tags=["aura-backend"])

# 스트리밍 이벤트 간 최소 지연시간 (초) - 프론트엔드 UI 안정성을 위해
STREAMING_EVENT_DELAY = 0.05  # 50ms


class BackendStreamRequest(BaseModel):
    """백엔드 스트리밍 요청 모델 (프론트엔드 API 스펙 준수)"""
    prompt: str = Field(..., min_length=1, description="사용자 프롬프트")
    context: dict[str, Any] = Field(default_factory=dict, description="컨텍스트 정보 (url, path, title, activeApp, itemId, metadata 등)")
    thread_id: str | None = Field(default=None, description="스레드 ID (선택)")


def format_sse_event(event_type: str, data: dict[str, Any], event_id: str | None = None) -> str:
    """
    SSE 이벤트 형식으로 변환 (백엔드 요구사항)
    
    백엔드 요구 형식:
        id: {event_id}  # 재연결 지원을 위한 이벤트 ID
        event: {event_type}
        data: {json_data}
    
    Args:
        event_type: 이벤트 타입 (thought, plan_step, tool_execution, hitl, content)
        data: 이벤트 데이터
        event_id: 이벤트 ID (재연결 지원용, None이면 자동 생성)
        
    Returns:
        SSE 형식 문자열
    """
    if event_id is None:
        # Unix timestamp (밀리초)를 이벤트 ID로 사용
        event_id = str(int(datetime.utcnow().timestamp() * 1000))
    
    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/test/stream")
async def backend_stream(
    request: BackendStreamRequest,
    user: CurrentUser,
    tenant_id: TenantId,
    x_dwp_source: str | None = Header(None, alias="X-DWP-Source"),
    x_dwp_caller_type: str | None = Header(None, alias="X-DWP-Caller-Type"),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
):
    """
    백엔드 연동용 SSE 스트리밍 엔드포인트 (POST)
    
    Gateway를 통한 접근: POST /api/aura/test/stream
    실제 경로: POST /aura/test/stream
    
    요청 본문:
    {
        "prompt": "사용자 질문",
        "context": {
            "url": "http://localhost:4200/mail",
            "path": "/mail",
            "title": "메일 인박스",
            "activeApp": "mail",
            "itemId": "msg-123",
            "metadata": {...}
        }
    }
    
    백엔드 요구사항:
    - SSE 이벤트 형식: `id: {event_id}\nevent: {type}\ndata: {json}` (재연결 지원)
    - 이벤트 타입: thought, plan_step, plan_step_update, timeline_step_update, tool_execution, hitl, content
    - 스트림 종료: `data: [DONE]\n\n`
    - HITL 이벤트 전송 시 실행 중지 및 Redis Pub/Sub 대기
    - Last-Event-ID 헤더 지원: 재연결 시 중단 지점부터 재개 (이벤트 ID 기반)
    """
    async def event_generator():
        """SSE 이벤트 생성기 (백엔드 요구사항 준수)"""
        # X-User-ID 헤더 검증 (백엔드 요구사항: JWT sub와 일치해야 함)
        if x_user_id and x_user_id != user.user_id:
            logger.warning(
                f"User ID mismatch: JWT sub={user.user_id}, X-User-ID header={x_user_id}"
            )
            error_data = {
                "type": "error",
                "error": "User ID mismatch",
                "errorType": "ValidationError",
                "message": f"X-User-ID header ({x_user_id}) does not match JWT sub claim ({user.user_id})",
            }
            yield format_sse_event("error", error_data, "0")
            return
        
        event_queue: list[dict[str, Any]] = []
        session_id = f"session_{user.user_id}_{int(datetime.utcnow().timestamp())}"
        
        # 이벤트 ID 카운터 (재연결 지원)
        event_id_counter = 0
        if last_event_id:
            try:
                # Last-Event-ID가 있으면 해당 지점부터 재개
                last_id = int(last_event_id)
                event_id_counter = last_id + 1
                logger.info(f"Resuming from event ID: {last_event_id}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid Last-Event-ID: {last_event_id}, starting from 0")
        
        try:
            # 시작 이벤트
            start_data = {
                "type": "start",
                "message": "Agent started",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            event_id_counter += 1
            yield format_sse_event("start", start_data, str(event_id_counter))
            
            # Checkpointer 가져오기
            checkpointer = await get_checkpointer()
            
            # Enhanced Agent 가져오기
            agent = get_enhanced_agent(checkpointer=checkpointer)
            
            # SSE Hook 생성
            hook = create_sse_hook(event_queue)
            
            # Thread ID 생성
            thread_id = request.thread_id or f"{user.user_id}_{tenant_id}_{int(datetime.utcnow().timestamp())}"
            
            # 컨텍스트 병합 (요청의 context와 헤더 정보)
            merged_context = {
                **(request.context or {}),
                "source": x_dwp_source,
                "caller_type": x_dwp_caller_type,
            }
            
            # 현재 상태 추적
            current_state: dict[str, Any] = {
                "messages": [],
                "thought_chain": [],
                "plan_steps": [],
                "execution_logs": [],
                "sources": [],
            }
            
            # 에이전트 스트리밍 실행 (prompt 사용)
            async for graph_event in agent.stream(
                user_input=request.prompt,
                user_id=user.user_id,
                tenant_id=tenant_id,
                context=merged_context,
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
                            event_id_counter += 1
                            yield format_sse_event("hitl", hitl_event.model_dump(), str(event_id_counter))
                            
                            # 승인 신호 대기 (Redis Pub/Sub)
                            logger.info(f"HITL: Waiting for approval signal (session: {session_id})")
                            signal = await hitl_manager.wait_for_approval_signal(
                                session_id=session_id,
                                timeout=300,  # 5분
                            )
                            
                            if signal is None:
                                # 타임아웃 처리: failed 이벤트 전송 및 상태 업데이트
                                logger.warning(f"HITL timeout after 300 seconds (session: {session_id}, request: {request_id})")
                                
                                # failed 이벤트 전송 (프론트엔드에 작업 취소 알림)
                                failed_data = {
                                    "type": "failed",
                                    "message": "사용자 응답 지연으로 작업이 취소되었습니다",
                                    "error": "HITL approval timeout",
                                    "errorType": "TimeoutError",
                                    "requestId": request_id,
                                    "sessionId": session_id,
                                    "timestamp": int(datetime.utcnow().timestamp()),
                                }
                                event_id_counter += 1
                                yield format_sse_event("failed", failed_data, str(event_id_counter))
                                
                                # error 이벤트도 함께 전송 (기존 호환성 유지)
                                error_data = {
                                    "type": "error",
                                    "error": "사용자 응답 지연으로 작업이 취소되었습니다",
                                    "errorType": "TimeoutError",
                                    "message": "HITL 승인 요청이 300초 내에 응답되지 않아 작업이 중단되었습니다.",
                                }
                                event_id_counter += 1
                                yield format_sse_event("error", error_data, str(event_id_counter))
                                
                                # 종료 이벤트 전송
                                end_data = {
                                    "type": "end",
                                    "message": "작업이 타임아웃으로 인해 중단되었습니다",
                                    "status": "failed",
                                    "timestamp": int(datetime.utcnow().timestamp()),
                                }
                                event_id_counter += 1
                                yield format_sse_event("end", end_data, str(event_id_counter))
                                
                                # 스트림 종료 표시
                                yield "data: [DONE]\n\n"
                                return
                            
                            if signal.get("type") == "rejection":
                                # 거절 처리
                                error_data = {
                                    "type": "error",
                                    "error": signal.get("reason", "Request rejected"),
                                    "errorType": "RejectionError",
                                }
                                event_id_counter += 1
                                yield format_sse_event("error", error_data, str(event_id_counter))
                                return
                            
                            # 승인됨 - 실행 계속
                            logger.info(f"HITL: Request approved (request: {request_id})")
                
                # 큐에 쌓인 이벤트 발행 (백엔드 요구 형식으로 변환)
                # 스트리밍 버퍼 관리: 이벤트 사이 최소 지연시간 적용
                while event_queue:
                    event = event_queue.pop(0)
                    event_type = event.get("type", "message")
                    
                    # 백엔드 요구 형식: {"type": "...", "data": {...}}
                    if "data" not in event:
                        formatted_data = {"type": event_type, "data": event}
                    else:
                        formatted_data = event
                    
                    event_id_counter += 1
                    yield format_sse_event(event_type, formatted_data, str(event_id_counter))
                    
                    # 프론트엔드 UI 안정성을 위한 최소 지연시간 적용
                    # 너무 빠른 이벤트 연속 전송 시 UI 깨짐 방지
                    await asyncio.sleep(STREAMING_EVENT_DELAY)
            
            # 종료 이벤트
            end_data = {
                "type": "end",
                "message": "Agent finished",
                "timestamp": int(datetime.utcnow().timestamp()),
            }
            event_id_counter += 1
            yield format_sse_event("end", end_data, str(event_id_counter))
            
            # 스트림 종료 표시 (프론트엔드 요구사항)
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Backend streaming failed: {e}", exc_info=True)
            error_data = {
                "type": "error",
                "error": str(e),
                "errorType": type(e).__name__,
            }
            event_id_counter += 1
            yield format_sse_event("error", error_data, str(event_id_counter))
    
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
