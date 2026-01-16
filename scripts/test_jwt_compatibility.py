#!/usr/bin/env python3
"""
JWT Python-Java 호환성 테스트

dwp_backend 가이드에 따라 JWT 토큰이 올바르게 생성되는지 검증합니다.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.security import create_token, verify_token, get_user_from_token
from jose import jwt
from core.config import settings


def test_jwt_timestamp_format():
    """JWT exp와 iat가 Unix timestamp (정수)인지 확인"""
    print("=" * 60)
    print("🔍 Testing JWT Timestamp Format (Unix timestamp)")
    print("=" * 60)
    
    # 토큰 생성
    token = create_token(
        user_id="test_user_001",
        tenant_id="tenant1",
        email="test@example.com",
        role="user",
    )
    
    # 토큰 디코딩 (검증 없이)
    payload = jwt.get_unverified_claims(token)
    
    # exp와 iat가 정수인지 확인
    assert isinstance(payload.get("exp"), int), "exp must be an integer (Unix timestamp)"
    assert isinstance(payload.get("iat"), int), "iat must be an integer (Unix timestamp)"
    
    print(f"\n✓ exp: {payload.get('exp')} (type: {type(payload.get('exp')).__name__})")
    print(f"✓ iat: {payload.get('iat')} (type: {type(payload.get('iat')).__name__})")
    
    # 현재 시간과 비교
    now_timestamp = int(datetime.now(timezone.utc).timestamp())
    exp_timestamp = payload.get("exp")
    iat_timestamp = payload.get("iat")
    
    print(f"\n✓ Current timestamp: {now_timestamp}")
    print(f"✓ Token iat: {iat_timestamp} (diff: {now_timestamp - iat_timestamp}s)")
    print(f"✓ Token exp: {exp_timestamp} (diff: {exp_timestamp - now_timestamp}s)")
    
    # iat는 현재 시간과 비슷해야 함 (5초 이내)
    assert abs(iat_timestamp - now_timestamp) < 5, "iat should be close to current time"
    
    print("\n" + "=" * 60)
    print("✅ JWT timestamp format test passed!")
    print("=" * 60)


def test_jwt_verification():
    """JWT 검증 테스트"""
    print("\n" + "=" * 60)
    print("🔍 Testing JWT Verification")
    print("=" * 60)
    
    # 토큰 생성
    token = create_token(
        user_id="test_user_002",
        tenant_id="tenant2",
        email="user2@example.com",
        role="admin",
    )
    
    # 토큰 검증
    payload = verify_token(token)
    assert payload is not None, "Token verification should succeed"
    
    print(f"\n✓ Token verified successfully")
    print(f"  - User ID: {payload.user_id}")
    print(f"  - Tenant ID: {payload.tenant_id}")
    print(f"  - Email: {payload.email}")
    print(f"  - Role: {payload.role}")
    print(f"  - Exp: {payload.exp} (Unix timestamp)")
    print(f"  - Iat: {payload.iat} (Unix timestamp)")
    
    # 사용자 정보 추출
    user = get_user_from_token(token)
    assert user is not None, "User extraction should succeed"
    assert user.user_id == "test_user_002", "User ID should match"
    assert user.tenant_id == "tenant2", "Tenant ID should match"
    
    print(f"\n✓ User extracted successfully")
    print(f"  - User ID: {user.user_id}")
    print(f"  - Tenant ID: {user.tenant_id}")
    print(f"  - Email: {user.email}")
    print(f"  - Role: {user.role}")
    
    print("\n" + "=" * 60)
    print("✅ JWT verification test passed!")
    print("=" * 60)


def test_jwt_expiration():
    """JWT 만료 테스트"""
    print("\n" + "=" * 60)
    print("🔍 Testing JWT Expiration")
    print("=" * 60)
    
    from core.security import get_auth_service
    
    auth = get_auth_service()
    
    # 1초 후 만료되는 토큰 생성
    token = auth.create_access_token(
        {"sub": "test_user_003", "tenant_id": "tenant3"},
        expires_delta=timedelta(seconds=1),
    )
    
    # 즉시 검증 (성공해야 함)
    payload = verify_token(token)
    assert payload is not None, "Token should be valid immediately"
    print("\n✓ Token is valid immediately after creation")
    
    # 2초 대기 후 검증 (실패해야 함)
    import time
    time.sleep(2)
    
    payload = verify_token(token)
    assert payload is None, "Token should be expired after 2 seconds"
    print("✓ Token is expired after expiration time")
    
    print("\n" + "=" * 60)
    print("✅ JWT expiration test passed!")
    print("=" * 60)


def test_jwt_secret_key_length():
    """시크릿 키 길이 검증"""
    print("\n" + "=" * 60)
    print("🔍 Testing Secret Key Length")
    print("=" * 60)
    
    secret_key = settings.secret_key
    key_length = len(secret_key)
    
    print(f"\n✓ Secret key length: {key_length} bytes")
    
    # 최소 32바이트 (256비트) 확인
    assert key_length >= 32, f"Secret key must be at least 32 bytes (current: {key_length})"
    
    print(f"✓ Secret key meets minimum requirement (32 bytes for HS256)")
    
    print("\n" + "=" * 60)
    print("✅ Secret key length test passed!")
    print("=" * 60)


def test_jwt_java_compatibility():
    """Java 호환성 테스트 (토큰 구조 확인)"""
    print("\n" + "=" * 60)
    print("🔍 Testing JWT Java Compatibility")
    print("=" * 60)
    
    token = create_token(
        user_id="java_test_user",
        tenant_id="tenant1",
        email="java@example.com",
        role="user",
    )
    
    # 토큰 디코딩
    payload = jwt.get_unverified_claims(token)
    
    # 필수 클레임 확인
    required_claims = ["sub", "exp", "iat", "tenant_id", "email", "role"]
    for claim in required_claims:
        assert claim in payload, f"Required claim '{claim}' is missing"
        print(f"✓ Claim '{claim}' present: {payload[claim]}")
    
    # 타입 확인
    assert isinstance(payload["sub"], str), "sub must be a string"
    assert isinstance(payload["exp"], int), "exp must be an integer (Unix timestamp)"
    assert isinstance(payload["iat"], int), "iat must be an integer (Unix timestamp)"
    assert isinstance(payload["tenant_id"], str), "tenant_id must be a string"
    assert isinstance(payload["email"], str), "email must be a string"
    assert isinstance(payload["role"], str), "role must be a string"
    
    print("\n✓ All claims have correct types")
    print("\n" + "=" * 60)
    print("✅ JWT Java compatibility test passed!")
    print("=" * 60)
    print("\n💡 This token can be verified by dwp_backend (Java/Spring)")
    print(f"Token: {token[:50]}...")


def main():
    """메인 테스트 함수"""
    print("\n╔════════════════════════════════════════════════════════════╗")
    print("║     JWT Python-Java Compatibility Test Suite              ║")
    print("╚════════════════════════════════════════════════════════════╝\n")
    
    try:
        # 1. 타임스탬프 형식 테스트
        test_jwt_timestamp_format()
        
        # 2. JWT 검증 테스트
        test_jwt_verification()
        
        # 3. 만료 테스트
        test_jwt_expiration()
        
        # 4. 시크릿 키 길이 테스트
        test_jwt_secret_key_length()
        
        # 5. Java 호환성 테스트
        test_jwt_java_compatibility()
        
        print("\n╔════════════════════════════════════════════════════════════╗")
        print("║        ✅ All JWT Compatibility Tests Passed!              ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print("\n📌 JWT tokens generated by Aura-Platform are now compatible")
        print("   with dwp_backend (Java/Spring)! ✅")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
