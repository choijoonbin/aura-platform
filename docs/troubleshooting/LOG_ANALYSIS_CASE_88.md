# 로그 분석: case_id=88 분석 런 (순서별)

아래는 `POST /aura/cases/88/analysis-runs` 후 스트림·분석·콜백까지의 로그를 **시간순**으로 정리한 해석입니다.

---

## 1. 분석 요청 수신 (13:03:23)

```
POST /aura/cases/88/analysis-runs - Client: 127.0.0.1
```

- **의미**: 백엔드/프론트가 **case_id=88** 로 분석 실행을 요청함.
- **결과**: 202 Accepted → 분석은 비동기로 진행되고, 클라이언트는 runId를 받아 스트림 URL로 연결.

---

## 2. 에이전트 선택 (13:03:24 ~ 13:03:34)

- `select_agent_for_request`: context에 `caseId`, `evidence` 전달.
- Synapse `GET /api/synapse/agents?discovery=true` → 5명 후보.
- LLM이 **finance_aura** 선택.
- `GET /api/v1/agents/config?agent_key=finance_aura` → doc_ids=[23] 등 설정 로드.

**정리**: case_id=88에 대해 finance_aura가 선택되었고, 문서 23번이 RAG에 바인딩됨.

---

## 3. 스트림 연결 (13:03:32)

```
case_analysis_stream: start consuming run_id=5f7c7a33-... case_id=88
GET /aura/cases/88/analysis/stream?runId=5f7c7a33-... → 200 OK
case_analysis_stream: first chunk sent
```

- **의미**: 클라이언트가 같은 **case_id=88**, 위에서 받은 **runId**로 스트림을 열었고, 첫 청크까지 전송됨.

---

## 4. 파이프라인 시작 (13:03:34)

```
audit_analysis start case_id=88 run_id=5f7c7a33-... body_evidence_keys=['evidence', 'ragRefs', 'document', 'partyIds', 'openItems', 'lineage', 'policies']
```

- **의미**: Aura가 **case_id=88**, 위 run_id로 분석을 시작함. body_evidence에는 evidence, document 등이 포함됨.

---

## 5. get_case 호출 및 응답 (13:03:34) — **금액 미수신 지점**

```
HTTP Request: GET http://localhost:8080/api/synapse/agent-tools/cases/88 "HTTP/1.1 200 OK"
get_case response case_id=88 belnr=None documentNumber=None amount=None totalAmount=None
```

- **의미**:
  - Aura는 **case_id=88**로 백엔드 **GET .../agent-tools/cases/88**만 호출함. (다른 ID 호출 없음)
  - 응답은 200 OK이나, Aura가 기대하는 **최상위 필드** `belnr`, `documentNumber`, `amount`, `totalAmount`가 **모두 없음(None)**.
- **결론**:
  - **금액이 “안 넘어온” 것은 맞음.**  
  - 원인은 **Aura가 잘못 요청한 것이 아니라**, 백엔드 **GET /api/synapse/agent-tools/cases/88** 응답에 다음 중 하나에 해당하는 상황으로 보는 것이 타당함.
    1. **필드 이름이 다름**: 예) `totalAmount` 대신 `amountInDocumentCurrency`, `belnr` 대신 `documentNo` 등 다른 키로 내려줌.
    2. **중첩 구조**: 예) `{ "data": { "amount": 109019, "belnr": "D2B6FC5" } }` 처럼 한 단계 안에 있어서, Aura는 현재 최상위만 보고 있음.
    3. **API 스펙상 해당 필드 미제공**: agent-tools 케이스 API가 전표번호·금액을 아예 안 내려주도록 되어 있음.

**다음 확인용 로그 (추가됨)**  
- 금액/전표번호가 없을 때, **실제 응답의 최상위 키 목록**을 로그에 남기도록 했음.  
- 다음 런에서는 예를 들어  
  `get_case response missing amount/belnr case_id=88 top_level_keys=[...]`  
  로그가 찍히므로, 백엔드가 사용하는 필드명/구조를 보고 Aura에서 해당 경로로 읽거나, 백엔드에서 `amount`/`belnr`(또는 documentNumber)를 최상위에 추가하는 방식으로 맞추면 됨.

