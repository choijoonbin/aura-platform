# Aura Platform AI 기능 적용 상세 가이드

> **목적**: 프로젝트에 개발된 Agentic AI의 기능, 트리거, 동작 방식을 이해하기 쉽게 정리  
> **대상**: 신규 팀원, PM, FE/BE 연동 담당자  
> **작성일**: 2026-02

---

## 1. 개요

Aura-Platform은 **LangGraph** 기반의 에이전틱 AI 시스템으로, 부서별 특화 에이전트를 제공합니다. 각 에이전트는 **LLM(OpenAI/Azure OpenAI)** 과 **도구(Tools)** 를 조합하여 복잡한 업무를 자동화합니다.

### 1.1 에이전트 목록

| 에이전트 | 도메인 | API 경로 | 용도 |
|----------|--------|----------|------|
| **Code Agent** | Dev | `POST /agents/chat`, `POST /agents/chat/stream` | 코드 분석, Git/GitHub 작업 |
| **Enhanced Agent** | Dev | `POST /agents/v2/chat/stream`, `POST /aura/test/stream` | 고도화된 코드 분석 (사고 과정 추적, HITL) |
| **Finance Agent** | Finance | `POST /agents/finance/stream` | 중복송장 케이스 조사, 조치 제안 |

---

## 2. LLM 통합

### 2.1 LLM 클라이언트

- **파일**: `core/llm/client.py`
- **지원**: OpenAI API / Azure OpenAI
- **설정**: `core/config.py` — `use_azure_openai`, `openai_model`, `azure_openai_deployment` 등
- **역할**: 모든 에이전트가 `get_llm_client()`를 통해 동일한 LLM 인스턴스를 사용

### 2.2 도메인별 시스템 프롬프트

- **파일**: `core/llm/prompts.py`
- **함수**: `get_system_prompt(domain, context=...)`

| domain | 용도 |
|--------|------|
| `base` | 기본 Aura 어시스턴트 |
| `dev` | Dev 에이전트 (Git, Jira, 코드 리뷰) |
| `finance` | Finance 에이전트 (케이스 조사, Synapse 도구) |
| `code_review` | 코드 리뷰 전용 |
| `issue_manager` | Jira 이슈 관리 전용 |

**Context 주입**: `context` dict에서 `activeApp`, `selectedItemIds`, `caseId`, `documentIds` 등을 추출하여 프롬프트에 반영합니다.

---

## 3. Code Agent (Dev 기본)

### 3.1 기능

- Git/GitHub 도구를 활용한 코드 분석, PR 분석
- LangGraph 단순 루프: `agent` → `tools` → `agent` (도구 호출 필요 시)
- HITL 없음 (승인 대기 없이 바로 실행)

### 3.2 트리거 (언제 실행되는가)

| API | 메서드 | 설명 |
|-----|--------|------|
| `POST /agents/chat` | 일반 | 스트리밍 없이 전체 응답 반환 |
| `POST /agents/chat/stream` | 스트리밍 | SSE로 스트리밍 응답 |

### 3.3 동작 흐름

```
[시작] → agent (LLM 호출) → 도구 필요? 
                              ├─ Yes → tools (도구 실행) → agent (반복)
                              └─ No  → END
```

- **agent 노드**: LLM에 시스템 프롬프트 + 사용자 메시지 전달, 도구 선택
- **tools 노드**: LangGraph `ToolNode` — 선택된 도구 실행
- **도구**: `GIT_TOOLS` + `GITHUB_TOOLS` (git_tool, github_tool)

### 3.4 코드 위치

- 에이전트: `domains/dev/agents/code_agent.py`
- 라우트: `api/routes/agents.py`

---

## 4. Enhanced Agent (Dev 고도화)

### 4.1 기능

- **사고 과정 추적**: analysis, planning, reasoning, decision, reflection
- **단계별 계획**: plan_steps (confidence 포함)
- **실행 로그**: execution_logs
- **HITL Interrupt**: `git_merge`, `github_create_pr`, `github_merge_pr` 실행 전 승인 대기
- **Source Attribution**: 참고 소스(파일 경로 등) 추출

### 4.2 트리거 (언제 실행되는가)

| API | 메서드 | 설명 |
|-----|--------|------|
| `POST /agents/v2/chat/stream` | 스트리밍 | 프론트엔드 명세 v1.0용 |
| `POST /aura/test/stream` | 스트리밍 | dwp-backend 연동용 (Gateway: `/api/aura/test/stream`) |

### 4.3 동작 흐름

```
[시작] → analyze → plan → execute → 도구 필요?
                                    ├─ Yes → tools (HITL 도구면 interrupt) → reflect
                                    └─ No  → reflect → END
```

