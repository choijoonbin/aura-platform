# Changelog

All notable changes to the Aura-Platform project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Case Detail 탭 실데이터 연결 (Prompt C P0-P2)** (2026-02-06)
  - P0: `GET /api/aura/cases/{caseId}/stream` — SSE Agent Stream, Last-Event-ID replay, in-memory ring buffer
  - P0: `POST /api/aura/cases/{caseId}/stream/trigger` — 수동 트리거 (admin 전용)
  - P1: `GET /api/aura/cases/{caseId}/rag/evidence` — RAG evidence 목록 (Synapse search_documents)
  - P1: `GET /api/aura/cases/{caseId}/similar` — 유사 케이스 (규칙 기반)
  - P1: `GET /api/aura/cases/{caseId}/confidence` — Confidence score breakdown
  - P2: `GET /api/aura/cases/{caseId}/analysis` — Analysis summary (template+facts)
  - `core/streaming/case_stream_store.py` — CaseStreamStore, CaseStreamEvent
  - `api/routes/aura_cases.py` — Case Detail 탭 API 라우트
  - `docs/prompts/PHASE_Cases_Aura_Bindings_P0-P2.md` — 구현 문서
- **E2E 재테스트 체크리스트 (P0/P1)** (2026-02-01)
  - P0-4: HITL payload에 proposal_id, action_type, evidence_refs 포함 (severity>=HIGH & status==NEW → hitl_proposed)
  - P1: 중복 트리거 방지 — caseId+updated_at 기반 dedup (웹훅 payload에 updatedAt 필드 추가)
  - `docs/phase-0/aura/event-schema.md`: hitl 이벤트 스키마 보강
- **Follow-up: P1 Evidence 확장 + Audit 정합** (2026-02-01)
  - P1-lineage: `get_lineage` 도구 추가, evidence_gather에서 lineage 4번째 evidence로 수집
  - P1-audit: SCAN_STARTED/COMPLETED에 caseId, caseKey, resource_type/resource_id 포함 (케이스 상세 추적)
  - SCAN_COMPLETED: tools 노드 미경유 시 reflect에서 발행 (tools 없이 완료된 run도 audit 추적)
  - `docs/phase-0/aura/tools-contract.md`: get_lineage, lineage evidence_refs 규칙 추가
- **Phase 0/A/B 작업** (2026-02-01)
  - Phase 0: docs/phase-0/aura/ — event-schema, tools-contract, state-sync
  - Phase A: evidence_gather 노드, evidence_refs 3종, hitl proposal payload, hooks 보강
  - Phase B: docs/phase-b/TRIGGER_POLICY_AFTER_BATCH.md — auto-start, on-open 규칙
- **AI 기능 적용 상세 가이드** (2026-02-01)
  - `docs/guides/AGENTIC_AI_FEATURES_GUIDE.md`: 에이전트별 기능, 트리거, 동작 흐름, 도구, HITL, LLM 통합
- **SSE/HITL 추가 작업 여부 확인** (2026-02-01)
  - `docs/guides/SSE_HITL_ADDITIONAL_WORK_VERIFICATION.md`: P0/P1/P2 완료 검증, 4항목 ✅ 확정, "Aura 추가 작업 없음" 결론
- **SSE/HITL P0 실행 체크리스트 구현 (P0-1, P0-2)** (2026-02-01)
  - P0-1: Finance stream `X-User-ID` 헤더 수용 및 JWT `sub` 검증 — 불일치 시 SSE `event: error` + [DONE] (aura_backend 패턴 통일)
  - P0-2: `_enrich_event_data`에 `user_id` 추가 — 모든 SSE 이벤트 payload에 trace_id, tenant_id, user_id, case_id 일관 포함
  - `docs/guides/SSE_HITL_EXECUTION_CHECKLIST.md`: 실행 체크리스트, DoD, 검증 시나리오, FE/BE 계약 문구
