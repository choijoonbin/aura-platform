# 프론트엔드: Finance Agent Stream API 연동 수정 요청

> **대상**: 프론트엔드 개발팀  
> **작성일**: 2026-02-06  
> **목적**: Finance 에이전트 스트리밍 API 요청 형식 수정

---

## 1. API 개요

**엔드포인트**: `POST /api/synapse/agent-tools/agents/finance/stream`  
(Gateway 경로, RewritePath 적용 시 Aura `/agents/finance/stream`로 전달)

**응답**: SSE (text/event-stream)

---

## 2. 요청 형식 (필수)

### Request Body (JSON)

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| **prompt** | string | ✅ (prompt 또는 message 중 하나) | 사용자 프롬프트/목표 |
| **message** | string | ✅ (prompt 또는 message 중 하나) | prompt와 동일 (필드명 호환용) |
| context | object | | caseId, documentIds 등 |
| goal | string | | 목표 (선택) |
| thread_id | string | | 스레드 ID (선택) |

**규칙**: `prompt` 또는 `message` 중 **반드시 하나**는 포함되어야 하며, **최소 1자** 이상이어야 합니다.

### 올바른 예시

```json
{ "prompt": "케이스 CS-001 조사 및 조치 제안", "context": { "caseId": "CS-001" } }
```

```json
{ "message": "중복송장 의심 케이스 조사", "context": { "caseId": "case-123" } }
```

### 잘못된 예시 (422 발생)

```json
{}
```
→ prompt 또는 message 필수

```json
{ "prompt": "", "message": "" }
```
→ 최소 1자 필요

```json
{ "context": { "caseId": "CS-001" } }
```
→ prompt 또는 message 없음

---

## 3. 요청 헤더

| 헤더 | 필수 | 설명 |
|------|------|------|
| Authorization | ✅ | Bearer {JWT} |
| X-Tenant-ID | ✅ | 테넌트 ID |
| Content-Type | ✅ | application/json |
| X-User-ID | | JWT sub와 일치 권장 |
| Last-Event-ID | | SSE 재연결 시 |

---

## 4. 수정 체크리스트

- [ ] 요청 Body에 `prompt` 또는 `message` 포함 (최소 1자)
- [ ] Content-Type: application/json
- [ ] 빈 객체 `{}` 전송 금지
- [ ] 케이스 상세 시 context에 caseId 포함 권장

---

## 5. 422 발생 시

`{"detail": [...]}` 응답에서 `detail` 배열의 `loc`(필드 경로)와 `msg`를 확인하여 누락된 필드를 수정하세요.
