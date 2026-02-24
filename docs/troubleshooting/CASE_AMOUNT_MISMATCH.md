# 전표 금액 불일치 원인 추적 (case_id vs get_case 응답)

분석 결과로 백엔드에 전달된 금액이 실제 전표 금액과 다를 때, **요청이 잘못된 것인지 / 백엔드가 잘못 준 것인지** Aura 로그로 확인하는 방법입니다.

---

## 1. 데이터 흐름 요약

- **Aura가 쓰는 금액의 유일한 출처**: Synapse(백엔드) **GET /cases/{caseId}** 응답입니다.
- Aura는 **요청으로 받은 `case_id`만** 사용해 `get_case.ainvoke({"caseId": case_id})`를 호출합니다.
- 파이프라인 내부에서 **다른 case_id로 재조회하거나, 다른 전표 데이터를 섞어 쓰는 로직은 없습니다.**

따라서:

- **백엔드가 Aura에 넘긴 `case_id`**와  
- **백엔드 GET /cases/{caseId}가 그 `case_id`에 대해 반환한 belnr(전표번호)·amount(금액)**  
이 일치하는지 보면, “요청이 잘못됐는지 / 백엔드가 잘못 줬는지” 구분할 수 있습니다.

---

## 2. Aura 로그로 확인하는 방법

분석 실행 시 아래 로그가 남습니다.

### (1) 분석 시작 시 — “어떤 case_id로 요청이 들어왔는지”

```
audit_analysis start case_id=<값> run_id=<값> body_evidence_keys=<키 목록>
```

- **case_id**: 백엔드/프론트가 **이번 분석에 넘긴 케이스 ID** (예: 숫자 ID 또는 전표키).
- 여기서 `case_id`가 의도한 전표(D2B6FC5)에 대응하는 ID가 맞는지 **백엔드·프론트에서 먼저 확인**해야 합니다.

### (2) get_case 응답 직후 — “해당 case_id에 대해 백엔드가 뭘 돌려줬는지”

```
get_case response case_id=<값> belnr=<값> documentNumber=<값> amount=<값> totalAmount=<값>
audit_analysis case_identifiers case_id=<값> belnr_or_docNo=<값> amount_used=<값>
```

- **belnr / documentNumber**: 백엔드가 **이 case_id에 대해** 내려준 전표번호입니다.  
  - D2B6FC5 전표를 기대했다면 여기가 `D2B6FC5`(또는 동일 식별자)인지 확인합니다.
- **amount / totalAmount**: 백엔드가 내려준 금액입니다.  
  - 실제 D2B6FC5 금액이 109,019.00 이라면 여기가 109019 또는 109019.00 인지 확인합니다.

**해석:**

| 로그에서 보이는 값 | 의미 |
|-------------------|------|
| belnr/documentNumber = D2B6FC5, amount = 109019(또는 109019.00) | 백엔드가 **해당 case_id**에 대해 D2B6FC5·109019를 정상 반환. 그럼 **Aura가 보낸 결과도 이 금액 기준**입니다. 이때 백엔드 UI에 1,200,000이 보인다면 **저장/표시 측(백엔드·FE)** 에서 다른 전표 금액을 쓰고 있을 가능성이 큼. |
| belnr/documentNumber = 다른 전표번호 또는 amount = 1,200,000 | **GET /cases/{caseId}**가 **이 case_id에 대해** 다른 전표 데이터를 반환한 것입니다. → **백엔드 CaseQueryService(또는 Synapse) 쪽**에서 case_id별로 잘못된 데이터를 내려주는지 확인 필요. |
| case_id 자체가 D2B6FC5가 아닌 다른 ID(예: 다른 케이스 ID) | **요청 단계**에서 잘못된 case_id가 Aura로 넘어온 것입니다. → **백엔드/프론트**에서 “D2B6FC5 전표 분석” 요청 시 어떤 case_id를 넣어 호출하는지 확인 필요. |

---

## 3. 확인 순서 (체크리스트)

1. **Aura 로그에서 `audit_analysis start case_id=...` 확인**  
   - D2B6FC5 전표 분석을 의도했다면, 이때 찍힌 `case_id`가 그 전표에 해당하는 ID가 맞는지 백엔드/프론트와 대조합니다.

2. **같은 run의 `get_case response` / `audit_analysis case_identifiers` 확인**  
   - `belnr`(또는 documentNumber) = D2B6FC5(또는 동일 식별자), `amount`(또는 totalAmount) = 109019(또는 109019.00) 인지 봅니다.

3. **판단**  
   - 로그에 D2B6FC5·109019가 맞게 나오면 → Aura는 올바른 데이터로 분석·콜백했고, **백엔드 저장/표시 또는 다른 케이스 매핑**을 의심합니다.  
   - 로그에 다른 전표번호 또는 1,200,000이 나오면 → **백엔드 GET /cases/{caseId}**가 해당 case_id에 대해 잘못된 전표를 반환한 것이므로, **백엔드(Synapse/CaseQueryService)** 확인이 필요합니다.  
   - 분석 시작 로그의 case_id가 이미 다른 케이스 ID면 → **요청 측(백엔드·프론트)**에서 잘못된 case_id를 넘긴 것입니다.

---

## 4. Aura 측에서 추가로 할 수 있는 것

- **금액/전표번호는 Aura가 생성·가공하지 않고**, get_case 응답과 그로 만든 `evidence`·`decision_reason` 등에 **그대로 반영**합니다.
- 콜백 payload의 `evidence` 안 첫 번째 항목(`source: get_case`)에 `keys.amount` 등이 들어가며, 이는 **get_case 응답에서 온 값**입니다.
- 따라서 **동일 run의 get_case 로그**와 **콜백 payload의 evidence[0].keys**를 비교하면, “Aura가 어떤 금액을 보고 분석·전달했는지” 한 번 더 검증할 수 있습니다.

이 문서는 **D2B6FC5 전표(실제 109,019.00)인데 분석 결과에 1,200,000이 나오는 경우**처럼, 전표 금액 불일치가 발생했을 때 위 순서로 원인(요청 vs 백엔드 응답)을 좁히기 위한 가이드입니다.
