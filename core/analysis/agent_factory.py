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
    
    # docIds (camelCase) → doc_ids (snake_case)
    doc_ids_raw = data.get("docIds") or data.get("doc_ids")
    logger.debug(f"[AgentConfig] Parsing docIds for {agent_id_val}: raw={doc_ids_raw}, type={type(doc_ids_raw)}")
    if doc_ids_raw is None:
        # 백엔드 API 응답에 docIds가 없을 경우, 지식이 없는 것으로 간주
        base.doc_ids = []
        logger.warning(f"[AgentConfig] docIds가 없습니다 (백엔드 응답에 docIds 필드 없음). 에이전트 {agent_id_val}는 할당된 지식이 없으므로 RAG 검색 결과 0건, 일반 LLM/웹 검색으로 Fallback합니다. 백엔드 API 응답 확인 필요: {list(data.keys())[:10]}")
    elif isinstance(doc_ids_raw, list):
        base.doc_ids = [int(d) for d in doc_ids_raw if d is not None]
        if len(base.doc_ids) == 0:
            logger.warning(f"[AgentConfig] docIds가 빈 리스트입니다. 에이전트 {agent_id_val}는 할당된 지식이 없으므로 RAG 검색 결과 0건, 일반 LLM/웹 검색으로 Fallback합니다. 백엔드에서 지식을 할당했는지 확인 필요.")
        else:
            logger.info(f"[AgentConfig] docIds 파싱 완료: {len(base.doc_ids)}개 문서 할당됨 (doc_ids={base.doc_ids[:5]}{'...' if len(base.doc_ids) > 5 else ''})")
    else:
        base.doc_ids = []
        logger.warning(f"[AgentConfig] docIds 형식이 올바르지 않습니다 (list가 아님, type={type(doc_ids_raw)}). 에이전트 {agent_id_val}는 할당된 지식이 없으므로 RAG 검색 결과 0건으로 처리합니다.")
    
    # tenantId (camelCase) → tenant_id (snake_case)
    tenant_id_raw = data.get("tenantId") or data.get("tenant_id")
    if tenant_id_raw is not None:
        try:
            base.tenant_id = int(tenant_id_raw)
        except (ValueError, TypeError):
            base.tenant_id = 0
    else:
        base.tenant_id = 0
    
    return base


