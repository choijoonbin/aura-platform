"""
Finance Agent Module

LangGraph 기반 재무/회계 케이스 조사 에이전트입니다.
- Synapse 백엔드 Tool API를 통한 데이터 조회
- evidence 수집 (규정 인용, 통계, 원천 링크)
- HITL: LangGraph interrupt()를 통한 위험 액션 승인 (checkpoint 저장 후 resume)
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

from core.llm import get_llm_client
from core.llm.prompts import get_system_prompt
from tools.synapse_finance_tool import (
    FINANCE_TOOLS,
    FINANCE_HITL_TOOLS,
    get_case,
    search_documents,
    get_open_items,
    get_lineage,
)

logger = logging.getLogger(__name__)

# 동적 팩토리: agent_tool_mapping 바인딩 시 레지스트리 사용
try:
    from core.analysis.agent_factory import register_tools
    register_tools(FINANCE_TOOLS)
except Exception:
    pass


class EvidenceItem(TypedDict):
    """증거 항목 (규정 인용/RAG, 통계근거, 원천데이터 링크)"""
    type: str  # case, documents, open_items, regulation, stats, source_link
    source: str
    content: str
    ref: str | None  # 원천 참조 (docId, entityId 등)
    timestamp: datetime


class HitlRequest(TypedDict):
    """HITL 승인 요청"""
    requestId: str
    toolName: str
    toolArgs: dict[str, Any]
    actionType: str
    context: dict[str, Any]


class FinanceAgentState(TypedDict, total=False):
    """Finance 에이전트 상태"""
    messages: Annotated[list[BaseMessage], "대화 메시지"]
    tenant_id: str
    user_id: str
    goal: str
    context: dict[str, Any]  # caseId, documentIds, entityIds, openItemIds
    evidence: Annotated[list[EvidenceItem], "규정/RAG/통계/원천 링크"]
    thought_chain: list[dict[str, Any]]
    plan_steps: list[dict[str, Any]]
    execution_logs: list[dict[str, Any]]
    pending_approvals: Annotated[list[HitlRequest], "승인 대기 중인 액션"]
    approval_results: Annotated[dict[str, bool], "HITL 승인/거절 결과 (requestId -> approved)"]
    current_step_id: str | None


class FinanceAgent:
    """
    Finance 도메인 에이전트
    
    - 중복송장 의심 케이스 조사 및 조치 제안
    - Synapse Tool API를 통한 데이터 조회
    - propose_action 등 위험 액션은 HITL 승인 필수
    """
    
    APPROVAL_REQUIRED_TOOLS = FINANCE_HITL_TOOLS
    
    def __init__(self, checkpointer=None, agent_config=None):
        model_name = getattr(agent_config, "model_name", None) if agent_config else None
        self.llm_client = get_llm_client(model_name)
        from core.analysis.agent_factory import get_tools_by_names
        if agent_config and getattr(agent_config, "agent_tool_mapping", None):
            self.tools, self._skipped_tool_names = get_tools_by_names(agent_config.agent_tool_mapping)
            if not self.tools:
                self.tools = FINANCE_TOOLS
                self._skipped_tool_names = []
        else:
            self.tools = FINANCE_TOOLS
            self._skipped_tool_names = []
        self.llm_with_tools = self.llm_client.client.bind_tools(self.tools)
        self.checkpointer = checkpointer or MemorySaver()
        self.agent_config = agent_config
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """LangGraph 워크플로우 구성"""
        workflow = StateGraph(FinanceAgentState)
        
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("evidence_gather", self._evidence_gather_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("tools", self._tools_node)
        workflow.add_node("reflect", self._reflect_node)
        
        workflow.set_entry_point("analyze")
        workflow.add_conditional_edges(
            "analyze",
            self._should_gather_evidence,
            {"gather": "evidence_gather", "plan": "plan"},
        )
        workflow.add_edge("evidence_gather", "plan")
        workflow.add_edge("plan", "execute")
        workflow.add_conditional_edges(
            "execute",
            self._should_use_tools,
            {"use_tools": "tools", "reflect": "reflect"},
        )
        workflow.add_edge("tools", "reflect")
        workflow.add_edge("reflect", END)
        
        return workflow.compile(checkpointer=self.checkpointer)
    
    def _should_gather_evidence(self, state: FinanceAgentState) -> str:
        """caseId가 있으면 evidence 수집, 없으면 plan으로"""
        ctx = state.get("context") or {}
        case_id = ctx.get("caseId") or ctx.get("case_id")
        return "gather" if case_id else "plan"

    async def _evidence_gather_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """증거 수집 노드: caseId로 get_case, search_documents, get_open_items 호출 (Phase A)"""
        import json as _json

        ctx = state.get("context") or {}
        case_id = ctx.get("caseId") or ctx.get("case_id") or ""
        if not case_id:
            return {"evidence": state.get("evidence", [])}

        evidence: list[EvidenceItem] = list(state.get("evidence", []))

        # 1. get_case
        try:
            result = await get_case.ainvoke({"caseId": case_id})
            parsed = _json.loads(result) if isinstance(result, str) else result
            if "error" not in parsed:
                evidence.append(EvidenceItem(
                    type="case",
                    source="get_case",
                    content=_json.dumps(parsed, ensure_ascii=False)[:500],
                    ref=case_id,
                    timestamp=datetime.utcnow(),
                ))
        except Exception as e:
            logger.debug(f"evidence_gather get_case: {e}")

        # 2. search_documents
        try:
            result = await search_documents.ainvoke({"filters": {"caseId": case_id}})
            parsed = _json.loads(result) if isinstance(result, str) else result
            if not (isinstance(parsed, dict) and "error" in parsed):
                doc_list = parsed if isinstance(parsed, list) else parsed.get("documents", parsed.get("items", []))
                evidence.append(EvidenceItem(
                    type="documents",
                    source="search_documents",
                    content=_json.dumps(doc_list[:5], ensure_ascii=False)[:500] if isinstance(doc_list, list) else str(parsed)[:500],
                    ref=case_id,
                    timestamp=datetime.utcnow(),
                ))
        except Exception as e:
            logger.debug(f"evidence_gather search_documents: {e}")

        # 3. get_open_items
        try:
            result = await get_open_items.ainvoke({"filters": {"caseId": case_id}})
            parsed = _json.loads(result) if isinstance(result, str) else result
            if not (isinstance(parsed, dict) and "error" in parsed):
                items = parsed if isinstance(parsed, list) else parsed.get("items", parsed.get("openItems", []))
                evidence.append(EvidenceItem(
                    type="open_items",
                    source="get_open_items",
                    content=_json.dumps(items[:5], ensure_ascii=False)[:500] if isinstance(items, list) else str(parsed)[:500],
                    ref=case_id,
                    timestamp=datetime.utcnow(),
                ))
        except Exception as e:
            logger.debug(f"evidence_gather get_open_items: {e}")

        # 4. get_lineage (P1: lineageRef)
        try:
            result = await get_lineage.ainvoke({"caseId": case_id})
            parsed = _json.loads(result) if isinstance(result, str) else result
            if not (isinstance(parsed, dict) and "error" in parsed):
                lineage = parsed.get("lineage", parsed) if isinstance(parsed, dict) else parsed
                evidence.append(EvidenceItem(
                    type="lineage",
                    source="get_lineage",
                    content=_json.dumps(lineage[:5], ensure_ascii=False)[:500] if isinstance(lineage, list) else str(parsed)[:500],
                    ref=case_id,
                    timestamp=datetime.utcnow(),
                ))
        except Exception as e:
            logger.debug(f"evidence_gather get_lineage: {e}")

        thought = {
            "thoughtType": "analysis",
            "content": f"evidence_refs {len(evidence)}종 수집 완료 (case, documents, open_items, lineage)",
            "timestamp": datetime.utcnow(),
            "sources": [e.get("source", "") for e in evidence],
        }
        return {
            "evidence": evidence,
            "thought_chain": state.get("thought_chain", []) + [thought],
        }

    async def _analyze_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """분석 노드: 목표 및 컨텍스트 분석. 스킵된 도구가 있으면 ThoughtStream에 알림 추가."""
        chain = list(state.get("thought_chain", []))
        if getattr(self, "_skipped_tool_names", None):
            chain.append({
                "thoughtType": "system",
                "content": f"다음 도구는 스튜디오 설정에 있으나 엔진에 등록되지 않아 이번 실행에서 제외되었습니다: {', '.join(self._skipped_tool_names)}.",
                "timestamp": datetime.utcnow(),
                "sources": [],
            })
        user_input = state["messages"][-1].content if state["messages"] else ""
        goal = state.get("goal") or user_input
        thought = {
            "thoughtType": "analysis",
            "content": f"목표 분석: {goal[:150]}...",
            "timestamp": datetime.utcnow(),
            "sources": [],
        }
        return {
            "thought_chain": chain + [thought],
            "goal": goal,
        }
    
    def _get_effective_system_prompt(self, context: dict[str, Any]) -> str:
        """API system_instruction 우선, 없으면 get_system_prompt(domain=system_prompt_key) Fallback."""
        if self.agent_config:
            raw = (self.agent_config.system_instruction or "").strip()
            if raw:
                return raw
            domain = self.agent_config.system_prompt_key or "finance"
            return get_system_prompt(domain=domain, context=context)
        return get_system_prompt(domain="finance", context=context)

    async def _plan_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """계획 노드: 조사 및 조치 계획 수립"""
        context = state.get("context", {})
        context["user_id"] = state.get("user_id")
        context["tenant_id"] = state.get("tenant_id")
        context["goal"] = state.get("goal", "")
        
        system_prompt = self._get_effective_system_prompt(context)
        planning_prompt = f"""
        목표: {state.get('goal', '')}
        컨텍스트: caseId={context.get('caseId')}, documentIds={context.get('documentIds')}
        
        단계별 조사 및 조치 계획을 수립하세요. 각 단계에 설명과 신뢰도를 제공하세요.
        """
        
        messages = [HumanMessage(content=system_prompt + "\n\n" + planning_prompt)]
        response = await self.llm_client.client.ainvoke(messages)
        
        plan_steps = self._parse_plan(response.content)
        evidence_refs = [
            {"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")}
            for e in state.get("evidence", [])
        ]
        for step in plan_steps:
            step["evidence_refs"] = evidence_refs
        thought = {
            "thoughtType": "planning",
            "content": f"계획 수립 완료: {len(plan_steps)}개 단계 (evidence_refs {len(evidence_refs)}종)",
            "timestamp": datetime.utcnow(),
            "sources": [e.get("source", "") for e in state.get("evidence", [])],
            "evidence_refs": evidence_refs,
        }

        return {
            "plan_steps": plan_steps,
            "thought_chain": state.get("thought_chain", []) + [thought],
            "current_step_id": plan_steps[0]["stepId"] if plan_steps else None,
        }
    
    async def _execute_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """실행 노드: LLM 호출 및 도구 선택"""
        context = {
            "user_id": state.get("user_id"),
            "tenant_id": state.get("tenant_id"),
            "goal": state.get("goal", ""),
            **(state.get("context") or {}),
        }
        
        system_message = HumanMessage(
            content=self._get_effective_system_prompt(context)
        )
        messages = [system_message] + state["messages"]
        
        response = await self.llm_with_tools.ainvoke(messages)
        
        current_step_id = state.get("current_step_id")
        if current_step_id:
            for step in state.get("plan_steps", []):
                if step.get("stepId") == current_step_id:
                    step["status"] = "in_progress"
                    break
        
        return {"messages": [response]}
    
    async def _tools_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """도구 실행 노드 (HITL: interrupt()로 승인 대기 후 resume)"""
        last_message = state["messages"][-1]
        
        if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
            return {}
        
        execution_logs = list(state.get("execution_logs", []))
        pending_approvals: list[tuple[int, HitlRequest]] = []
        approval_results: dict[str, bool] = dict(state.get("approval_results", {}))
        
        for idx, tool_call in enumerate(last_message.tool_calls):
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            requires_approval = tool_name in self.APPROVAL_REQUIRED_TOOLS
            
            log = {
                "toolName": tool_name,
                "toolArgs": tool_args,
                "status": "pending",
                "result": None,
                "error": None,
                "timestamp": datetime.utcnow(),
                "requiresApproval": requires_approval,
            }
            execution_logs.append(log)
            
            if requires_approval:
                request_id = f"req_{uuid.uuid4().hex[:12]}"
                approval_req: HitlRequest = {
                    "requestId": request_id,
                    "toolName": tool_name,
                    "toolArgs": tool_args,
                    "actionType": tool_args.get("actionType", tool_name),
                    "context": tool_args,
                }
                pending_approvals.append((idx, approval_req))
                log["status"] = "pending"
        
        # HITL: 각 승인 요청마다 interrupt() 호출 (첫 실행 시 pause, resume 시 decision 반환)
        evidence_refs = [
            {"type": e.get("type"), "source": e.get("source"), "ref": e.get("ref")}
            for e in state.get("evidence", [])
        ]
        for _idx, approval_req in pending_approvals:
            request_id = approval_req["requestId"]
            payload = {
                "requestId": request_id,
                "toolName": approval_req["toolName"],
                "actionType": approval_req["actionType"],
                "context": approval_req["toolArgs"],
                "message": f"{approval_req['toolName']} 실행을 승인하시겠습니까?",
                "evidence_refs": evidence_refs,
            }
            logger.info(f"Finance HITL interrupt: {request_id} ({approval_req['toolName']})")
            decision = interrupt(payload)
            approved = bool(decision) if not isinstance(decision, dict) else decision.get("approved", False)
            approval_results[request_id] = approved
            if not approved:
                for log in execution_logs:
                    if log.get("toolName") == approval_req["toolName"] and log.get("status") == "pending":
                        log["status"] = "rejected"
                        log["error"] = "사용자가 거절했습니다."
                        break
        
        # 승인된 도구만 실행 (원본 tool_calls 순서 유지)
        approved_by_idx = {
            idx: approval_results.get(approval_req["requestId"], False)
            for idx, approval_req in pending_approvals
        }
        tool_node = ToolNode(self.tools)
        tool_calls_to_run = [
            tc for i, tc in enumerate(last_message.tool_calls)
            if tc.get("name") not in self.APPROVAL_REQUIRED_TOOLS
            or approved_by_idx.get(i, False)
        ]
        
        if tool_calls_to_run:
            from langchain_core.messages import AIMessageChunk
            msg_to_run = AIMessageChunk(
                content="",
                tool_calls=tool_calls_to_run,
            ) if hasattr(AIMessageChunk, "tool_calls") else last_message
            result = await tool_node.ainvoke({"messages": [msg_to_run]})
            executed_messages = result["messages"]
        else:
            executed_messages = []
        
        # tool_calls 순서대로 ToolMessage 구성 (실행 결과 또는 거절 메시지)
        exec_idx = 0
        new_messages: list[BaseMessage] = []
        for i, tool_call in enumerate(last_message.tool_calls):
            tool_name = tool_call.get("name", "")
            tool_call_id = tool_call.get("id", "unknown")
            if tool_name not in self.APPROVAL_REQUIRED_TOOLS:
                if exec_idx < len(executed_messages):
                    new_messages.append(executed_messages[exec_idx])
                    exec_idx += 1
            else:
                req = next((a for idx, a in pending_approvals if idx == i), None)
                if req and approval_results.get(req["requestId"], False):
                    if exec_idx < len(executed_messages):
                        new_messages.append(executed_messages[exec_idx])
                        exec_idx += 1
                else:
                    new_messages.append(
                        ToolMessage(
                            content="사용자가 액션 실행을 거절했습니다.",
                            tool_call_id=tool_call_id,
                        )
                    )
        
        for log in execution_logs:
            if log.get("status") == "pending":
                tool_name = log.get("toolName", "")
                if tool_name in self.APPROVAL_REQUIRED_TOOLS:
                    req = next((a for _, a in pending_approvals if a["toolName"] == tool_name), None)
                    if req and approval_results.get(req["requestId"], False):
                        log["status"] = "success"
                else:
                    log["status"] = "success"
        
        return {
            "messages": state["messages"] + new_messages,
            "execution_logs": execution_logs,
            "approval_results": approval_results,
            "pending_approvals": [],
        }
    
    async def _reflect_node(self, state: FinanceAgentState) -> dict[str, Any]:
        """반성 노드: 결과 검토 및 최종 응답"""
        thought = {
            "thoughtType": "reflection",
            "content": "조사 결과 검토 및 조치 제안 정리 중...",
            "timestamp": datetime.utcnow(),
            "sources": state.get("evidence", []),
        }
        
        final_response = AIMessage(
            content="조사 및 조치 제안이 완료되었습니다. 결과를 확인해주세요."
        )
        
        return {
            "messages": state["messages"] + [final_response],
            "thought_chain": state.get("thought_chain", []) + [thought],
        }
    
    def _should_use_tools(self, state: FinanceAgentState) -> str:
        """도구 사용 여부 결정"""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "use_tools"
        return "reflect"
    
    def _parse_plan(self, content: str) -> list[dict[str, Any]]:
        """LLM 응답에서 계획 단계 파싱"""
        steps = []
        for i, line in enumerate(content.split("\n")):
            if line.strip().startswith(("1.", "2.", "3.", "-", "*")):
                steps.append({
                    "stepId": str(uuid.uuid4()),
                    "description": line.strip(),
                    "status": "pending",
                    "confidence": 0.8,
                    "timestamp": datetime.utcnow(),
                    "metadata": {},
                })
        if not steps:
            steps.append({
                "stepId": str(uuid.uuid4()),
                "description": "케이스 조사 및 조치 제안",
                "status": "pending",
                "confidence": 0.7,
                "timestamp": datetime.utcnow(),
                "metadata": {},
            })
        return steps
    
    async def stream(
        self,
        user_input: str,
        user_id: str,
        tenant_id: str,
        goal: str | None = None,
        context: dict[str, Any] | None = None,
        thread_id: str | None = None,
        resume_value: Any = None,
    ):
        """
        에이전트 실행 (스트리밍)
        
        Args:
            user_input: 사용자 입력
            user_id: 사용자 ID
            tenant_id: 테넌트 ID
            goal: 목표 (예: "중복송장 의심 케이스 조치 제안")
            context: caseId, documentIds, entityIds, openItemIds
            thread_id: 스레드 ID (checkpoint 복원용, HITL resume 시 필수)
            resume_value: HITL interrupt 후 재개 시 Command(resume=...) 값
        """
        from langgraph.types import Command
        
        config: dict[str, Any] = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        
        if resume_value is not None:
            input_data = Command(resume=resume_value)
        else:
            input_data = {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id,
                "tenant_id": tenant_id,
                "goal": goal or user_input,
                "context": context or {},
                "evidence": [],
                "thought_chain": [],
                "plan_steps": [],
                "execution_logs": [],
                "current_step_id": None,
            }
        
        stream_mode = ["updates", "values"]
        async for event in self.graph.astream(
            input_data, config=config, stream_mode=stream_mode
        ):
            yield event


_finance_agent: FinanceAgent | None = None


def get_finance_agent(checkpointer=None) -> FinanceAgent:
    """FinanceAgent 인스턴스 반환 (checkpointer 미지정 시 get_finance_checkpointer 사용)"""
    global _finance_agent
    if _finance_agent is None:
        from core.memory.checkpointer_factory import get_finance_checkpointer
        cp = checkpointer if checkpointer is not None else get_finance_checkpointer()
        _finance_agent = FinanceAgent(checkpointer=cp)
    return _finance_agent
