# JWT Python-Java 호환성 가이드

Aura-Platform (Python)과 DWP Backend (Java/Spring) 간 JWT 토큰 호환성을 보장하는 가이드입니다.

## ✅ 구현 완료

Aura-Platform의 JWT 구현은 **dwp_backend 가이드에 완벽히 부합**합니다:

- ✅ `exp`와 `iat`는 Unix timestamp (초 단위 정수)로 저장
- ✅ 시크릿 키 최소 32바이트 (256비트) 검증
- ✅ `SECRET_KEY` 또는 `JWT_SECRET` 환경 변수 지원
- ✅ JWT 표준 준수 (RFC 7519)

---

## 🔑 시크릿 키 설정

### 환경 변수 이름

Aura-Platform은 다음 환경 변수를 지원합니다:

1. **`SECRET_KEY`** (우선순위 높음)
2. **`JWT_SECRET`** (SECRET_KEY가 없을 때 사용)

### .env 파일 설정

```bash
# Aura-Platform .env
# 둘 중 하나만 설정하면 됩니다 (SECRET_KEY 우선)

# 방법 1: SECRET_KEY 사용 (권장)
SECRET_KEY=your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256

# 방법 2: JWT_SECRET 사용 (dwp_backend와 동일한 이름)
JWT_SECRET=your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256
```

### 시크릿 키 생성

```bash
# 256비트(32바이트) 이상의 랜덤 키 생성
openssl rand -base64 32

# 또는 Python으로 생성
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**⚠️ 중요**: JWT를 발급하는 **dwp-auth-server**와 **동일한 시크릿 키**를 사용해야 합니다!

### dwp-auth-server 연동

| 서비스 | 설정 | 환경 변수 |
|--------|------|----------|
| Auth Server | dwp-auth-server/application.yml | JWT_SECRET |
| Aura-Platform | .env | JWT_SECRET |

Gateway(8080)는 `Authorization: Bearer <token>` 헤더를 Aura까지 그대로 전달합니다.

---

## 📋 JWT 클레임 구조

### 표준 클레임 (JWT 표준)

| 클레임 | 타입 | 설명 | 필수 |
|--------|------|------|------|
| `sub` | String | Subject (사용자 ID) | ✅ |
| `exp` | **Number** | Expiration Time (**Unix timestamp, 초 단위**) | ✅ |
| `iat` | **Number** | Issued At (**Unix timestamp, 초 단위**) | ✅ |

### 커스텀 클레임 (DWP)

| 클레임 | 타입 | 설명 | 필수 |
|--------|------|------|------|
| `tenant_id` | String | 테넌트 ID | ✅ |
| `email` | String | 사용자 이메일 | ✅ |
| `role` | String | 사용자 역할 | ✅ |

---

## 🔍 코드 구현

### 토큰 생성 (Aura-Platform)

```python
from core.security import create_token

# 토큰 생성
token = create_token(
    user_id="user_001",
    tenant_id="tenant1",
    email="user@example.com",
    role="user",
)

# 내부적으로 다음과 같이 처리됩니다:
# exp: int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp())
# iat: int(datetime.now(timezone.utc).timestamp())
```

### 토큰 검증 (Aura-Platform)

```python
from core.security import verify_token, get_user_from_token

# 토큰 검증
payload = verify_token(token)
if payload:
    print(f"User ID: {payload.user_id}")
    print(f"Tenant ID: {payload.tenant_id}")
    print(f"Exp: {payload.exp} (Unix timestamp)")

# 사용자 정보 추출
user = get_user_from_token(token)
if user:
    print(f"User: {user.user_id}, Role: {user.role}")
```

---

## 🧪 테스트

### 호환성 테스트 실행

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python scripts/test_jwt_compatibility.py
```

**예상 출력**:
```
╔════════════════════════════════════════════════════════════╗
║     JWT Python-Java Compatibility Test Suite              ║
╚════════════════════════════════════════════════════════════╝

🔍 Testing JWT Timestamp Format (Unix timestamp)
  ✓ exp: 1234567890 (type: int)
  ✓ iat: 1234567890 (type: int)

🔍 Testing JWT Verification
  ✓ Token verified successfully

🔍 Testing JWT Expiration
  ✓ Token is valid immediately after creation
  ✓ Token is expired after expiration time

🔍 Testing Secret Key Length
  ✓ Secret key length: 32 bytes
  ✓ Secret key meets minimum requirement

🔍 Testing JWT Java Compatibility
  ✓ All claims have correct types

╔════════════════════════════════════════════════════════════╗
║        ✅ All JWT Compatibility Tests Passed!              ║
╚════════════════════════════════════════════════════════════╝
```

