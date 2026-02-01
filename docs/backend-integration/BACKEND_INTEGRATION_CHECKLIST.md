# DWP Backend 통합 체크리스트

> **작성일**: 2026-01-16  
> **목적**: 백엔드 통합 전 필수 확인 사항

---

## ✅ 필수 확인 사항

### 1. 포트 설정 확인

- [x] **Aura-Platform 포트**: 9000
  - `core/config.py`: `api_port` 기본값 9000
  - `.env` 파일: `API_PORT=9000` (또는 환경 변수)
  - 확인 방법:
    ```bash
    curl http://localhost:9000/health
    ```

- [x] **포트 충돌 해결**
  - Auth Server: 포트 8001
  - Aura-Platform: 포트 9000
  - 충돌 없음 ✅

---

### 2. HITL API 구현 완료 확인

- [x] **백엔드 HITL API 구현 완료** (2026-01-16)
  - `POST /api/aura/hitl/approve/{requestId}` ✅
  - `POST /api/aura/hitl/reject/{requestId}` ✅
  - Redis Pub/Sub 발행 ✅
  - 신호 저장 (`hitl:signal:{sessionId}`) ✅

- [x] **Aura-Platform HITL 구독 구현 완료**
  - `core/memory/hitl_manager.py`: `wait_for_approval_signal()` ✅
  - Redis Pub/Sub 구독 (`hitl:channel:{sessionId}`) ✅
  - 타임아웃 처리 (300초) ✅

**확인 문서**: [AURA_PLATFORM_UPDATE.md](AURA_PLATFORM_UPDATE.md)

---

### 3. Redis Pub/Sub 신호 형식 확인

- [x] **신호 형식**: Unix timestamp (초 단위 정수) ✅

**승인 신호 형식**:
```json
{
  "type": "approval",
  "requestId": "req-12345",
  "status": "approved",
  "timestamp": 1706152860  // ✅ Unix timestamp (초 단위 정수)
}
```

**거절 신호 형식**:
```json
{
  "type": "rejection",
  "requestId": "req-12345",
  "status": "rejected",
  "reason": "사용자 거절",
  "timestamp": 1706152860  // ✅ Unix timestamp (초 단위 정수)
}
```

**Aura-Platform 처리**: `core/memory/hitl_manager.py`의 `wait_for_approval_signal()` 메서드가 이미 올바르게 구현됨 ✅

---

### 4. Gateway 라우팅 설정 확인

- [x] **Gateway 라우팅 규칙** (백엔드에서 설정)
  1. `/api/aura/hitl/**` → Main Service (포트 8081) - 우선 매칭
  2. `/api/aura/**` → Aura-Platform (포트 9000) - 나머지 경로

- [x] **Aura-Platform 엔드포인트**
  - `GET /aura/test/stream` (Gateway: `/api/aura/test/stream`)
  - `GET /aura/hitl/requests/{id}` (Gateway: `/api/aura/hitl/requests/{id}`)
  - `GET /aura/hitl/signals/{id}` (Gateway: `/api/aura/hitl/signals/{id}`)

**주의**: HITL 승인/거절 API는 Main Service에 있으므로 Gateway에서 `/api/aura/hitl/**` 경로를 Main Service로 라우팅해야 합니다.

---

### 5. 테스트 방법

#### 5.1 자동 테스트 스크립트

```bash
# 통합 테스트 실행
python scripts/test_backend_integration.py
```

**테스트 항목**:
- 포트 설정 확인
- Aura-Platform 헬스체크
- Redis 연결
- Gateway 라우팅
- HITL 승인 API
- HITL 거절 API

---

#### 5.2 수동 테스트

**1. 포트 확인**
```bash
# Aura-Platform 헬스체크
curl http://localhost:9000/health

# Gateway를 통한 접근
curl http://localhost:8080/api/aura/test/stream?message=test \
  -H "Authorization: Bearer {TOKEN}" \
  -H "X-Tenant-ID: tenant1"
```

**2. HITL 승인 플로우 테스트**
```bash
# 1. JWT 토큰 생성
TOKEN=$(cd /path/to/dwp-backend/dwp-auth-server && python3 test_jwt_for_aura.py --token-only)

# 2. SSE 스트리밍 시작 (HITL 이벤트 발생 대기)
curl -N http://localhost:8080/api/aura/test/stream?message=test \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1"

# 3. HITL 이벤트 수신 후 requestId 확인
# 예: {"type":"hitl","data":{"requestId":"req-12345",...}}

# 4. 승인 처리 (백엔드 API)
curl -X POST http://localhost:8080/api/aura/hitl/approve/req-12345 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -d '{"userId": "user123"}'

# 5. Redis Pub/Sub에서 신호 확인
redis-cli PUBSUB CHANNELS hitl:channel:*
```

**3. HITL 거절 플로우 테스트**
```bash
# 거절 처리
curl -X POST http://localhost:8080/api/aura/hitl/reject/req-12345 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "X-User-ID: user123" \
  -H "Content-Type: application/json" \
  -d '{"userId": "user123", "reason": "사용자 거절"}'
```

---

## 📋 체크리스트

### 사전 준비
- [ ] Aura-Platform 포트 9000으로 실행 확인
- [ ] Redis 연결 확인 (`localhost:6379`)
- [ ] Gateway 실행 확인 (`localhost:8080`)
- [ ] JWT 토큰 생성 스크립트 준비

### 통합 테스트
- [ ] 포트 설정 확인 테스트
- [ ] Aura-Platform 헬스체크 테스트
- [ ] Redis 연결 테스트
- [ ] Gateway 라우팅 테스트
- [ ] HITL 승인 API 테스트
- [ ] HITL 거절 API 테스트
- [ ] End-to-End HITL 플로우 테스트

### 문서 확인
- [ ] 백엔드 업데이트 문서 확인 (`docs/AURA_PLATFORM_UPDATE.md`)
- [ ] Gateway 라우팅 설정 확인
- [ ] Redis Pub/Sub 신호 형식 확인

---

## 🔗 관련 문서

- [AURA_PLATFORM_UPDATE.md](AURA_PLATFORM_UPDATE.md) - 백엔드 업데이트 사항 상세
- [BACKEND_HANDOFF.md](BACKEND_HANDOFF.md) - 백엔드 전달 문서
- [BACKEND_INTEGRATION_STATUS.md](BACKEND_INTEGRATION_STATUS.md) - 연동 상태 상세
- [test_backend_integration.py](../scripts/test_backend_integration.py) - 통합 테스트 스크립트

---

**최종 업데이트**: 2026-01-16