---

## 6. 이후 파이프라인 (13:03:36 ~ 13:03:49)

- **EVIDENCE_GATHER**: thought_stream LLM 호출 시 Azure content filter 경고 → 독백 실패해도 파이프라인은 계속 진행.
- **get_case 재호출**: `GET .../agent-tools/cases/88` 한 번 더 (search_documents 등에서 case 조회 시).
- **RAG**: doc_ids=[23], 쿼리 결과 0건 → need_web_search=True → 외부 검색 수행.
- **open-items, lineage** 등 추가 조회 후, LLM reasonText(gpt-4o) 호출까지 정상 완료.

**정리**: get_case를 제외한 나머지 단계는 에러 없이 진행되었고, **사용된 케이스 데이터(금액 등)는 get_case 응답에서만 오기 때문에**, 그 응답에 금액이 없어서 이후 스코어/판단/콜백에 반영된 “금액”도 없거나 0으로 처리된 상태일 가능성이 큼.

---

## 7. 콜백 (13:03:49)

```
Callback sending: ... caseId=88 status=COMPLETED ... finalResult=<dict>
POST .../internal/aura/callback "HTTP/1.1 200 OK"
Callback ok
```

- **의미**: 분석이 COMPLETED로 끝났고, **case_id=88**에 대한 finalResult가 그대로 백엔드 콜백 URL로 전달됨.  
- finalResult 안의 금액/전표 정보는 **get_case에서 받은 값**만 사용하므로, 위 단계 5에서 amount/belnr가 비어 있었으면 콜백 payload에도 해당 필드가 비어 있거나 없을 수 있음.

---

## 8. 정리 표

| 순서 | 시각       | 내용 | 비고 |
|------|------------|------|------|
| 1 | 13:03:23 | POST /aura/cases/88/analysis-runs | case_id=88 요청 |
| 2 | 13:03:24~34 | 에이전트 선택 (finance_aura), 설정 로드 | doc_ids=[23] |
| 3 | 13:03:32 | 스트림 연결 (runId 일치) | 정상 |
| 4 | 13:03:34 | audit_analysis start case_id=88 | body_evidence 포함 |
| 5 | 13:03:34 | GET .../cases/88 → 200 OK, **amount/belnr 등 전부 None** | **금액 미수신** |
| 6 | 13:03:36~49 | thought_stream, RAG(0건), web_search, LLM reasonText | 정상 진행 |
| 7 | 13:03:49 | 콜백 전송 200 OK | case_id=88 유지 |

---

## 9. 권장 조치

1. **다음 분석 실행 후**  
   - `get_case response missing amount/belnr case_id=88 top_level_keys=...` 로그를 확인하여,  
     백엔드가 실제로 내려주는 **필드 이름·구조**를 확인.
2. **백엔드(Synapse/agent-tools)**  
   - `GET /api/synapse/agent-tools/cases/{caseId}` 응답에  
     전표 식별자(예: belnr/documentNumber)와 **금액(amount 또는 totalAmount)** 를  
     Aura가 읽는 이름으로 최상위에 넣거나,  
     중첩 구조라면 그 경로를 문서화해 주면, Aura에서 해당 경로로 파싱하도록 수정 가능.
3. **Aura**  
   - top_level_keys 로그로 확인한 키/구조에 맞춰  
     `case_data`에서 amount, belnr(또는 documentNumber)를 읽는 부분을 한 곳에서 보완하면,  
     동일 API 스펙으로도 금액이 분석·콜백까지 일관되게 전달됨.

이 문서는 “로그 순서대로 보면 금액이 왜 안 넘어오는지”와 “다음에 무엇을 확인하면 되는지”를 정리한 것입니다.
