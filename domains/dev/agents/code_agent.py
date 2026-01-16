"""
Code Agent Module

LangGraph를 사용한 코드 분석 에이전트입니다.
Git 및 GitHub 도구를 활용하여 코드 리뷰, PR 분석 등을 수행합니다.
"""

import logging
from typing import Annotated, Any, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

from core.llm import get_llm_client
from core.llm.prompts import get_system_prompt
from tools.integrations.git_tool import GIT_TOOLS
from tools.integrations.github_tool import GITHUB_TOOLS

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """에이전트 상태"""
    messages: list[BaseMessage]
    user_id: str
    tenant_id: str | None
    context: dict[str, Any]


class CodeAgent:
    """
    코드 분석 에이전트
    
    LangGraph를 사용하여 도구를 선택하고 실행하며,
    결과를 스트리밍으로 반환합니다.
    """
    
    def __init__(self):
        """CodeAgent 초기화"""
        self.llm_client = get_llm_client()
        self.tools = GIT_TOOLS + GITHUB_TOOLS
        
        # LLM에 도구 바인딩
        self.llm_with_tools = self.llm_client.client.bind_tools(self.tools)
        
        # LangGraph 워크플로우 구성
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 워크플로우 구성"""
        workflow = StateGraph(AgentState)
        
        # 노드 추가
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("tools", ToolNode(self.tools))
        
        # 엔트리 포인트
        workflow.set_entry_point("agent")
        
        # 조건부 엣지: 에이전트 -> 도구 또는 종료
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END,
            },
        )
        
        # 도구 실행 후 다시 에이전트로
        workflow.add_edge("tools", "agent")
        
        return workflow.compile()
    
    async def _agent_node(self, state: AgentState) -> dict[str, Any]:
        """에이전트 노드: LLM 호출"""
        messages = state["messages"]
        
        # 시스템 프롬프트 추가
        system_message = HumanMessage(
            content=get_system_prompt(
                domain="dev",
                context=f"User: {state['user_id']}, Tenant: {state.get('tenant_id')}",
            )
        )
        
        # LLM 호출
        response = await self.llm_with_tools.ainvoke([system_message] + messages)
        
        return {"messages": [response]}
    
    def _should_continue(self, state: AgentState) -> str:
        """도구 호출 여부 결정"""
        last_message = state["messages"][-1]
        
        # 도구 호출이 있으면 계속
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "continue"
        
        # 없으면 종료
        return "end"
    
    async def run(
        self,
        user_input: str,
        user_id: str,
        tenant_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        에이전트 실행 (일반 모드)
        
        Args:
            user_input: 사용자 입력
            user_id: 사용자 ID
            tenant_id: 테넌트 ID
            context: 추가 컨텍스트
            
        Returns:
            실행 결과
        """
        initial_state: AgentState = {
            "messages": [HumanMessage(content=user_input)],
            "user_id": user_id,
            "tenant_id": tenant_id,
            "context": context or {},
        }
        
        result = await self.graph.ainvoke(initial_state)
        
        return {
            "response": result["messages"][-1].content,
            "messages": result["messages"],
        }
    
    async def stream(
        self,
        user_input: str,
        user_id: str,
        tenant_id: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        """
        에이전트 실행 (스트리밍 모드)
        
        Args:
            user_input: 사용자 입력
            user_id: 사용자 ID
            tenant_id: 테넌트 ID
            context: 추가 컨텍스트
            
        Yields:
            스트리밍 이벤트
        """
        initial_state: AgentState = {
            "messages": [HumanMessage(content=user_input)],
            "user_id": user_id,
            "tenant_id": tenant_id,
            "context": context or {},
        }
        
        async for event in self.graph.astream(initial_state):
            yield event


# 전역 에이전트 인스턴스
_code_agent: CodeAgent | None = None


def get_code_agent() -> CodeAgent:
    """CodeAgent 인스턴스 반환"""
    global _code_agent
    if _code_agent is None:
        _code_agent = CodeAgent()
    return _code_agent
