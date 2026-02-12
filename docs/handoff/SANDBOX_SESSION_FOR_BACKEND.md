# 테스트 채팅(샌드박스) 임시 세션 — BE 협의 사항

## 목적

샌드박스에서 대화한 내용이 **DB에 영구 저장되지 않도록** '임시 세션' 처리가 되었는지 확인하고, Aura–BE 간 계약을 정리합니다.

## 현재 Aura 동작

- **Finance Agent 스트림**: `thread_id`는 요청 시 클라이언트가 넘기거나 `finance_{user_id}_{tenant_id}_{timestamp}` 형태로 생성됩니다.
- **Checkpointer**: 에이전트 기본은 **MemorySaver**(인메모리)로, 프로세스 재시작 시 대화 이력이 사라집니다. DB/SQLite 등 영구 체크포인트는 별도 설정 시에만 사용합니다.
- **감사 분석**: `run_audit_analysis` 결과는 `case_stream_store`(Redis 등)에 임시 저장 후 콜백으로 BE에 전달됩니다. BE가 콜백 수신 시 DB에 저장하는 구조입니다.

## 협의 필요 사항

1. **세션 구분**
   - BE/FE에서 **테스트·샌드박스**용 요청인지 구분할 수 있는 방법을 정합니다.
   - 제안: 쿼리 파라미 또는 헤더 예시  
     - `X-Session-Type: sandbox`  
     - 또는 요청 body에 `"session_type": "sandbox"` / `"temporary_session": true`

2. **Aura 측 대응(협의 후 구현 가능)**
   - `session_type=sandbox` 또는 `temporary_session=true` 수신 시:
     - 콜백을 **보내지 않거나**, 콜백 payload에 `"is_sandbox": true`(또는 `"temporary_session": true`) 필드를 포함할 수 있습니다.
     - 감사 분석 결과를 Redis/저장소에 쓰지 않거나, TTL을 짧게 두는 정책을 적용할 수 있습니다.
   - 에이전트 스트림은 이미 인메모리 체크포인트이므로, **BE가 샌드박스 요청으로 받은 분석/이벤트를 DB에 저장하지 않으면** “임시 세션” 효과를 낼 수 있습니다.

3. **BE 측 권장**
   - **샌드박스/테스트 채팅**으로 식별된 요청에 대해서는:
     - Aura 콜백 수신 시 `finalResult`를 **영구 DB(case_analysis_result 등)에 저장하지 않음**
     - 또는 `is_sandbox`/`temporary_session` 플래그가 있으면 저장 스킵
   - 동일하게, 에이전트 활동 로그(agent_activity_log 등)도 샌드박스 세션은 저장하지 않거나 별도 테이블/플래그로 구분하는 방안을 검토

## 제안 계약 요약

| 구분 | 제안 |
|------|------|
| 세션 구분 | FE/BE가 요청 시 `session_type=sandbox` 또는 `temporary_session=true` 전달 |
| Aura → BE | 콜백/이벤트에 `is_sandbox` 또는 `temporary_session` 포함 가능 (협의 후 구현) |
| BE 저장 | `is_sandbox`/`temporary_session`이 true이면 case_analysis_result 등에 **영구 저장하지 않음** |

이 문서를 기준으로 BE와 협의하여, 샌드박스 여부 전달 방식과 저장 스킵 규칙을 확정하는 것을 권장합니다.