### 토큰 디버깅

```python
from jose import jwt

# 토큰 디코딩 (검증 없이)
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
payload = jwt.get_unverified_claims(token)

print("Claims:")
for key, value in payload.items():
    print(f"  {key}: {value} (type: {type(value).__name__})")
```

또는 [JWT.io](https://jwt.io/)에서 토큰을 디버깅할 수 있습니다.

---

## 🔄 dwp_backend 연동

### 1. 시크릿 키 동기화

**Aura-Platform `.env`**:
```bash
SECRET_KEY=your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256
```

**dwp_backend `application.yml`**:
```yaml
jwt:
  secret: ${JWT_SECRET:your_shared_secret_key_must_be_at_least_256_bits_long_for_HS256}
```

**⚠️ 두 값이 완전히 동일해야 합니다!**

### 2. 토큰 교환 테스트

```bash
# 1. Aura-Platform에서 토큰 생성
python scripts/test_jwt_standalone.py
# 출력: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# 2. dwp_backend API 호출
curl -X GET http://localhost:8080/api/auth/info \
  -H "Authorization: Bearer <토큰>"

# 3. Aura-Platform에서 dwp_backend 호출
curl -X GET http://localhost:8080/api/main/agent/tasks \
  -H "Authorization: Bearer <토큰>" \
  -H "X-DWP-Source: AURA" \
  -H "X-Tenant-ID: tenant1"
```

---

## ❌ 문제 해결

### 문제 1: "Invalid token" 에러

**원인**: 시크릿 키 불일치 또는 토큰 형식 오류

**해결**:
```bash
# 1. 시크릿 키 확인
echo $SECRET_KEY
# 또는
echo $JWT_SECRET

# 2. 토큰 디코딩 (Python)
python3 -c "
from jose import jwt
token = 'YOUR_TOKEN'
payload = jwt.decode(token, 'YOUR_SECRET', algorithms=['HS256'])
print(payload)
"
```

### 문제 2: "exp claim is not a number" 에러

**원인**: `exp` 필드가 datetime 객체로 저장됨 (이미 수정됨 ✅)

**해결**: Aura-Platform은 이미 Unix timestamp로 변환합니다.

### 문제 3: "Secret key too short" 에러

**원인**: HS256 알고리즘은 최소 256비트(32바이트) 키가 필요

**해결**:
```bash
# 더 긴 시크릿 키 생성
openssl rand -base64 32

# .env 파일 업데이트
SECRET_KEY=<생성된_키>
```

---

## 📚 참고 자료

### Python 라이브러리
- [python-jose 문서](https://python-jose.readthedocs.io/)
- [JWT.io](https://jwt.io/) - 토큰 디버깅 도구

### Java/Spring 라이브러리
- [Spring Security OAuth2 Resource Server](https://docs.spring.io/spring-security/reference/servlet/oauth2/resource-server/index.html)
- [Nimbus JOSE + JWT](https://connect2id.com/products/nimbus-jose-jwt)

### JWT 표준
- [RFC 7519 - JSON Web Token (JWT)](https://tools.ietf.org/html/rfc7519)

---

## ✅ 체크리스트

### Aura-Platform (Python)
- [x] `exp`와 `iat`를 Unix timestamp로 변환
- [x] 시크릿 키를 환경 변수로 관리
- [x] 시크릿 키 길이 확인 (최소 32바이트)
- [x] `SECRET_KEY` 또는 `JWT_SECRET` 지원
- [x] 토큰 생성 후 자체 검증
- [x] 호환성 테스트 스크립트

### dwp_backend (Java/Spring)
- [x] JWT Decoder 설정 (HS256)
- [x] 시크릿 키를 환경 변수로 관리
- [x] Security Filter Chain 설정
- [x] 호환성 테스트 작성

### 통합 테스트
- [x] Python → Java 토큰 검증
- [x] 실제 API 호출 테스트

---

**✅ Aura-Platform의 JWT 구현은 dwp_backend와 완벽히 호환됩니다!**
