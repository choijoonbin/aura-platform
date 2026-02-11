# Action Integrity: 승인/거절 루프 정합성 (역할 분리)

Aura는 **DB에 조치 이력을 직접 쓰지 않습니다**. 조치 확정 신호를 받으면 HITL 피드백 로그와 Redis 알림만 수행합니다.

## 1. 역할 분리 (Aura vs 백엔드)

- **백엔드**: `case_action_history`, `fi_doc_header` 등 조치 이력·전표 상태를 **자체 DB에 기록·동기화**합니다.
- **Aura**: 조치 확정 신호 수신 시
  1. **HITL 피드백 로그** (가중치 업데이트/재학습용) 기록
  2. **Redis Pub/Sub**으로 조치 완료 알림 발행 → 워크벤치 Refetch 등 후속 프로세스
  - `dwp_aura.case_action_history` / `fi_doc_header`에 대한 INSERT/UPDATE는 **하지 않습니다**.

## 2. HITL 피드백 로그

- **목적**: 향후 분석 정확도·가중치 업데이트용.
- **방식**: 구조화 로그(`hitl_feedback` 로거) + (설정 시) JSONL 파일(`hitl_feedback_log_path`).
- **페이로드 예시**: `event=hitl_feedback`, `case_id`, `request_id`, `executor_id`, `action_type`, `approved`, `comment`, `doc_key`, `at`.

## 3. Redis Pub/Sub (조치 완료 신호)

- **채널**: `workbench:case:action` (기본값, `case_action_redis_channel`로 변경 가능)
- **발행 시점**: 조치 확정 신호 수신 후 (Aura는 DB에 쓰지 않음)
- **페이로드 예시**:
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

### 3.1 구독 측 (워크벤치 / 에이전트)

- 워크벤치를 열고 있는 다른 사용자나 Aura 에이전트가 이 채널을 구독하면, 메시지 수신 시 **즉시 Refetch**(케이스 상세, 전표 상태 등)하여 화면을 갱신할 수 있습니다.
- Redis 구독 예시 (Spring Boot):
```java
// RedisMessageListenerContainer 또는 Lettuce subscribe
redisTemplate.listenToChannel("workbench:case:action", (message) -> {
    CaseActionCompletedEvent event = parse(message);
    notifyWorkbenchToRefetch(event.getCaseId());
});
```

## 4. API

### 4.1 POST /api/aura/action/record

- **역할**: 조치 확정 신호 수신 → HITL 피드백 로그 기록 + Redis 조치 완료 알림 발행 (DB 기록 없음)
- **호출 주체**: Synapse(백엔드)에서 사용자 승인/거절 처리 후 호출 권장
- **Body**:
```json
{
  "case_id": "DEMO00001",
  "request_id": "req-xxx",
  "executor_id": "user-123",
  "approved": true,
  "comment": "검토 후 승인",
  "doc_key": "optional-doc-key"
}
```

### 4.2 HITL 스트림 연동

- Aura 백엔드 스트림에서 Redis로 승인/거절 신호를 수신하면, `caseId`·`executor_id`를 요청 컨텍스트에서 추출하여 **자동으로** `record_case_action()`을 호출합니다 (HITL 피드백 로그 + Redis 알림만, DB 기록 없음).

## 5. 설정

- `core/config.py`: `case_action_redis_channel` (기본 `workbench:case:action`), `hitl_feedback_log_path` (선택, JSONL 경로)
- 동일 Redis 인스턴스를 사용하는 워크벤치/에이전트가 해당 채널을 구독하면 됩니다.
