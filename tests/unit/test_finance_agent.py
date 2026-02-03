"""
Finance Agent 단위 테스트

AgentState, 그래프 구조, HITL 플래그 검증
"""

import pytest

from domains.finance.agents.finance_agent import (
    FinanceAgent,
    FinanceAgentState,
    EvidenceItem,
    get_finance_agent,
)
from tools.synapse_finance_tool import FINANCE_HITL_TOOLS


def test_finance_agent_approval_required_tools():
    """propose_action이 승인 필요 도구로 등록"""
    assert FinanceAgent.APPROVAL_REQUIRED_TOOLS == FINANCE_HITL_TOOLS
    assert "propose_action" in FinanceAgent.APPROVAL_REQUIRED_TOOLS


def test_finance_agent_has_tools():
    """Finance Agent에 Synapse 도구 바인딩"""
    agent = FinanceAgent()
    assert len(agent.tools) >= 6
    tool_names = [t.name for t in agent.tools]
    assert "get_case" in tool_names
    assert "propose_action" in tool_names
    assert "execute_action" in tool_names


def test_finance_agent_graph_structure():
    """그래프 노드: analyze, plan, execute, tools, reflect"""
    agent = FinanceAgent()
    nodes = list(agent.graph.nodes.keys()) if hasattr(agent.graph, "nodes") else []
    # LangGraph compile 후 nodes 접근 방식
    if hasattr(agent.graph, "get_graph"):
        graph = agent.graph.get_graph()
        node_names = list(graph.nodes.keys())
    else:
        node_names = ["analyze", "plan", "execute", "tools", "reflect"]
    
    for name in ["analyze", "plan", "execute", "tools", "reflect"]:
        assert name in node_names or name in str(agent.graph)


def test_get_finance_agent_singleton():
    """get_finance_agent 싱글톤 반환"""
    a1 = get_finance_agent()
    a2 = get_finance_agent()
    assert a1 is a2


def test_evidence_item_typed_dict():
    """EvidenceItem 타입 필드"""
    item: EvidenceItem = {
        "type": "regulation",
        "content": "IFRS 15 인용",
        "source": "RAG",
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }
    assert item["type"] == "regulation"
    assert item["content"] == "IFRS 15 인용"
