# 테스트 보완 사항 수정 보고서

## 📅 수정 일시
2026-01-16

## 🔍 발견된 문제점

### 1. `/agents/tools` 엔드포인트 인증 실패
- **증상**: 올바른 JWT 토큰을 사용해도 "Not authenticated" 에러 발생
- **원인**: 
  - 미들웨어에서 토큰 검증은 성공하지만, `request.state.user`가 제대로 설정되지 않을 수 있음
  - 의존성 주입에서 `request.state.user`를 찾지 못하는 경우 처리 부족

### 2. 미들웨어 예외 처리 부족
- **문제**: 토큰 검증 중 예외 발생 시 적절한 에러 응답 없음
- **영향**: 디버깅 어려움

### 3. 로깅 개선 필요
- **문제**: 인증 실패 시 경로 정보가 로그에 포함되지 않음
- **영향**: 문제 추적 어려움

---

## ✅ 수정 사항

### 1. 미들웨어 개선 (`api/middleware.py`)

#### 1.1 EXEMPT_PATHS에 `/agents/health` 추가
```python
EXEMPT_PATHS = [
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/agents/health",  # 에이전트 헬스체크는 공개
]
```

#### 1.2 토큰 검증 예외 처리 추가
```python
# 토큰 검증 및 사용자 정보 추출
try:
    user = get_user_from_token(token)
    
    if user is None:
        logger.warning(f"Invalid or expired token for path: {path}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 사용자 정보를 request.state에 저장
    request.state.user = user
    request.state.tenant_id = user.tenant_id
    
    logger.debug(
        f"Authenticated user: {user.user_id} (tenant: {user.tenant_id}) for path: {path}"
    )
    
except Exception as e:
    logger.error(f"Error during token verification: {e}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Token verification failed"},
        headers={"WWW-Authenticate": "Bearer"},
    )
```

#### 1.3 로깅 개선
- 경로 정보를 로그에 포함
- 인증 성공/실패 시 상세 로그 추가

---

### 2. 의존성 주입 개선 (`api/dependencies.py`)

#### 2.1 Fallback 인증 로직 추가
```python
async def get_current_user(request: Request) -> User:
    """
    현재 인증된 사용자 반환
    
    미들웨어에서 이미 검증된 사용자 정보를 request.state에서 가져옵니다.
    미들웨어에서 설정되지 않은 경우, Authorization 헤더에서 직접 토큰을 확인합니다.
    """
    # 미들웨어에서 설정된 사용자 정보 확인
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user
    
    # 미들웨어를 통과하지 못한 경우, 직접 토큰 확인 (fallback)
    authorization = request.headers.get("Authorization")
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            user = get_user_from_token(token)
            if user:
                # request.state에 저장 (다음 요청을 위해)
                request.state.user = user
                request.state.tenant_id = user.tenant_id
                logger.debug(f"User authenticated via fallback: {user.user_id}")
                return user
    
    # 인증 실패
    logger.warning(f"Authentication failed for path: {request.url.path}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
```

**개선 사항**:
- 미들웨어를 통과하지 못한 경우에도 직접 토큰 확인
- 인증 성공 시 `request.state`에 저장하여 일관성 유지
- 상세한 로깅 추가

---

## 🧪 수정 후 테스트 방법

### 1. 서버 재시작
```bash
# 서버 재시작 (변경사항 적용)
# Ctrl+C로 서버 중지 후
python main.py
```

### 2. JWT 토큰 생성
```bash
python scripts/test_jwt_standalone.py
```

### 3. API 인증 테스트
```bash
# 토큰 설정
export TOKEN="<생성된_토큰>"

# /agents/tools 테스트
curl -s http://localhost:8000/agents/tools \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" | python3 -m json.tool
```

### 4. 인증 실패 테스트
```bash
# 토큰 없이 요청
curl -s -w "\nHTTP Status: %{http_code}\n" \
  http://localhost:8000/agents/tools

# 잘못된 토큰
curl -s -w "\nHTTP Status: %{http_code}\n" \
  http://localhost:8000/agents/tools \
  -H "Authorization: Bearer invalid_token"
```

---

## 📊 예상 결과

### 수정 전
- `/agents/tools`: ❌ "Not authenticated" (올바른 토큰 사용 시에도)
- 로깅: 경로 정보 부족
- 예외 처리: 부족

### 수정 후
- `/agents/tools`: ✅ 정상 작동 (올바른 토큰 사용 시)
- 로깅: 경로 정보 포함, 상세 로그
- 예외 처리: 완전한 예외 처리 및 에러 응답

---

## 🔄 다음 단계

1. **서버 재시작**: 변경사항 적용
2. **테스트 재실행**: JWT 인증 테스트
3. **로그 확인**: 인증 성공/실패 로그 확인
4. **전체 통합 테스트**: 모든 엔드포인트 테스트

---

## 📝 변경된 파일

1. `api/middleware.py`
   - EXEMPT_PATHS에 `/agents/health` 추가
   - 토큰 검증 예외 처리 추가
   - 로깅 개선

2. `api/dependencies.py`
   - `get_current_user`에 fallback 인증 로직 추가
   - 로깅 개선

---

**✅ 모든 보완 사항이 수정되었습니다!**

**서버를 재시작한 후 테스트를 다시 실행하세요.** 🚀