| 노드 | 역할 |
|------|------|
| **analyze** | 사용자 요청 분석, thoughtType: analysis |
| **plan** | LLM으로 실행 계획 수립, plan_steps 생성 |
| **execute** | LLM 호출 및 도구 선택, confidence 계산 |
| **tools** | 도구 실행. HITL 도구면 `pending_approvals`에 추가 후 대기 (실제 interrupt는 Enhanced Agent에서 상태만 저장, route에서 Redis 대기) |
| **reflect** | 결과 검토, 최종 content 생성 |

### 4.4 HITL 도구

- `git_merge`
- `github_create_pr`
- `github_merge_pr`

**HITL 처리 방식**: Enhanced Agent의 `_tools_node`는 승인 필요 도구를 `pending_approvals`에 추가하고 도구 실행을 보류합니다. **aura_backend** route의 `event_generator`에서 `pending_approvals` 감지 시:
1. HitlManager에 승인 요청 저장
2. SSE `hitl` 이벤트 발행
3. `wait_for_approval_signal()`로 Redis `hitl:channel:{session_id}` 구독
4. 승인 시 스트림 계속, 거절/타임아웃 시 `failed`/`error` 이벤트 후 종료

### 4.5 SSE 이벤트

- `start` → `thought` → `plan_step` → `tool_execution` → `content` → `end`
- `hitl`: 승인 요청 시 (aura_backend 경로)

### 4.6 코드 위치

- 에이전트: `domains/dev/agents/enhanced_agent.py`
- 라우트: `api/routes/agents_enhanced.py`, `api/routes/aura_backend.py`
- Hook: `domains/dev/agents/hooks.py`

---

## 5. Finance Agent (재무 도메인)

### 5.1 기능

- **중복송장 의심 케이스 조사** 및 조치 제안
- **Synapse 백엔드 Tool API**를 통한 데이터 조회 (Aura는 Postgres 직접 접근 없음)
- **evidence 수집**: 규정 인용, 통계, 원천 링크
- **HITL**: `propose_action` 등 위험 액션은 **LangGraph `interrupt()`** 로 승인 대기 후 resume

### 5.2 트리거 (언제 실행되는가)

| API | 메서드 | 설명 |
|-----|--------|------|
| `POST /agents/finance/stream` | 스트리밍 | Finance 에이전트 SSE 스트리밍 (Gateway: `/api/aura/agents/finance/stream` 등) |

**요청 Body**:
```json
{
  "prompt": "중복송장 의심 케이스 CS-2026-0001 조사 후 조치 제안",
  "goal": "중복송장 의심 케이스 조사 및 조치 제안",
  "context": {
    "caseId": "case-001",
    "documentIds": ["doc-1", "doc-2"],
    "entityIds": ["ent-1"],
    "openItemIds": ["oi-1"]
  },
  "thread_id": "optional"
}
```

### 5.3 동작 흐름

```
[시작] → analyze → plan → execute → 도구 필요?
                                    ├─ Yes → tools (propose_action이면 interrupt) → reflect
                                    └─ No  → reflect → END
```

| 노드 | 역할 |
|------|------|
| **analyze** | 목표 및 컨텍스트 분석, thought_chain에 analysis 추가 |
| **plan** | LLM으로 조사/조치 계획 수립, plan_steps 생성 |
| **execute** | LLM 호출, Synapse 도구 선택 |
| **tools** | 도구 실행. **propose_action**이면 `interrupt(payload)` 호출 → Redis `hitl:channel:{session_id}` 대기 → 승인/거절 수신 후 `Command(resume=...)`로 재개 |
| **reflect** | 조사 결과 검토, 최종 응답 생성 |

### 5.4 Finance 도구 목록

| 도구 | 설명 | HITL |
|------|------|------|
| `get_case` | 케이스 상세 조회 | ❌ |
| `search_documents` | 문서 검색 | ❌ |
| `get_document` | 단일 문서 조회 (bukrs, belnr, gjahr) | ❌ |
| `get_entity` | 엔티티 조회 | ❌ |
| `get_open_items` | 미결 항목 조회 | ❌ |
| `simulate_action` | 액션 시뮬레이션 (실행 없이 결과 확인) | ❌ |
| `propose_action` | 액션 제안 (write_off, clear 등) | ✅ **승인 필요** |
| `execute_action` | 승인 완료된 액션 실행 | ❌ |

**코드**: `tools/synapse_finance_tool.py` — `FINANCE_TOOLS`, `FINANCE_HITL_TOOLS = {"propose_action"}`

### 5.5 HITL 동작 (Finance)

