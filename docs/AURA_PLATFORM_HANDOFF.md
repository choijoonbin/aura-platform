# Aura-Platform 전달 문서

> **전달 대상**: Aura-Platform (Python/FastAPI) 개발팀  
> **전달 일자**: 2024-01-16  
> **DWP Backend 버전**: v1.0

---

## 📦 전달 자료

다음 문서들을 Aura-Platform 프로젝트에 복사하여 참고하세요:

### 필수 문서

1. **[AURA_PLATFORM_INTEGRATION_GUIDE.md](./AURA_PLATFORM_INTEGRATION_GUIDE.md)**
   - **상세 통합 가이드** (가장 중요)
   - 모든 API 엔드포인트, 데이터 형식, 통신 프로토콜 상세 설명
   - **반드시 읽어야 할 문서**

2. **[AURA_PLATFORM_QUICK_REFERENCE.md](./AURA_PLATFORM_QUICK_REFERENCE.md)**
   - **빠른 참조 가이드**
   - 핵심 정보와 코드 스니펫만 요약
   - 개발 중 빠르게 확인용

### 참고 문서 (선택)

3. [JWT 호환성 가이드](./JWT_COMPATIBILITY_GUIDE.md) - JWT 토큰 생성/검증 상세
4. [AI 에이전트 인프라](./AI_AGENT_INFRASTRUCTURE.md) - 전체 아키텍처 개요

---

## 🚀 빠른 시작

### 1. 필수 환경 변수

```bash
# JWT 시크릿 키 (Python-Java 공유)
export JWT_SECRET=your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256

# Redis 연결
export REDIS_HOST=localhost
export REDIS_PORT=6379
```

### 2. 핵심 엔드포인트

| 경로 | 설명 | 메서드 |
|------|------|--------|
| `/aura/test/stream` | SSE 스트리밍 | GET |
| `/aura/hitl/approve/{requestId}` | 승인 처리 | POST |
| `/aura/hitl/reject/{requestId}` | 거절 처리 | POST |

**⚠️ 주의**: Gateway를 통한 접근 시 `/api/aura/**` 경로 사용

### 3. 필수 헤더

```
Authorization: Bearer {JWT_TOKEN}
X-Tenant-ID: {tenant_id}
```

### 4. SSE 이벤트 타입

- `thought` - 사고 과정
- `plan_step` - 실행 계획 단계
- `tool_execution` - 도구 실행
- `hitl` - 승인 요청 (⚠️ 실행 중지 후 대기)
- `content` - 최종 결과

### 5. HITL 프로세스

```
1. hitl 이벤트 전송 → 실행 중지
2. Redis Pub/Sub 구독: hitl:channel:{sessionId}
3. 승인/거절 신호 수신
4. 승인 시 실행 재개, 거절 시 중단
```

---

## 📋 통합 체크리스트

### 필수 구현 사항

- [ ] SSE 스트리밍 엔드포인트 (`/aura/test/stream`)
  - [ ] `Content-Type: text/event-stream` 헤더
  - [ ] `Cache-Control: no-cache` 헤더
  - [ ] 5가지 이벤트 타입 전송

- [ ] JWT 인증
  - [ ] HS256 알고리즘 검증
  - [ ] `Authorization` 헤더에서 토큰 추출
  - [ ] `X-Tenant-ID` 헤더 확인

- [ ] HITL 통신
  - [ ] `hitl` 이벤트 전송 시 실행 중지
  - [ ] Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`)
  - [ ] 승인/거절 신호 수신 및 처리

---

## 🔗 네트워크 정보

| 서비스 | 포트 | 접근 방법 |
|--------|------|----------|
| Gateway | 8080 | `http://localhost:8080` |
| Aura-Platform | 8000 | 직접 접근 또는 Gateway 경유 |
| Main Service | 8081 | Gateway 경유 (`/api/main/**`) |
| Redis | 6379 | `localhost:6379` |

---

## 📞 문의

통합 과정에서 문제가 발생하거나 추가 정보가 필요한 경우, DWP Backend 개발팀에 문의하세요.

**다음 단계**: Aura-Platform 개발팀에서 메시지를 보내주시면 추가 지원을 제공하겠습니다.

---

**문서 위치**: `dwp-backend/docs/AURA_PLATFORM_INTEGRATION_GUIDE.md`
