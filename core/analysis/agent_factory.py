"""
동적 LangGraph 팩토리

백엔드 API에서 에이전트 설정을 읽어와 StateGraph를 동적으로 구성하고,
agent_tool_mapping에 정의된 도구만 llm.bind_tools()에 주입합니다.
"""

import logging
from typing import Any, Callable

import httpx
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from core.config import get_settings
from core.analysis.agent_config_schema import (
    AgentConfig,
    AgentEdgeConfig,
    AgentToolItem,
    DEFAULT_AUDIT_AGENT_CONFIG,
)

logger = logging.getLogger(__name__)

# 도구 이름 -> 도구 인스턴스 레지스트리 (모듈 로드 시 채워짐)
TOOL_REGISTRY: dict[str, Any] = {}


def register_tools(tools: list[Any]) -> None:
    """도구 목록을 레지스트리에 등록 (name 속성으로 조회)."""
    for t in tools:
        name = getattr(t, "name", None)
        if name:
            TOOL_REGISTRY[name] = t


def get_tools_by_names(names: list[str]) -> tuple[list[Any], list[str]]:
    """
    agent_tool_mapping에 정의된 이름만 반환. 레지스트리에 없는 도구는 스킵(에러 없음).
    Returns:
        (tools, skipped_names): 바인딩할 도구 목록, 엔진에서 인식하지 못해 스킵된 도구 이름 목록
    """
    out: list[Any] = []
    skipped: list[str] = []
    for n in names:
        if n in TOOL_REGISTRY:
            out.append(TOOL_REGISTRY[n])
        else:
            skipped.append(n)
            logger.warning("Tool not in registry, skipping (ThoughtStream 알림): %s", n)
    return (out, skipped)


def _parse_config_response(data: dict[str, Any], fallback_agent_id: str) -> AgentConfig | None:
    """
    백엔드 ApiResponse.data (camelCase) → AgentConfig 변환.
    tools[].toolName을 모아 agent_tool_mapping으로 사용.
    """
    if not data or not isinstance(data, dict):
        return None
    agent_key = data.get("agentKey") or data.get("agent_key")
    agent_id_val = agent_key or str(data.get("agentId", fallback_agent_id))
    version_val = data.get("version")
    version_str = str(version_val) if version_val is not None else "1.0"
    model_obj = data.get("model") or {}
    model_name_val = model_obj.get("modelName") or model_obj.get("model_name") if isinstance(model_obj, dict) else None
    tools_raw = data.get("tools") or []
    tool_names = [t.get("toolName") or t.get("tool_name") for t in tools_raw if t.get("toolName") or t.get("tool_name")]
    tool_items = [
        AgentToolItem(
            toolName=t.get("toolName") or t.get("tool_name"),
            description=t.get("description"),
            schemaJson=t.get("schemaJson") or t.get("schema_json"),
        )
        for t in tools_raw
        if t.get("toolName") or t.get("tool_name")
    ]
    base = DEFAULT_AUDIT_AGENT_CONFIG.model_copy(deep=True)
    base.agent_id = agent_id_val
    base.version = version_str
    base.name = data.get("name") or base.name
    base.system_instruction = data.get("systemInstruction") or data.get("system_instruction") or base.system_instruction
    base.model_name = model_name_val or base.model_name
    base.agent_tool_mapping = tool_names or base.agent_tool_mapping
    base.tools = tool_items if tool_items else base.tools
    return base


