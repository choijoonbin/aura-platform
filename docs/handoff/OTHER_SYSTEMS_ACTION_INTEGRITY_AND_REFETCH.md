# 다른 시스템 전달: Action Integrity 및 워크벤치 Refetch

> **전달 대상**: DWP Backend (Synapse), Frontend (워크벤치/에이전트 연동)  
> **전달 일자**: 2026-02-11  
> **관련 기능**: 승인/거절 조치 정합성, 실시간 화면 갱신

---

## 1. 전달 요약

- **승인/거절 시** Aura는 DB에 조치 이력을 쓰지 않습니다. 조치 이력·전표는 백엔드가 관리하며, Aura는 HITL 피드백 로그와 Redis로 “조치 완료” 신호를 발행합니다.
- **다른 시스템**은 아래 API 호출·Redis 구독만 구현하면, 케이스 상태와 전표 상태를 정합 있게 유지하고 워크벤치를 즉시 갱신할 수 있습니다.

---

## 2. Backend (Synapse)에서 할 일

### 2.1 (선택) 승인/거절 처리 후 Aura API 호출

**백엔드가 조치를 자체 DB에 기록한 뒤** 필요 시 아래 API를 호출하면 Aura가 HITL 피드백 로그와 Redis “조치 완료”알림만 수행합니다. (Aura는 DB에 기록하지 않음.)

| 항목 | 내용 |
|------|------|
| **Method** | `POST` |
| **URL** | Gateway 경유: `POST {GATEWAY_BASE}/api/aura/action/record` (예: `http://localhost:8080/api/aura/action/record`) |
| **인증** | `Authorization: Bearer {JWT}`, `X-Tenant-ID: {tenantId}` (기존과 동일) |
| **Content-Type** | `application/json` |

**Request Body**:

```json
{
  "case_id": "DEMO00001",
  "request_id": "req-xxx",
  "executor_id": "user-123",
  "approved": true,
  "comment": "검토 후 승인",
  "doc_key": "1000-1900000001-2024"
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| case_id | string | O | 케이스 ID |
| request_id | string | O | HITL 요청 ID (`hitl:request:{requestId}`와 동일) |
| executor_id | string | O | 승인/거절한 사용자 ID |
| approved | boolean | O | true=승인, false=거절 |
| comment | string | X | 사용자 코멘트 (거절 사유 등) |
| doc_key | string | X | 연동할 전표 식별자 (있으면 해당 전표만 status 갱신) |

**Response (200)**:

```json
{
  "status": "SUCCESS",
  "message": "Action recorded",
  "data": { "ok": true, "logged": true },
  "success": true,
  "timestamp": "2026-02-11T12:00:00.000000"
}
```

- **참고**: Aura는 DB에 쓰지 않으므로 `history_id`/`fi_doc_updated`는 반환하지 않습니다. Aura 스트림에서 승인/거절 신호를 받으면 자동으로 HITL 피드백 로그 + Redis 발행만 수행합니다.

### 2.2 Redis 구독: 워크벤치 Refetch 알림

조치 완료 시 다른 사용자/에이전트 화면을 갱신하려면 **동일 Redis**에서 아래 채널을 구독하면 됩니다.

| 항목 | 내용 |
|------|------|
| **채널명** | `workbench:case:action` (기본값, Aura 설정 `case_action_redis_channel`로 변경 가능) |
| **발행 시점** | 승인/거절이 DB에 기록된 직후 (Aura가 발행) |
| **메시지 형식** | UTF-8 JSON 문자열 |

**메시지 예시**:

```json
{
  "type": "case_action_completed",
  "case_id": "DEMO00001",
  "request_id": "req-xxx",
  "executor_id": "user-123",
  "action_type": "APPROVE",
  "approved": true,
  "status_code": "APPROVED",
  "at": "2026-02-11T12:00:00.000Z"
}
```

**Backend (Spring Boot) 구독 예시**:

```java
// RedisMessageListenerContainer 또는 Lettuce 사용
@Component
public class CaseActionSubscriber {

