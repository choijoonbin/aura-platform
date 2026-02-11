# 백엔드 검토 회신에 대한 Aura 측 확인·답변

> **대상**: 백엔드 검토 결과 (back.txt)  
> **일자**: 2026-02-11  
> **참조**: `BACKEND_AURA_CONTRACT_AFTER_ROLE_SEPARATION.md` (aura.txt 규격)

---

## 1. 백엔드 검토 요약 수신 확인

백엔드에서 아래 내용으로 확인·수정해 주신 것을 확인했습니다.

| 항목 | 백엔드 상태 | Aura 측 인지 |
|------|-------------|--------------|
| 조치 이력·전표 상태 DB | 백엔드 단일 담당 (ActionCommandService) | ✅ Aura는 DB 미사용으로 유지 |
| `POST /api/aura/action/record` | 백엔드에서 호출하지 않음 | ✅ 동의. Aura 스트림 경로에서만 HITL 피드백·Redis 발행용으로 사용 |
| Redis 구독 시 `history_id`/`fi_doc_updated` | 백엔드는 구독하지 않음 (발행만) | ✅ 확인 |
| Redis 채널명 | `workbench:case:action` 으로 통일 | ✅ Aura 기본값과 일치 |

---

## 2. Aura 측 확인·답변 (§3 요청사항)

### 2.1 Redis 구독 시 `history_id`, `fi_doc_updated` optional 처리 (§3.1)

- **현재**: Aura는 **`workbench:case:action` 채널을 구독하지 않고, 발행만** 수행합니다.
- **향후**: Aura에서 해당 채널을 구독하는 로직을 추가할 경우, **`history_id`, `fi_doc_updated`는 optional**로 처리하겠습니다 (백엔드 발행분에는 포함될 수 있음).
- **문서 반영**: 구독 시 파싱 규격에 “`history_id`, `fi_doc_updated` optional (백엔드 발행분에만 존재 가능)” 명시하겠습니다.

### 2.2 채널 설정 일치 (§3.2)

- **확인**: Aura 설정 **`case_action_redis_channel`** 기본값은 **`workbench:case:action`** 입니다.
- **위치**: `core/config.py` — `case_action_redis_channel: str = Field(default="workbench:case:action", ...)`
- **결과**: 양쪽 발행·구독이 동일 채널로 정렬된 상태입니다.

### 2.3 Phase2 분석 요청 시 doc_id / item_id (§3.3)

- **확인**: Aura Phase2에서 **이미 구현되어 있습니다.**
- **위치**: `core/analysis/phase2_pipeline.py`
- **동작**: `body_evidence.doc_id`(또는 `body_evidence.document.docKey`), `body_evidence.item_id` 를 읽어, 해당 문서·항목에 대한 규정 준수 여부 판단을 프롬프트에 반영합니다.
- **규격**: aura.txt §1.4 및 §2.2 Aura 확인사항 #4와 동일합니다.

### 2.4 `/action/record` 호출 실패 시 (§3.4)

- **확인**: 백엔드가 해당 API를 호출하지 않으므로, “백엔드 → Aura /action/record 호출 실패” 시나리오는 **현재 플로우에 없음**을 공유해 주신 내용과 일치합니다.
- **Aura 측**: Aura 스트림 등 자체 플로우에서 `/action/record`를 호출하는 경우, 실패 시 재시도·알림 정책은 Aura(및 해당 클라이언트) 측에서 관리하겠습니다.

---

## 3. Aura 체크리스트 (§4.2) — 완료 상태

| # | 항목 | Aura 상태 |
|---|------|-----------|
| 1 | Redis 구독 시 `history_id`, `fi_doc_updated` optional 처리 | ✅ 현재 구독 없음. 향후 구독 시 optional 처리 예정·문서화 |
| 2 | `case_action_redis_channel` = `workbench:case:action` 확인 | ✅ 기본값 일치 |
| 3 | Phase2에서 `body_evidence.doc_id`, `document.docKey`, `body_evidence.item_id` 수신·프롬프트 반영 | ✅ 구현 완료 |

---

## 4. 참고 — Aura 발행 포맷 (통일 알림)

Aura는 **통일 알림 포맷**으로 발행합니다 (백엔드 수신 용이 목적).

- **공통**: `type: "NOTIFICATION"`, `category`, `message`, `timestamp` + category별 추가 필드
- **CASE_ACTION**: `workbench:case:action` 에 `category: "CASE_ACTION"`, `message: "조치 승인됨"` / `"조치 거절됨"` 및 `case_id`, `request_id`, `executor_id`, `action_type`, `approved`, `status_code` 등
- 백엔드 발행분에는 `history_id`, `fi_doc_updated` 등이 포함될 수 있으므로, **구독 측**에서는 위 필드를 optional로 처리하면 됩니다.

---

## 5. 결론

- 백엔드 검토 결과 및 수정 사항을 반영하여 Aura 측 확인을 완료했습니다.
- 채널명·Phase2 규격은 이미 맞춰져 있으며, Redis 구독 시 optional 처리 요청은 향후 Aura가 해당 채널을 구독할 때 적용·문서화하겠습니다.

추가로 맞춰야 할 규격이 있으면 알려 주시면 됩니다.
