# AI Screening Aura ↔ Backend 연동 규격 (상세 구현 가이드 v1.1)

## 1. Aura 엔드포인트

| 메서드 | 경로 | 용도 |
|--------|------|------|
| POST | `/aura/detect/screen` | 단건 전표 첫인상 스캔 (caseId 기반 get_case 후 스크리닝) |
| POST | `/aura/detect/screen-batch` | 대량 전표 배치 스캔 (**50건 단위** 호출 권장) |

- Base URL: API Gateway 경유 시 Gateway 기준.
- 인증: `Authorization: Bearer ...`, `X-Tenant-ID` 등 기존 Aura 호출과 동일.
- **배치 전용 S2S 인증**: `POST /aura/detect/screen-batch` 는 **X-Internal-Service-Key** 헤더로도 인증 가능합니다. Aura에 환경 변수 `AURA_INTERNAL_API_KEY` 가 설정되어 있고, BE가 해당 값을 `X-Internal-Service-Key` 로 보내면 JWT 없이 호출할 수 있습니다. (내부 네트워크에서만 사용 권장, 키 외부 노출 금지)

---

## 2. DRIVER_TYPE (caseType) — 6종 고정

BE 코드 테이블(DB Migration)은 아래 **6가지 비즈니스 코드**로 동기화해야 합니다.

| 코드 | 설명 |
|------|------|
| `HOLIDAY_USAGE` | 휴일/심야 사적 유용 의심 |
| `DUPLICATE_SUSPECT` | 중복 청구 및 분할 결제 의심 |
| `SPLIT_PAYMENT` | 한도 우회를 위한 전표 쪼개기 의심 |
| `PRIVATE_USE_RISK` | 가맹점 성격이 업무와 무관 (유흥, 취미 등) |
| `LIMIT_EXCEED` | 사내 지출 한도 및 가이드라인 초과 |
| `UNUSUAL_PATTERN` | 과거 패턴과 다른 이상 거래 |

- Aura는 위 6종 외 값을 반환하지 않으며, 인식 불가 시 `UNUSUAL_PATTERN`으로 내려줍니다.
- **`caseType = "DEFAULT"`**: Aura는 **절대 "DEFAULT"를 반환하지 않습니다.** DB에 `case_type = "DEFAULT"`가 있다면, BE의 기본값이 들어갔거나 Aura 호출 전/실패 시 해당 필드를 갱신하지 않아 기존값이 유지된 경우입니다. 케이스 생성 시 (1) 실제로 `POST /aura/detect/screen` 또는 `screen-batch`를 호출했는지, (2) 응답의 `caseType`을 DB `case_type`에 반영했는지를 로그로 추적하는 것을 권장합니다.

**Aura 측 로그 (BE 추적용)**  
- 단건: 요청 시 `Aura detect_screen called: case_id=...`, 응답 시 `Aura detect_screen response: case_id=... caseType=...`  
- 배치: 요청 시 `Aura detect_screen_batch called: n=... case_ids=...`, 응답 시 `Aura detect_screen_batch response: n=... caseTypes=[...]`  
동일 요청에서 위 로그가 보이면 Aura는 호출된 것이고, 반환된 `caseType`을 DB에 반영하면 됩니다.

---

## 3. 단건 스크리닝 `POST /aura/detect/screen`

**Request (JSON)**

```json
{
  "caseId": "필수",
  "amount": null,
  "occurredAt": null,
  "expenseType": null,
  "merchantName": null,
  "riskTypeKey": null
}
```

- `caseId` 필수. 나머지는 선택이며, 있으면 get_case 결과에 병합되어 스크리닝 문맥에 반영됩니다.

**Response (JSON)** — BE에서 해당 케이스 1건 매핑용

```json
{
  "caseType": "HOLIDAY_USAGE",
  "severity": "HIGH",
  "score": 92,
  "reasonText": "휴일 심야 시간대에 유흥 업종에서 발생한 고액 결제로 사적 유용 가능성이 매우 높습니다.",
  "reasoningProcess": "2026-01-04은 일요일임을 확인하였으며, 사용자 근태 상태(VACATION)와 결합하여 제9조 위반으로 판정함.",
  "caseId": "요청에서 보낸 caseId"
}
```

- **reasoningProcess** (v3.1, 선택): 자율 일자 판단 근거 및 위반 조항 결합 논리. LLM이 생성한 경우에만 포함됩니다.

---

## 4. 배치 스크리닝 `POST /aura/detect/screen-batch`

