#!/usr/bin/env python3
"""
Phase 2 검증 스크립트

Phase 2에서 구현한 기능들이 정상적으로 작동하는지 확인합니다.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 Python 패스에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_imports() -> bool:
    """모듈 임포트 테스트"""
    print("🔍 Testing imports...")
    try:
        # Memory modules
        from core.memory import (
            RedisStore,
            LangGraphCheckpointer,
            ConversationHistory,
            Message,
            MessageRole,
        )
        print("  ✓ Memory modules imported")
        
        # Security modules
        from core.security import (
            User,
            TokenPayload,
            AuthService,
            UserRole,
            Permission,
            PermissionService,
        )
        print("  ✓ Security modules imported")
        
        # API modules
        from api.middleware import (
            AuthMiddleware,
            TenantMiddleware,
            RequestLoggingMiddleware,
            ErrorHandlingMiddleware,
        )
        print("  ✓ API middleware imported")
        
        from api.dependencies import (
            get_current_user,
            get_tenant_id,
            require_permission,
        )
        print("  ✓ API dependencies imported")
        
        # LLM streaming
        from core.llm.client import LLMClient
        client = LLMClient()
        assert hasattr(client, 'astream')
        print("  ✓ LLM streaming support verified")
        
        return True
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_config() -> bool:
    """설정 검증"""
    print("\n🔍 Testing configuration...")
    try:
        from core.config import settings
        
        # Redis 설정 확인
        assert hasattr(settings, 'redis_url')
        assert hasattr(settings, 'redis_ttl')
        assert hasattr(settings, 'redis_checkpoint_ttl')
        print(f"  ✓ Redis TTL: {settings.redis_ttl}s")
        print(f"  ✓ Checkpoint TTL: {settings.redis_checkpoint_ttl}s")
        
        # 보안 설정 확인
        assert hasattr(settings, 'secret_key')
        assert hasattr(settings, 'allowed_origins')
        assert hasattr(settings, 'require_auth')
        print(f"  ✓ Auth required: {settings.require_auth}")
        print(f"  ✓ Allowed origins: {len(settings.allowed_origins)} configured")
        
        return True
    except Exception as e:
        print(f"  ✗ Configuration test failed: {e}")
        return False


def test_jwt() -> bool:
    """JWT 기능 테스트"""
    print("\n🔍 Testing JWT functionality...")
    try:
        from core.security import create_token, verify_token, get_user_from_token
        
        # 토큰 생성
        token = create_token(
            user_id="test_user",
            tenant_id="test_tenant",
            role="user",
        )
        print("  ✓ JWT token created")
        
        # 토큰 검증
        payload = verify_token(token)
        assert payload is not None
        assert payload.user_id == "test_user"
        print("  ✓ JWT token verified")
        
        # 사용자 정보 추출
        user = get_user_from_token(token)
        assert user is not None
        assert user.user_id == "test_user"
        assert user.tenant_id == "test_tenant"
        print("  ✓ User info extracted from token")
        
        return True
    except Exception as e:
        print(f"  ✗ JWT test failed: {e}")
        return False


def test_permissions() -> bool:
    """권한 시스템 테스트"""
    print("\n🔍 Testing permission system...")
    try:
        from core.security import User, Permission, has_permission, can_execute_agent, is_admin
        
        # 관리자 테스트
        admin = User(user_id="admin1", role="admin")
        assert can_execute_agent(admin) is True
        assert is_admin(admin) is True
        print("  ✓ Admin permissions verified")
        
        # 일반 사용자 테스트
        user = User(user_id="user1", role="user")
        assert can_execute_agent(user) is True
        assert is_admin(user) is False
        print("  ✓ User permissions verified")
        
        # 게스트 테스트
        guest = User(user_id="guest1", role="guest")
        assert can_execute_agent(guest) is False
        assert is_admin(guest) is False
        print("  ✓ Guest permissions verified")
        
        return True
    except Exception as e:
        print(f"  ✗ Permission test failed: {e}")
        return False


def test_models() -> bool:
    """데이터 모델 테스트"""
    print("\n🔍 Testing data models...")
    try:
        from core.memory import Message, MessageRole
        from core.security import User, TokenPayload
        
        # Message 모델
        msg = Message(
            role=MessageRole.USER,
            content="Test message",
        )
        assert msg.role == MessageRole.USER
        print("  ✓ Message model works")
        
        # User 모델
        user = User(
            user_id="test",
            tenant_id="tenant1",
            email="test@example.com",
            role="user",
        )
        assert user.is_authenticated is True
        print("  ✓ User model works")
        
        return True
    except Exception as e:
        print(f"  ✗ Model test failed: {e}")
        return False


def main() -> None:
    """메인 테스트 함수"""
    print("=" * 60)
    print("🚀 Phase 2 Verification")
    print("=" * 60)
    
    results = {
        "Imports": test_imports(),
        "Configuration": test_config(),
        "JWT": test_jwt(),
        "Permissions": test_permissions(),
        "Models": test_models(),
    }
    
    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)
    
    total = len(results)
    passed = sum(results.values())
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {test_name:.<40} {status}")
    
    print("\n" + "-" * 60)
    print(f"  Total: {passed}/{total} tests passed")
    print("-" * 60)
    
    if passed == total:
        print("\n🎉 All Phase 2 tests passed!")
        print("\n📌 Next steps:")
        print("  1. Install Redis: brew install redis (or start existing)")
        print("  2. Test Redis connection: redis-cli ping")
        print("  3. See docs/PHASE2_INTEGRATION_TEST.md for integration tests")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Please fix the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
