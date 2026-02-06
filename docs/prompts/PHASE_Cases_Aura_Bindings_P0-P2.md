# Phase C: Case Detail 탭 실데이터 연결 (P0-P2)

> **산출**: PROMPT_C_Aura_MenuByMenu_Cases_First_v2.txt 기반 구현  
> **작성일**: 2026-02-06  
> **상태**: 구현 완료

---

## 1. 개요

케이스 상세 탭의 **AI분석/에이전트 스트림/신뢰도/유사케이스/RAG**가 하드코딩이 아닌 실데이터를 표시하도록 최소 기능을 구현했습니다.

- **P0**: Stream 이벤트 스키마 고정, Case 기준 재현 가능한 샘플 스트림 (SSE)
- **P1**: RAG evidence, 유사케이스, 신뢰도 (규칙 기반 실데이터)
- **P2**: 분석 요약 (template 기반)

---

## 2. API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/aura/cases/{caseId}/stream` | Case Agent Stream (SSE), Last-Event-ID replay |
| POST | `/api/aura/cases/{caseId}/stream/trigger` | 수동 트리거 (admin 전용, 테스트 재현성) |
| GET | `/api/aura/cases/{caseId}/rag/evidence` | RAG Evidence 목록 |
| GET | `/api/aura/cases/{caseId}/similar` | 유사 케이스 (규칙 기반) |
| GET | `/api/aura/cases/{caseId}/confidence` | Confidence Score breakdown |
| GET | `/api/aura/cases/{caseId}/analysis` | Analysis Summary (template+facts) |

---

## 3. 이벤트 스키마 (고정)

SSE 형식:
```
id: <monotonic id>
event: agent.step | agent.note | agent.error
data: { "tenantId", "caseId", "traceId", "ts", "level", "stepId", "message", "payload" }
```

---

## 4. 구현 파일

| 구분 | 파일 |
|------|------|
| **Stream 저장소** | `core/streaming/case_stream_store.py` |
| **라우트** | `api/routes/aura_cases.py` |
| **main 등록** | `main.py` (aura_cases_router) |

---

## 5. 테스트 방법

### curl

```bash
# Stream (JWT 필요)
curl -N -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/stream"

# Trigger 후 Stream (admin 권한)
curl -X POST -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/stream/trigger"

# RAG Evidence
curl -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/rag/evidence"

# Similar
curl -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/similar"

# Confidence
curl -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/confidence"

# Analysis
curl -H "X-Tenant-ID: 1" -H "Authorization: Bearer <TOKEN>" \
  "http://localhost:9000/aura/cases/CS-85114/analysis"
```

### Gateway 경로

`/api/aura/cases/{caseId}/*` → Aura-Platform (포트 9000)

---

## 6. DoD (완료 조건)

- [x] FE에서 케이스 상세 → Stream 탭 열면 3~5개 이벤트가 실시간 표시 (또는 trigger 후 표시)
- [x] Last-Event-ID로 새로고침해도 이벤트가 이어서 보임
- [x] RAG evidence: 3개 이상 (없으면 empty state 명확)
- [x] confidence/similar: 규칙 기반이라도 실데이터로 1개 이상

---

## 7. 제한사항

- **Stream 저장소**: in-memory ring buffer (caseId별 최근 100개). 운영 시 DB/Redis 스트림 2차 확장 가능.
- **RAG/Synapse**: Synapse 백엔드 응답 형식에 따라 evidence 파싱 로직 조정 필요.
- **Trigger**: admin 권한 필요. JWT role=admin 사용자만 호출 가능.