- **Agent Stream 실제 로그 연동 (Prompt C)** (2026-02-01)
  - agent_event 스키마: tenantId, timestamp, stage, message, caseKey/caseId, severity, traceId
  - Aura → Synapse REST push: POST /api/synapse/agent/events (batch)
  - Audit 발행 시 자동 Agent Stream push (core/audit/writer 연동)
  - stage 매핑: SCAN/DETECT/ANALYZE/SIMULATE/EXECUTE/MATCH
  - scripts/seed_agent_stream_events.py: 20건+ 샘플 이벤트 시드
  - docs/guides/AGENT_STREAM_SPEC.md
- **Audit Event 대시보드 보강 (C-1/C-2/C-3)** (2026-02-01)
  - C-1: event_category CASE 추가, SIMULATION_RUN→ACTION 카테고리, case_created/case_status_changed/case_assigned 헬퍼
  - C-2: evidence_json correlation 키(traceId, gatewayRequestId, caseId, caseKey, actionId) 보장, context에 case_id/case_key 추가
  - C-3: DETECTION_FOUND tags(driverType, severity), ACTION_PROPOSED 승인대기 시점 기록
  - `core/context.py`: set_request_context에 case_id, case_key 파라미터 추가
  - `api/routes/finance_agent.py`: 요청 context에서 caseKey 추출 후 set_request_context 전달
  - `docs/handoff/AUDIT_DASHBOARD_CONFIRMATION_ITEMS.md`: 시스템별 확인사항 정리
- **Finance Agent HITL interrupt/resume (LangGraph + Checkpointer)** (2026-02-03)
  - LangGraph `interrupt()` 기반 HITL: `_tools_node`에서 propose_action 등 승인 필요 시 `interrupt(payload)` 호출
  - `Command(resume=...)`로 재개: route에서 Redis Pub/Sub 신호 수신 후 `stream(resume_value=...)` 호출
  - `approval_results` state: 승인/거절 결과를 agent state에 반영 (audit용)
  - Checkpointer: `core/memory/checkpointer_factory.py` - SqliteSaver(영속) 또는 MemorySaver(폴백)
  - `langgraph-checkpoint-sqlite` 의존성 추가 (pyproject.toml)
  - HITL 통합 테스트: `test_finance_stream_hitl_interrupt_resume` (Redis/HITL Manager mock)
- **Finance Agent Runtime 안정화 (운영형)** (2026-02-03)
  - Tool 호출 표준화: X-Tenant-ID, X-User-ID, X-Trace-ID, X-Idempotency-Key 헤더
  - 5xx/timeout 시 exponential backoff 재시도 (synapse_max_retries)
  - simulate/execute 멱등성: idempotency key로 중복 방지
  - HITL 타임아웃: hitl_timeout_seconds 설정, 만료 시 failed/error/end 이벤트
  - SSE 이벤트 순서 문서화, Last-Event-ID dedupe
  - pytest: tool mocking, idempotency, SSE 순서 검증
- **SSE 이벤트 페이로드 스키마 버전(version) 필드**
  - 모든 SSE 이벤트 페이로드에 `version: "1.0"` 포함 (권장 스펙)
  - `api/schemas/events.py`: `SSEEventPayloadBase` 및 상수 `SSE_EVENT_PAYLOAD_VERSION` 추가, 각 이벤트 모델 상속
  - `api/schemas/hitl_events.py`: `HITLEvent`에 `version` 필드 추가
  - `api/routes/aura_backend.py`: `format_sse_event`에서 누락 시 `version` 자동 보강
- **SSE 재연결 정책 문서** (`docs/backend-integration/SSE_RECONNECT_POLICY.md`)
  - 모든 SSE 이벤트에 `id: <eventId>` 필수 여부 코드 근거
  - Last-Event-ID 수신 시 그 이후 이벤트만 재전송 정책 및 구현 근거
  - 중복/순서: At-least-once + 클라이언트 dedupe(id) 기준 문서화
  - 모든 서버 종료 경로에서 `data: [DONE]\n\n` 보장 근거 및 테스트 시나리오(중간 끊김, 재연결, 중복 클릭, HITL 대기 포함)

### Planned
- Database session management (SQLAlchemy)
- Code Review Agent 특화
- Jira, Slack 통합
- Performance optimization

---

## [0.3.4] - 2026-01-16

