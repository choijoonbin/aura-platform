"""
Pre-Analysis Screening (Detection) Routes — 상세 구현 가이드 v1.1 (정합성 최종)

POST /aura/detect/screen — 단건 전표 첫인상 스캔.
POST /aura/detect/screen-batch — 대량 전표 배치. **Request Body: 순수 JSON 배열 [...]** (BE index 기반 매핑, 응답 순서 1:1 보장).
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from api.dependencies import CurrentUser, TenantId
from core.context import set_request_context
from core.analysis.precheck_pipeline import run_screen, run_screen_batch, pick_briefing_priority, generate_briefing_insight
from core.analysis.analysis_pipeline import _normalize_get_case_response
from tools.synapse_finance_tool import get_case

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/detect", tags=["aura-detect"])

# 배치 요청 최대 건수 (BE 50건 단위 호출 권장)
SCREEN_BATCH_MAX_ITEMS = 100

# occurredAt 파싱 오류 시 해당 건을 UNUSUAL_PATTERN으로 덮어쓸 때 사용하는 사유
DATE_PARSE_ERROR_REASON = "전표 일시(occurredAt) 파싱 오류로 이상 거래로 분류합니다."


def _is_valid_iso_datetime(value: str | None) -> bool:
    """BE occurredAt(ISO_DATE_TIME) 파싱 가능 여부. 오류 시 UNUSUAL_PATTERN 처리용."""
    if not value or not isinstance(value, str):
        return True  # 없으면 파싱 오류로 간주하지 않음
    s = value.strip()
    if not s:
        return True
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


class ScreenRequest(BaseModel):
    """Pre-Analysis Screening 단건 요청. caseId 필수, 나머지는 BE가 전달 시 정규화 결과에 병합. v3.0: hrStatus, mccCode, mccName, budgetExceeded 지원."""
    caseId: str = Field(..., description="케이스 ID")
    amount: float | None = Field(default=None, description="전표 금액 (선택, get_case 결과에 병합)")
    occurredAt: str | None = Field(default=None, description="발생 시각 (선택)")
    expenseType: str | None = Field(default=None, description="경비 유형 (선택)")
    merchantName: str | None = Field(default=None, description="가맹점명 (선택)")
    caseType: str | None = Field(default=None, description="백엔드 분류 유형 (camelCase, 선택)")
    case_type: str | None = Field(default=None, description="백엔드 분류 유형 (snake_case, 선택)")
    hrStatus: str | None = Field(default=None, description="근태 상태: WORKING, VACATION, OFF 등 (v3.0)")
    hrStatusRaw: str | None = Field(default=None, description="근태 원본 상태: OFF, VACATION, WORKING 등")
    mccCode: str | None = Field(default=None, description="가맹점 업종 코드 (v3.0)")
    mccCodeRaw: str | None = Field(default=None, description="가맹점 업종 코드 원본")
    mccName: str | None = Field(default=None, description="가맹점 업종명 (v3.0)")
    mccRiskCategory: str | None = Field(default=None, description="MCC 위험도 분류: LOW|MEDIUM|HIGH|UNKNOWN")
    budgetExceeded: str | None = Field(default=None, description="예산 초과 여부 Y/N (v3.0). BE가 boolean으로 보낼 수 있음: true→Y, false→N")
    budgetExceededFlag: str | None = Field(default=None, description="예산 초과 플래그 Y/N")
    isHoliday: bool | None = Field(default=None, description="휴일 여부 boolean")
    holidayType: str | None = Field(default=None, description="휴일 유형: WEEKEND|PUBLIC_HOLIDAY|NONE")
    isWeekendAllowed: str | None = Field(default=None, description="주말 사용 허용 여부 Y/N")
    expenseTypeName: str | None = Field(default=None, description="경비유형 표시명")
    relatedArticleHint: list[str] = Field(default_factory=list, description="조항 힌트(참고용, 항상 배열)")
    relatedArticleHintUsage: str | None = Field(default=None, description="HINT_ONLY 고정")
    sourceSystem: str | None = Field(default=None, description="출처 시스템")
    sourceTimestamp: str | None = Field(default=None, description="출처 생성시각")
    schemaVersion: str | None = Field(default=None, description="payload 스키마 버전")
    normalizationFlags: dict[str, Any] | None = Field(default=None, description="정규화 메타")
    dataQuality: dict[str, Any] | None = Field(default=None, description="입력 품질 메타")

    @field_validator("budgetExceeded", mode="before")
    @classmethod
    def coerce_budget_exceeded_request(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return "Y" if v else "N"
        if isinstance(v, str):
            s = v.strip().upper()
            return "Y" if s == "Y" else "N" if s == "N" else s or None
        return None


class ScreenBatchItem(BaseModel):
    """배치 스크리닝 1건. BE 필드 정확히 파싱. v3.0: hrStatus, mccCode, mccName, budgetExceeded 지원."""
    caseId: str | None = Field(default=None, description="케이스 ID (응답 매핑용 권장)")
    tenantId: int | None = Field(default=None, description="테넌트 ID")
    voucherKey: str | None = Field(default=None, description="전표키(bukrs-belnr-gjahr)")
    bukrs: str | None = Field(default=None, description="회사코드")
    belnr: str | None = Field(default=None, description="전표번호")
    gjahr: str | None = Field(default=None, description="회계연도")
    buzei: str | None = Field(default=None, description="전표행")
    amount: float | None = Field(default=None, description="전표 금액 (숫자 또는 숫자 문자열)")
    currency: str | None = Field(default=None, description="통화코드")
    occurredAt: str | None = Field(default=None, description="발생 시각 (ISO_DATE_TIME)")
    timezone: str | None = Field(default=None, description="타임존")
    expenseType: str | None = Field(default=None, description="경비 유형")
    expenseTypeName: str | None = Field(default=None, description="경비 유형명")
    merchantName: str | None = Field(default=None, description="가맹점명")
    merchantId: str | None = Field(default=None, description="가맹점 ID")
    caseType: str | None = Field(default=None, description="백엔드 분류 유형 (camelCase)")
    case_type: str | None = Field(default=None, description="백엔드 분류 유형 (snake_case)")
    hrStatus: str | None = Field(default=None, description="근태 상태: WORKING, VACATION, OFF 등 (v3.0)")
    hrStatusRaw: str | None = Field(default=None, description="근태 원본 상태")
    mccCode: str | None = Field(default=None, description="가맹점 업종 코드 (v3.0)")
    mccCodeRaw: str | None = Field(default=None, description="가맹점 업종 코드 원본")
    mccName: str | None = Field(default=None, description="가맹점 업종명 (v3.0)")
    mccRiskCategory: str | None = Field(default=None, description="MCC 위험도")
    budgetExceeded: str | None = Field(default=None, description="예산 초과 여부 Y/N (v3.0). BE가 boolean으로 보낼 수 있음: true→Y, false→N")
    budgetExceededFlag: str | None = Field(default=None, description="예산 초과 플래그 Y/N")
    isHoliday: bool | None = Field(default=None, description="휴일 여부")
    holidayType: str | None = Field(default=None, description="휴일 유형")
    isWeekendAllowed: str | None = Field(default=None, description="주말 허용 여부 Y/N")
    relatedArticleHint: list[str] = Field(default_factory=list, description="조항 힌트 배열(항상 배열)")
    relatedArticleHintUsage: str | None = Field(default=None, description="HINT_ONLY")
    sourceSystem: str | None = Field(default=None, description="출처 시스템")
    sourceTimestamp: str | None = Field(default=None, description="출처 생성시각")
    schemaVersion: str | None = Field(default=None, description="스키마 버전")
    normalizationFlags: dict[str, Any] | None = Field(default=None, description="정규화 메타")
    dataQuality: dict[str, Any] | None = Field(default=None, description="입력 품질 메타")

    @field_validator("budgetExceeded", mode="before")
    @classmethod
    def coerce_budget_exceeded_batch(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return "Y" if v else "N"
        if isinstance(v, str):
            s = v.strip().upper()
            return "Y" if s == "Y" else "N" if s == "N" else s or None
        return None

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v: Any) -> float | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return None

    @field_validator("relatedArticleHint", mode="before")
    @classmethod
    def coerce_related_article_hint(cls, v: Any) -> list[str] | None:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        s = str(v).strip()
        return [s] if s else []

    @field_validator("mccRiskCategory", mode="before")
    @classmethod
    def normalize_mcc_risk_category(cls, v: Any) -> str | None:
        if v is None:
            return "UNKNOWN"
        s = str(v).strip().upper()
        if s in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            return s
        return "UNKNOWN"


@router.post("/screen")
async def detect_screen(
    body: ScreenRequest,
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
) -> dict[str, Any]:
    """
    Pre-Analysis Screening — 전표 첫인상 분류.

    정밀 분석(Analysis Run) 전, 찰나에 전표를 스캔하여 caseType, severity, reasonText, score를 반환합니다.
    시간+업종+금액 조합으로 위험 테마를 판단합니다.

    - **caseId**: 필수. get_case로 전표 데이터 조회 후 스크리닝.
    - body에 amount, occurredAt, expenseType 등이 있으면 정규화 결과에 병합하여 LLM 문맥에 반영합니다.
    """
    case_id = (body.caseId or "").strip()
    if not case_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="caseId is required")

    logger.info(
        "Aura detect_screen called: case_id=%s (BE가 이 로그가 보이면 실제로 Aura를 호출한 것)",
        case_id,
    )
    tenant = tenant_id or "1"
    trace_id = f"trace-screen-{case_id}"
    set_request_context(
        tenant_id=tenant,
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=trace_id,
        case_id=case_id,
    )

    voucher: dict[str, Any] = {}
    try:
        raw = await get_case.ainvoke({"caseId": case_id})
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict) and data.get("error"):
            logger.warning("detect_screen get_case error case_id=%s res=%s", case_id, data.get("error"))
            voucher = {"amount": None, "keys": {}}
        else:
            voucher = _normalize_get_case_response(data)
    except Exception as e:
        logger.warning("detect_screen get_case failed case_id=%s: %s", case_id, e)
        voucher = {"amount": None, "keys": {}}

    # BE가 보낸 필드로 보강
    if body.amount is not None:
        voucher["amount"] = body.amount
        voucher["totalAmount"] = body.amount
    if body.occurredAt is not None:
        voucher["occurredAt"] = body.occurredAt
    if body.expenseType is not None:
        voucher["expenseType"] = body.expenseType
    if body.merchantName is not None:
        voucher["merchantName"] = body.merchantName
    if body.case_type is not None or body.caseType is not None:
        voucher["case_type"] = body.case_type or body.caseType
    if body.hrStatus is not None:
        voucher["hrStatus"] = body.hrStatus
    if body.hrStatusRaw is not None:
        voucher["hrStatusRaw"] = body.hrStatusRaw
    if body.mccCode is not None:
        voucher["mccCode"] = body.mccCode
    if body.mccCodeRaw is not None:
        voucher["mccCodeRaw"] = body.mccCodeRaw
    if body.mccName is not None:
        voucher["mccName"] = body.mccName
    if body.mccRiskCategory is not None:
        voucher["mccRiskCategory"] = body.mccRiskCategory
    if body.budgetExceeded is not None:
        voucher["budgetExceeded"] = body.budgetExceeded
    if body.budgetExceededFlag is not None:
        voucher["budgetExceededFlag"] = body.budgetExceededFlag
    if body.isHoliday is not None:
        voucher["isHoliday"] = body.isHoliday
    if body.holidayType is not None:
        voucher["holidayType"] = body.holidayType
    if body.isWeekendAllowed is not None:
        voucher["isWeekendAllowed"] = body.isWeekendAllowed
    if body.expenseTypeName is not None:
        voucher["expenseTypeName"] = body.expenseTypeName
    if body.relatedArticleHint is not None:
        voucher["relatedArticleHint"] = body.relatedArticleHint
    if body.relatedArticleHintUsage is not None:
        voucher["relatedArticleHintUsage"] = body.relatedArticleHintUsage
    if body.sourceSystem is not None:
        voucher["sourceSystem"] = body.sourceSystem
    if body.sourceTimestamp is not None:
        voucher["sourceTimestamp"] = body.sourceTimestamp
    if body.schemaVersion is not None:
        voucher["schemaVersion"] = body.schemaVersion
    if body.normalizationFlags is not None:
        voucher["normalizationFlags"] = body.normalizationFlags
    if body.dataQuality is not None:
        voucher["dataQuality"] = body.dataQuality

    result = await run_screen(voucher, case_id)
    # BE 추적용: 응답의 caseType을 DB case_type에 반영했는지 확인할 때 이 로그와 매칭
    logger.info(
        "Aura detect_screen response: case_id=%s caseType=%s severity=%s score=%s (Aura는 caseType DEFAULT를 반환하지 않음)",
        case_id,
        result.get("caseType"),
        result.get("severity"),
        result.get("score"),
    )
    return result


@router.post("/screen-batch")
async def detect_screen_batch(
    request: Request,
    user: CurrentUser,
    tenant_id: TenantId,
    body: list[ScreenBatchItem] = Body(..., min_length=1, max_length=SCREEN_BATCH_MAX_ITEMS),
) -> dict[str, Any]:
    """
    Pre-Analysis Screening 배치 — 대량 전표 첫인상 분류.

    **Request Body: 순수 JSON 배열** `[ { "caseId", "amount", "occurredAt", "merchantName", ... }, ... ]`
    **Response: 객체** — FE가 판단 없이 즉시 포커싱할 수 있도록 최상단에 briefing_priority_case_id, briefing_insight 포함.
    - results: 요청과 동일 순서의 배열 (BE index 기반 매핑 1:1).
    - briefing_priority_case_id: 가장 주목해야 할 케이스 ID (score·severity 기준 1건).
    - briefing_insight: 해당 케이스에 대한 브리핑용 인사이트 문장 (단답형 아님).
    - occurredAt(ISO_DATE_TIME) 파싱 오류 건은 UNUSUAL_PATTERN으로 반환.
    """
    if not body:
        return {"results": [], "briefing_priority_case_id": None, "briefing_insight": None}
    if len(body) > SCREEN_BATCH_MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"배치 최대 {SCREEN_BATCH_MAX_ITEMS}건까지 허용됩니다.",
        )

    logger.info(
        "Aura detect_screen_batch called: n=%d case_ids=%s (BE가 이 로그가 보이면 실제로 Aura를 호출한 것)",
        len(body),
        [getattr(it, "caseId", None) or "" for it in body[:10]] + (["..."] if len(body) > 10 else []),
    )
    tenant = tenant_id or "1"
    set_request_context(
        tenant_id=tenant,
        user_id=user.user_id,
        auth_token=request.headers.get("Authorization"),
        trace_id=f"trace-screen-batch-{len(body)}",
    )

    vouchers: list[dict[str, Any]] = []
    case_ids: list[str] = []
    indices_date_parse_error: set[int] = set()

    for idx, it in enumerate(body):
        v: dict[str, Any] = {}
        if it.amount is not None:
            v["amount"] = v["totalAmount"] = it.amount
        if it.currency is not None:
            v["currency"] = it.currency
        if it.occurredAt is not None:
            if not _is_valid_iso_datetime(it.occurredAt):
                indices_date_parse_error.add(idx)
            v["occurredAt"] = it.occurredAt
        if it.timezone is not None:
            v["timezone"] = it.timezone
        if it.expenseType is not None:
            v["expenseType"] = it.expenseType
        if it.expenseTypeName is not None:
            v["expenseTypeName"] = it.expenseTypeName
        if it.merchantName is not None:
            v["merchantName"] = str(it.merchantName).strip() or None
        if it.merchantId is not None:
            v["merchantId"] = it.merchantId
        if it.case_type is not None or it.caseType is not None:
            v["case_type"] = it.case_type or it.caseType
        if it.hrStatus is not None:
            v["hrStatus"] = it.hrStatus
        if it.hrStatusRaw is not None:
            v["hrStatusRaw"] = it.hrStatusRaw
        if it.mccCode is not None:
            v["mccCode"] = it.mccCode
        if it.mccCodeRaw is not None:
            v["mccCodeRaw"] = it.mccCodeRaw
        if it.mccName is not None:
            v["mccName"] = it.mccName
        if it.mccRiskCategory is not None:
            v["mccRiskCategory"] = it.mccRiskCategory
        if it.budgetExceeded is not None:
            v["budgetExceeded"] = it.budgetExceeded
        if it.budgetExceededFlag is not None:
            v["budgetExceededFlag"] = it.budgetExceededFlag
        if it.isHoliday is not None:
            v["isHoliday"] = it.isHoliday
        if it.holidayType is not None:
            v["holidayType"] = it.holidayType
        if it.isWeekendAllowed is not None:
            v["isWeekendAllowed"] = it.isWeekendAllowed
        if it.relatedArticleHint is not None:
            v["relatedArticleHint"] = it.relatedArticleHint
        if it.relatedArticleHintUsage is not None:
            v["relatedArticleHintUsage"] = it.relatedArticleHintUsage
        if it.sourceSystem is not None:
            v["sourceSystem"] = it.sourceSystem
        if it.sourceTimestamp is not None:
            v["sourceTimestamp"] = it.sourceTimestamp
        if it.schemaVersion is not None:
            v["schemaVersion"] = it.schemaVersion
        if it.normalizationFlags is not None:
            v["normalizationFlags"] = it.normalizationFlags
        if it.dataQuality is not None:
            v["dataQuality"] = it.dataQuality
        for k in ("tenantId", "voucherKey", "bukrs", "belnr", "gjahr", "buzei"):
            val = getattr(it, k, None)
            if val is not None:
                v[k] = val
        vouchers.append(v)
        case_ids.append((it.caseId or "").strip())

    # 배치 스크리닝 실행 — 반환 배열 순서는 요청과 1:1 동일 보장
    result = await run_screen_batch(vouchers, case_ids)

    # occurredAt 파싱 오류 건은 UNUSUAL_PATTERN으로 덮어쓰기 (순서 유지)
    for idx in indices_date_parse_error:
        if idx < len(result):
            result[idx] = {
                "caseType": "UNUSUAL_PATTERN",
                "severity": "MEDIUM",
                "score": 50,
                "reasonText": DATE_PARSE_ERROR_REASON,
                "reasoningProcess": "occurredAt 형식 오류로 요일/공휴일 판단 불가. UNUSUAL_PATTERN으로 분류함.",
                **({"caseId": case_ids[idx]} if idx < len(case_ids) and case_ids[idx] else {}),
            }

    # 브리핑 우선순위: 가장 주목해야 할 케이스 1건 + 브리핑 인사이트 문장
    priority_index, briefing_priority_case_id = pick_briefing_priority(result, case_ids)
    briefing_insight: str | None = None
    if priority_index is not None and briefing_priority_case_id and priority_index < len(vouchers):
        briefing_insight = await generate_briefing_insight(
            result[priority_index],
            vouchers[priority_index],
            briefing_priority_case_id,
        )

    # BE 추적용: 응답 caseType 목록 (Aura는 DEFAULT를 반환하지 않음; DB가 DEFAULT면 BE 기본값 또는 미반영)
    _case_types = [r.get("caseType") for r in result]
    _to_log = _case_types[:15]
    _suffix = f" ... (+{len(result) - 15} more)" if len(result) > 15 else ""
    logger.info(
        "Aura detect_screen_batch response: n=%d caseTypes=%s%s (Aura는 caseType DEFAULT를 반환하지 않음)",
        len(result),
        _to_log,
        _suffix,
    )
    return {
        "results": result,
        "briefing_priority_case_id": briefing_priority_case_id,
        "briefing_insight": briefing_insight,
    }
