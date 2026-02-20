"""
Agent Routes Module

에이전트 실행을 위한 API 엔드포인트를 제공합니다.
SSE(Server-Sent Events)를 통한 스트리밍을 지원합니다.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CurrentUser, TenantId
from core.stores.config_store import get_config_store
from core.analysis.agent_factory import invalidate_agent_list_cache
from domains.dev.agents.code_agent import get_code_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/agents", tags=["agents"])


class ChatRequest(BaseModel):
    """채팅 요청 모델"""
    message: str = Field(..., min_length=1, description="사용자 메시지")
    context: dict[str, Any] = Field(default_factory=dict, description="추가 컨텍스트")
    stream: bool = Field(default=True, description="스트리밍 여부")


class ChatResponse(BaseModel):
    """채팅 응답 모델"""
    response: str = Field(..., description="에이전트 응답")
    metadata: dict[str, Any] = Field(default_factory=dict, description="메타데이터")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: CurrentUser,
    tenant_id: TenantId,
) -> ChatResponse:
    """
    에이전트와 대화 (일반 모드)
    
    스트리밍 없이 전체 응답을 한번에 반환합니다.
    """
    try:
        agent = get_code_agent()
        
        result = await agent.run(
            user_input=request.message,
            user_id=user.user_id,
            tenant_id=tenant_id,
            context=request.context,
        )
        
        return ChatResponse(
            response=result["response"],
            metadata={
                "user_id": user.user_id,
                "tenant_id": tenant_id,
                "message_count": len(result["messages"]),
            },
        )
        
    except Exception as e:
        logger.error(f"Chat failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {str(e)}",
        )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    에이전트와 대화 (스트리밍 모드)
    
    SSE(Server-Sent Events)를 통해 실시간으로 응답을 스트리밍합니다.
    
    Example:
        ```javascript
        const response = await fetch('/agents/chat/stream', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer <token>',
                'X-Tenant-ID': 'tenant1',
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                message: 'Analyze this PR: facebook/react#123',
                stream: true,
            }),
        });
        
        const reader = response.body.getReader();
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            // 처리...
        }
        ```
    """
    async def event_generator():
        """SSE 이벤트 생성기"""
        try:
            # 시작 이벤트
            yield f"data: {json.dumps({'type': 'start', 'message': 'Agent started'})}\n\n"
            
            agent = get_code_agent()
            
            # 에이전트 스트리밍
            async for event in agent.stream(
                user_input=request.message,
                user_id=user.user_id,
                tenant_id=tenant_id,
                context=request.context,
            ):
                # 이벤트를 SSE 형식으로 변환
                event_data = _format_event(event)
                if event_data:
                    yield f"data: {json.dumps(event_data)}\n\n"
            
            # 종료 이벤트
            yield f"data: {json.dumps({'type': 'end', 'message': 'Agent finished'})}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming failed: {e}", exc_info=True)
            error_data = {
                "type": "error",
                "error": str(e),
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 버퍼링 비활성화
        },
    )


def _format_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """LangGraph 이벤트를 SSE 형식으로 변환"""
    # 이벤트 구조 파악
    if not event:
        return None
    
    # 노드별 이벤트 처리
    for node_name, node_data in event.items():
        if node_name == "agent":
            # 에이전트 응답
            messages = node_data.get("messages", [])
            if messages:
                last_message = messages[-1]
                
                # AI 메시지
                if hasattr(last_message, "content"):
                    return {
                        "type": "agent_message",
                        "content": last_message.content,
                        "node": node_name,
                    }
                
                # 도구 호출
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    return {
                        "type": "tool_calls",
                        "tools": [
                            {
                                "name": tc["name"],
                                "args": tc["args"],
                            }
                            for tc in last_message.tool_calls
                        ],
                        "node": node_name,
                    }
        
        elif node_name == "tools":
            # 도구 실행 결과
            messages = node_data.get("messages", [])
            if messages:
                return {
                    "type": "tool_result",
                    "result": [msg.content for msg in messages if hasattr(msg, "content")],
                    "node": node_name,
                }
    
    # 기타 이벤트
    return {
        "type": "raw_event",
        "data": str(event),
    }


