#!/usr/bin/env python3
"""JWT 독립 테스트"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.security import create_token, verify_token, get_user_from_token

def test_jwt_standalone():
    print("=" * 60)
    print("🔍 Testing JWT (Standalone)")
    print("=" * 60)
    
    # 1. 토큰 생성
    print("\n1. Creating token...")
    token = create_token(
        user_id="test_user_001",
        tenant_id="tenant1",
        email="test@example.com",
        role="user",
    )
    print(f"  ✓ Token created")
    print(f"  Token (first 50 chars): {token[:50]}...")
    
    # 2. 토큰 검증
    print("\n2. Verifying token...")
    payload = verify_token(token)
    assert payload is not None
    print(f"  ✓ Token verified")
    print(f"  - User ID: {payload.user_id}")
    print(f"  - Tenant ID: {payload.tenant_id}")
    print(f"  - Role: {payload.role}")
    
    # 3. 사용자 정보 추출
    print("\n3. Extracting user info...")
    user = get_user_from_token(token)
    assert user is not None
    print(f"  ✓ User extracted")
    print(f"  - User ID: {user.user_id}")
    print(f"  - Email: {user.email}")
    print(f"  - Role: {user.role}")
    print(f"  - Authenticated: {user.is_authenticated}")
    
    print("\n" + "=" * 60)
    print("✅ JWT standalone test passed!")
    print("=" * 60)
    print(f"\n💡 Use this token for API testing:")
    print(f"\n{token}\n")
    print("Test with:")
    print(f'export TOKEN="{token}"')
    print('curl http://localhost:8000/health \\')
    print('  -H "Authorization: Bearer $TOKEN" \\')
    print('  -H "X-Tenant-ID: tenant1"')

if __name__ == "__main__":
    test_jwt_standalone()