async def fetch_agent_config(
    agent_id: str = "audit",
    version: str | None = None,
    tenant_id: str | None = None,
) -> AgentConfig:
    """
    백엔드 API에서 에이전트 설정 조회. 캐시 우선, 없으면 API 호출 후 캐시 저장.
    실패 시 기본 설정 반환.

    호출: GET /api/v1/agents/config?agent_key={agent_id} (X-Tenant-ID 필수).
    응답: ApiResponse 래퍼 → data (camelCase). tools[].toolName을 agent_tool_mapping으로 사용.
    """
    from core.stores.config_store import AgentConfigStore
    
    tenant_id_str = tenant_id or "1"
    store = AgentConfigStore()
    
    # 캐시 확인
    cached = store.get(tenant_id_str, agent_id)
    if cached is not None:
        logger.debug(f"fetch_agent_config: Cache hit for {tenant_id_str}:{agent_id}")
        return cached
    
    # 캐시 미스: 백엔드 API 호출
    logger.debug(f"fetch_agent_config: Cache miss for {tenant_id_str}:{agent_id}, fetching from backend")
    settings = get_settings()
    base = getattr(settings, "dwp_gateway_url", "") or ""
    if not base:
        config = _default_config(agent_id, version)
        store.set(tenant_id_str, agent_id, config)
        return config
    
    base = base.rstrip("/")
    path = getattr(settings, "agent_config_path", None) or "api/v1/agents/config"
    path = path.lstrip("/")
    url = f"{base}/{path}"
    params: dict[str, str] = {"agent_key": agent_id}
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-ID": tenant_id_str,
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
                        # 캐시에 저장
                        store.set(tenant_id_str, agent_id, parsed)
                        return parsed
            elif r.status_code == 404:
                logger.info("fetch_agent_config: agent not found (404), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id_str)
            elif r.status_code == 400:
                logger.warning("fetch_agent_config: bad request (400), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id_str)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            logger.info("fetch_agent_config: agent not found (404), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id_str)
        elif e.response.status_code == 400:
            logger.warning("fetch_agent_config: bad request (400), agent_key=%s, tenant_id=%s, using default", agent_id, tenant_id_str)
        else:
            logger.debug("fetch_agent_config failed, status=%d, using default: %s", e.response.status_code, e)
    except Exception as e:
        logger.debug("fetch_agent_config failed, using default: %s", e)
    
    # 기본 설정 반환 및 캐시 저장
    config = _default_config(agent_id, version)
    store.set(tenant_id_str, agent_id, config)
    return config


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


# ==================== Agent Discovery & Selection ====================

# 에이전트 목록 캐시 (tenant_id:agent_list)
_agent_list_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_AGENT_LIST_CACHE_TTL = 300.0  # 5분


async def discover_available_agents(tenant_id: str | int) -> list[dict[str, Any]]:
    """
    Discovery: 백엔드에서 가용한 에이전트 목록 조회 (캐싱 적용)
    
    호출: GET /api/synapse/agents (X-Tenant-ID 필수)
    응답: 에이전트 목록 (agentKey, name, domain, is_active 등)
    
    Returns:
        [{"agentKey": str, "name": str, "domain": str, "is_active": bool, ...}, ...]
    """
    import time
    from core.stores.config_store import AgentConfigStore
    
    tenant_id_str = str(tenant_id)
    now = time.time()
    
    # 캐시 확인
    if tenant_id_str in _agent_list_cache:
        cached_list, cached_time = _agent_list_cache[tenant_id_str]
        if now - cached_time < _AGENT_LIST_CACHE_TTL:
            logger.debug(f"discover_available_agents: Cache hit for tenant {tenant_id_str}")
            return cached_list
    
    # 캐시 미스: 백엔드 API 호출
    logger.debug(f"discover_available_agents: Cache miss for tenant {tenant_id_str}, fetching from backend")
    settings = get_settings()
    base = getattr(settings, "dwp_gateway_url", "") or ""
    if not base:
        logger.warning("discover_available_agents: dwp_gateway_url not configured, returning empty list")
        return []
    
    base = base.rstrip("/")
    url = f"{base}/api/synapse/agents"
    params: dict[str, str] = {"discovery": "true"}
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Tenant-ID": tenant_id_str,
    }
    try:
        from core.context import get_synapse_headers
        syn_headers = get_synapse_headers()
        if syn_headers.get("Authorization"):
            headers["Authorization"] = syn_headers["Authorization"]
        if syn_headers.get("X-Tenant-ID") and tenant_id_str == "1":
            headers["X-Tenant-ID"] = syn_headers["X-Tenant-ID"]
    except Exception:
        pass
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200:
                body = r.json()
                agents_data: list[dict[str, Any]] = []
                
                if isinstance(body, dict):
                    # Backend 응답 구조: { "data": { "agents": [...] } }
                    data_field = body.get("data")
                    if isinstance(data_field, dict):
                        # 중첩 구조: data.agents
                        agents_data = data_field.get("agents") or data_field.get("items") or data_field.get("content") or []
                    elif isinstance(data_field, list):
                        # data가 직접 리스트인 경우
                        agents_data = data_field
                    else:
                        # 최상위에 agents가 있는 경우
                        agents_data = body.get("agents") or body.get("items") or body.get("content") or []
                elif isinstance(body, list):
                    agents_data = body
                
                # 디버그 로그
                logger.debug(f"discover_available_agents: raw response keys={list(body.keys()) if isinstance(body, dict) else 'list'}")
                logger.debug(f"discover_available_agents: parsed agents_data count={len(agents_data)}")
                
                # is_active 또는 isActive가 True인 에이전트만 필터링 (필드 없으면 활성으로 간주)
                active_agents = [
                    agent for agent in agents_data
                    if isinstance(agent, dict) and agent.get("is_active", agent.get("isActive", True))
                ]
                
                # 캐시 저장
                _agent_list_cache[tenant_id_str] = (active_agents, now)
                logger.info(f"discover_available_agents: Found {len(active_agents)} active agents for tenant {tenant_id_str} (raw={len(agents_data)})")
                return active_agents
            else:
                logger.warning(f"discover_available_agents: Backend returned {r.status_code}, returning empty list")
                return []
    except Exception as e:
        logger.warning(f"discover_available_agents failed: {e}, returning empty list")
        return []


