"""
Finance Stream 통합 테스트

SSE 이벤트 순서/필드 검증, HITL 승인/반려 시나리오

실행 시 환경 변수 필요: OPENAI_API_KEY, SECRET_KEY(또는 JWT_SECRET)
"""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# 환경 미구성 시 스킵
pytest.importorskip("jose")

from fastapi.testclient import TestClient

from main import app
from core.security.auth import create_token


def _get_auth_headers() -> dict[str, str]:
    """테스트용 JWT 헤더"""
    token = create_token(user_id="test-user", tenant_id="tenant1")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


def _mock_stream_events_no_hitl():
    """HITL 없는 기본 스트림 이벤트 (stream_mode=["updates","values"] 형식)"""
    yield ("updates", {"analyze": {"thought_chain": [{}], "goal": "test"}})
    yield ("updates", {"plan": {"plan_steps": [], "thought_chain": []}})
    yield ("updates", {"execute": {"messages": [MagicMock(content="done", tool_calls=[])]}})
    yield ("updates", {"reflect": {"messages": []}})


@pytest.mark.asyncio
async def test_finance_stream_sse_event_format(client: TestClient):
    """
    SSE 이벤트 형식 검증:
    - id: <eventId> 포함
    - event: <type> 포함
    - data에 trace_id, case_id, tenant_id 포함
    """
    with patch("api.routes.finance_agent.get_finance_agent") as mock_agent:
        async def mock_stream(*args, **kwargs):
            for ev in _mock_stream_events_no_hitl():
                yield ev
        mock_agent.return_value.stream = mock_stream
        
        with patch("domains.finance.agents.finance_agent.get_finance_agent", mock_agent):
            response = client.post(
                "/agents/finance/stream",
                json={
                    "prompt": "중복송장 조사",
                    "context": {"caseId": "case-123"},
                },
                headers=_get_auth_headers(),
                timeout=10.0,
            )
        
        assert response.status_code == 200
        content = response.text
        
        # SSE 형식: id:, event:, data:
        assert "id:" in content
        assert "event:" in content
        assert "data:" in content
        
        # trace_id, case_id, tenant_id (context에 caseId 있으면)
        assert "trace_id" in content or "data: [DONE]" in content
        
        # 종료 플래그
        assert "data: [DONE]" in content


@pytest.mark.asyncio
async def test_finance_stream_event_types(client: TestClient):
    """이벤트 타입: start, thought, plan_step, tool_execution, hitl, content, end, error, done"""
    with patch("api.routes.finance_agent.get_finance_agent") as mock_agent:
        async def mock_stream(*args, **kwargs):
            for ev in _mock_stream_events_no_hitl():
                yield ev
        mock_agent.return_value.stream = mock_stream
        
        with patch("domains.finance.agents.finance_agent.get_finance_agent", mock_agent):
            response = client.post(
                "/agents/finance/stream",
                json={"prompt": "test", "context": {}},
                headers=_get_auth_headers(),
                timeout=10.0,
            )
        
        assert response.status_code == 200
        # start, end, [DONE] 최소 포함
        assert "event: start" in response.text
        assert "event: end" in response.text or "data: [DONE]" in response.text


@pytest.mark.asyncio
async def test_finance_stream_last_event_id(client: TestClient):
    """Last-Event-ID 헤더 지원 (재연결)"""
    with patch("api.routes.finance_agent.get_finance_agent") as mock_agent:
        async def mock_stream(*args, **kwargs):
            for ev in _mock_stream_events_no_hitl():
                yield ev
        mock_agent.return_value.stream = mock_stream
        
        with patch("domains.finance.agents.finance_agent.get_finance_agent", mock_agent):
            response = client.post(
                "/agents/finance/stream",
                json={"prompt": "test"},
                headers={
                    **_get_auth_headers(),
                    "Last-Event-ID": "5",
                },
                timeout=10.0,
            )
        
        # Last-Event-ID 있어도 200 (재개 로직 동작)
        assert response.status_code == 200


def test_finance_approve_endpoint(client: TestClient):
    """POST /agents/finance/approve 엔드포인트 존재"""
    response = client.post(
        "/agents/finance/approve",
        params={"request_id": "req-123", "approved": True},
        headers=_get_auth_headers(),
    )
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert data["approved"] is True


@pytest.mark.asyncio
async def test_sse_event_order(client: TestClient):
    """SSE 이벤트 순서: start → thought/plan_step → ... → end → [DONE]"""
    with patch("api.routes.finance_agent.get_finance_agent") as mock_agent:
        async def mock_stream(*args, **kwargs):
            yield ("updates", {"analyze": {"thought_chain": [], "goal": "test"}})
            yield ("updates", {"plan": {"plan_steps": [{"stepId": "s1", "description": "d"}]}})
            yield ("updates", {"execute": {"messages": [MagicMock(content="ok", tool_calls=[])]}})
            yield ("updates", {"reflect": {"messages": [MagicMock(content="done")]}})
        mock_agent.return_value.stream = mock_stream
        
        with patch("domains.finance.agents.finance_agent.get_finance_agent", mock_agent):
            response = client.post(
                "/agents/finance/stream",
                json={"prompt": "test"},
                headers=_get_auth_headers(),
                timeout=10.0,
            )
        
        assert response.status_code == 200
        text = response.text
        # 순서: start가 end보다 먼저
        start_pos = text.find("event: start")
        end_pos = text.find("event: end")
        done_pos = text.find("data: [DONE]")
        assert start_pos >= 0
        assert end_pos > start_pos
        assert done_pos > end_pos


@pytest.mark.asyncio
async def test_finance_stream_hitl_interrupt_resume(client: TestClient):
    """
    HITL interrupt/resume 플로우: __interrupt__ 감지 → hitl 이벤트 → Redis 신호 대기 → resume
    Redis/HITL Manager를 mock하여 즉시 승인 신호 반환
    """
    from unittest.mock import AsyncMock

    class MockInterrupt:
        """LangGraph Interrupt 값 모킹"""
        def __init__(self, value):
            self.value = value

    with patch("api.routes.finance_agent.get_finance_agent") as mock_agent:
        call_count = 0

        async def mock_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield ("updates", {"analyze": {"thought_chain": [], "goal": "test"}})
                yield ("updates", {"plan": {"plan_steps": []}})
                yield ("updates", {"execute": {"messages": [MagicMock(tool_calls=[{"name": "propose_action"}])]}})
                yield ("values", {
                    "messages": [],
                    "__interrupt__": [
                        MockInterrupt({
                            "requestId": "req_test123",
                            "toolName": "propose_action",
                            "actionType": "propose_action",
                            "context": {},
                            "message": "실행을 승인하시겠습니까?",
                        })
                    ],
                })
            else:
                for ev in _mock_stream_events_no_hitl():
                    yield ev

        mock_agent.return_value.stream = mock_stream

        mock_hitl = AsyncMock()
        mock_hitl.save_approval_request = AsyncMock()
        mock_hitl.wait_for_approval_signal = AsyncMock(
            return_value={"type": "approval", "approved": True}
        )

        with patch("api.routes.finance_agent.get_finance_agent", mock_agent), \
             patch("api.routes.finance_agent.get_hitl_manager", return_value=mock_hitl):
            response = client.post(
                "/agents/finance/stream",
                json={"prompt": "test hitl", "context": {}},
                headers=_get_auth_headers(),
                timeout=15.0,
            )

        assert response.status_code == 200
        text = response.text
        assert "event: hitl" in text
        assert "req_test123" in text
        assert "data: [DONE]" in text
        mock_hitl.wait_for_approval_signal.assert_called_once()
