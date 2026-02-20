"""
에이전트 설정 스키마 (백엔드 API 연동)

백엔드에서 에이전트 설정을 읽어와 StateGraph를 동적으로 구성할 때 사용하는 Pydantic 모델.
agent_tool_mapping에 정의된 도구만 llm.bind_tools()에 주입된다.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentEdgeConfig(BaseModel):
    """엣지 정의: source -> target (조건부 시 condition 사용)"""
    source: str = Field(..., description="시작 노드 ID")
    target: str = Field(..., description="도착 노드 ID")
    condition: str | None = Field(default=None, description="conditional_edges용 라우팅 키 (예: gather, plan)")


class AgentToolItem(BaseModel):
    """에이전트 설정 API 응답의 tools[] 항목 (agent_tool_inventory 기반, V58 description/schemaJson)"""
    toolName: str = Field(..., description="도구 이름 (agent_tool_mapping과 동일 키)")
    description: str | None = Field(default=None, description="도구 설명 (V58)")
    schemaJson: dict[str, Any] | None = Field(default=None, description="파라미터 스키마 (V58)")


class AgentConfig(BaseModel):
    """백엔드에서 내려주는 에이전트 설정 (이력 관리: agent_id + version)"""
    agent_id: str = Field(..., description="에이전트 식별자 (예: audit, finance)")
    version: str = Field(default="1.0", description="설정 버전 (콜백 이력 관리용)")
    name: str | None = Field(default=None, description="표시명")
    entry_point: str = Field(default="analyze", description="진입 노드 ID")
    nodes: list[str] = Field(default_factory=list, description="노드 ID 목록 (순서는 edges로 결정)")
    edges: list[AgentEdgeConfig] = Field(default_factory=list, description="엣지 목록 (source->target)")
    conditional_edges: list[dict[str, Any]] = Field(
        default_factory=list,
        description="조건부 엣지: [{source, path_key, targets: {key: target}}]",
    )
    agent_tool_mapping: list[str] = Field(
        default_factory=list,
        description="LLM에 바인딩할 도구 이름 목록. 이 목록에 있는 도구만 bind_tools()에 주입.",
    )
    tools: list[AgentToolItem] | None = Field(
        default=None,
        description="API 응답의 tools[] (agent_tool_inventory 조회: toolName, description, schemaJson). 바인딩은 agent_tool_mapping 사용.",
    )
    system_prompt_key: str | None = Field(default=None, description="시스템 프롬프트 도메인 키 (예: finance). system_instruction이 없을 때 Fallback으로 사용")
    system_instruction: Optional[str] = Field(default=None, description="API로 수신한 시스템 지침 본문. 있으면 get_system_prompt() 대신 최우선 주입 (동적 배포)")
    model_name: str | None = Field(default=None, description="DB model_name 코드 → LLM 엔진 식별자 (Synapse와 동일 코드값)")
    checkpointer: str | None = Field(default="memory", description="memory | sqlite | none")
    doc_ids: list[int] = Field(default_factory=list, description="에이전트가 접근 가능한 문서 ID 목록. 빈 리스트면 RAG 검색 결과 0건 (Secure by Default)")
    tenant_id: int = Field(default=0, description="테넌트 ID. 0이면 시스템 에이전트(테넌트 필터 제외), >0이면 해당 테넌트만 접근")


# 기본 감사 에이전트 설정 (백엔드 API 미제공 시 폴백)
DEFAULT_AUDIT_AGENT_CONFIG = AgentConfig(
    agent_id="audit",
    version="1.0",
    name="Case Audit Agent",
    entry_point="analyze",
    nodes=["analyze", "evidence_gather", "plan", "execute", "tools", "reflect"],
    edges=[
        AgentEdgeConfig(source="evidence_gather", target="plan"),
        AgentEdgeConfig(source="plan", target="execute"),
        AgentEdgeConfig(source="tools", target="reflect"),
        AgentEdgeConfig(source="reflect", target="__end__"),
    ],
    conditional_edges=[
        {"source": "analyze", "path_key": "next", "targets": {"gather": "evidence_gather", "plan": "plan"}},
        {"source": "execute", "path_key": "next", "targets": {"use_tools": "tools", "reflect": "reflect"}},
    ],
    agent_tool_mapping=[
        "get_case",
        "search_documents",
        "get_document",
        "get_entity",
        "get_open_items",
        "get_lineage",
        "web_search",
        "simulate_action",
        "propose_action",
        "execute_action",
    ],
    system_prompt_key="finance",
)
