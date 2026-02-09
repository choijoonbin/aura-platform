# Synapse API 500 오류 확인 요청

> **대상**: Synapse 백엔드 개발팀  
> **작성일**: 2026-02-06  
> **배경**: Finance Agent 스트리밍 시 Synapse API 호출에서 500 발생

---

## 0. 백엔드 응답 (2026-02-06)

백엔드에서 확인 완료 후 조치 내용을 공유했습니다.

**참조**: `dwp-backend/docs/integration/SYNAPSE_API_500_VERIFICATION_RESULT.md`

### 요약

| 확인 항목 | 결과 |
|----------|------|
| **경로 불일치** | Aura `/tools/finance/**` ↔ Synapse `/api/synapse/agent-tools/**` |
| **요청 형식** | search_documents, get_open_items: Aura POST+body ↔ Synapse GET+query |
| **caseId 지원** | documents/open-items에 caseId 기반 조회 없음 |
| **lineage** | belnr/gjahr/bukrs 직접 전달 → Synapse 개선 완료 (docKey, bukrs+belnr+gjahr 지원) |
| **agent/events** | 스키마 호환 ✅ |

### Aura 권장 조치

| 조치 | 내용 |
|------|------|
| **Base URL** | `http://{gateway}:8080` (8081 아님) |
| **경로** | `/api/synapse/agent-tools/**` 사용 |
| **get_case** | `GET /api/synapse/agent-tools/cases/{caseId}` |
| **search_documents** | `GET /api/synapse/agent-tools/documents?page=0&size={topK}` + case의 bukrs/belnr/gjahr로 필터 |
| **get_open_items** | `GET /api/synapse/agent-tools/open-items?page=0&size=20` |
| **get_lineage** | `GET /api/synapse/agent-tools/lineage?caseId={caseId}` (docKey, bukrs+belnr+gjahr도 지원) |
| **agent/events** | `POST /api/synapse/agent/events` |

### Aura 적용 완료 (2026-02-06)

- `core/config.py`: synapse_base_url 기본값 `http://localhost:8080/api/synapse/agent-tools`
- `tools/synapse_finance_tool.py`: 경로/메서드 변경 (GET documents, open-items), lineage Field 메타데이터 검증
- `core/agent_stream/writer.py`: agent-tools 사용 시 agent/events URL 분리

---

## 1. 500 발생 API 목록 (원본)

| API | 메서드 | 호출 시점 |
|-----|--------|----------|
| `/tools/finance/cases/{caseId}` | GET | get_case (케이스 조회) |
| `/tools/finance/documents/search` | POST | search_documents (문서 검색) |
| `/tools/finance/open-items/search` | POST | get_open_items (미결 항목 조회) |
| `/tools/finance/lineage` | GET | get_lineage (라인리지 조회) |
| `/api/synapse/agent/events` | POST | Agent Stream push |

---

## 2. 요청 형식 (Aura → Synapse)

### get_case
```
GET http://localhost:8081/tools/finance/cases/85114
Headers: X-Tenant-ID, X-User-ID, X-Trace-ID, Authorization
```

### search_documents
```
POST http://localhost:8081/tools/finance/documents/search
Body: {"caseId": "85114", "topK": 10} (또는 filters)
```

### get_open_items
```
POST http://localhost:8081/tools/finance/open-items/search
Body: {"caseId": "85114"}
```

### get_lineage
```
GET http://localhost:8081/tools/finance/lineage?caseId=85114
또는
GET .../lineage?belnr=xxx&gjahr=xxx&bukrs=xxx
```

### agent/events
```
POST http://localhost:8081/api/synapse/agent/events
Body: {"events": [...]}
```

---

## 3. 확인 요청 사항

1. **500 원인**: 위 API 호출 시 Synapse 서버 로그에서 스택 트레이스 확인
2. **케이스 85114**: 해당 caseId가 Synapse DB에 존재하는지
3. **헤더 검증**: X-Tenant-ID, X-User-ID, Authorization 등 필수 헤더 누락 여부
4. **agent/events**: Request body 스키마가 Synapse 기대 형식과 일치하는지

---

## 4. 추가 확인 (get_lineage)

로그에서 lineage 호출 시 `belnr`, `gjahr`, `bukrs`가 Field 메타데이터 문자열로 전달된 흔적이 있습니다.  
caseId 기반 호출이 정상인데, LLM이 belnr/gjahr/bukrs를 잘못 전달한 경우일 수 있습니다.  
Synapse 측에서 해당 파라미터 검증/에러 메시지 개선이 가능한지 확인 부탁드립니다.

---

## 5. Aura 측 동작

- 5xx 발생 시 exponential backoff로 최대 3회 재시도
- 재시도 후에도 500이면 에이전트는 에러 반환
- Agent Stream push 실패 시 로그만 남기고 계속 진행 (fire-and-forget)