async def select_agent_for_request(
    user_query: str | None = None,
    context: dict[str, Any] | None = None,
    tenant_id: str | int = "1",
) -> str:
    """
    Selection: 사용자 요청/컨텍스트를 분석하여 적절한 에이전트 선택 (LLM Reasoning)
    
    Args:
        user_query: 사용자 질문 (예: "전표 확인해줘")
        context: 컨텍스트 정보 (예: {"caseId": "...", "evidence": {...}})
        tenant_id: 테넌트 ID
    
    Returns:
        선택된 agentKey (예: "finance_aura", "dev_aura")
    
    Fallback: 가용 에이전트가 없거나 선택 실패 시 "finance_aura" 반환 (백엔드에 실재하는 기본 키)
    """
    logger.info(
        "select_agent_for_request: start tenant_id=%s user_query=%s context_keys=%s",
        tenant_id,
        (user_query[:200] + "..." if user_query and len(user_query) > 200 else user_query),
        list(context.keys()) if isinstance(context, dict) else None,
    )
    # 1. Discovery: 가용한 에이전트 목록 조회
    agents = await discover_available_agents(tenant_id)
    
    if not agents:
        logger.warning(f"select_agent_for_request: No available agents found for tenant {tenant_id}, falling back to 'finance_aura'")
        return "finance_aura"
    
    # 2. 단일 에이전트면 바로 반환
    if len(agents) == 1:
        agent_key = agents[0].get("agentKey") or agents[0].get("agent_key")
        if agent_key:
            logger.info("select_agent_for_request: single-agent shortcut key=%s", agent_key)
            logger.info(f"select_agent_for_request: Single agent available, selected {agent_key}")
            return agent_key
    
    # 3. LLM 기반 선택 로직
    try:
        from core.llm import get_llm_client
        from langchain_core.messages import HumanMessage
        
        # 에이전트 목록을 LLM에 전달할 형식으로 변환
        agents_summary = [
            {
                "agentKey": a.get("agentKey") or a.get("agent_key", ""),
                "name": a.get("name", ""),
                "domain": a.get("domain", ""),
                "description": a.get("description", ""),
            }
            for a in agents[:10]  # 최대 10개만 고려
        ]
        logger.info(
            "select_agent_for_request: candidates=%s",
            [a.get("agentKey") or a.get("agent_key") for a in agents_summary],
        )
        
        # LLM 프롬프트 구성
        query_context = user_query or ""
        if context:
            case_id = context.get("caseId")
            if case_id:
                query_context += f" 케이스 ID: {case_id}"
        
        # 도메인 매핑: 백엔드 app_codes 규격 준수 (DEVOPS → DEV)
        # 백엔드 domain 필드 값: DEV, FINANCE, HR 등
        domain_mapping = {
            "DEVOPS": "DEV",  # 백엔드가 DEV를 사용하므로 매핑
            "DEV": "DEV",
            "FINANCE": "FINANCE",
            "HR": "HR",
        }
        
        prompt = f"""다음은 사용 가능한 에이전트 목록입니다:

{chr(10).join([f"- {a['agentKey']} (도메인: {a['domain']}): {a.get('name', '')} - {a.get('description', '')}" for a in agents_summary])}

사용자 요청/컨텍스트: {query_context or '(케이스 분석)'}

위 요청을 분석하여 가장 적합한 에이전트의 agentKey만 반환하세요.
- 코드/개발/리뷰 관련 → DEV 도메인 (백엔드 규격: DEV, 예: dev_aura)
- 전표/회계/경비 관련 → FINANCE 도메인 (예: finance_aura)
- 인사/채용 관련 → HR 도메인
- 케이스 분석/감사 → finance_aura

**중요**: 도메인은 백엔드 app_codes 규격을 따릅니다 (DEV, FINANCE, HR). DEVOPS가 아닌 DEV를 사용합니다.

JSON 형식 없이 agentKey만 반환합니다.
예: dev_aura"""
        
        llm_client = get_llm_client()
        response = await llm_client.ainvoke(prompt)
        
        # 응답에서 agentKey 추출
        selected_key = str(response).strip()
        
        # agentKey 검증
        available_keys = [a.get("agentKey") or a.get("agent_key") for a in agents_summary]
        if selected_key in available_keys:
            logger.info("select_agent_for_request: decision=llm key=%s", selected_key)
            logger.info(f"select_agent_for_request: LLM selected {selected_key} for query: {query_context[:50]}")
            return selected_key
        else:
            # 응답이 agentKey가 아니면 도메인 기반 추론
            query_lower = query_context.lower()
            
            # 도메인별 키워드 매칭 (백엔드 규격: DEV, FINANCE, HR)
            if any(kw in query_lower for kw in ["코드", "프로그램", "개발", "리뷰", "pr", "코드리뷰", "devops", "code", "review"]):
                for a in agents_summary:
                    domain_upper = a.get("domain", "").upper()
                    # DEVOPS 또는 DEV 도메인 매칭 (백엔드는 DEV를 사용)
                    if domain_upper in ("DEV", "DEVOPS"):
                        selected_key = a.get("agentKey") or a.get("agent_key")
                        if selected_key:
                            logger.info("select_agent_for_request: decision=domain key=%s domain=%s", selected_key, domain_upper)
                            logger.info(f"select_agent_for_request: Domain-based selection (DEV/DEVOPS): {selected_key}")
                            return selected_key
            elif any(kw in query_lower for kw in ["finance", "전표", "회계", "경비", "지출", "송장", "재무", "accounting"]):
                for a in agents_summary:
                    if a.get("domain", "").upper() == "FINANCE":
                        selected_key = a.get("agentKey") or a.get("agent_key")
                        if selected_key:
                            logger.info("select_agent_for_request: decision=domain key=%s domain=FINANCE", selected_key)
                            logger.info(f"select_agent_for_request: Domain-based selection (FINANCE): {selected_key}")
                            return selected_key
            elif any(kw in query_lower for kw in ["인사", "채용", "직원", "hr", "human"]):
                for a in agents_summary:
                    if a.get("domain", "").upper() == "HR":
                        selected_key = a.get("agentKey") or a.get("agent_key")
                        if selected_key:
                            logger.info("select_agent_for_request: decision=domain key=%s domain=HR", selected_key)
                            logger.info(f"select_agent_for_request: Domain-based selection (HR): {selected_key}")
                            return selected_key
            
            logger.info("select_agent_for_request: decision=fallback_first key=%s", agents_summary[0].get("agentKey") or agents_summary[0].get("agent_key") or "finance_aura")
            logger.warning(f"select_agent_for_request: LLM selected invalid key '{selected_key}', falling back to first agent")
            return agents_summary[0].get("agentKey") or agents_summary[0].get("agent_key") or "finance_aura"
    
    except Exception as e:
        logger.info("select_agent_for_request: decision=exception fallback to first agent (if any)")
        logger.warning(f"select_agent_for_request: LLM selection failed: {e}, falling back to first agent")
        if agents:
            return agents[0].get("agentKey") or agents[0].get("agent_key") or "finance_aura"
        return "finance_aura"


def invalidate_agent_list_cache(tenant_id: str | int | None = None) -> None:
    """
    에이전트 목록 캐시 무효화 (백엔드에서 에이전트 추가/삭제/수정 시 호출)
    
    Args:
        tenant_id: 특정 테넌트만 무효화 (None이면 전체 무효화)
    """
    if tenant_id is None:
        _agent_list_cache.clear()
        logger.info("invalidate_agent_list_cache: All caches cleared")
    else:
        tenant_id_str = str(tenant_id)
        _agent_list_cache.pop(tenant_id_str, None)
        logger.info(f"invalidate_agent_list_cache: Cache cleared for tenant {tenant_id_str}")
