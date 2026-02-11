# Aura RAG 참조 로그 형식 (백엔드 연동)

Aura에서 변경·추가된 RAG 참조 관련 로그 형식을 정리합니다. 백엔드(Synapse)는 **Agent Stream 수신** 및 **콜백 finalResult** 처리 시 아래 스키마를 참고하면 됩니다.

---

## 1. 전달 경로 요약

| 경로 | 용도 | RAG 관련 필드 |
|------|------|----------------|
| **POST /api/synapse/agent/events** | Agent Stream (실시간 로그) → `agent_activity_log` 적재 | `payload.evidence.ragContributions`, `payload.evidence.policy_reference` |
| **POST 콜백 (분석 완료)** | Phase2/Phase3 완료 시 `finalResult` 전달 | `finalResult.ragRefs` (기존), 확장 시 `finalResult.ragContributions` (선택) |

---

## 2. Agent Stream 이벤트 (agent_activity_log 수신)

Aura가 `POST /api/synapse/agent/events`로 보내는 각 이벤트는 다음 형태입니다.

```json
{
  "events": [
    {
      "tenantId": "1",
      "timestamp": "2026-02-11T12:00:00Z",
      "stage": "ANALYZE",
      "message": "RAG queried: 5 docs, topK=10, 120ms",
      "caseKey": "CS-2026-0001",
      "caseId": "85116",
      "severity": "INFO",
      "traceId": "trace-xxx",
      "actionId": null,
      "payload": {
        "title": "추론·분석",
        "reasoning": "RAG queried: 5 docs, topK=10, 120ms",
        "evidence": {
          "docIds": ["1000/1900000001/2024", "1000/1900000002/2024"],
          "topK": 10,
          "latencyMs": 120,
          "bukrs": "1000",
          "belnr": "1900000001",
          "gjahr": "2024",
          "resource_key": "1000/1900000001/2024",
          "ragContributions": [
            {
              "refId": "ref-1",
              "sourceType": "DOCUMENT",
              "sourceKey": "1000/1900000001/2024",
              "title": "비용 한도 관련 규정",
              "location": "규정 제3조 2항",
              "excerpt": "..."
            }
          ],
          "policy_reference": {
            "configSource": "dwp_aura.sys_monitoring_configs",
            "profileName": "policy_profile"
          }
        },
        "status": "SUCCESS"
      }
    }
  ]
}
```

### 2.1 payload.evidence 추가 필드 (신규)

- **ragContributions** (array, 선택)  
  RAG 검색 시 문서별 **구체적 참조 정보**.  
  - `refId`: 참조 ID (예: ref-1)  
  - `sourceType`: `"DOCUMENT"` 등  
  - `sourceKey`: 문서 키 (docKey, id, belnr 등)  
  - **title** (선택): 문서/규정 제목 (예: "비용 한도 관련 규정")  
  - **excerpt** (선택): 발췌문(400자 이내). **WorkbenchThoughtChain 인용 클릭 시 원문 표시용.**  
  - **article** (선택): 규정 조문 표기 (예: "제5조 2항"). **FE WorkbenchThoughtChain 인용 클릭 시 원문과 함께 표시할 규정 식별자.**  
  - **location** (선택): 규정 위치 (예: "규정 제3조 2항")  
  - FE 동기화: 인용 클릭 시 원문 표시를 위해 **{ title, excerpt, article }** 구조로 통일.

- **policy_reference** (object, 선택)  
  추론 시 참조한 정책/임계치 출처.  
  - `configSource`: 예) `"dwp_aura.sys_monitoring_configs"`  
  - `profileName`: 예) `"policy_profile"`, `"default"`

- **SAP 원천 식별자** (Phase 3):  
  `bukrs`, `belnr`, `gjahr`, `resource_key` 는 기존과 동일하게 evidence 내에 포함됩니다.

### 2.2 백엔드 저장 시 권장

- `agent_activity_log.payload_json` (또는 동일 용도의 metadata 컬럼)에 위 `payload` 객체 전체를 저장.
- 타임라인/필터용으로 `payload.evidence.ragContributions`, `payload.evidence.policy_reference` 를 파싱해 사용 가능.
- `ragContributions[].location`, `title` 로 “규정 제3조 2항(비용 한도) 참조”와 같은 문구를 FE에서 조합 가능.

---

## 3. 기존 콜백 finalResult.ragRefs (유지)

분석 완료 콜백의 `finalResult.ragRefs` 는 **기존 스키마 유지**합니다.

```json
{
  "finalResult": {
    "score": 75,
    "severity": "MEDIUM",
    "reasonText": "...",
    "confidence": { "overall": 0.75 },
    "evidence": [...],
    "ragRefs": [
      {
        "refId": "ref-1",
        "sourceType": "DOCUMENT",
        "sourceKey": "DOC-0",
        "excerpt": "...",
        "score": 0.9
      }
    ],
    "similar": [],
    "proposals": []
  }
}
```

- **ragRefs**: `refId`, `sourceType`, `sourceKey`, `excerpt`, `score` (Phase2/Phase3 기존 형식).
- 백엔드는 기존대로 `finalResult.ragRefs` 를 저장·노출하면 됩니다.

---

## 4. 확장 시 선택 사항 (콜백에 ragContributions 넣는 경우)

나중에 **분석 완료 콜백**에도 구체적 참조를 넘기고 싶다면, `finalResult` 에 다음을 추가할 수 있습니다.

- **ragContributions** (array, 선택):  
  위 2.1과 동일한 항목 배열 (`refId`, `sourceType`, `sourceKey`, `title`, `location`, `excerpt`).

이 경우 백엔드에서:

- `finalResult.ragRefs`: 기존 호환 유지  
- `finalResult.ragContributions`: 새 필드로 저장 후, FE에서 “규정 제3조 2항(비용 한도) 참조” 등 표시에 사용  

하도록 정하면 됩니다. **현재 Aura는 콜백에 ragContributions를 보내지 않고**, Agent Stream(agent_activity_log) 쪽에만 ragContributions를 넣습니다.

---

## 5. 요약

| 구분 | 전달 경로 | 필드 | 용도 |
|------|-----------|------|------|
| 실시간 로그 | Agent Stream (agent_events) | `payload.evidence.ragContributions` | 문서별 location/title 참조 (예: 규정 제3조 2항) |
| 실시간 로그 | Agent Stream (agent_events) | `payload.evidence.policy_reference` | 정책/임계치 참조 출처 |
| 분석 완료 | 콜백 finalResult | `ragRefs` | 기존 형식 유지 (refId, sourceType, sourceKey, excerpt, score) |

백엔드에서는 **Agent Stream 수신 시 `payload.evidence.ragContributions` 와 `payload.evidence.policy_reference` 를 파싱·저장**하면, 변경된 RAG 참조 로그 형식을 그대로 활용할 수 있습니다.