@router.get("/tools")
async def list_tools(user: CurrentUser):
    """
    사용 가능한 도구 목록 조회
    
    에이전트가 사용할 수 있는 모든 도구를 반환합니다.
    """
    from tools.integrations.git_tool import GIT_TOOLS
    from tools.integrations.github_tool import GITHUB_TOOLS
    
    tools = []
    
    for tool in GIT_TOOLS + GITHUB_TOOLS:
        tools.append({
            "name": tool.name,
            "description": tool.description,
            "args": tool.args if hasattr(tool, "args") else {},
        })
    
    return {
        "tools": tools,
        "count": len(tools),
    }


@router.post("/{agent_id}/refresh")
async def refresh_agent_config(
    agent_id: str,
    tenant_id: int = Query(..., description="테넌트 ID"),
    store: Any = None,
) -> dict[str, Any]:
    """
    에이전트 설정 캐시 무효화 (백엔드에서 호출)
    
    백엔드에서 에이전트 설정이나 지식 바인딩이 변경되었을 때,
    Aura의 메모리 캐시를 즉시 무효화하여 다음 요청 시 최신 설정을 가져오도록 합니다.
    
    Args:
        agent_id: 에이전트 ID
        tenant_id: 테넌트 ID (쿼리 파라미터 또는 헤더에서 추출)
        store: AgentConfigStore 인스턴스 (의존성 주입)
    
    Returns:
        {"success": True, "agentId": str, "tenantId": int}
    
    멱등성: 존재하지 않는 에이전트에 대해서도 성공(200) 반환.
    """
    if store is None:
        store = get_config_store()
    
    # tenant_id가 없으면 기본값 1 사용 (시스템 에이전트 고려)
    tenant_id_val = tenant_id if tenant_id is not None else 1
    
    try:
        invalidated = store.invalidate(tenant_id_val, agent_id)
        # 에이전트 목록 캐시도 무효화 (에이전트 설정 변경 시 목록도 갱신 필요)
        invalidate_agent_list_cache(tenant_id_val)
        logger.info(
            f"[Refresh] Agent config cache invalidated: {tenant_id_val}:{agent_id} "
            f"(was_cached={invalidated})"
        )
        return {
            "success": True,
            "agentId": agent_id,
            "tenantId": tenant_id_val,
        }
    except Exception as e:
        logger.error(f"[Refresh] Failed to invalidate cache for {tenant_id_val}:{agent_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh agent config: {str(e)}",
        )


@router.get("/cache/stats")
async def get_cache_stats() -> dict[str, Any]:
    """
    에이전트 설정 캐시 상태 조회 (디버깅/모니터링용)
    
    Returns:
        캐시 통계: total_entries, valid_entries, expired_entries, ttl_seconds, entries
    """
    store = get_config_store()
    stats = store.stats()
    logger.info(f"[Cache Stats] {stats['total_entries']} entries, {stats['valid_entries']} valid, TTL={stats['ttl_seconds']}s")
    return {
        "success": True,
        "cache": stats,
    }


@router.post("/cache/clear")
async def clear_cache() -> dict[str, Any]:
    """
    전체 에이전트 설정 캐시 삭제 (긴급 상황용)
    
    주의: 이 API는 모든 에이전트의 캐시를 삭제합니다.
    다음 요청 시 모든 에이전트 설정이 Backend에서 다시 로드됩니다.
    
    Returns:
        {"success": True, "message": str}
    """
    store = get_config_store()
    store.clear()
    # 에이전트 목록 캐시도 모두 삭제
    from core.analysis.agent_factory import _agent_list_cache
    _agent_list_cache.clear()
    logger.info("[Cache Clear] All agent config and list caches cleared")
    return {
        "success": True,
        "message": "All agent config caches cleared. Next requests will fetch fresh configs from Backend.",
    }


@router.get("/health")
async def agent_health():
    """에이전트 헬스체크"""
    try:
        agent = get_code_agent()
        return {
            "status": "healthy",
            "agent_initialized": agent is not None,
            "tools_count": len(agent.tools) if agent else 0,
        }
    except Exception as e:
        logger.error(f"Agent health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }
