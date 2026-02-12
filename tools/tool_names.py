"""
Canonical Tool Names (백엔드 DB tool_name과 일치 필수)

Aura의 @tool 함수명과 백엔드 DB의 tool_name은 반드시 아래 상수와 동일해야 합니다.
Google Search / web_search 등 별칭 사용 금지 — 아래 이름만 사용.
"""

# Finance Agent 도구 (BE case_analysis_result, agent_activity_log 등에서 tool_name으로 저장 시 사용)
TOOL_GET_CASE = "get_case"
TOOL_SEARCH_DOCUMENTS = "search_documents"
TOOL_GET_DOCUMENT = "get_document"
TOOL_GET_ENTITY = "get_entity"
TOOL_GET_OPEN_ITEMS = "get_open_items"
TOOL_GET_LINEAGE = "get_lineage"
TOOL_WEB_SEARCH = "web_search"
TOOL_SIMULATE_ACTION = "simulate_action"
TOOL_PROPOSE_ACTION = "propose_action"
TOOL_EXECUTE_ACTION = "execute_action"

# 백엔드 DB와 계약된 전체 목록 (snake_case 통일)
FINANCE_TOOL_NAMES = [
    TOOL_GET_CASE,
    TOOL_SEARCH_DOCUMENTS,
    TOOL_GET_DOCUMENT,
    TOOL_GET_ENTITY,
    TOOL_GET_OPEN_ITEMS,
    TOOL_GET_LINEAGE,
    TOOL_WEB_SEARCH,
    TOOL_SIMULATE_ACTION,
    TOOL_PROPOSE_ACTION,
    TOOL_EXECUTE_ACTION,
]

__all__ = [
    "TOOL_GET_CASE",
    "TOOL_SEARCH_DOCUMENTS",
    "TOOL_GET_DOCUMENT",
    "TOOL_GET_ENTITY",
    "TOOL_GET_OPEN_ITEMS",
    "TOOL_GET_LINEAGE",
    "TOOL_WEB_SEARCH",
    "TOOL_SIMULATE_ACTION",
    "TOOL_PROPOSE_ACTION",
    "TOOL_EXECUTE_ACTION",
    "FINANCE_TOOL_NAMES",
]
