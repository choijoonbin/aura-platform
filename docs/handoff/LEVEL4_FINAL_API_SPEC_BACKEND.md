# Level 4 최종 API 규격서 (Aura · Frontend 공용)

> **목적**: Aura와 Frontend가 복사해 바로 사용할 수 있는 요청/응답 JSON 규격  
> **검증 일자**: 2026-02-11  
> **Backend 검증**: body_evidence(doc_id, item_id) 명시 포함 · wrbtr number · actionAt ISO8601

---

## Part A — With Aura (Backend → Aura)

### A.1 규격 검증 요약

| 항목 | Backend 구현 | Aura 기대 | 검증 |
|------|--------------|-----------|------|
| `body_evidence` | `AuraAnalyzeRequest.bodyEvidence` → JSON `body_evidence` | 요청 body 내 `body_evidence` 존재 | ✅ |
| `body_evidence.doc_id` | `BodyEvidenceDto.docId` → `@JsonProperty("doc_id")` | 문자열 (BELNR) | ✅ |
| `body_evidence.item_id` | `BodyEvidenceDto.itemId` → `@JsonProperty("item_id")` | 문자열 (BUZEI) | ✅ |

Backend DTO: `BodyEvidenceDto` (doc_id, item_id), `AuraAnalyzeRequest` (bodyEvidence 직렬화 키 `body_evidence`).  
Phase2 트리거 시 `CaseAnalysisService.buildBodyEvidence(agentCase)`에서 belnr → doc_id, buzei → item_id 세팅.

---

### A.2 샘플 JSON — Aura가 수신하는 분석 요청 (복사용)

**Endpoint**: `POST /aura/cases/{caseId}/analysis-runs`  
**Content-Type**: `application/json`

```json
{
  "caseId": 12345,
  "runId": "550e8400-e29b-41d4-a716-446655440000",
  "mode": "phase2",
  "requestedBy": "USER:user-uuid",
  "evidence": {
    "evidence": {},
    "ragRefs": [],
    "document": {
      "type": "DOCUMENT",
      "docKey": "1000-1900000001-2024",
      "header": {
        "bukrs": "1000",
        "belnr": "1900000001",
        "gjahr": "2024",
        "budat": "2024-01-15",
        "xblnr": ""
      },
      "items": [
        {
          "buzei": "001",
          "hkont": "0000100000",
          "wrbtr": 1000.00,
          "sgtxt": "Sample"
        }
      ]
    },
    "openItems": [],
    "partyIds": [],
    "lineage": {},
    "policies": []
  },
  "options": {
    "model": "default",
    "policyVersion": "v1"
  },
  "body_evidence": {
    "doc_id": "1900000001",
    "item_id": "001"
  }
}
```

- **body_evidence**: Aura는 이 블록에서 `doc_id`, `item_id`를 읽음.  
- **doc_id**: 전표 번호(BELNR).  
- **item_id**: 전표 라인(BUZEI). 해당 라인만 규정 준수 판단 시 사용.

---

## Part B — With Frontend (Backend → FE)

### B.1 규격 검증 요약

| 항목 | FE 기대 | Backend 구현 | 검증 |
|------|---------|--------------|------|
| **wrbtr** | `number` | `DocumentLineItemDto.wrbtr` (BigDecimal) → JSON number | ✅ |
| **actionAt** | ISO8601 문자열 | `CaseActionHistoryItemDto.actionAt` (Instant) → JavaTimeModule ISO8601 | ✅ |

- **wrbtr**: 금액 필드. Backend는 `BigDecimal` 사용 → Jackson 직렬화 시 JSON **number** (정수/소수).  
- **actionAt**: 조치 시각. Backend는 `Instant` 사용 → Jackson `JavaTimeModule`으로 **ISO-8601** 문자열 (예: `"2024-01-15T10:30:00.123456789Z"`).

---

### B.2 샘플 JSON — GET 케이스 상세 (복사용)

