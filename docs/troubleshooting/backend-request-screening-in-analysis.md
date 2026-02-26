# Aura 분석 Run 시 스크리닝 결과 전달 요청사항

## 배경

- Aura는 **스크리닝(screen-batch)** 결과와 **케이스 분석(analysis run)** 결과를 별도 API로 처리합니다.
- 분석 시 **스크리닝에서 판단한 caseType·reasonText**를 전달받지 않으면, Aura는 기본 위험 유형(예: DUPLICATE_INVOICE)으로 fallback하여 reasonText를 생성합니다.
- 그 결과, 휴일 사용(제9조) 등으로 스크리닝된 케이스가 분석 결과에서는 "중복 송장"으로 표시되는 문제가 발생했습니다.
- **분석 run 요청 시 또는 get_case 응답에 스크리닝 결과를 포함해 주시면** Aura가 해당 분류와 판단 요약에 맞춰 reasonText를 생성합니다.

---

## 요청사항 요약

1. **분석 run 요청 body**에 스크리닝 결과(`case_type`, `screening_reason_text`)를 포함해 주세요.
2. (선택) **get_case 응답**에도 동일 필드를 포함해 주시면, body에 누락된 경우에도 분석에 사용됩니다.

---

## 1. 분석 run 요청 시 body_evidence에 포함

**POST /aura/cases/{caseId}/analysis-runs** 호출 시, 요청 body 안의 **body_evidence**에 아래 필드를 포함해 주세요.

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `case_type` | string | 권장 | 스크리닝에서 반환한 6종 중 하나. 예: `HOLIDAY_USAGE`, `DUPLICATE_SUSPECT`, `SPLIT_PAYMENT`, `PRIVATE_USE_RISK`, `LIMIT_EXCEED`, `UNUSUAL_PATTERN` |
| `screening_reason_text` | string | 권장 | 스크리닝에서 생성한 판단 요약 문장. 예: "제9조(공휴일·휴무일 사용 제한)에 따라, hrStatus가 LEAVE인 상태에서의 결제로 위반 의심." |

**예시 (변경 후 기대 형식)**

```json
{
  "body_evidence": {
    "doc_id": "1000-5105012345-2025",
    "item_id": "001",
    "case_type": "HOLIDAY_USAGE",
    "screening_reason_text": "제9조(공휴일·휴무일 사용 제한)에 따라, hrStatus가 LEAVE인 상태에서의 결제로 위반 의심."
  }
}
```

- Aura는 **camelCase**(`caseType`, `reasonText`)도 동일하게 인식합니다.  
  기존 스키마가 `caseType`/`reasonText`라면 그대로 보내셔도 됩니다.
- `case_type`만 있고 `screening_reason_text`가 없어도 동작하며, 둘 다 있으면 분석 품질이 가장 좋습니다.

---

## 2. (선택) get_case 응답에 포함

Aura가 **GET get_case (케이스 상세)** 를 호출할 때 응답에도 동일한 스크리닝 결과를 넣어 주시면, body_evidence에 값이 없을 때 보조로 사용합니다.

- **caseType** 또는 **case_type**: 스크리닝 caseType (6종 중 하나).
- **reasonText** 또는 **screening_reason_text**: 스크리닝 판단 요약 문장.

예: CaseDetailDto 등 응답 DTO의 최상위 또는 `data` 내부에  
`caseType`(또는 `case_type`), `reasonText`(또는 `screening_reason_text`) 필드 포함.

---

## 3. 스크리닝 결과의 출처

- **POST /aura/detect/screen-batch** 응답에서 케이스별로 내려주는  
  `caseType`, `reasonText`(및 필요 시 `severity`, `score`)를  
  해당 케이스 저장 시 함께 persist 하시고,  
  이후 **분석 run 요청 body_evidence** 및/또는 **get_case 응답**에 위 필드명으로 담아 주시면 됩니다.

---

## 4. 검증 방법

- 분석 run 후 Aura 로그에서 아래 메시지가 나오면 정상 반영된 것입니다.
  - `audit_analysis body_evidence: case_id=... evidence_caseType=HOLIDAY_USAGE has_reasonText=True`
  - `audit_analysis: using screening caseType from get_case/evidence case_id=... caseType=HOLIDAY_USAGE`
- 반대로 아래와 같으면 아직 스크리닝 결과가 전달되지 않은 상태입니다.
  - `evidence_caseType=None has_reasonText=False`
  - `risk_type from case_data fallback ... risk_type=DUPLICATE_INVOICE (no screening_case_type)`

---

## 5. 문의

- Aura 쪽 필드명·형식 추가 문의: [담당자/팀 명시]
- BE 스키마·API 스펙 조율이 필요하면 위 예시를 기준으로 협의 가능합니다.