### Added
- **통합 테스트 문서 작성**
  - `docs/integration-tests/INTEGRATION_TEST_SUMMARY.md`: 통합 테스트 전체 요약
  - `docs/integration-tests/AURA_PLATFORM_INTERNAL_TEST.md`: Aura-Platform 내부 동작 검증 가이드
    - SSE 이벤트 스키마 준수 검증
    - LangGraph Interrupt 검증 (HITL 중단 및 체크포인트 저장)
    - 승인 신호 대기 및 재개 검증
    - Context 활용 검증 (프롬프트 동적 반영)
    - 종료 플래그 검증 (`data: [DONE]` 전송)
  - `docs/integration-tests/BACKEND_INTEGRATION_TEST.md`: 백엔드 팀용 통합 테스트 가이드
  - `docs/integration-tests/FRONTEND_INTEGRATION_TEST.md`: 프론트엔드 팀용 통합 테스트 가이드
  - 각 모듈별 상세 테스트 시나리오 및 검증 방법 포함
  - React 예제 코드 및 문제 해결 가이드 포함

---

## [0.3.3] - 2026-01-16

### Added
- **백엔드 통합 체크리스트 응답 구현**
  - X-User-ID 헤더 검증: JWT `sub`와 `X-User-ID` 헤더 값 일치 확인
  - 불일치 시 에러 이벤트 전송 및 요청 중단
  - `docs/backend-integration/BACKEND_INTEGRATION_RESPONSE.md`: 백엔드 응답 문서 추가

### Changed
- `api/routes/aura_backend.py`:
  - `X-User-ID` 헤더 파라미터 추가
  - JWT `sub`와 `X-User-ID` 일치 검증 로직 추가
  - 불일치 시 즉시 에러 이벤트 전송 및 요청 중단

### Documentation
- **요청 본문 크기 제한 가이드**
  - Gateway 기본 제한: 256KB
  - `context` 데이터 최적화 권장사항
  - 큰 데이터 처리 방법 안내

---

## [0.3.2] - 2026-01-16

### Added
- **백엔드 검증 문서 응답 구현**
  - SSE 이벤트 ID 포함: 각 이벤트에 `id: {event_id}` 라인 추가 (재연결 지원)
  - Last-Event-ID 헤더 처리: 재연결 시 중단 지점부터 이벤트 재개
  - SSE 응답 헤더 설정: Content-Type, Cache-Control, Connection, X-Accel-Buffering
  - `docs/backend-integration/BACKEND_VERIFICATION_RESPONSE.md`: 백엔드 검증 문서 응답 추가
  - 모든 백엔드 검증 요구사항 구현 완료 ✅

### Changed
- `api/routes/aura_backend.py`:
  - `format_sse_event` 함수에 `event_id` 파라미터 추가
  - 모든 SSE 이벤트에 고유 ID 부여 (Unix timestamp 기반)
  - `Last-Event-ID` 헤더 읽기 및 처리 로직 추가
  - 이벤트 ID 카운터를 통한 순차적 ID 생성

---

## [0.3.1] - 2026-01-16

### Added
- **DWP Backend 연동 구현 완료 (Aura-Platform 측)**
  - `api/routes/aura_backend.py`: 백엔드 연동용 SSE 스트리밍 엔드포인트
    - `GET /aura/test/stream`: 백엔드 요구 형식 준수 (event: {type}\ndata: {json})
    - 5가지 이벤트 타입: thought, plan_step, tool_execution, hitl, content
  - `core/memory/hitl_manager.py`: HITL Manager 구현
    - Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
    - 승인 요청 저장/조회 (`hitl:request:{requestId}`, `hitl:session:{sessionId}`)
    - 승인 신호 대기 및 처리 (타임아웃 300초)
  - `api/schemas/hitl_events.py`: HITL 이벤트 스키마
  - HITL API 엔드포인트:
    - `GET /aura/hitl/requests/{request_id}`: 승인 요청 조회
    - `GET /aura/hitl/signals/{session_id}`: 승인 신호 조회
  - 전달 문서:
    - `docs/handoff/BACKEND_HANDOFF.md`: 백엔드 전달 문서
    - `docs/handoff/FRONTEND_HANDOFF.md`: 프론트엔드 전달 문서
    - `docs/backend-integration/INTEGRATION_STATUS.md`: 통합 상태 요약
