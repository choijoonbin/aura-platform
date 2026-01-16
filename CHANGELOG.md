# Changelog

All notable changes to the Aura-Platform project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Database session management (SQLAlchemy)
- Code Review Agent 특화
- Jira, Slack 통합
- Frontend/Backend integration testing
- Performance optimization

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
    - `docs/BACKEND_HANDOFF.md`: 백엔드 전달 문서
    - `docs/FRONTEND_HANDOFF.md`: 프론트엔드 전달 문서
    - `docs/INTEGRATION_STATUS.md`: 통합 상태 요약
- **백엔드 HITL API 구현 완료 확인** (2026-01-16)
  - 백엔드에서 HITL 승인/거절 API 구현 완료 확인
  - `docs/AURA_PLATFORM_UPDATE.md`: 백엔드 업데이트 문서 추가
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
  - `docs/JWT_COMPATIBILITY.md`: Python-Java 호환성 가이드 추가

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
  - `docs/SETUP_SUCCESS.md`: Detailed setup completion report
  - `docs/QUICK_START.md`: Quick start guide for developers
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
