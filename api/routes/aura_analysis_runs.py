"""
Phase2 Analysis Runs (runId 기반)

GET /aura/analysis-runs/{runId}/stream - runId 기반 SSE 스트림
"""

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.dependencies import CurrentUser, TenantId
from api.sse_utils import SSE_HEADERS, format_sse_line
from core.analysis.run_store import get_event, queue_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/analysis-runs", tags=["aura-analysis-runs"])
STREAM_EVENT_DELAY = 0.15


@router.get("/{run_id}/stream")
async def analysis_run_stream(
    run_id: str,
    user: CurrentUser,
    tenant_id: TenantId,
):
    """
    Phase2 분석 스트림 (runId 기반)

    GET /aura/analysis-runs/{runId}/stream
    started → step → evidence → confidence → proposal → completed | failed

    빈 응답이 나오는 경우 확인할 것:
    - runId가 트리거(POST .../analysis-runs)에서 반환한 값과 동일한지
    - 트리거와 스트림이 같은 서버 인스턴스로 가는지 (run_store는 in-memory)
    - 분석이 이미 끝난 뒤 스트림을 열었는지 (완료 후 큐 제거됨)
    """
    if not queue_exists(run_id):
        logger.info("analysis_run_stream: runId not found or already completed run_id=%s", run_id)
        return {"error": "runId not found or already completed", "runId": run_id}

    logger.info("analysis_run_stream: start consuming run_id=%s", run_id)

    async def event_generator():
        # 연결 직후 한 줄 전송해 클라이언트/프록시가 스트림을 인식하도록 함 (빈 응답 방지)
        yield ": connected\n\n"
        sent_completed = False
        case_id = ""
        while True:
            ev = await get_event(run_id, timeout=300.0)
            if ev is None:
                logger.info("analysis_run_stream: get_event None (timeout or queue removed) run_id=%s", run_id)
                break
            event_type, payload = ev
            if event_type == "started":
                case_id = payload.get("caseId", "")
            yield format_sse_line(event_type, payload)
            await asyncio.sleep(STREAM_EVENT_DELAY)
            if event_type in ("completed", "failed"):
                sent_completed = True
                break
        # FE 정상 종료 인식: completed 미수신 시 [DONE] 직전에 보강
        if not sent_completed:
            fallback = {"status": "completed", "runId": run_id, "caseId": case_id}
            yield format_sse_line("completed", fallback)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