- **백엔드 HITL API 구현 완료 확인** (2026-01-16)
  - 백엔드에서 HITL 승인/거절 API 구현 완료 확인
  - `docs/updates/AURA_PLATFORM_UPDATE.md`: 백엔드 업데이트 문서 추가
  - 전체 통합 진행률: 100% ✅
  - 통합 테스트 준비 완료

### Fixed
- **JWT Python-Java 호환성 개선**
  - `exp`와 `iat` 클레임을 Unix timestamp (초 단위 정수)로 변환
  - JWT 표준 준수 (RFC 7519)
  - `SECRET_KEY` 또는 `JWT_SECRET` 환경 변수 지원
  - 시크릿 키 최소 길이 검증 (32바이트)
  - 불필요한 datetime 비교 로직 제거 (jwt.decode가 자동 검증)
  
- **테스트 및 문서**
  - `scripts/test_jwt_compatibility.py`: JWT 호환성 테스트 추가
  - `docs/guides/JWT_COMPATIBILITY.md`: Python-Java 호환성 가이드 추가

### Changed
- **포트 변경**: API 포트 8000 → 9000 (포트 충돌 해결)
  - `core/config.py`: `api_port` 기본값 변경
  - Auth Server와 포트 분리 완료
- `TokenPayload.exp`, `TokenPayload.iat`: `datetime` → `int` (Unix timestamp)
- `create_access_token()`: Unix timestamp 변환 로직 추가
- `verify_token()`: 자동 만료 검증 (추가 로직 제거)
- `core/config.py`: `JWT_SECRET` 환경 변수 지원 추가

---

## [0.3.0] - 2026-01-15

### Added
- **Phase 3 Completion: Dev Domain - 에이전트 & 도구**
  
- **Git 통합 도구**
  - `tools/base.py`: 도구 기본 클래스
  - `tools/integrations/git_tool.py`: 로컬 Git 작업 도구
    - git_diff: Git diff 조회
    - git_log: 커밋 로그 조회
    - git_status: Git 상태 확인
    - git_show_file: 특정 커밋의 파일 내용
    - git_branch_list: 브랜치 목록
    - @tool 데코레이터 사용 (LangChain)
  
- **GitHub 통합 도구**
  - `tools/integrations/github_tool.py`: GitHub API 통합
    - GitHubClient: 비동기 GitHub API 클라이언트
    - github_get_pr: PR 정보 조회
    - github_list_prs: PR 목록 조회
    - github_get_pr_diff: PR 변경 파일 목록
    - github_get_file: 파일 내용 조회
    - Personal Access Token 지원
  
- **LangGraph 에이전트**
  - `domains/dev/agents/code_agent.py`: 코드 분석 에이전트
    - AgentState: 에이전트 상태 타입
    - StateGraph: LangGraph 워크플로우
    - 도구 자동 선택 및 실행
    - 조건부 엣지 (도구 호출 여부)
    - 스트리밍 지원 (astream)
    - user_id, tenant_id 컨텍스트 관리
  
- **SSE API 엔드포인트**
  - `api/routes/agents.py`: 에이전트 실행 API
    - POST /agents/chat: 일반 모드 (전체 응답)
    - POST /agents/chat/stream: 스트리밍 모드 (SSE)
    - GET /agents/tools: 도구 목록 조회
    - GET /agents/health: 에이전트 헬스체크
    - JWT 인증 필수 (CurrentUser)
    - X-Tenant-ID 헤더 지원
    - 실시간 이벤트 스트리밍
      - agent_message: LLM 응답
      - tool_calls: 도구 호출
      - tool_result: 도구 실행 결과
  
- **테스트 스크립트**
  - `scripts/test_agent_stream.py`: 에이전트 테스트
    - 기본 에이전트 동작
    - 도구 사용 검증
    - 스트리밍 이벤트 확인

