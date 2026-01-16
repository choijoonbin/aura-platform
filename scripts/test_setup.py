#!/usr/bin/env python3
"""
Aura-Platform Setup Verification Script

프로젝트 설정이 올바르게 되었는지 확인하는 스크립트입니다.
"""

import sys
from pathlib import Path

# 프로젝트 루트를 Python 패스에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_imports() -> bool:
    """필수 패키지 임포트 테스트"""
    print("🔍 Testing imports...")
    try:
        import langchain
        import langgraph
        import fastapi
        import pydantic
        from langchain_openai import ChatOpenAI
        print("  ✓ All core packages imported successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False


def test_config() -> bool:
    """설정 로딩 테스트"""
    print("\n🔍 Testing configuration...")
    try:
        from core.config import settings
        print(f"  ✓ Config loaded: {settings.app_name} v{settings.app_version}")
        print(f"  ✓ Environment: {settings.app_env}")
        print(f"  ✓ OpenAI Model: {settings.openai_model}")
        print(f"  ✓ Dev Domain: {'Enabled' if settings.dev_domain_enabled else 'Disabled'}")
        return True
    except Exception as e:
        print(f"  ✗ Config loading failed: {e}")
        return False


def test_llm_client() -> bool:
    """LLM 클라이언트 초기화 테스트"""
    print("\n🔍 Testing LLM client...")
    try:
        from core.llm import get_llm_client
        client = get_llm_client()
        print(f"  ✓ LLM Client initialized")
        print(f"  ✓ Model: {client.model}")
        print(f"  ✓ Temperature: {client.temperature}")
        return True
    except Exception as e:
        print(f"  ✗ LLM client initialization failed: {e}")
        return False


def test_project_structure() -> bool:
    """프로젝트 구조 검증"""
    print("\n🔍 Testing project structure...")
    required_dirs = [
        "core",
        "core/llm",
        "core/memory",
        "core/security",
        "domains",
        "domains/dev",
        "domains/dev/agents",
        "domains/dev/workflows",
        "api",
        "api/routes",
        "api/schemas",
        "tools",
        "tools/integrations",
        "database",
        "database/models",
        "tests",
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        full_path = project_root / dir_path
        if full_path.exists():
            print(f"  ✓ {dir_path}")
        else:
            print(f"  ✗ {dir_path} (missing)")
            all_exist = False
    
    return all_exist


def test_env_file() -> bool:
    """환경변수 파일 검증"""
    print("\n🔍 Testing environment file...")
    env_file = project_root / ".env"
    
    if not env_file.exists():
        print("  ✗ .env file not found")
        return False
    
    print("  ✓ .env file exists")
    
    # 중요 환경변수 확인
    with open(env_file) as f:
        content = f.read()
        
    required_vars = [
        "OPENAI_API_KEY",
        "SECRET_KEY",
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
    ]
    
    all_present = True
    for var in required_vars:
        if var in content:
            print(f"  ✓ {var} present")
        else:
            print(f"  ✗ {var} missing")
            all_present = False
    
    return all_present


def main() -> None:
    """메인 테스트 함수"""
    print("=" * 60)
    print("🚀 Aura-Platform Setup Verification")
    print("=" * 60)
    
    results = {
        "Imports": test_imports(),
        "Configuration": test_config(),
        "LLM Client": test_llm_client(),
        "Project Structure": test_project_structure(),
        "Environment File": test_env_file(),
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
        print("\n🎉 All tests passed! Your setup is ready.")
        print("\n📌 Next steps:")
        print("  1. Update OPENAI_API_KEY in .env with your actual API key")
        print("  2. Start the server: python main.py")
        print("  3. Visit http://localhost:8000/docs")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Please fix the issues above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
