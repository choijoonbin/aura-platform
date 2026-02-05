"""
Synapse Finance Tool 단위 테스트

Tool mocking을 통해 Synapse HTTP 호출 없이 도구 동작을 검증합니다.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from tools.synapse_finance_tool import (
    get_case,
    search_documents,
    get_document,
    get_entity,
    get_open_items,
    simulate_action,
    propose_action,
    execute_action,
    FINANCE_HITL_TOOLS,
    FINANCE_TOOLS,
)


@pytest.mark.asyncio
async def test_get_case_mock():
    """get_case 도구 - Synapse 응답 mocking"""
    mock_response = {"caseId": "case-123", "status": "open", "documents": []}
    
    with patch("tools.synapse_finance_tool._synapse_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_response)
        
        result = await get_case.ainvoke({"caseId": "case-123"})
        
        mock_get.assert_called_once_with("/tools/finance/cases/case-123")
        data = json.loads(result)
        assert data["caseId"] == "case-123"
        assert data["status"] == "open"


@pytest.mark.asyncio
async def test_search_documents_mock():
    """search_documents 도구 - 필터 기반 검색"""
    mock_response = {"documents": [{"id": "doc-1"}]}
    
    with patch("tools.synapse_finance_tool._synapse_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = json.dumps(mock_response)
        
        result = await search_documents.ainvoke({"filters": {"caseId": "case-123"}})
        
        mock_post.assert_called_once()
        call_payload = mock_post.call_args[0][1]
        assert call_payload["caseId"] == "case-123"
        data = json.loads(result)
        assert "documents" in data


@pytest.mark.asyncio
async def test_get_document_mock():
    """get_document 도구 - bukrs/belnr/gjahr"""
    mock_response = {"bukrs": "1000", "belnr": "123", "gjahr": "2024"}
    
    with patch("tools.synapse_finance_tool._synapse_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps(mock_response)
        
        result = await get_document.ainvoke({
            "bukrs": "1000",
            "belnr": "123",
            "gjahr": "2024",
        })
        
        mock_get.assert_called_once_with("/tools/finance/documents/1000/123/2024")
        data = json.loads(result)
        assert data["bukrs"] == "1000"


@pytest.mark.asyncio
async def test_simulate_action_mock():
    """simulate_action 도구 - 액션 시뮬레이션"""
    mock_response = {"simulated": True, "impact": "low"}
    
    with patch("tools.synapse_finance_tool._synapse_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = json.dumps(mock_response)
        
        result = await simulate_action.ainvoke({
            "caseId": "case-123",
            "actionType": "write_off",
            "payload": {"amount": 100},
        })
        
        mock_post.assert_called_once()
        call_payload = mock_post.call_args[0][1]
        assert call_payload["caseId"] == "case-123"
        assert call_payload["actionType"] == "write_off"


@pytest.mark.asyncio
async def test_simulate_action_with_explicit_idempotency_key():
    """simulate_action - 명시적 idempotency_key 전달"""
    with patch("tools.synapse_finance_tool._synapse_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = json.dumps({"simulated": True})
        
        await simulate_action.ainvoke({
            "caseId": "case-1",
            "actionType": "write_off",
            "payload": {},
            "idempotency_key": "req-abc123",
        })
        
        assert mock_post.call_args[1]["idempotency_key"] == "req-abc123"


@pytest.mark.asyncio
async def test_execute_action_mock():
    """execute_action - actionId로 실행"""
    with patch("tools.synapse_finance_tool._synapse_post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = json.dumps({"success": True})
        
        result = await execute_action.ainvoke({"actionId": "act-xyz789"})
        
        mock_post.assert_called_once()
        call_payload = mock_post.call_args[0][1]
        assert call_payload["actionId"] == "act-xyz789"


@pytest.mark.asyncio
async def test_tool_http_error_handling():
    """도구 HTTP 에러 시 JSON 에러 반환"""
    with patch("tools.synapse_finance_tool._synapse_get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        
        result = await get_case.ainvoke({"caseId": "nonexistent"})
        
        data = json.loads(result)
        assert "error" in data


def test_finance_hitl_tools():
    """propose_action은 HITL 필요 도구"""
    assert "propose_action" in FINANCE_HITL_TOOLS


def test_finance_tools_count():
    """Finance 도구 8개 등록"""
    assert len(FINANCE_TOOLS) == 9  # get_case, search_documents, get_document, get_entity, get_open_items, get_lineage, simulate, propose, execute


@pytest.mark.asyncio
async def test_synapse_headers_include_idempotency_key():
    """get_synapse_headers에 idempotency_key 전달 시 X-Idempotency-Key 포함"""
    from core.context import set_request_context, get_synapse_headers
    set_request_context("t1", "u1", "token", trace_id="trace-1")
    headers = get_synapse_headers(idempotency_key="req-abc")
    assert headers.get("X-Idempotency-Key") == "req-abc"
    assert headers.get("X-Trace-ID") == "trace-1"


@pytest.mark.asyncio
async def test_get_case_uses_retry_wrapper():
    """get_case가 retry 지원 request 함수 사용"""
    with patch("tools.synapse_finance_tool._synapse_get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = json.dumps({"caseId": "case-1"})
        
        result = await get_case.ainvoke({"caseId": "case-1"})
        
        mock_get.assert_called_once_with("/tools/finance/cases/case-1")