1. **propose_action** 호출 시: `_tools_node`에서 `interrupt(payload)` 실행
2. **Checkpoint 저장**: LangGraph가 현재 상태를 checkpoint에 저장
3. **Redis 저장**: `HitlManager.save_approval_request()` — `hitl:request:{request_id}`, `hitl:session:{session_id}`
4. **SSE hitl 이벤트**: 클라이언트에 `requestId`, `sessionId` 전달
5. **승인 대기**: `HitlManager.wait_for_approval_signal()` — Redis `hitl:channel:{session_id}` 구독
6. **승인/거절**: Synapse 백엔드가 사용자 승인 시 Redis에 `{"type":"approval","approved":true}` 발행
7. **재개**: `agent.stream(resume_value={"approved": true})` — `Command(resume=...)`로 그래프 재개

### 5.6 Audit 이벤트

- **SCAN_STARTED**: analyze 노드 시작
- **SCAN_COMPLETED**: tools 노드 종료 (processed_count, duration_ms)
- **REASONING_COMPOSED**: reflect 노드 종료 (case_id)
- **ACTION_PROPOSED**, **ACTION_APPROVED**: HITL 관련 (finance_agent route, synapse_finance_tool)

### 5.7 SSE 이벤트 순서

```
start → thought → plan_step → tool_execution → [hitl (필요시)] → content → end → [DONE]
```

### 5.8 코드 위치

- 에이전트: `domains/finance/agents/finance_agent.py`
- 도구: `tools/synapse_finance_tool.py`
- 라우트: `api/routes/finance_agent.py`
- Hook: `domains/finance/agents/hooks.py`
- HITL: `core/memory/hitl_manager.py`

---

## 6. HITL (Human-In-The-Loop) 통합

### 6.1 구현 방식 비교

| 에이전트 | HITL 방식 | 대기 위치 |
|----------|-----------|-----------|
| **Enhanced Agent** | `pending_approvals` 상태 저장 | aura_backend route (Redis 구독) |
| **Finance Agent** | LangGraph `interrupt()` | finance_agent route (HitlManager.wait_for_approval_signal) |

### 6.2 Redis 채널

- **발행**: Synapse 백엔드 (사용자 승인 시)
- **구독**: Aura-Platform `HitlManager`
- **채널**: `hitl:channel:{session_id}`

### 6.3 Redis 키

| 키 | TTL | 내용 |
|----|-----|------|
| `hitl:request:{request_id}` | 30분 | requestId, sessionId, actionType, context |
| `hitl:session:{session_id}` | 60분 | sessionId, requestId, userId, tenantId |

---

## 7. SSE 이벤트 스키마

### 7.1 공통 필드 (P0-2 적용 후)

모든 SSE `data`에 포함:
- `trace_id`, `tenant_id`, `user_id`, `case_id` (context에 있을 때)

### 7.2 이벤트 타입

| event | 설명 |
|-------|------|
| `start` | 스트림 시작 |
| `thought` | 사고 과정 (thoughtType: analysis, planning, reasoning, reflection) |
| `plan_step` | 계획 단계 (stepId, description, status, confidence) |
| `tool_execution` | 도구 실행 (toolName, toolArgs, status, requiresApproval) |
| `hitl` | 승인 요청 (requestId, sessionId, actionType, message, context) |
| `content` | 최종 응답 콘텐츠 |
| `end` | 스트림 종료 |
| `error` | 에러 |
| `failed` | HITL 타임아웃 등 실패 |

### 7.3 Last-Event-ID

- **지원**: id 연속성만 (replay 미지원)
- **재연결 시**: 새 스트림 시작, event id만 `Last-Event-ID + 1`부터 이어 붙임

---

## 8. 요약 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Aura Platform API Layer                          │
├─────────────────────────────────────────────────────────────────────────┤
│  /agents/chat          │ Code Agent      │ Git, GitHub 도구              │
│  /agents/chat/stream   │                 │ HITL 없음                     │
├────────────────────────┼─────────────────┼──────────────────────────────┤
│  /agents/v2/chat/stream│ Enhanced Agent  │ Git, GitHub 도구              │
│  /aura/test/stream     │                 │ HITL: merge, create_pr 등    │
├────────────────────────┼─────────────────┼──────────────────────────────┤
│  /agents/finance/stream│ Finance Agent   │ Synapse Tool API (8개 도구)   │
│                        │                 │ HITL: propose_action         │
└────────────────────────┴─────────────────┴──────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  LLM (OpenAI / Azure OpenAI)  │  Redis (HITL, Audit)  │  Synapse (Finance)│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. 참고 문서

- [SSE/HITL 실행 체크리스트](./SSE_HITL_EXECUTION_CHECKLIST.md)
- [Aura Platform 통합 가이드](./AURA_PLATFORM_INTEGRATION_GUIDE.md)
- [프론트엔드 v1 스펙](./FRONTEND_V1_SPEC.md)
- [Audit Event 명세](./AUDIT_EVENTS_SPEC.md)
