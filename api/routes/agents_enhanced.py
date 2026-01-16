"""
Enhanced Agent Routes Module

프론트엔드 명세 v1.0에 맞춘 고도화된 에이전트 API 엔드포인트입니다.
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
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
from domains.dev.agents.enhanced_agent import get_enhanced_agent
from domains.dev.agents.hooks import create_sse_hook
from core.memory import get_checkpointer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/v2", tags=["agents-v2"])


class EnhancedChatRequest(BaseModel):
    """고도화된 채팅 요청 모델"""
    message: str = Field(..., min_length=1, description="사용자 메시지")
    context: dict[str, Any] = Field(default_factory=dict, description="추가 컨텍스트")
    thread_id: str | None = Field(default=None, description="스레드 ID (이전 대화 이어가기)")


@router.post("/chat/stream")
async def enhanced_chat_stream(
    request: EnhancedChatRequest,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    고도화된 에이전트 스트리밍 (프론트엔드 명세 v1.0)
    
    SSE를 통해 다음 이벤트 타입을 발행합니다:
    - thought: 사고 과정 (analysis, planning, reasoning, decision, reflection)
    - plan_step: 계획 단계 (confidence 포함)
    - tool_execution: 도구 실행 (승인 필요 여부 포함)
    - content: 최종 응답 콘텐츠
    """
    async def event_generator():
        """SSE 이벤트 생성기 (프론트엔드 명세 v1.0)"""
        event_queue: list[dict[str, Any]] = []
        
        try:
            # 시작 이벤트
            start_event = StartEvent(message="Enhanced agent started")
            yield f"data: {json.dumps(start_event.model_dump())}\n\n"
            
            # Checkpointer 가져오기
            checkpointer = await get_checkpointer()
            
            # Enhanced Agent 가져오기
            agent = get_enhanced_agent(checkpointer=checkpointer)
            
            # SSE Hook 생성
            hook = create_sse_hook(event_queue)
            
            # Thread ID 생성 (없는 경우)
            thread_id = request.thread_id or f"{user.user_id}_{tenant_id}_{int(datetime.utcnow().timestamp())}"
            
            # 현재 상태 추적 (Hook에서 사용)
            current_state: dict[str, Any] = {
                "messages": [],
                "thought_chain": [],
                "plan_steps": [],
                "execution_logs": [],
                "sources": [],
            }
            
            # 에이전트 스트리밍 실행
            async for graph_event in agent.stream(
                user_input=request.message,
                user_id=user.user_id,
                tenant_id=tenant_id,
                context=request.context,
                thread_id=thread_id,
            ):
                # LangGraph 이벤트 처리
                for node_name, node_data in graph_event.items():
                    # 노드 데이터를 상태로 변환
                    if isinstance(node_data, dict):
                        # 상태 업데이트
                        current_state.update(node_data)
                        state = current_state.copy()
                    else:
                        # 메시지 리스트인 경우
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
                        # 승인 대기 이벤트 발행
                        for approval in state["pending_approvals"]:
                            tool_event = ToolExecutionEvent(
                                toolName=approval["toolName"],
                                toolArgs=approval["toolArgs"],
                                status="pending",
                                requiresApproval=True,
                            )
                            yield f"data: {json.dumps(tool_event.model_dump())}\n\n"
                        
                        # Interrupt 발생 (실제로는 checkpoint에 저장되고 대기)
                        logger.info(f"HITL Interrupt: Waiting for approval on thread {thread_id}")
                        # TODO: 실제로는 checkpoint를 확인하고 승인 신호를 기다리는 로직 필요
                        # 현재는 이벤트만 발행하고 계속 진행
                
                # 큐에 쌓인 이벤트 발행
                while event_queue:
                    event = event_queue.pop(0)
                    yield f"data: {json.dumps(event)}\n\n"
            
            # 종료 이벤트
            end_event = EndEvent(message="Enhanced agent finished")
            yield f"data: {json.dumps(end_event.model_dump())}\n\n"
            
        except Exception as e:
            logger.error(f"Enhanced streaming failed: {e}", exc_info=True)
            error_event = ErrorEvent(
                error=str(e),
                errorType=type(e).__name__,
            )
            yield f"data: {json.dumps(error_event.model_dump())}\n\n"
    
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
async def approve_tool_execution(
    execution_id: str,
    approved: bool,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    도구 실행 승인
    
    HITL Interrupt로 대기 중인 도구 실행을 승인/거부합니다.
    """
    # TODO: Checkpoint에서 대기 중인 실행을 찾아 승인/거부 처리
    # 실제 구현은 checkpoint와 interrupt 메커니즘을 사용
    
    return {
        "execution_id": execution_id,
        "approved": approved,
        "status": "processed",
    }