async def fetch_agent_config(
    agent_id: str = "audit",
    version: str | None = None,
    tenant_id: str | None = None,
) -> AgentConfig:
    """
    백엔드 API에서 에이전트 설정 조회. 실패 시 기본 설정 반환.

    호출: GET /api/v1/agents/config?agent_key={agent_id} (X-Tenant-ID 필수).
    응답: ApiResponse 래퍼 → data (camelCase). tools[].toolName을 agent_tool_mapping으로 사용.
    """
    settings = get_settings()
    base = getattr(settings, "dwp_gateway_url", "") or ""
    if not base:
        return _default_config(agent_id, version)
    base = base.rstrip("/")
    path = getattr(settings, "agent_config_path", None) or "api/v1/agents/config"
    path = path.lstrip("/")
    url = f"{base}/{path}"
    params: dict[str, str] = {"agent_key": agent_id}
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-ID": tenant_id or "1",
    }
    try:
        from core.context import get_synapse_headers
        syn_headers = get_synapse_headers()
        if syn_headers.get("Authorization"):
            headers["Authorization"] = syn_headers["Authorization"]
        if syn_headers.get("X-Tenant-ID") and not tenant_id:
            headers["X-Tenant-ID"] = syn_headers["X-Tenant-ID"]
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200:
                body = r.json()
                if isinstance(body, dict):
                    data = body.get("data") or body
                    parsed = _parse_config_response(data, agent_id)
                    if parsed:
                        return parsed
            elif r.status_code == 404:
                logger.info("fetch_agent_config: agent not found (404), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id or "N/A")
            elif r.status_code == 400:
                logger.warning("fetch_agent_config: bad request (400), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id or "N/A")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info("fetch_agent_config: agent not found (404), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id or "N/A")
        elif e.response.status_code == 400:
            logger.warning("fetch_agent_config: bad request (400), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id or "N/A")
        else:
            logger.debug("fetch_agent_config failed, status=%d, using default: %s", e.response.status_code, e)
    except Exception as e:
        logger.debug("fetch_agent_config failed, using default: %s", e)
    return _default_config(agent_id, version)


def _default_config(agent_id: str, version: str | None) -> AgentConfig:
    if agent_id == "audit":
        c = DEFAULT_AUDIT_AGENT_CONFIG.model_copy(deep=True)
        if version:
            c.version = version
        return c
    return AgentConfig(
        agent_id=agent_id,
        version=version or "1.0",
        agent_tool_mapping=DEFAULT_AUDIT_AGENT_CONFIG.agent_tool_mapping,
        nodes=DEFAULT_AUDIT_AGENT_CONFIG.nodes,
        edges=DEFAULT_AUDIT_AGENT_CONFIG.edges,
        conditional_edges=DEFAULT_AUDIT_AGENT_CONFIG.conditional_edges,
        entry_point=DEFAULT_AUDIT_AGENT_CONFIG.entry_point,
    )


def build_graph_from_config(
    config: AgentConfig,
    state_schema: type[Any],
    node_impls: dict[str, Callable[..., Any]],
    *,
    checkpointer: Any = None,
) -> Any:
    """
    설정으로부터 StateGraph를 동적으로 구성하여 컴파일된 그래프 반환.

    node_impls: 노드 ID -> (state) -> state 업데이트를 반환하는 콜러블.
    """
    workflow = StateGraph(state_schema)
    for node_id in config.nodes:
        if node_id in node_impls:
            workflow.add_node(node_id, node_impls[node_id])
        else:
            logger.warning("Node implementation missing for: %s", node_id)

    workflow.set_entry_point(config.entry_point)

    # 조건부 엣지: source -> path_key에 따라 targets 중 하나로
    for ce in config.conditional_edges:
        source = ce.get("source")
        path_key = ce.get("path_key", "next")
        targets = ce.get("targets") or {}
        if source and targets:
            def _router(state: dict[str, Any], _src=source, _key=path_key, _t=targets) -> str:
                val = (state.get(_key) or state.get("__next")) or "reflect"
                return _t.get(val, list(_t.values())[0] if _t else "reflect")
            workflow.add_conditional_edges(source, _router, targets)

    # 일반 엣지
    for edge in config.edges:
        if edge.target == "__end__":
            workflow.add_edge(edge.source, END)
        elif edge.source in config.nodes and edge.target in config.nodes:
            workflow.add_edge(edge.source, edge.target)

    cp = checkpointer
    if config.checkpointer == "memory" and cp is None:
        cp = MemorySaver()
    return workflow.compile(checkpointer=cp)


def bind_llm_with_mapped_tools(llm: Any, agent_tool_mapping: list[str]) -> Any:
    """agent_tool_mapping에 정의된 도구만 llm.bind_tools()에 주입. 스킵된 도구는 바인딩에서 제외."""
    tools, _ = get_tools_by_names(agent_tool_mapping)
    if not tools:
        return llm
    return llm.bind_tools(tools)