### Changed
- **Main Application**
  - `main.py`: 에이전트 라우터 등록
  - /agents/* 엔드포인트 활성화

### Security
- 모든 에이전트 API에 JWT 인증 적용
- Tenant ID 검증
- 도구 실행 권한 확인

---

## [0.2.0] - 2026-01-15

### Added
- **Phase 2 Completion: Core 확장 - 지능형 메모리 & 보안**
  
- **Redis & LangGraph Checkpointer**
  - `core/memory/redis_store.py`: Redis 기반 저장소 구현
    - RedisStore 클래스: 기본 Redis 작업 (get, set, delete, JSON 지원)
    - LangGraphCheckpointer 클래스: 에이전트 상태 저장/복원
    - Checkpoint 저장, 로드, 리스트, 삭제 기능
    - 에이전트가 중단된 지점에서 재개 가능한 구조
  - TTL 설정: 일반 캐시 24시간, Checkpoint 7일
  
- **대화 메모리 시스템**
  - `core/memory/conversation.py`: 대화 히스토리 관리
    - ConversationHistory 클래스: 메시지 저장/조회
    - Message 모델: role, content, timestamp, metadata
    - 멀티테넌시 지원 (tenant_id 기반)
    - LLM 컨텍스트 자동 생성 함수
    - 최대 메시지 개수 제한 (기본 100개)
  
- **LLM Streaming 지원**
  - `core/llm/client.py`: 비동기 스트리밍 추가
    - `astream()` 메서드: AsyncGenerator로 실시간 응답
    - React 프론트엔드 SSE 연동 준비
    - 메시지 타입 변환 유틸리티 함수
  
- **JWT 인증 시스템**
  - `core/security/auth.py`: JWT 기반 인증
    - AuthService 클래스: 토큰 생성/검증
    - TokenPayload 모델: JWT 페이로드 구조
    - User 모델: 사용자 정보 (user_id, tenant_id, role)
    - dwp_backend와 동일한 SECRET_KEY 사용 설계
    - Bearer Token 추출 유틸리티
  
- **RBAC 권한 관리**
  - `core/security/permissions.py`: 역할 기반 권한
    - UserRole enum: Admin, Manager, User, Guest
    - Permission enum: 11가지 세밀한 권한 정의
    - PermissionService 클래스: 권한 확인 로직
    - 역할별 권한 매핑 (ROLE_PERMISSIONS)
  
- **API 미들웨어**
  - `api/middleware.py`: 4가지 미들웨어 구현
    - AuthMiddleware: JWT 검증 및 사용자 인증
    - TenantMiddleware: X-Tenant-ID 헤더 처리
    - RequestLoggingMiddleware: 요청/응답 로깅
    - ErrorHandlingMiddleware: 통합 에러 처리
    - 인증 제외 경로 설정 (/, /health, /docs 등)
  
- **의존성 주입**
  - `api/dependencies.py`: FastAPI 의존성 함수들
    - get_current_user: 인증된 사용자 반환
    - get_tenant_id: 테넌트 ID 추출
    - require_permission: 권한 확인 의존성
    - 타입 별칭: CurrentUser, TenantId, AgentExecutor 등

### Changed
- **Configuration Updates**
  - `core/config.py`: Redis 설정 확장
    - redis_ttl: 일반 캐시 TTL (기본 24시간)
    - redis_checkpoint_ttl: Checkpoint TTL (기본 7일)
    - allowed_origins: CORS 허용 Origin 리스트
    - require_auth: 인증 필수 여부 플래그 (개발 모드용)
  
- **Main Application**
  - `main.py`: 라이프사이클 및 미들웨어 통합
    - Lifespan 컨텍스트: Redis 연결 초기화/정리
    - 로깅 설정 추가
    - 커스텀 미들웨어 적용
    - CORS 설정을 allowed_origins로 변경

- **Dependencies**
  - `requirements.txt`: 보안 패키지 추가
    - python-jose[cryptography]: JWT 처리
    - passlib[bcrypt]: 비밀번호 해싱
    - redis[hiredis]: Redis 성능 향상

### Documentation
- Updated README.md with Phase 2 completion
- Module __init__.py files updated with exports
- Added comprehensive docstrings to all new modules

---

## [0.1.1] - 2026-01-15

### Added
- **Phase 1 Completion: Environment Setup & First Run**
  - Generated secure SECRET_KEY automatically
  - Created `.env` file with all required environment variables
  - Set up Python virtual environment (venv)
  - Successfully installed all dependencies via pip
  
- **Core Module Implementation**
  - `core/config.py`: Complete Pydantic Settings-based configuration
    - OpenAI API configuration
    - Database and Redis settings
    - Security configuration (JWT)
    - Logging and domain-specific settings
    - Validation logic for environment and log level
  - `core/llm/client.py`: LangChain ChatOpenAI wrapper
    - Async/sync LLM invocation support
    - Configuration override capability
    - Global instance caching
  - `core/llm/prompts.py`: System prompt templates
    - Base system prompt
    - Dev Domain specialized prompts
    - Code review and issue manager prompts
    
- **FastAPI Application**
  - `main.py`: Basic API server with Uvicorn
  - Root endpoint (`/`) with welcome message
  - Health check endpoint (`/health`)
  - CORS middleware configuration
  - Auto-generated API documentation (Swagger UI, ReDoc)
  
- **Documentation**
  - `docs/updates/SETUP_SUCCESS.md`: Detailed setup completion report
  - `docs/guides/QUICK_START.md`: Quick start guide for developers
  - `scripts/test_setup.py`: Automated setup verification script
    - Tests imports, configuration, LLM client, project structure, and .env file
    - 5/5 tests passing ✅
    
- **Server Verification**
  - Successfully started Uvicorn server on http://0.0.0.0:8000
  - Verified all API endpoints working correctly
  - Swagger UI accessible at http://localhost:8000/docs

### Changed
- Updated README.md to reflect Phase 1 completion
  - Moved completed tasks from "In Progress" to "Completed"
  - Added detailed Phase 1 accomplishments
  - Reorganized upcoming phases (2-5)

### Fixed
- Pydantic v2 compatibility issue in `core/config.py`
  - Removed duplicate `Config` class (incompatible with `model_config`)
  - Now using only `model_config` attribute

### Infrastructure
- Python virtual environment: `/venv`
- Installed packages:
  - LangGraph 1.0.6
  - LangChain 1.2.4
  - LangChain-OpenAI 1.1.7
  - FastAPI 0.128.0
  - Uvicorn 0.40.0
  - Pydantic 2.12.5

---

## [0.1.0] - 2026-01-15

### Added
- **Project Initialization**
  - Created modular directory structure (core, domains, api, tools, database)
  - Organized subdirectories for each module (llm, memory, security, agents, workflows, etc.)
  
- **Dependency Management**
  - `pyproject.toml` with Poetry configuration
  - `requirements.txt` for pip compatibility
  - Included core dependencies: LangGraph, LangChain, FastAPI, Pydantic v2, etc.
  - Added development tools: pytest, black, ruff, mypy, pre-commit
  
- **Configuration Files**
  - `.env.example` template with comprehensive environment variables
  - `.gitignore` for Python, virtual environments, and IDE files
  
- **Documentation**
  - Comprehensive README.md with:
    - Project overview and goals
    - Architecture diagram and principles
    - Technology stack details
    - Project structure with detailed explanations
    - Installation and running instructions
    - Development guide and coding standards
    - Current progress tracking
    - Roadmap for Q1-Q4 2026
  - `CHANGELOG.md` for version tracking
  
- **Project Rules**
  - `.cursorrules` defining:
    - Project identity and architecture
    - Directory structure conventions
    - Coding standards (type hints, async/await, PEP 8)
    - Documentation requirements
    - Agent logic principles

### Infrastructure
- Prepared test directories (unit, integration)
- Created docs folder for additional documentation
- Set up database migration structure with Alembic support

---

## Template for Future Releases

## [Version] - YYYY-MM-DD

### Added
- New features

### Changed
- Changes in existing functionality

### Deprecated
- Soon-to-be removed features

### Removed
- Removed features

### Fixed
- Bug fixes

### Security
- Security improvements
