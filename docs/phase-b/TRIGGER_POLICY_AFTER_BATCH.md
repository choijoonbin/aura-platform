# Phase B: Detection Batch 이후 Agentic Trigger 규칙

> **목표**: 배치가 케이스를 생성/업데이트하면, Aura는 조건에 따라 분석을 시작하거나 운영자 오픈 시 시작  
> **원칙**: 배치 단계에서 LLM 무조건 실행 금지, Trigger 조건은 정책 프로파일로 옵션화

---

## 1. Trigger 기본값 (권장)

### 1.1 Auto-start 조건

다음 조건을 **모두** 충족하면 자동으로 분석 시작:

| 조건 | 설명 |
|------|------|
| `severity >= HIGH` | 케이스 심각도가 HIGH 이상 (CRITICAL 포함) |
| `status == NEW` | 케이스 상태가 NEW |
| **또는** | |
| `status == ACTION_REQUIRED` | Action Required로 전환된 케이스 |

### 1.2 대기 (분석 미실행)

- 위 조건 미충족 시: **"대기"** 상태로만 기록
- 분석은 실행하지 않음
- 운영자가 케이스를 열 때(on-open) 시작

---

## 2. case created/updated 이벤트 수신 방식

### 2.1 수신 방식 (구현 기반 선택)

| 방식 | 설명 | Aura 역할 |
|------|------|-----------|
| **웹훅** | Synapse/배치가 `POST /api/aura/triggers/case-updated` 호출 | 엔드포인트 수신, 조건 평가 |
| **메시지 (Redis/Kafka)** | `case:created`, `case:updated` 토픽 구독 | 메시지 수신, 조건 평가 |
| **폴링** | 주기적으로 Synapse API에서 신규/변경 케이스 조회 | 폴링 작업, 조건 평가 |

**권장**: 웹훅 또는 메시지 (실시간성, 배치와 분리)

### 2.2 이벤트 페이로드 (최소)

```json
{
  "eventType": "case_created" | "case_updated",
  "caseId": "case-001",
  "caseKey": "CS-2026-0001",
  "tenantId": "1",
  "severity": "HIGH" | "MEDIUM" | "LOW" | "CRITICAL",
  "status": "NEW" | "OPEN" | "ACTION_REQUIRED" | "RESOLVED" | "...",
  "timestamp": "2026-02-01T12:00:00Z"
}
```

---

## 3. Auto-start 시 동작

조건 충족 시:

1. **SCAN_STARTED** audit 이벤트 발행
2. `POST /agents/finance/stream` 또는 내부 호출 (caseId, context)
3. tool로 evidence 수집 → analysis → plan → hitl_proposed(필요시) → END
4. **SCAN_COMPLETED** audit 이벤트 발행

---

## 4. 조건 미충족 시 (대기)

1. **대기** 상태로만 기록 (agent_activity_log 또는 audit)
2. `event_type`: `ANALYSIS_PENDING` 또는 `TRIGGER_WAITING`
3. `evidence_json`: `{"reason": "severity/status 미충족", "caseId": "...", "severity": "...", "status": "..."}`

---

## 5. On-open 경로 (운영자 케이스 오픈 시)

### 5.1 트리거

- 프론트엔드/백엔드가 운영자가 케이스 상세 화면을 열 때
- `GET /cases/{caseId}` 또는 케이스 오픈 API 호출 시

### 5.2 분석 시작

- **방식 A**: 프론트엔드가 케이스 오픈 시 `POST /agents/finance/stream` 호출 (context에 caseId)
- **방식 B**: 백엔드가 케이스 오픈 이벤트 수신 시 Aura trigger API 호출

### 5.3 재현 절차

1. 케이스 목록에서 케이스 클릭 (또는 `/cases/{caseId}` 이동)
2. 프론트엔드: `POST /api/aura/agents/finance/stream` — body: `{"prompt": "케이스 조사", "context": {"caseId": "case-001"}}`
3. Aura: start → evidence_gather → plan → ... → end

---

## 6. 정책 프로파일 (옵션화)

| 프로파일 | auto_start_severity_min | auto_start_statuses | 설명 |
|----------|-------------------------|---------------------|------|
| **default** | HIGH | NEW, ACTION_REQUIRED | 기본값 |
| **conservative** | CRITICAL | ACTION_REQUIRED | 최소 자동 시작 |
| **aggressive** | MEDIUM | NEW, OPEN, ACTION_REQUIRED | 더 많은 자동 시작 |

**설정 위치**: `core/config.py` 또는 환경 변수

---

## 7. Definition of Done

- [x] 배치로 생성된 케이스 중 HIGH 이상 자동 분석 시작 조건 문서화
- [x] 조건 미충족 시 "대기" 상태 로그/이벤트 명세
- [x] 케이스 오픈 시 분석 시작(on-open) 경로 문서화 및 재현 절차
- [ ] 실제 웹훅/메시지/폴링 수신 구현 (추후)