**Endpoint**: `GET /api/synapse/cases/{id}`  
**Response**: 케이스 상세 (fi_doc_items 포함)

```json
{
  "caseId": 12345,
  "status": "OPEN",
  "keys": {
    "sourceType": "DOCUMENT",
    "bukrs": "1000",
    "belnr": "1900000001",
    "gjahr": "2024",
    "buzei": "001",
    "dedupKey": null
  },
  "links": {
    "openItems": "/api/synapse/open-items?caseId=12345",
    "lineage": "/api/synapse/lineage?caseId=12345"
  },
  "fi_doc_items": [
    {
      "buzei": "001",
      "hkont": "0000100000",
      "wrbtr": 1000.00,
      "sgtxt": "Sample line text",
      "lifnr": null,
      "kunnr": null,
      "bschl": "40",
      "shkzg": "S",
      "dmbtr": 1000.00,
      "waers": "KRW",
      "isTarget": true
    },
    {
      "buzei": "002",
      "hkont": "0000200000",
      "wrbtr": -500.00,
      "sgtxt": "Other line",
      "lifnr": null,
      "kunnr": null,
      "isTarget": false
    }
  ],
  "evidence": {
    "documentOrOpenItem": {
      "type": "DOCUMENT",
      "docKey": "1000-1900000001-2024",
      "headerSummary": {
        "bukrs": "1000",
        "belnr": "1900000001",
        "gjahr": "2024"
      },
      "items": [],
      "lineCount": 2,
      "amount": 500.00,
      "currency": "KRW"
    },
    "amount": 500.00,
    "currency": "KRW"
  },
  "reasoning": {
    "score": 0.72,
    "reasonText": "..."
  },
  "action": {
    "availableActionTypes": ["PAYMENT_BLOCK", "REQUEST_INFO", "DISMISS", "RELEASE_BLOCK"],
    "actions": [],
    "lineageLinkParams": {}
  }
}
```

**타입 정리 (FE 참고)**  
- `fi_doc_items[].wrbtr`: **number** (금액).  
- `fi_doc_items[].buzei`, `hkont`, `sgtxt`: **string**.  
- `evidence.documentOrOpenItem.amount`, `evidence.amount`: **number**.

---

### B.3 샘플 JSON — GET 조치 이력 (actionAt ISO8601)

**Endpoint**: `GET /api/synapse/workbench/cases/{caseId}/history`  
**Response**: `ApiResponse<List<CaseActionHistoryItemDto>>`

```json
{
  "success": true,
  "data": [
    {
      "id": 1,
      "caseId": 12345,
      "actionType": "PAYMENT_BLOCK",
      "actorId": "USER:user-uuid",
      "commentText": "Approved after review",
      "actionAt": "2024-01-15T10:30:00.123456789Z",
      "metadataJson": null,
      "createdAt": "2024-01-15T10:30:00.123456789Z"
    }
  ],
  "errorCode": null,
  "message": null
}
```

**타입 정리 (FE 참고)**  
- `data[].actionAt`: **string**, ISO-8601 형식 (UTC, 예: `YYYY-MM-DDTHH:mm:ss.SSSSSSSSSZ`).  
- `data[].createdAt`: **string**, 동일 ISO-8601.  
- 그 외 id, caseId: **number**; actionType, actorId, commentText: **string**.

---

## 요약

| 대상 | 규격 | 샘플 위치 |
|------|------|-----------|
| **Aura** | `body_evidence.doc_id`, `body_evidence.item_id` 명시 (문자열 BELNR/BUZEI) | Part A.2 |
| **Frontend** | `wrbtr` → number, `actionAt`/`createdAt` → ISO8601 string | Part B.2, B.3 |

위 JSON은 Backend 실제 직렬화 규격과 맞춰 두었으며, Aura·Frontend는 해당 블록을 복사해 스키마/타입 정의 및 테스트에 사용하면 됩니다.
