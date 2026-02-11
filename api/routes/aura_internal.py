"""
Phase3 Internal Trigger (PHASE3_SPEC §A)

POST /aura/internal/cases/{caseId}/analysis-runs — BE 호출, 즉시 ack.
"""

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi import Query
from pydantic import BaseModel, Field, field_validator

from api.schemas.common import coerce_case_run_id
from core.context import set_request_context
from core.analysis.phase3_pipeline import run_phase3_analysis
from core.analysis.phase3_callback import send_phase3_callback
from core.analysis.run_store import get_or_create_queue, put_event, remove_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/internal", tags=["aura-internal"])


class Phase3CallbacksModel(BaseModel):
    """callbacks: resultCallbackUrl, auth"""
    resultCallbackUrl: str = Field(..., description="BE 콜백 URL")
    auth: dict[str, Any] | None = Field(default=None, description='{"type": "BEARER", "token": "..."}')


class Phase3OptionsModel(BaseModel):
    """options: ragTopK, temperature, promptVersion"""
    ragTopK: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    promptVersion: str = Field(default="phase3-mvp-v1")


class Phase3TriggerRequest(BaseModel):
    """Phase3 Trigger 요청 (PHASE3_SPEC §A)"""
    runId: str = Field(..., description="BE가 생성한 run 식별자")
    caseId: str | None = Field(default=None, description="path와 중복 가능")
    requestedBy: str = Field(default="HUMAN", description="userId 또는 HUMAN | SYSTEM")
    artifacts: dict[str, Any] = Field(
        default_factory=dict,
        description="fiDocument, lineItems, openItems, parties, policies, documents",
    )
    callbacks: Phase3CallbacksModel = Field(..., description="resultCallbackUrl, auth")
    options: Phase3OptionsModel | None = Field(default=None)

    @field_validator("caseId", "runId", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> Any:
        return coerce_case_run_id(v)


async def _run_phase3_background(
    case_id: str,
    run_id: str,
    artifacts: dict[str, Any],
    callbacks: Phase3CallbacksModel,
    options: Phase3OptionsModel | None,
    test_fail: str | None = None,
):
    """Phase3 파이프라인 실행, 이벤트 큐 적재, 완료 시 resultCallbackUrl로 콜백. test_fail=rag|llm 시 해당 단계에서 의도적 실패."""
    set_request_context(
        tenant_id="1",
        user_id="",
        auth_token=None,
        trace_id=f"trace-p3-{case_id}-{run_id[:8]}",
        case_id=case_id,
    )
    callback_url = callbacks.resultCallbackUrl
    auth = callbacks.auth
    opts = (options or Phase3OptionsModel()).model_dump()
    callback_payload: dict[str, Any] | None = None
    last_event = "failed"
    failed_payload: dict[str, Any] = {}

    try:
        async for event_type, payload in run_phase3_analysis(
            case_id, run_id, artifacts=artifacts, callbacks=callbacks.model_dump(), options=opts, test_fail=test_fail
        ):
            if event_type == "_phase3_callback_payload":
                callback_payload = payload
                continue
            put_event(run_id, event_type, payload)
            if event_type in ("completed", "failed"):
                last_event = event_type
                if event_type == "failed":
                    failed_payload = payload
                break

        if last_event == "completed" and callback_payload:
            await send_phase3_callback(callback_url, auth, callback_payload)
        elif last_event == "failed" and callback_payload:
            await send_phase3_callback(callback_url, auth, callback_payload)
        elif last_event == "failed":
            fail_body = {
                "runId": run_id,
                "caseId": case_id,
                "status": "FAILED",
                "error": {"message": failed_payload.get("error", "unknown"), "stage": "pipeline"},
            }
            await send_phase3_callback(callback_url, auth, fail_body)
    except Exception as e:
        logger.exception("Phase3 background failed case=%s run=%s", case_id, run_id)
        put_event(run_id, "failed", {
            "runId": run_id,
            "status": "failed",
            "error": {"message": str(e), "stage": "background"},
            "retryable": True,
        })
        await send_phase3_callback(
            callback_url, auth,
            {"runId": run_id, "caseId": case_id, "status": "FAILED", "error": {"message": str(e), "stage": "background"}},
        )
    finally:
        await asyncio.sleep(2.0)
        remove_queue(run_id)


@router.post("/cases/{case_id}/analysis-runs")
async def phase3_analysis_runs(
    case_id: str,
    body: Phase3TriggerRequest,
    request: Request,
    test_fail_query: str | None = Query(None, description="테스트: rag | llm 이면 해당 단계에서 의도적 실패 (query param)"),
):
    """
    Phase3 분석 트리거 (BE 호출, 즉시 ack).

    POST /aura/internal/cases/{caseId}/analysis-runs
    Response: accepted, runId, streamPath
    테스트: Header X-Aura-Test-Fail 또는 query ?test_fail_query=rag|llm 이면 해당 단계에서 의도적 실패.
    """
    if os.environ.get("DEMO_OFF", "").upper() in ("1", "TRUE", "YES"):
        return JSONResponse(
            status_code=200,
            content={"accepted": False, "runId": body.runId, "message": "Analysis disabled (DEMO_OFF)"},
        )

    run_id = str(body.runId)
    case_id_str = str(case_id)
    test_fail = (
        request.headers.get("X-Aura-Test-Fail") or request.headers.get("x-aura-test-fail") or test_fail_query
    )
    if test_fail and test_fail.lower() not in ("rag", "llm"):
        test_fail = None
    else:
        test_fail = test_fail.lower() if test_fail else None
    get_or_create_queue(run_id)

    asyncio.create_task(_run_phase3_background(
        case_id_str,
        run_id,
        body.artifacts,
        body.callbacks,
        body.options,
        test_fail=test_fail,
    ))

    stream_path = f"/aura/cases/{case_id_str}/analysis/stream?runId={run_id}"
    return JSONResponse(
        status_code=202,
        content={
            "accepted": True,
            "runId": run_id,
            "streamPath": stream_path,
        },
    )
