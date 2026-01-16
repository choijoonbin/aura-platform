"""
Enhanced Code Agent Module

프론트엔드 명세 v1.0에 맞춘 고도화된 코드 분석 에이전트입니다.
- 사고 과정 추적 (thought_chain)
- 단계별 계획 수립 (plan_steps)
- 실행 로그 기록 (execution_logs)
- HITL Interrupt 지원
- Confidence Score 계산
- Source Attribution
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

from core.llm import get_llm_client
from core.llm.prompts import get_system_prompt
from tools.integrations.git_tool import GIT_TOOLS
from tools.integrations.github_tool import GITHUB_TOOLS

logger = logging.getLogger(__name__)


class ThoughtEntry(TypedDict):
    """사고 과정 항목"""
    thoughtType: str  # analysis, planning, reasoning, decision, reflection
    content: str
    timestamp: datetime
    sources: list[str]


class PlanStep(TypedDict):
    """계획 단계"""
    stepId: str
    description: str
    status: str  # pending, in_progress, completed, failed, skipped
    confidence: float  # 0.0~1.0
    timestamp: datetime
    metadata: dict[str, Any]


class ExecutionLog(TypedDict):
    """실행 로그"""
    toolName: str
    toolArgs: dict[str, Any]
    status: str  # pending, running, success, failed, cancelled
    result: Any
    error: str | None
    timestamp: datetime
    requiresApproval: bool


class EnhancedAgentState(TypedDict, total=False):
    """고도화된 에이전트 상태"""
    messages: Annotated[list[BaseMessage], "대화 메시지"]
    user_id: str
    tenant_id: str | None
    context: dict[str, Any]
    thought_chain: Annotated[list[ThoughtEntry], "사고 과정 체인"]
    plan_steps: Annotated[list[PlanStep], "계획 단계 목록"]
    execution_logs: Annotated[list[ExecutionLog], "실행 로그"]
    current_step_id: str | None
    sources: Annotated[list[str], "참고 소스 목록"]
    pending_approvals: Annotated[list[dict[str, Any]], "승인 대기 중인 도구 목록"]


class EnhancedCodeAgent:
    """
    고도화된 코드 분석 에이전트
    
    프론트엔드 명세 v1.0에 맞춰:
    - 사고 과정 추적
    - 단계별 계획 수립
    - 실행 로그 기록
    - HITL Interrupt 지원
    - Confidence Score 계산
    - Source Attribution
    """
    
    # 승인이 필요한 중요 도구 목록
    APPROVAL_REQUIRED_TOOLS = {
        "git_merge",
        "github_create_pr",
        "github_merge_pr",
        # 추가 도구는 여기에...
    }
    
    def __init__(self, checkpointer=None):
        """
        EnhancedCodeAgent 초기화
        
        Args:
            checkpointer: LangGraph Checkpointer (None이면 MemorySaver 사용)
        """
        self.llm_client = get_llm_client()
        self.tools = GIT_TOOLS + GITHUB_TOOLS
        
        # LLM에 도구 바인딩
        self.llm_with_tools = self.llm_client.client.bind_tools(self.tools)
        
        # Checkpointer 설정
        self.checkpointer = checkpointer or MemorySaver()
        
        # LangGraph 워크플로우 구성
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 워크플로우 구성"""
        workflow = StateGraph(EnhancedAgentState)
        
        # 노드 추가
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("tools", self._tools_node)
        workflow.add_node("reflect", self._reflect_node)
        
        # 엔트리 포인트
        workflow.set_entry_point("analyze")
        
        # 엣지 정의
        workflow.add_edge("analyze", "plan")
        workflow.add_edge("plan", "execute")
        workflow.add_conditional_edges(
            "execute",
            self._should_use_tools,
            {
                "use_tools": "tools",
                "reflect": "reflect",
            },
        )
        workflow.add_edge("tools", "reflect")
        workflow.add_edge("reflect", END)
        
        return workflow.compile(checkpointer=self.checkpointer)
    
    async def _analyze_node(self, state: EnhancedAgentState) -> dict[str, Any]:
        """분석 노드: 사용자 요청 분석"""
        user_input = state["messages"][-1].content if state["messages"] else ""
        
        # 사고 과정 추가
        thought: ThoughtEntry = {
            "thoughtType": "analysis",
            "content": f"사용자 요청 분석 중: {user_input[:100]}...",
            "timestamp": datetime.utcnow(),
            "sources": [],
        }
        
        # 소스 추출 (대화 히스토리 등)
        sources = self._extract_sources(state)
        thought["sources"] = sources
        
        return {
            "thought_chain": state.get("thought_chain", []) + [thought],
            "sources": state.get("sources", []) + sources,
        }
    
    async def _plan_node(self, state: EnhancedAgentState) -> dict[str, Any]:
        """계획 노드: 실행 계획 수립"""
        # LLM을 사용하여 계획 수립
        system_prompt = get_system_prompt(
            domain="dev",
            context=f"User: {state['user_id']}, Tenant: {state.get('tenant_id')}",
        )
        
        planning_prompt = f"""
        사용자 요청을 분석하여 단계별 실행 계획을 수립하세요.
        각 단계에 대해 설명과 예상 신뢰도를 제공하세요.
        
        사용자 요청: {state['messages'][-1].content if state['messages'] else ''}
        """
        
        messages = [HumanMessage(content=system_prompt + "\n\n" + planning_prompt)]
        response = await self.llm_client.client.ainvoke(messages)
        
        # 계획 단계 생성
        plan_steps = self._parse_plan_from_response(response.content)
        
        # 사고 과정 추가
        thought: ThoughtEntry = {
            "thoughtType": "planning",
            "content": f"실행 계획 수립 완료: {len(plan_steps)}개 단계",
            "timestamp": datetime.utcnow(),
            "sources": state.get("sources", []),
        }
        
        return {
            "plan_steps": plan_steps,
            "thought_chain": state.get("thought_chain", []) + [thought],
            "current_step_id": plan_steps[0]["stepId"] if plan_steps else None,
        }
    
    async def _execute_node(self, state: EnhancedAgentState) -> dict[str, Any]:
        """실행 노드: LLM 호출 및 도구 선택"""
        messages = state["messages"]
        
        # Context 기반 프롬프트 생성 (activeApp, selectedItemIds 포함)
        context = state.get("context", {})
        context_for_prompt = {
            "user_id": state.get("user_id"),
            "tenant_id": state.get("tenant_id"),
            **context,  # 프론트엔드에서 전달된 context 정보 포함
        }
        
        system_message = HumanMessage(
            content=get_system_prompt(
                domain="dev",
                context=context_for_prompt,  # dict 형태로 전달하여 activeApp, selectedItemIds 자동 추출
            )
        )
        
        # LLM 호출
        response = await self.llm_with_tools.ainvoke([system_message] + messages)
        
        # Confidence Score 계산
        confidence = self._calculate_confidence(response)
        
        # 현재 단계 업데이트
        current_step_id = state.get("current_step_id")
        if current_step_id:
            plan_steps = state.get("plan_steps", [])
            for step in plan_steps:
                if step["stepId"] == current_step_id:
                    step["status"] = "in_progress"
                    step["confidence"] = confidence
                    break
        
        return {"messages": [response]}
    
    async def _tools_node(self, state: EnhancedAgentState) -> dict[str, Any]:
        """도구 실행 노드"""
        last_message = state["messages"][-1]
        
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {}
        
        execution_logs = state.get("execution_logs", [])
        pending_approvals = []
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            
            # 승인 필요 여부 확인
            requires_approval = tool_name in self.APPROVAL_REQUIRED_TOOLS
            
            # 실행 로그 추가
            log: ExecutionLog = {
                "toolName": tool_name,
                "toolArgs": tool_args,
                "status": "pending",
                "result": None,
                "error": None,
                "timestamp": datetime.utcnow(),
                "requiresApproval": requires_approval,
            }
            execution_logs.append(log)
            
            # HITL Interrupt: 승인이 필요한 경우
            if requires_approval:
                logger.info(f"HITL Interrupt: {tool_name} 실행 승인 대기")
                # 승인 대기 목록에 추가
                pending_approvals.append({
                    "toolName": tool_name,
                    "toolArgs": tool_args,
                    "log": log,
                })
                # 상태 업데이트: 승인 대기 플래그
                # 실제 실행은 승인 후 진행
                log["status"] = "pending"
        
        # 승인 대기 중인 도구가 있으면 상태 저장 후 대기
        if pending_approvals:
            # 상태에 승인 대기 정보 저장
            state["pending_approvals"] = pending_approvals
            # Checkpoint에 저장 (실제로는 LangGraph가 자동으로 처리)
            # 여기서는 상태만 업데이트하고, 실제 interrupt는 그래프 레벨에서 처리
            return {
                "execution_logs": execution_logs,
                "pending_approvals": pending_approvals,
            }
        
        # ToolNode 실행
        tool_node = ToolNode(self.tools)
        result = await tool_node.ainvoke({"messages": [last_message]})
        
        # 실행 로그 업데이트
        for log in execution_logs:
            if log["status"] == "pending":
                log["status"] = "success"
                # 결과는 ToolMessage에서 추출
        
        return {
            "messages": result["messages"],
            "execution_logs": execution_logs,
        }
    
    async def _reflect_node(self, state: EnhancedAgentState) -> dict[str, Any]:
        """반성 노드: 결과 검토 및 최종 응답 생성"""
        # 사고 과정 추가
        thought: ThoughtEntry = {
            "thoughtType": "reflection",
            "content": "작업 완료 및 결과 검토 중...",
            "timestamp": datetime.utcnow(),
            "sources": state.get("sources", []),
        }
        
        # 최종 응답 생성
        final_response = AIMessage(
            content="작업이 완료되었습니다. 결과를 확인해주세요."
        )
        
        return {
            "messages": state["messages"] + [final_response],
            "thought_chain": state.get("thought_chain", []) + [thought],
        }
    
    def _should_use_tools(self, state: EnhancedAgentState) -> str:
        """도구 사용 여부 결정"""
        last_message = state["messages"][-1]
        
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "use_tools"
        
        return "reflect"
    
    def _parse_plan_from_response(self, response_content: str) -> list[PlanStep]:
        """LLM 응답에서 계획 단계 파싱"""
        # 간단한 파싱 로직 (실제로는 더 정교하게 구현)
        steps = []
        lines = response_content.split("\n")
        
        for i, line in enumerate(lines):
            if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                step: PlanStep = {
                    "stepId": str(uuid.uuid4()),
                    "description": line.strip(),
                    "status": "pending",
                    "confidence": 0.8,  # 기본값 (실제로는 LLM에서 추출)
                    "timestamp": datetime.utcnow(),
                    "metadata": {},
                }
                steps.append(step)
        
        # 파싱 실패 시 기본 단계 생성
        if not steps:
            steps.append({
                "stepId": str(uuid.uuid4()),
                "description": "요청 처리",
                "status": "pending",
                "confidence": 0.7,
                "timestamp": datetime.utcnow(),
                "metadata": {},
            })
        
        return steps
    
    def _calculate_confidence(self, response: AIMessage) -> float:
        """
        Confidence Score 계산
        
        LLM의 로그 확률이나 자체 평가를 통해 0.0~1.0 사이의 값을 계산합니다.
        """
        # 방법 1: LLM의 logprobs 사용 (가능한 경우)
        if hasattr(response, "response_metadata"):
            metadata = response.response_metadata
            if "logprobs" in metadata:
                # logprobs에서 평균 확률 계산
                logprobs = metadata["logprobs"]
                # 실제 구현은 logprobs 구조에 따라 다름
                return 0.85  # 임시값
        
        # 방법 2: 응답 길이와 구조 기반 추정
        content = response.content if hasattr(response, "content") else ""
        if len(content) > 100:
            return 0.8
        elif len(content) > 50:
            return 0.7
        else:
            return 0.6
    
    def _extract_sources(self, state: EnhancedAgentState) -> list[str]:
        """참고 소스 추출"""
        sources = []
        
        # 대화 히스토리에서 파일 경로 추출
        for msg in state.get("messages", []):
            content = msg.content if hasattr(msg, "content") else str(msg)
            # 파일 경로 패턴 찾기 (간단한 예시)
            if "/" in content and ("." in content.split("/")[-1]):
                sources.append(content)
        
        # 컨텍스트에서 소스 추출
        context = state.get("context", {})
        if "file_paths" in context:
            sources.extend(context["file_paths"])
        
        return list(set(sources))  # 중복 제거
    
    async def stream(
        self,
        user_input: str,
        user_id: str,
        tenant_id: str | None = None,
        context: dict[str, Any] | None = None,
        thread_id: str | None = None,
    ):
        """
        에이전트 실행 (스트리밍 모드)
        
        Args:
            user_input: 사용자 입력
            user_id: 사용자 ID
            tenant_id: 테넌트 ID
            context: 추가 컨텍스트
            thread_id: 스레드 ID (checkpoint 복원용)
            
        Yields:
            스트리밍 이벤트 (LangGraph 이벤트)
        """
        initial_state: EnhancedAgentState = {
            "messages": [HumanMessage(content=user_input)],
            "user_id": user_id,
            "tenant_id": tenant_id,
            "context": context or {},
            "thought_chain": [],
            "plan_steps": [],
            "execution_logs": [],
            "current_step_id": None,
            "sources": [],
        }
        
        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        
        async for event in self.graph.astream(initial_state, config=config):
            yield event


# 전역 에이전트 인스턴스
_enhanced_agent: EnhancedCodeAgent | None = None


def get_enhanced_agent(checkpointer=None) -> EnhancedCodeAgent:
    """EnhancedCodeAgent 인스턴스 반환"""
    global _enhanced_agent
    if _enhanced_agent is None:
        _enhanced_agent = EnhancedCodeAgent(checkpointer=checkpointer)
    return _enhanced_agent