    @Autowired
    private RedisTemplate<String, String> redisTemplate;

    @Value("${aura.case-action-channel:workbench:case:action}")
    private String channel;

    @PostConstruct
    public void subscribe() {
        redisTemplate.listenToChannel(channel, (message) -> {
            String payload = new String(message.getBody(), StandardCharsets.UTF_8);
            CaseActionCompletedEvent event = objectMapper.readValue(payload, CaseActionCompletedEvent.class);
            // 워크벤치에 Refetch 요청 전달 (WebSocket/SSE/폴링 등)
            notifyWorkbenchToRefetch(event.getCaseId());
        });
    }
}
```

- 수신 시 **해당 `case_id`에 대한 케이스 상세·전표 상태 등을 다시 조회(Refetch)** 하여 화면에 반영하면 됩니다.

---

## 3. Frontend (워크벤치)에서 할 일

### 3.1 Refetch 트리거

- Backend가 Redis `workbench:case:action` 메시지를 수신하면, 해당 케이스를 보고 있는 클라이언트에게 **Refetch**를 요청하면 됩니다.
- 구현 방식 예:
  - Backend가 WebSocket/SSE로 `case_action_completed` 이벤트를 푸시 → Frontend는 해당 `case_id`로 케이스 상세·전표 API 재호출
  - 또는 주기적 폴링 + Backend API에서 “최근 조치 완료 목록” 제공 후, 해당 케이스만 재조회

### 3.2 표시 참고

- `status_code`: `APPROVED` / `REJECTED` (전표 상태)
- `approved`: 승인 여부
- `executor_id`: 조치한 사용자 (감사/이력 표시용)

---

## 4. Aura-Platform 측 동작 (참고)

- **DB**: Aura는 **case_action_history / fi_doc_header에 쓰지 않습니다.** 조치 이력·전표 상태는 백엔드가 관리합니다.
- **HITL 피드백**: 조치 확정 신호 수신 시 구조화 로그 및 (설정 시) JSONL 파일에 기록 → 향후 가중치 업데이트/재학습용
- **Redis**: `workbench:case:action` 채널로 위 JSON 발행 → 워크벤치 Refetch 등 알림
- **HITL 스트림**: Aura가 Redis로 승인/거절 신호를 받으면, `caseId`·`executor_id`를 요청 컨텍스트에서 추출해 자동으로 HITL 피드백 로그 + Redis 발행만 수행

---

## 5. 체크리스트 (다른 시스템)

| 구분 | 항목 | 비고 |
|------|------|------|
| Backend | 조치 이력·전표 상태를 **자체 DB**에 기록 (case_action_history, fi_doc_header 등) | Aura는 DB에 쓰지 않음 |
| Backend | (선택) 조치 확정 후 `POST /api/aura/action/record` 호출 | HITL 피드백·Redis 알림용 |
| Backend | Redis 채널 `workbench:case:action` 구독 | 동일 Redis 인스턴스 사용 |
| Backend | 구독 메시지 수신 시 해당 `case_id`에 대해 Refetch/알림 로직 연동 | WebSocket/SSE 등 |
| Frontend | Backend에서 내려준 Refetch 요청 수신 시 케이스 상세·전표 재조회 | |

---

## 6. 관련 문서

- **규격·확인사항 (기능 제거 후 협업용)**: [BACKEND_AURA_CONTRACT_AFTER_ROLE_SEPARATION.md](BACKEND_AURA_CONTRACT_AFTER_ROLE_SEPARATION.md) — API/Redis 규격 변경, 양쪽 확인 체크리스트
- Aura 내부 가이드: `docs/guides/ACTION_INTEGRITY_APPROVAL_LOOP.md`
- HITL 연동: `docs/handoff/BACKEND_HANDOFF.md` (Redis `hitl:channel:{sessionId}` 발행 등)
