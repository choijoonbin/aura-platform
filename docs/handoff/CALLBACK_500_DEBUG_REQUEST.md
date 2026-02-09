# Aura 콜백 500 오류 — BE 확인 요청

> **대상**: Synapse 백엔드 개발팀  
> **작성일**: 2026-02-09  
> **배경**: Aura → BE 콜백 호출 시 500 Internal Server Error 발생

---

## 1. 발생 상황

| 시점 | 이벤트 |
|------|--------|
| 분석 트리거 | 202 Accepted |
| 파이프라인 | get_case, documents, open-items, lineage, LLM 정상 |
| **콜백** | **500** (3회 재시도 모두 실패) |

### BE 응답 예시
```json
{
  "status": "ERROR",
  "message": "내부 서버 오류가 발생했습니다.",
  "errorCode": "E1000",
  "traceId": "688ea51e-a530-4085-86d8-e20b93e3b3a2",
  "gatewayRequestId": "7eed24..."
}
```

---

## 2. Aura 콜백 스펙

**POST** `{DWP_GATEWAY_URL}/api/synapse/internal/aura/callback`

### Request Body (일반)

```json
{
  "runId": "f1b200de-cf62-473a-bc77-fe651464ba4a",
  "caseId": "85115",
  "status": "COMPLETED",
  "finalResult": {
    "score": 0.67,
    "severity": "MEDIUM",
    "reasonText": "케이스 85115: DUPLICATE_INVOICE 위험 유형...",
    "confidence": {
      "anomalyScore": 0.5,
      "patternMatch": 0.7,
      "ruleCompliance": 0.85,
      "overall": 0.67
    },
    "evidence": [{"type": "CASE", "source": "get_case", "caseId": "85115", "keys": {...}}],
    "ragRefs": [...],
    "similar": [{"caseId": "85115-sim-1", "similarity": "vendor", ...}],
    "proposals": [
      {
        "type": "PAYMENT_BLOCK",
        "riskLevel": "HIGH",
        "rationale": "위험 점수에 따른 추가 검토 권고",
        "payload": {"caseId": "85115", "action": "block"},
        "createdAt": "2026-02-09T21:21:14.000Z",
        "requiresApproval": true
      },
      {
        "type": "REQUEST_INFO",
        "riskLevel": "MEDIUM",
        "rationale": "거래처 확인 요청",
        "payload": {"caseId": "85115"},
        "createdAt": "2026-02-09T21:21:14.000Z",
        "requiresApproval": false
      }
    ]
  }
}
```

### 필드 타입

| 필드 | 타입 | 설명 |
|------|------|------|
| runId | string | UUID |
| caseId | string | path의 caseId (예: "85115") |
| status | string | COMPLETED \| FAILED |
| finalResult | object | status=COMPLETED 시 필수 |
| finalResult.score | number | 0~1 |
| finalResult.severity | string | LOW \| MEDIUM \| HIGH |
| finalResult.reasonText | string | |
| finalResult.confidence | object | |
| finalResult.evidence | array | |
| finalResult.ragRefs | array | |
| finalResult.similar | array | |
| finalResult.proposals | array | |
| proposals[].type | string | |
| proposals[].riskLevel | string | |
| proposals[].rationale | string | |
| proposals[].payload | object | |
| proposals[].createdAt | string | ISO 8601 |
| proposals[].requiresApproval | boolean | |

---

## 3. BE 확인 요청

1. **traceId로 로그 검색**  
   - `688ea51e-a530-4085-86d8-e20b93e3b3a2` 등으로 콜백 처리 시점 스택 트레이스 확인

2. **콜백 handler 예외 원인**  
   - DB 저장 시 null/타입 불일치  
   - caseId Long 매핑 (Aura는 string "85115" 전송)  
   - proposals JSON 역직렬화

3. **AuraCallbackPayload 스키마**  
   - Aura flat 구조와 BE 모델 일치 여부 재확인

---

## 4. BE 확인 결과 (2026-02-09)

| 이슈 | 원인 | 조치 |
|------|------|------|
| 400 (X-Tenant-ID) | Gateway가 콜백 경로에 X-Tenant-ID 필수 검증 | `/api/synapse/internal/` 제외 경로 추가 |
| 400 (UnrecognizedPropertyException caseId) | Aura가 caseId 전송, BE DTO에 없음 | `@JsonIgnoreProperties(ignoreUnknown = true)` 추가 |
| 500 (ClassCastException confidence) | confidence ObjectNode 강제 캐스팅 | JsonNode 그대로 사용 |
| createdAt 파싱 실패 | Python 마이크로초/타임존 없는 형식 | LenientInstantDeserializer 적용 |
| JSON parse 500 | HttpMessageNotReadableException 미처리 | GlobalExceptionHandler 400 핸들러 추가 |

**결과**: 콜백 정상 수신·처리 확인. Aura 측 추가 작업 불필요.

---

## 5. 참조

- `docs/phase2/PHASE2_TRIGGER_STANDARD.md` — 콜백 스펙
- `core/analysis/callback.py` — Aura 콜백 전송 로직