**Request Body: 순수 JSON 배열** (객체 래퍼 없음). BE는 **index 기반**으로 응답을 매핑하므로 순서가 중요합니다.

```json
[
  {
    "caseId": "uuid-1",
    "amount": 100000,
    "occurredAt": "2025-02-20T22:30:00",
    "expenseType": "MEAL",
    "merchantName": "○○ 유흥주점",
    "riskTypeKey": null
  },
  { "caseId": "uuid-2", "amount": 50000, "occurredAt": "2025-02-20T22:35:00", "merchantName": "○○ 유흥주점" }
]
```

- **Body**: `[...]` 형태로 직접 전송 (1~100건, **50건 단위** 호출 권장).
- `amount`: 숫자 또는 숫자 문자열 가능. `occurredAt`: **ISO_DATE_TIME** (파싱 오류 시 해당 건은 `UNUSUAL_PATTERN`으로 반환).
- `caseId`: 응답 매핑 및 AgentCase 저장 시 권장.

**Response (JSON 객체)** — **요청 배열과 1:1 동일 순서의 results** (index 기반 매핑 보장). FE가 판단 없이 즉시 포커싱할 수 있도록 최상단에 `briefing_priority_case_id`, `briefing_insight` 포함.

```json
{
  "results": [
    {
      "caseType": "HOLIDAY_USAGE",
      "severity": "HIGH",
      "score": 92,
      "reasonText": "휴일 심야 시간대에 유흥 업종에서 발생한 고액 결제로 사적 유용 가능성이 매우 높습니다.",
      "reasoningProcess": "2026-01-04은 일요일임을 확인하였으며, 사용자 근태(VACATION)와 결합하여 제9조 위반으로 판정함.",
      "caseId": "uuid-1"
    },
    {
      "caseType": "SPLIT_PAYMENT",
      "severity": "MEDIUM",
      "score": 78,
      "reasonText": "동일 가맹점에서 10분 내 유사 금액 2건 결제로 분할 결제 의심.",
      "caseId": "uuid-2"
    }
  ],
  "briefing_priority_case_id": "uuid-1",
  "briefing_insight": "휴일 심야 시간대에 유흥 업종에서 발생한 고액 결제로 사적 유용 가능성이 매우 높습니다."
}
```

- `results`: 기존과 동일한 스크리닝 결과 배열. **요청 배열의 i번째 요소 = results[i]** (1:1 보장). v3.1부터 각 항목에 **reasoningProcess**(선택)가 포함될 수 있음.
- `briefing_priority_case_id`: **가장 주목해야 할 케이스 ID** 1건. score 최대 → 동점이면 severity HIGH 우선. FE는 이 ID로 즉시 포커싱 가능.
- `briefing_insight`: 위 케이스에 대한 **브리핑용 인사이트 문장** 한 개. "분석 완료" 같은 단답이 아닌, 전체 문맥을 관통하는 문장.
- `caseType`: 위 6종 중 하나.
- `severity`: `LOW` | `MEDIUM` | `HIGH` (금액+시각+업종 조합으로 판단).
- `score`: **0~100 정수** (백분율 위험 점수).
- `reasonText`: 한국어 한 문장. **occurredAt 파싱 오류 건**은 `"전표 일시(occurredAt) 파싱 오류로 이상 거래로 분류합니다."`로 고정.
- `caseId`: 요청 항목에 있으면 그대로 반환.
- **순서**: 응답 results 배열의 i번째 요소는 요청 배열의 i번째 전표에 대응 (1:1 보장).

---

## 5. Backend 측 작업 요약 (지시서 기준)

1. **Chunking**: 전표를 한 건씩 보내지 말고 **50건 단위**로 묶어 `POST /aura/detect/screen-batch` 호출.
2. **하드코딩 제거**: `DetectBatchService` 등에서 금액 기반 severity/score 산출 로직 **전면 삭제**, Aura 응답 값을 그대로 AgentCase(또는 동일 엔티티)에 매핑.
3. **코드 테이블 동기화**: DRIVER_TYPE 그룹 코드를 위 **6가지**로 DB Migration.
4. **비동기 알림**: 배치 완료 시 기존 WebSocket 채널 `workbench:case:action`으로 **"전체 탐지 완료"** 메시지 발행.

---

## 6. Aura 판단 로직 요약 (참고)

- **[금액 + 시각 + 가맹점 업종]** 결합 분석. 금액만으로 severity/score 산출하지 않음.
- **분할 결제**: 동일 가맹점에서 짧은 시간(예: 10분 내) + 유사 금액 반복 → `SPLIT_PAYMENT`로 분류하고 score를 높게 부여.
