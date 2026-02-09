"""
Phase2 Analysis Runs (runId 기반)

GET /aura/analysis-runs/{runId}/stream - runId 기반 SSE 스트림
"""

import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.dependencies import CurrentUser, TenantId
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
    """
    if not queue_exists(run_id):
        return {"error": "runId not found or already completed", "runId": run_id}

    async def event_generator():
        sent_completed = False
        case_id = ""
        while True:
            ev = await get_event(run_id, timeout=300.0)
            if ev is None:
                break
            event_type, payload = ev
            if event_type == "started":
                case_id = payload.get("caseId", "")
            yield f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(STREAM_EVENT_DELAY)
            if event_type in ("completed", "failed"):
                sent_completed = True
                break
        # FE 정상 종료 인식: completed 미수신 시 [DONE] 직전에 보강
        if not sent_completed:
            fallback = {"status": "completed", "runId": run_id, "caseId": case_id}
            yield f"event: completed\ndata: {json.dumps(fallback, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
