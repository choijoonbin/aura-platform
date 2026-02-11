# Pre-Test Checklist: Aura AI (Analyzer Role)

> **목적**: 1차 통합 테스트 진입 전 구현 반영 여부 확인  
> **일자**: 2026-02-11

---

## 1. [Role] DB 직접 쓰기 제거 — 분석·Redis만 수행

**기준**: 조치 이력·전표 관련 DB INSERT/UPDATE가 제거되고, 분석 결과 반환 및 Redis 발행에만 집중하는가?

| 확인 항목 | 소스 | 결과 |
|-----------|------|------|
| case_action_history / fi_doc_header 미사용 | `core/action_integrity/service.py` | DB 엔진·세션·INSERT/UPDATE 코드 없음. 주석·docstring으로 "Aura는 case_action_history / fi_doc_header에 INSERT/UPDATE하지 않습니다" 명시. |
| 분석 결과 반환·Redis 발행만 수행 | `core/action_integrity/service.py` | `_log_hitl_feedback()` + `build_notification_payload()` 후 Redis `publish()` 만 호출. |

**판정**: **PASS**  
- 참고: `core/analysis/rag.py`의 `INSERT INTO dwp_aura.rag_chunk` 는 RAG 지식베이스 적재용이며, 조치 이력·전표 DB와 무관.

---

## 2. [Analysis] Phase2에서 doc_id / item_id 인식·상세 내역 기반 추론

**기준**: 백엔드가 넘긴 `doc_id`, `item_id`를 인식하여 상세 내역 기반 추론을 수행하는가?

| 확인 항목 | 소스 | 결과 |
|-----------|------|------|
| body_evidence에서 doc_id 추출 | `core/analysis/phase2_pipeline.py` (239–249행) | `body_evidence.get("doc_id")` 또는 `body_evidence.get("document", {}).get("docKey")` 로 추출. |
| body_evidence에서 item_id 추출 | `core/analysis/phase2_pipeline.py` (244, 248행) | `body_evidence.get("item_id")` 로 추출. |
| 프롬프트에 반영 | `core/analysis/phase2_pipeline.py` (257–260행) | `doc_id` 또는 `item_id` 존재 시 `"백엔드에서 지정한 문서·항목(doc_id=..., item_id=...)에 대한 상세 내역을 우선 참고하여 규정 준수 여부를 판단"` 문구를 LLM 프롬프트에 추가. |

**판정**: **PASS**

---

## 3. [Notification] 3가지 상황에서 Redis 규격 발행

**기준**: `{ "type": "NOTIFICATION", "category": "...", "message": "...", "timestamp": "..." }` 규격으로 아래 3채널 발행하는가?

| 상황 | 채널 | 소스 | 결과 |
|------|------|------|------|
| 고위험 탐지 | `workbench:alert` | `core/analysis/phase2_pipeline.py` (383–394행) | `severity == "HIGH"` 시 `publish_workbench_notification(workbench_alert_channel, "AI_DETECT", "신규 이상 징후 탐지", ...)` 호출. 채널 기본값 `core/config.py` `workbench_alert_channel` = `"workbench:alert"`. |
| RAG 학습 완료 | `workbench:rag:status` | `core/analysis/rag.py` (216–225행) | `process_and_vectorize_pgvector` 성공 직후 `publish_workbench_notification_sync(workbench_rag_status_channel, "RAG_STATUS", "학습 완료", ...)` 호출. 기본값 `workbench_rag_status_channel` = `"workbench:rag:status"`. |
| 조치 결과 통보 | `workbench:case:action` | `core/action_integrity/service.py` (104–120행) | `record_case_action()` 내부에서 `build_notification_payload("CASE_ACTION", message, ...)` 후 `store.client.publish(case_action_redis_channel, ...)` 호출. 기본값 `case_action_redis_channel` = `"workbench:case:action"`. |

통일 포맷 생성: `core/notifications.py` — `build_notification_payload()` 가 `type: "NOTIFICATION"`, `category`, `message`, `timestamp` 및 extra 필드 구성.

**판정**: **PASS**

---

## 4. [HITL] 승인/거절 피드백 → 학습용 JSONL 로그 기록

**기준**: 사용자 승인/거절 피드백을 수신하여 HITL Feedback Log(학습용 JSONL)로 기록하는가?

| 확인 항목 | 소스 | 결과 |
|-----------|------|------|
| 피드백 구조화 로그 | `core/action_integrity/service.py` (29–54행) | `_log_hitl_feedback()`: `event`, `case_id`, `request_id`, `executor_id`, `action_type`, `approved`, `comment`, `doc_key`, `at` 를 JSON으로 `hitl_feedback` 로거에 기록. |
| JSONL 파일 적재 (설정 시) | `core/action_integrity/service.py` (56–63행) | `hitl_feedback_log_path` 설정 시 해당 경로에 JSONL 한 줄씩 append. |
| 조치 시 호출 | `core/action_integrity/service.py` (91–100행) | `record_case_action()` 진입 시 항상 `_log_hitl_feedback()` 호출 (승인/거절/타임아웃 모두). |
| 설정 | `core/config.py` (318–321행) | `hitl_feedback_log_path: str \| None` 필드로 JSONL 경로 지정 가능. |

**판정**: **PASS**  
- 로거 기록은 항상 수행되고, JSONL 파일 기록은 `hitl_feedback_log_path` 설정 시 수행됨.

---

## 요약

| # | 항목 | 판정 | 주요 소스 |
|---|------|------|------------|
| 1 | [Role] DB 직접 쓰기 제거, 분석·Redis만 | **PASS** | `core/action_integrity/service.py` |
| 2 | [Analysis] doc_id / item_id 인식·상세 추론 | **PASS** | `core/analysis/phase2_pipeline.py` |
| 3 | [Notification] 고위험/RAG/조치 3채널 규격 발행 | **PASS** | `core/notifications.py`, `core/analysis/phase2_pipeline.py`, `core/analysis/rag.py`, `core/action_integrity/service.py`, `core/config.py` |
| 4 | [HITL] 승인/거절 피드백 → 학습용 JSONL 로그 | **PASS** | `core/action_integrity/service.py`, `core/config.py` |

**전체**: **4/4 PASS** — 1차 통합 테스트 진입 조건 충족.
