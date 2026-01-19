# 🌟 Aura-Platform

> **혁신적인 에이전틱 AI 시스템 for DWP**  
> Modular Monolith Architecture로 설계된 확장 가능한 SDLC 자동화 플랫폼

![Version](https://img.shields.io/badge/version-0.3.1-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

---

## 📋 목차

- [프로젝트 개요](#-프로젝트-개요)
- [아키텍처](#-아키텍처)
- [기술 스택](#-기술-스택)
- [프로젝트 구조](#-프로젝트-구조)
- [설치 및 실행](#-설치-및-실행)
- [개발 가이드](#-개발-가이드)
- [현재 진행 상황](#-현재-진행-상황)
- [로드맵](#-로드맵)

---

## 🎯 프로젝트 개요

**Aura-Platform**은 DWP(Digital Workplace)를 위한 차세대 에이전틱 AI 시스템입니다. 이 플랫폼은 SDLC(Software Development Life Cycle) 전반의 자동화를 목표로 하며, 부서별로 특화된 AI 에이전트를 통해 업무 효율성을 극대화합니다.

### 핵심 목표

- ✅ **모듈러 아키텍처**: 중앙 집중형 Core와 독립적인 Domain 모듈
- ✅ **부서별 특화**: 각 부서(Dev, HR, Finance 등)에 최적화된 AI 에이전트
- ✅ **확장 가능성**: 새로운 도메인과 도구를 쉽게 추가
- ✅ **Human-in-the-Loop**: 중요한 의사결정에 인간 개입 보장
- ✅ **엔터프라이즈 준비**: 보안, 감사, 규정 준수 고려

### 첫 번째 타겟: **개발팀 (Dev Domain)**

- Git 워크플로우 자동화
- 코드 리뷰 보조
- Jira 이슈 관리
- CI/CD 파이프라인 모니터링
- 기술 문서 자동 생성

---

## 🏗️ 아키텍처

Aura-Platform은 **Modular Monolith** 아키텍처를 채택하여 마이크로서비스의 복잡성 없이 모듈화의 이점을 누립니다.

```
┌─────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                  │
│                 /api/routes & /api/schemas               │
└─────────────┬───────────────────────────────────────────┘
              │
┌─────────────┴───────────────────────────────────────────┐
│                    Core Engine                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  LLM Config  │  │    Memory    │  │   Security   │  │
│  │   (OpenAI)   │  │  (Redis/DB)  │  │    (Auth)    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────┬───────────────────────────────────────────┘
              │
┌─────────────┴───────────────────────────────────────────┐
│                   Domain Agents                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Dev Agent   │  │   HR Agent   │  │ Finance Agent│  │
│  │ (LangGraph)  │  │  (Future)    │  │   (Future)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────┬───────────────────────────────────────────┘
              │
┌─────────────┴───────────────────────────────────────────┐
│                  Integration Tools                       │
│      Git  │  Jira  │  Slack  │  GitHub  │  GitLab       │
└─────────────────────────────────────────────────────────┘
```

### 아키텍처 원칙

1. **중앙 집중형 Core**: 모든 도메인이 공유하는 LLM 설정, 메모리, 보안 로직
2. **독립적인 Domains**: 각 부서별 비즈니스 로직을 독립적으로 관리
3. **재사용 가능한 Tools**: 여러 도메인에서 사용할 수 있는 통합 도구
4. **명확한 경계**: 모듈 간 의존성을 명확히 정의

---

## 🛠️ 기술 스택

### Core Framework
- **Python 3.10+**: 최신 타입 힌팅 및 async/await 지원
- **LangGraph**: 복잡한 에이전트 워크플로우 및 상태 관리
- **LangChain**: LLM 통합 및 체인 구성
- **OpenAI GPT-4**: 주력 언어 모델

### Web & API
- **FastAPI**: 고성능 비동기 웹 프레임워크
- **Uvicorn**: ASGI 서버
- **Pydantic v2**: 데이터 검증 및 설정 관리

### Database & Storage
- **PostgreSQL**: 주 데이터베이스
- **SQLAlchemy 2.0**: ORM
- **Alembic**: 데이터베이스 마이그레이션
- **Redis**: 캐싱 및 세션 관리

### Development Tools
- **Poetry**: 의존성 관리
- **Black**: 코드 포매터
- **Ruff**: 빠른 린터
- **MyPy**: 정적 타입 체커
- **Pytest**: 테스팅 프레임워크

---

## 📁 프로젝트 구조

```
aura-platform/
├── core/                       # 공통 핵심 로직
│   ├── llm/                   # LLM 설정 및 프롬프트
│   │   ├── __init__.py
│   │   ├── client.py          # OpenAI 클라이언트
│   │   └── prompts.py         # 시스템 프롬프트
│   ├── memory/                # 메모리 및 상태 관리
│   │   ├── __init__.py
│   │   ├── redis_store.py     # Redis 기반 메모리
│   │   ├── conversation.py    # 대화 히스토리
│   │   └── hitl_manager.py    # HITL 통신 관리
│   ├── security/              # 인증 및 권한
│   │   ├── __init__.py
│   │   ├── auth.py            # JWT 인증
│   │   └── permissions.py     # RBAC
│   ├── config.py              # 전역 설정
│   └── __init__.py
│
├── domains/                   # 부서별 도메인 모듈
│   ├── dev/                   # 개발팀 도메인 (첫 번째 타겟)
│   │   ├── agents/           # LangGraph 에이전트
│   │   │   ├── __init__.py
│   │   │   ├── code_agent.py          # 기본 코드 분석 에이전트
│   │   │   ├── enhanced_agent.py      # 고도화된 에이전트 (v1.0)
│   │   │   └── hooks.py               # SSE 이벤트 Hook
│   │   ├── workflows/        # 복잡한 워크플로우
│   │   │   ├── __init__.py
│   │   │   └── sdlc_workflow.py       # (예정)
│   │   └── __init__.py
│   └── __init__.py
│
├── api/                       # FastAPI 애플리케이션
│   ├── routes/               # API 엔드포인트
│   │   ├── __init__.py
│   │   ├── agents.py         # 기본 에이전트 API
│   │   ├── agents_enhanced.py # 고도화된 에이전트 API (v1.0)
│   │   └── aura_backend.py   # 백엔드 연동 API
│   ├── schemas/              # API 스키마
│   │   ├── __init__.py
│   │   ├── events.py         # SSE 이벤트 스키마
│   │   └── hitl_events.py    # HITL 이벤트 스키마
│   ├── middleware.py         # 미들웨어 (JWT, Tenant, Logging)
│   ├── dependencies.py       # 의존성 주입
│   └── __init__.py
│
├── tools/                    # 재사용 가능한 통합 도구
│   ├── integrations/        # 외부 서비스 연동
│   │   ├── __init__.py
│   │   ├── git_tool.py      # Git 작업 (5개 도구) ✅
│   │   ├── github_tool.py    # GitHub API (4개 도구) ✅
│   │   ├── jira_tool.py      # Jira API (예정)
│   │   └── slack_tool.py     # Slack 알림 (예정)
│   ├── base.py              # 기본 도구 클래스
│   └── __init__.py
│
├── database/                 # 데이터베이스 관련
│   ├── models/              # SQLAlchemy 모델
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── agent_logs.py
│   ├── migrations/          # Alembic 마이그레이션
│   └── session.py           # DB 세션 관리
│
├── tests/                    # 테스트
│   ├── unit/                # 단위 테스트
│   └── integration/         # 통합 테스트
│
├── docs/                     # 프로젝트 문서
│   ├── architecture.md
│   ├── api_reference.md
│   └── development.md
│
├── .env.example             # 환경변수 템플릿
├── .gitignore
├── pyproject.toml           # Poetry 설정
├── requirements.txt         # pip 의존성
├── CHANGELOG.md             # 변경 이력
└── README.md                # 이 파일
```

---

## 🚀 설치 및 실행

### 사전 요구사항

- Python 3.10 이상
- PostgreSQL 14+ (또는 Docker Compose)
- Redis 7+ (또는 Docker Compose - dwp_backend와 공유 가능)
- Poetry (선택사항)

**Redis 설정 방법**:
- **권장**: dwp_backend의 Docker Compose Redis 사용 (`localhost:6379`)
  - 별도 설치 불필요
  - 자세한 내용: [`docs/DOCKER_REDIS_SETUP.md`](docs/DOCKER_REDIS_SETUP.md)
- **대안**: 로컬에 Redis 직접 설치 (`brew install redis`)

### 1. 프로젝트 클론

```bash
git clone <repository-url>
cd aura-platform
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 API 키 및 설정 입력
```

### 3. 의존성 설치

**Option A: Poetry 사용 (권장)**
```bash
poetry install
poetry shell
```

**Option B: pip 사용**
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 데이터베이스 마이그레이션

```bash
alembic upgrade head
```

### 5. 서버 실행

```bash
# 개발 모드
uvicorn api.main:app --reload --host 0.0.0.0 --port 9000

# 프로덕션 모드
uvicorn api.main:app --host 0.0.0.0 --port 9000 --workers 4
```

### 6. API 문서 확인

브라우저에서 다음 주소로 접속:
- Swagger UI: http://localhost:9000/docs
- ReDoc: http://localhost:9000/redoc

---

## 👨‍💻 개발 가이드

### 코딩 표준

1. **타입 힌팅**: 모든 함수에 타입 힌트 사용
   ```python
   async def process_request(data: dict[str, Any]) -> ProcessResult:
       ...
   ```

2. **비동기 프로그래밍**: API 및 외부 호출에 async/await 사용
   ```python
   async def fetch_data() -> dict:
       async with httpx.AsyncClient() as client:
           response = await client.get(url)
           return response.json()
   ```

3. **Pydantic 모델**: 데이터 검증에 Pydantic 사용
   ```python
   from pydantic import BaseModel, Field

   class AgentRequest(BaseModel):
       query: str = Field(..., min_length=1)
       context: dict[str, Any] | None = None
   ```

4. **에러 핸들링**: 명확한 예외 처리
   ```python
   from core.exceptions import AgentError
   
   try:
       result = await agent.run()
   except AgentError as e:
       logger.error(f"Agent failed: {e}")
       raise
   ```

### 테스트 작성

```bash
# 전체 테스트 실행
pytest

# 커버리지 포함
pytest --cov=. --cov-report=html

# 특정 테스트만
pytest tests/unit/test_config.py
```

### 코드 포맷팅 및 린팅

```bash
# 코드 포맷팅
black .

# 린팅
ruff check .

# 타입 체크
mypy core domains api tools
```

### 새로운 도메인 추가

1. `domains/` 아래 새 디렉토리 생성
2. `agents/`, `workflows/` 서브디렉토리 구성
3. `schemas.py`에 도메인 데이터 모델 정의
4. `api/routes/domains/`에 API 라우트 추가
5. README.md 업데이트

---

## 📊 현재 진행 상황

### ✅ 완료된 작업 (Phase 0: 프로젝트 초기화)

- [x] 프로젝트 디렉토리 구조 생성
  - `core/`, `domains/`, `api/`, `tools/`, `database/` 폴더 구성
  - 테스트 및 문서 디렉토리 준비
- [x] 의존성 관리 파일 생성
  - `pyproject.toml` (Poetry 설정)
  - `requirements.txt` (pip 호환)
- [x] 환경 설정 파일 준비
  - `.env` (환경변수 설정 완료)
  - `.gitignore` (Git 무시 파일)
- [x] 프로젝트 문서화
  - 상세한 README.md 작성
  - 아키텍처 다이어그램 포함
  - QUICK_START.md 가이드 추가
  - SETUP_SUCCESS.md 리포트 생성

### ✅ 완료된 작업 (Phase 1: 환경 설정 및 첫 실행)

- [x] **환경변수 설정**
  - `.env` 파일 생성 및 SECRET_KEY 자동 생성
  - 모든 필수 환경변수 구성
- [x] **의존성 설치**
  - Python venv 가상환경 생성
  - LangGraph 1.0.6, LangChain 1.2.4, FastAPI 0.128.0 등 설치 완료
- [x] **Core 모듈 구현**
  - `core/config.py` - Pydantic Settings 기반 전역 설정 (완성)
  - `core/llm/client.py` - LangChain ChatOpenAI 래퍼 (완성)
  - `core/llm/prompts.py` - 시스템 프롬프트 템플릿 (완성)
- [x] **FastAPI 애플리케이션**
  - `main.py` - 기본 API 서버 (완성)
  - `/`, `/health` 엔드포인트 구현
  - CORS 미들웨어 설정
- [x] **서버 시작 및 검증**
  - Uvicorn 서버 정상 작동 확인 ✅
  - API 엔드포인트 테스트 완료 ✅
  - Swagger UI 접근 가능 (http://localhost:9000/docs) ✅
- [x] **검증 스크립트**
  - `scripts/test_setup.py` - 자동 설정 검증 스크립트
  - 5/5 테스트 통과 ✅

### ✅ 완료된 작업 (Phase 2: Core 확장 - 지능형 메모리 & 보안)

- [x] **Redis & LangGraph Checkpointer**
  - `core/memory/redis_store.py` - Redis 기반 LangGraph Checkpointer (완성)
  - 에이전트 상태 저장 및 복원 지원
  - 중단된 지점에서 재개 가능한 구조
- [x] **대화 메모리 시스템**
  - `core/memory/conversation.py` - 대화 히스토리 관리 (완성)
  - 멀티테넌시 지원 (Tenant ID 기반)
  - LLM 컨텍스트 자동 생성
- [x] **LLM Streaming 지원**
  - `core/llm/client.py` - 비동기 스트리밍 기능 추가
  - React 프론트엔드 실시간 응답 지원
- [x] **JWT 인증 시스템**
  - `core/security/auth.py` - JWT 생성/검증 (완성)
  - dwp_backend와 동일한 SECRET_KEY 사용
  - Bearer Token 지원
- [x] **RBAC 권한 관리**
  - `core/security/permissions.py` - 역할 기반 권한 (완성)
  - Admin, Manager, User, Guest 역할 정의
  - 세밀한 권한 제어
- [x] **API 미들웨어**
  - `api/middleware.py` - JWT 인증 미들웨어 (완성)
  - X-Tenant-ID 헤더 처리
  - 요청 로깅 및 에러 핸들링
- [x] **의존성 주입**
  - `api/dependencies.py` - FastAPI 의존성 (완성)
  - 사용자 인증 의존성
  - 권한 확인 의존성

### ✅ 완료된 작업 (Phase 3: Dev Domain 구현 - 에이전트 & 도구)

- [x] **Git 도구**
  - `tools/integrations/git_tool.py` - 로컬 Git 작업 도구 (완성)
  - git_diff, git_log, git_status, git_show_file, git_branch_list
  - @tool 데코레이터 사용
- [x] **GitHub 도구**
  - `tools/integrations/github_tool.py` - GitHub API 통합 (완성)
  - github_get_pr, github_list_prs, github_get_pr_diff, github_get_file
  - PR 조회, 코드 분석 기능
- [x] **LangGraph 에이전트**
  - `domains/dev/agents/code_agent.py` - 코드 분석 에이전트 (완성)
  - 도구 선택 및 실행
  - 상태 관리 (AgentState)
  - 스트리밍 지원
- [x] **SSE API 엔드포인트**
  - `api/routes/agents.py` - 에이전트 API (완성)
  - POST /agents/chat - 일반 모드
  - POST /agents/chat/stream - 스트리밍 모드 (SSE)
  - GET /agents/tools - 도구 목록
- [x] **JWT 인증 통합**
  - 모든 엔드포인트에 JWT 인증 적용
  - X-Tenant-ID 헤더 지원
- [x] **테스트 스크립트**
  - `scripts/test_agent_stream.py` - 에이전트 스트리밍 검증

### ✅ 완료된 작업 (프론트엔드 명세 v1.0: Enhanced Agent)

- [x] **SSE 이벤트 스키마**
  - `api/schemas/events.py` - 프론트엔드 명세 v1.0 이벤트 스키마 (완성)
  - thought, plan_step, tool_execution, content 이벤트 타입
  - Pydantic v2 모델 기반 타입 안전성
- [x] **Enhanced Agent State**
  - `domains/dev/agents/enhanced_agent.py` - 고도화된 에이전트 (완성)
  - thought_chain, plan_steps, execution_logs 추적
  - 5개 노드 워크플로우 (analyze → plan → execute → tools → reflect)
- [x] **LangGraph Hook**
  - `domains/dev/agents/hooks.py` - SSE 이벤트 발행 Hook (완성)
  - 노드 실행 시 자동 이벤트 생성
- [x] **HITL Interrupt**
  - 중요 도구 실행 전 승인 대기 기능
  - Checkpoint 기반 상태 저장
  - pending_approvals 상태 관리
- [x] **Confidence Score**
  - LLM logprobs 기반 신뢰도 계산 (0.0~1.0)
  - plan_step에 confidence 포함
- [x] **Source Attribution**
  - 참고 파일 경로 추출
  - thought 이벤트에 sources 배열 포함
- [x] **Enhanced API 엔드포인트**
  - `api/routes/agents_enhanced.py` - 고도화된 스트리밍 API (완성)
  - POST /agents/v2/chat/stream - 프론트엔드 명세 v1.0 스트리밍
  - POST /agents/v2/approve - 도구 실행 승인

### ✅ 완료된 작업 (DWP Backend 연동)

- [x] **백엔드 연동용 SSE 스트리밍**
  - `api/routes/aura_backend.py` - 백엔드 연동 엔드포인트 (완성)
  - POST /aura/test/stream - 백엔드 요구 형식 준수
  - SSE 이벤트 형식: `id: {event_id}\nevent: {type}\ndata: {json}` (재연결 지원)
  - 요청 본문: `{"prompt": "...", "context": {...}}` 형식
  - 이벤트 타입: thought, plan_step, plan_step_update, timeline_step_update, tool_execution, hitl, content
  - 스트림 종료: `data: [DONE]\n\n` 전송
  - Last-Event-ID 헤더 지원: 재연결 시 중단 지점부터 재개
  - SSE 응답 헤더: Content-Type, Cache-Control, Connection, X-Accel-Buffering
- [x] **HITL 통신 시스템**
  - `core/memory/hitl_manager.py` - HITL Manager 구현 (완성)
  - Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
  - 승인 요청 저장/조회 (`hitl:request:{requestId}`, `hitl:session:{sessionId}`)
  - 승인 신호 대기 및 처리 (타임아웃 300초)
- [x] **HITL API 엔드포인트**
  - GET /aura/hitl/requests/{request_id} - 승인 요청 조회
  - GET /aura/hitl/signals/{session_id} - 승인 신호 조회
  - 백엔드 ApiResponse<T> 형식 준수
- [x] **포트 변경**
  - API 포트 8000 → 9000으로 변경 (포트 충돌 해결)
  - Auth Server와 포트 분리 완료
- [x] **백엔드 HITL API 구현 완료** ✅ (2026-01-16)
  - POST /api/aura/hitl/approve/{requestId} - 승인 처리 (백엔드 구현 완료)
  - POST /api/aura/hitl/reject/{requestId} - 거절 처리 (백엔드 구현 완료)
  - Redis Pub/Sub 발행 및 신호 저장 (백엔드 구현 완료)
  - 전체 통합 진행률: 100% ✅

### 🚧 진행 중 (Phase 4: 고도화)

- [ ] `database/session.py` - SQLAlchemy 세션 관리
- [ ] `database/models/base.py` - Base 모델
- [ ] Code Review Agent 특화
- [ ] Jira, Slack 통합 도구
- [ ] LangGraph 표준 Checkpointer 인터페이스 완성

### 📅 예정된 작업

**Phase 4: 추가 통합**
- [ ] `tools/integrations/jira_tool.py` - Jira API 통합
- [ ] `tools/integrations/slack_tool.py` - Slack 알림
- [ ] `domains/dev/agents/code_review_agent.py` - 코드 리뷰 에이전트 특화
- [ ] `domains/dev/agents/issue_manager_agent.py` - Issue 관리 에이전트
- [ ] `domains/dev/workflows/sdlc_workflow.py` - SDLC 워크플로우

**Phase 5: 테스트 & 문서화**
- [ ] 단위 테스트 작성
- [ ] 통합 테스트 작성
- [ ] API 문서 자동 생성
- [ ] 개발자 가이드 작성

---

## 🗺️ 로드맵

### Q1 2026: 기초 구축
- ✅ 프로젝트 초기화 및 아키텍처 설계
- ✅ Core 엔진 개발 (Redis, JWT, 메모리)
- ✅ Dev Domain 기본 기능 구현 (Git/GitHub 도구, 에이전트)
- ✅ 프론트엔드 명세 v1.0 구현 (Enhanced Agent)

### Q2 2026: Dev Domain 완성
- Git/GitHub/GitLab 완전 통합
- Jira/Linear 이슈 관리 자동화
- CI/CD 파이프라인 모니터링
- 코드 리뷰 자동화

### Q3 2026: 다중 도메인 확장
- HR Domain 추가 (채용, 온보딩)
- Finance Domain 추가 (예산 관리)
- 도메인 간 협업 워크플로우

### Q4 2026: 엔터프라이즈 기능
- 고급 보안 및 감사 로그
- 멀티테넌시 지원
- 온프레미스 배포 옵션
- 성능 최적화 및 확장성 개선

---

## 📝 변경 이력

모든 주요 변경사항은 [CHANGELOG.md](CHANGELOG.md)에 기록됩니다.

### [0.3.1] - 2026-01-16

**Added**
- 프론트엔드 명세 v1.0 구현 완료
  - Enhanced Agent (사고 과정 추적, 계획 수립)
  - SSE 이벤트 스키마 (thought, plan_step, tool_execution, content)
  - HITL Interrupt (승인 대기)
  - Confidence Score 계산
  - Source Attribution
  - POST /agents/v2/chat/stream 엔드포인트
- DWP Backend 연동 구현 완료
  - 백엔드 연동용 SSE 스트리밍 (`POST /aura/test/stream`)
  - 요청 형식: `{"prompt": "...", "context": {...}}`
  - 새로운 이벤트 타입: plan_step_update, timeline_step_update
  - 스트림 종료 표시: `data: [DONE]\n\n`
  - HITL 통신 시스템 (Redis Pub/Sub 구독)
  - HITL API 엔드포인트 (승인 요청/신호 조회)
  - 백엔드 전달 문서 (`docs/BACKEND_HANDOFF.md`)
  - 프론트엔드 전달 문서 (`docs/FRONTEND_HANDOFF.md`)
- 백엔드 HITL API 구현 완료 확인 (2026-01-16)
  - 백엔드에서 HITL 승인/거절 API 구현 완료
  - 전체 통합 진행률: 100% ✅
- 백엔드 검증 문서 응답 (2026-01-16)
  - SSE 이벤트 ID 포함 (재연결 지원)
  - Last-Event-ID 헤더 처리 구현
  - SSE 응답 헤더 설정 완료
  - `docs/BACKEND_VERIFICATION_RESPONSE.md`: 검증 응답 문서 추가
- 백엔드 통합 체크리스트 응답 (2026-01-16)
  - X-User-ID 헤더 검증 로직 추가 (JWT sub와 일치 확인)
  - 요청 본문 크기 제한 문서화 (Gateway 256KB 제한)
  - `docs/BACKEND_INTEGRATION_RESPONSE.md`: 백엔드 응답 문서 추가
  - 백엔드 업데이트 문서 (`docs/AURA_PLATFORM_UPDATE.md`)
- 백엔드 업데이트 반영 (2026-01-16)
  - SSE 엔드포인트 GET → POST 변경
  - 요청 본문에 prompt와 context 포함
  - 새로운 이벤트 타입 구현 (plan_step_update, timeline_step_update)
  - 스트림 종료 시 data: [DONE] 전송

**Changed**
- API 포트 8000 → 9000으로 변경 (포트 충돌 해결)

**Fixed**
- JWT Python-Java 호환성 개선 (Unix timestamp)
- API 인증 미들웨어 개선

### [0.3.0] - 2026-01-15

**Added**
- Phase 3: Dev Domain 구현
  - Git/GitHub 도구 통합 (9개 도구)
  - LangGraph 에이전트
  - SSE 스트리밍 API

### [0.2.0] - 2026-01-15

**Added**
- Phase 2: Core 확장
  - Redis 기반 LangGraph Checkpointer
  - JWT 인증 시스템
  - RBAC 권한 관리
  - 대화 히스토리 관리

### [0.1.0] - 2026-01-15

**Added**
- 프로젝트 초기 구조 생성
- 의존성 관리 설정 (Poetry, pip)
- 환경변수 템플릿 (.env.example)
- 상세한 README.md 및 프로젝트 문서

---

## 🤝 기여 가이드

1. 이슈 생성 또는 기존 이슈 선택
2. Feature 브랜치 생성 (`git checkout -b feature/amazing-feature`)
3. 변경사항 커밋 (`git commit -m 'Add amazing feature'`)
4. 브랜치 푸시 (`git push origin feature/amazing-feature`)
5. Pull Request 생성

---

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

## 👥 팀

DWP Development Team

---

## 📞 문의

프로젝트 관련 문의사항은 이슈 트래커를 통해 등록해주세요.

---

## 🔗 통합/협업 문서

프론트엔드 및 백엔드 팀과의 협업을 위한 상세 문서:

- **[통합 테스트 문서 전달 가이드](docs/INTEGRATION_TEST_DELIVERY_GUIDE.md)** - 문서 전달 대상 및 방법 안내
- **[통합 테스트 요약](docs/INTEGRATION_TEST_SUMMARY.md)** - 통합 테스트 전체 요약 (PM/QA/모든 팀 공유)
- **[Aura-Platform 내부 테스트](docs/AURA_PLATFORM_INTERNAL_TEST.md)** - 에이전트 엔진 내부 동작 검증 (Aura-Platform 팀/QA 팀)
- **[백엔드 통합 테스트](docs/BACKEND_INTEGRATION_TEST.md)** - 백엔드 팀용 통합 테스트 가이드
- **[프론트엔드 통합 테스트](docs/FRONTEND_INTEGRATION_TEST.md)** - 프론트엔드 팀용 통합 테스트 가이드
- **[백엔드 통합 체크리스트 응답 검토](docs/BACKEND_INTEGRATION_CHECKLIST_RESPONSE.md)** - 백엔드 통합 체크리스트 응답 검토 및 대응 완료 보고서
- **[통합/협업 체크리스트](docs/INTEGRATION_CHECKLIST.md)** - 통합 시 확인해야 할 사항
- **[백엔드 전달 문서](docs/BACKEND_HANDOFF.md)** - 백엔드 팀 전달 문서
- **[프론트엔드 전달 문서](docs/FRONTEND_HANDOFF.md)** - 프론트엔드 팀 전달 문서
- **[통합 가이드](docs/AURA_PLATFORM_INTEGRATION_GUIDE.md)** - 상세 통합 가이드
- **[빠른 참조](docs/AURA_PLATFORM_QUICK_REFERENCE.md)** - 핵심 정보 빠른 참조

---

**Built with ❤️ by DWP Team**
