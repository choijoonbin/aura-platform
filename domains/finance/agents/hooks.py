"""
Finance Agent SSE Hooks

Finance 에이전트 노드 실행 시 SSE 이벤트를 발행하는 Hook입니다.
"""

import logging
from typing import Any

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


class FinanceSSEHook:
    """Finance 에이전트용 SSE 이벤트 Hook"""
    
    def __init__(self, event_queue: list[dict[str, Any]]):
        self.event_queue = event_queue
    
    async def on_node_start(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 시작 시 호출"""
        logger.debug(f"Finance node started: {node_name}")
        
        if node_name == "analyze":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.ANALYSIS,
                    content="케이스 목표 및 컨텍스트 분석을 시작합니다.",
                    sources=state.get("evidence", []),
                ).model_dump()
            )
        elif node_name == "plan":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.PLANNING,
                    content="조사 및 조치 계획을 수립합니다.",
                    sources=[],
                ).model_dump()
            )
        elif node_name == "execute":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REASONING,
                    content="Synapse 도구 선택 및 실행을 준비합니다.",
                    sources=[],
                ).model_dump()
            )
        elif node_name == "tools":
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                self.event_queue.append(
                    ToolExecutionEvent(
                        toolName=last_log.get("toolName", ""),
                        toolArgs=last_log.get("toolArgs", {}),
                        status=ToolExecutionStatus.RUNNING,
                        requiresApproval=last_log.get("requiresApproval", False),
                    ).model_dump()
                )
        elif node_name == "reflect":
            self.event_queue.append(
                ThoughtEvent(
                    thoughtType=ThoughtType.REFLECTION,
                    content="조사 결과를 검토합니다.",
                    sources=state.get("evidence", []),
                ).model_dump()
            )
    
    async def on_node_end(self, node_name: str, state: dict[str, Any]) -> None:
        """노드 종료 시 호출"""
        logger.debug(f"Finance node ended: {node_name}")
        
        if node_name == "plan":
            for step in state.get("plan_steps", []):
                self.event_queue.append(
                    PlanStepEvent(
                        stepId=step.get("stepId", ""),
                        description=step.get("description", ""),
                        status=PlanStepStatus(step.get("status", "pending")),
                        confidence=step.get("confidence", 0.7),
                    ).model_dump()
                )
        elif node_name == "tools":
            execution_logs = state.get("execution_logs", [])
            if execution_logs:
                last_log = execution_logs[-1]
                self.event_queue.append(
                    ToolExecutionEvent(
                        toolName=last_log.get("toolName", ""),
                        toolArgs=last_log.get("toolArgs", {}),
                        status=ToolExecutionStatus.SUCCESS,
                        result=last_log.get("result"),
                        requiresApproval=last_log.get("requiresApproval", False),
                    ).model_dump()
                )
        elif node_name == "reflect":
            messages = state.get("messages", [])
            if messages:
                last_message = messages[-1]
                if hasattr(last_message, "content"):
                    self.event_queue.append(
                        ContentEvent(content=last_message.content, chunk=False).model_dump()
                    )


def create_finance_sse_hook(event_queue: list[dict[str, Any]]) -> FinanceSSEHook:
    """Finance SSE Hook 생성"""
    return FinanceSSEHook(event_queue)
