"""
LangGraph Hooks

노드 실행 시 SSE 이벤트를 발행하는 Hook을 구현합니다.
"""

import logging
from typing import Any

from langgraph.graph import StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

from api.schemas.events import (
    ThoughtEvent,
    PlanStepEvent,
    ToolExecutionEvent,
    ContentEvent,
    ThoughtType,
    PlanStepStatus,
    ToolExecutionStatus,
)

logger = logging.getLogger(__name__)


class SSEEventHook:
    """
    SSE 이벤트 발행 Hook
    
    LangGraph 노드 실행 시 프론트엔드 명세 v1.0에 맞는 이벤트를 발행합니다.
    """
    
    def __init__(self, event_queue: list[dict[str, Any]]):
        """
        SSEEventHook 초기화
        
        Args:
            event_queue: 이벤트를 저장할 큐 (리스트)
        """
        self.event_queue = event_queue
    
    async def on_node_start(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 시작 시 호출"""
        logger.debug(f"Node started: {node_name}")
        
        # 노드별 이벤트 생성
        if node_name == "analyze":
            event = ThoughtEvent(
                thoughtType=ThoughtType.ANALYSIS,
                content="사용자 요청 분석을 시작합니다.",
                sources=state.get("sources", []),
            )
            self.event_queue.append(event.model_dump())
        
        elif node_name == "plan":
            event = ThoughtEvent(
                thoughtType=ThoughtType.PLANNING,
                content="실행 계획을 수립합니다.",
                sources=state.get("sources", []),
            )
            self.event_queue.append(event.model_dump())
        
        elif node_name == "execute":
            event = ThoughtEvent(
                thoughtType=ThoughtType.REASONING,
                content="도구 선택 및 실행을 준비합니다.",
                sources=state.get("sources", []),
            )
            self.event_queue.append(event.model_dump())
        
        elif node_name == "tools":
            # 도구 실행 시작
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                event = ToolExecutionEvent(
                    toolName=last_log.get("toolName", ""),
                    toolArgs=last_log.get("toolArgs", {}),
                    status=ToolExecutionStatus.RUNNING,
                    requiresApproval=last_log.get("requiresApproval", False),
                )
                self.event_queue.append(event.model_dump())
        
        elif node_name == "reflect":
            event = ThoughtEvent(
                thoughtType=ThoughtType.REFLECTION,
                content="작업 결과를 검토합니다.",
                sources=state.get("sources", []),
            )
            self.event_queue.append(event.model_dump())
    
    async def on_node_end(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 종료 시 호출"""
        logger.debug(f"Node ended: {node_name}")
        
        if node_name == "plan":
            # 계획 단계 이벤트 발행
            plan_steps = state.get("plan_steps", [])
            for step in plan_steps:
                event = PlanStepEvent(
                    stepId=step.get("stepId", ""),
                    description=step.get("description", ""),
                    status=PlanStepStatus(step.get("status", "pending")),
                    confidence=step.get("confidence", 0.7),
                )
                self.event_queue.append(event.model_dump())
        
        elif node_name == "tools":
            # 도구 실행 완료
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                event = ToolExecutionEvent(
                    toolName=last_log.get("toolName", ""),
                    toolArgs=last_log.get("toolArgs", {}),
                    status=ToolExecutionStatus.SUCCESS,
                    result=last_log.get("result"),
                    requiresApproval=last_log.get("requiresApproval", False),
                )
                self.event_queue.append(event.model_dump())
        
        elif node_name == "reflect":
            # 최종 콘텐츠 이벤트
            messages = state.get("messages", [])
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    event = ContentEvent(
                        content=last_message.content,
                        chunk=False,
                    )
                    self.event_queue.append(event.model_dump())


def create_sse_hook(event_queue: list[dict[str, Any]]) -> SSEEventHook:
    """SSE 이벤트 Hook 생성"""
    return SSEEventHook(event_queue)
