# SSE/HITL 추가 작업 여부 확인

> **목적**: P0/P1/P2 완료 후 추가 개발 필요 여부 최종 확인  
> **근거**: 실제 코드 검증 (추정 금지)  
> **작성일**: 2026-02

---

## 확인 항목

### 1) Finance stream: X-User-ID 수용/불일치 검증(SSE error + [DONE]) 적용 완료 여부

| 상태 | 코드 근거 |
|------|-----------|
| ✅ | `api/routes/finance_agent.py:60` — `x_user_id: str \| None = Header(None, alias="X-User-ID")` 파라미터 |
| ✅ | `api/routes/finance_agent.py:96-111` — `x_user_id and x_user_id != user.user_id` 검증, SSE `event: error` + `data: [DONE]` + return |

**검증**: X-User-ID 헤더 수용 및 JWT `sub` 불일치 시 SSE error + [DONE] 적용 완료.

---

### 2) 모든 SSE 이벤트 payload에 user_id 포함(enrich) 적용 완료 여부

| 상태 | 코드 근거 |
|------|-----------|
| ✅ | `api/routes/finance_agent.py:44-55` — `_enrich_event_data` 시그니처에 `user_id` 추가, `data["user_id"] = user_id` |
| ✅ | `api/routes/finance_agent.py:126-128, 180-182, 193-217, 280-283, 288-292, 299-304` — 모든 `_enrich_event_data` 호출에 `user.user_id` 전달 |

**검증**: start, hitl, failed, error, end, event_queue 등 모든 SSE 이벤트에 user_id 포함 적용 완료.

---

### 3) Last-Event-ID 정책: id 연속만 지원, replay 미지원 계약 문구 확정 여부

| 상태 | 코드 근거 |
|------|-----------|
| ✅ | `api/routes/finance_agent.py:66, 116-122` — `Last-Event-ID` 수용, `event_id_counter = last_id + 1` (id 연속만) |
| ✅ | 저장소 없음 — replay 미구현 (이벤트 로그 미저장) |
| ✅ | `docs/guides/SSE_HITL_EXECUTION_CHECKLIST.md` §(D), §P1-1, §P1-2 — 계약 문구 확정 |

**검증**: id 연속만 지원, replay 미지원. FE/BE 전달용 계약 문구 문서화 완료.

---

### 4) HITL/Audit: Redis 저장 + Synapse 저장(단일 수집점) 책임 분리 확정 여부

| 상태 | 코드 근거 |
|------|-----------|
| ✅ | `core/memory/hitl_manager.py:80, 88` — Redis `hitl:request:{request_id}`, `hitl:session:{session_id}` 저장 (TTL 30분/60분) |
| ✅ | `core/audit/writer.py:22, 139-146` — Redis `audit:events:ingest` 채널로 발행 (Synapse가 구독) |
| ✅ | `core/config.py:260` — `audit_redis_channel` 기본값 `audit:events:ingest` |
| ✅ | `docs/guides/SSE_HITL_EXECUTION_CHECKLIST.md` §P2-1, §P2-2 — 저장 범위·책임 분리 문서화 |

**검증**: HITL은 Aura Redis 저장, Audit은 Aura 발행 → Synapse 단일 수집점 저장. 책임 분리 확정.

---

## 요약

| # | 항목 | 결과 |
|---|------|------|
| 1 | X-User-ID 수용/불일치 검증 (SSE error + [DONE]) | ✅ |
| 2 | SSE 이벤트 payload user_id 포함 | ✅ |
| 3 | Last-Event-ID 정책 (id 연속, replay 미지원) 계약 문구 | ✅ |
| 4 | HITL/Audit Redis + Synapse 책임 분리 | ✅ |

---

> **결론: Aura 추가 작업 없음. 계약 문구/검증 시나리오 기준으로 프로젝트 진행 가능.**
