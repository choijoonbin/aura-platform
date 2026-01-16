#!/usr/bin/env python3
"""
DWP Backend 통합 테스트 스크립트

백엔드 HITL API 구현 완료 후 통합 테스트를 수행합니다.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()

# 설정
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
AURA_PLATFORM_URL = os.getenv("AURA_PLATFORM_URL", "http://localhost:9000")
JWT_SECRET = os.getenv("JWT_SECRET", os.getenv("SECRET_KEY", ""))
TENANT_ID = os.getenv("TEST_TENANT_ID", "tenant1")
USER_ID = os.getenv("TEST_USER_ID", "test_user_001")


def generate_jwt_token() -> str:
    """JWT 토큰 생성 (테스트용)"""
    from jose import jwt
    
    now = datetime.now(timezone.utc)
    expiration = now.replace(hour=now.hour + 1)  # 1시간 후 만료
    
    payload = {
        "sub": USER_ID,
        "tenant_id": TENANT_ID,
        "email": "test@dwp.com",
        "role": "user",
        "exp": int(expiration.timestamp()),
        "iat": int(now.timestamp()),
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token


async def test_aura_platform_health():
    """Aura-Platform 헬스체크"""
    print("\n1️⃣ Aura-Platform 헬스체크 테스트")
    print("=" * 60)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{AURA_PLATFORM_URL}/health")
            
            if response.status_code == 200:
                print(f"✅ Aura-Platform 헬스체크 성공")
                print(f"   응답: {response.json()}")
                return True
            else:
                print(f"❌ Aura-Platform 헬스체크 실패: {response.status_code}")
                return False
    except Exception as e:
        print(f"❌ Aura-Platform 연결 실패: {e}")
        print(f"   확인: Aura-Platform이 포트 9000에서 실행 중인지 확인하세요")
        return False


async def test_gateway_routing():
    """Gateway 라우팅 테스트"""
    print("\n2️⃣ Gateway 라우팅 테스트")
    print("=" * 60)
    
    token = generate_jwt_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": TENANT_ID,
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Gateway를 통한 Aura-Platform 접근 테스트
            response = await client.get(
                f"{GATEWAY_URL}/api/aura/test/stream",
                params={"message": "test"},
                headers=headers,
            )
            
            if response.status_code == 200:
                print(f"✅ Gateway 라우팅 성공")
                print(f"   경로: {GATEWAY_URL}/api/aura/test/stream")
                print(f"   대상: Aura-Platform (포트 9000)")
                return True
            else:
                print(f"⚠️  Gateway 라우팅 응답: {response.status_code}")
                print(f"   응답: {response.text[:200]}")
                return False
    except Exception as e:
        print(f"❌ Gateway 연결 실패: {e}")
        print(f"   확인: Gateway가 포트 8080에서 실행 중인지 확인하세요")
        return False


async def test_hitl_approval_api():
    """HITL 승인 API 테스트"""
    print("\n3️⃣ HITL 승인 API 테스트")
    print("=" * 60)
    
    token = generate_jwt_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": TENANT_ID,
        "X-User-ID": USER_ID,
        "Content-Type": "application/json",
    }
    
    # 테스트용 requestId (실제로는 SSE 스트리밍에서 받아야 함)
    test_request_id = "test-req-12345"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 승인 API 호출
            response = await client.post(
                f"{GATEWAY_URL}/api/aura/hitl/approve/{test_request_id}",
                headers=headers,
                json={"userId": USER_ID},
            )
            
            print(f"   요청: POST {GATEWAY_URL}/api/aura/hitl/approve/{test_request_id}")
            print(f"   상태 코드: {response.status_code}")
            
            if response.status_code in [200, 404]:  # 404는 테스트용 requestId가 없어서 정상
                print(f"✅ HITL 승인 API 엔드포인트 접근 가능")
                if response.status_code == 404:
                    print(f"   참고: 테스트용 requestId가 없어서 404 응답 (정상)")
                else:
                    print(f"   응답: {response.json()}")
                return True
            else:
                print(f"❌ HITL 승인 API 실패: {response.status_code}")
                print(f"   응답: {response.text[:200]}")
                return False
    except Exception as e:
        print(f"❌ HITL 승인 API 연결 실패: {e}")
        return False


async def test_hitl_reject_api():
    """HITL 거절 API 테스트"""
    print("\n4️⃣ HITL 거절 API 테스트")
    print("=" * 60)
    
    token = generate_jwt_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": TENANT_ID,
        "X-User-ID": USER_ID,
        "Content-Type": "application/json",
    }
    
    # 테스트용 requestId
    test_request_id = "test-req-12345"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 거절 API 호출
            response = await client.post(
                f"{GATEWAY_URL}/api/aura/hitl/reject/{test_request_id}",
                headers=headers,
                json={"userId": USER_ID, "reason": "테스트 거절"},
            )
            
            print(f"   요청: POST {GATEWAY_URL}/api/aura/hitl/reject/{test_request_id}")
            print(f"   상태 코드: {response.status_code}")
            
            if response.status_code in [200, 404]:  # 404는 테스트용 requestId가 없어서 정상
                print(f"✅ HITL 거절 API 엔드포인트 접근 가능")
                if response.status_code == 404:
                    print(f"   참고: 테스트용 requestId가 없어서 404 응답 (정상)")
                else:
                    print(f"   응답: {response.json()}")
                return True
            else:
                print(f"❌ HITL 거절 API 실패: {response.status_code}")
                print(f"   응답: {response.text[:200]}")
                return False
    except Exception as e:
        print(f"❌ HITL 거절 API 연결 실패: {e}")
        return False


async def test_redis_connection():
    """Redis 연결 테스트"""
    print("\n5️⃣ Redis 연결 테스트")
    print("=" * 60)
    
    try:
        from core.memory import get_redis_store
        
        redis_store = await get_redis_store()
        await redis_store.connect()
        
        # 간단한 테스트
        test_key = "test:connection"
        await redis_store.set(test_key, "test_value", ttl=10)
        value = await redis_store.get(test_key)
        
        if value:
            print(f"✅ Redis 연결 성공")
            print(f"   호스트: localhost:6379")
            await redis_store.delete(test_key)
            return True
        else:
            print(f"❌ Redis 연결 실패: 값 조회 실패")
            return False
    except Exception as e:
        print(f"❌ Redis 연결 실패: {e}")
        print(f"   확인: Redis가 localhost:6379에서 실행 중인지 확인하세요")
        return False


async def test_port_configuration():
    """포트 설정 확인"""
    print("\n6️⃣ 포트 설정 확인")
    print("=" * 60)
    
    from core.config import settings
    
    print(f"   Aura-Platform 포트: {settings.api_port}")
    
    if settings.api_port == 9000:
        print(f"✅ 포트 설정 정상 (9000)")
        return True
    else:
        print(f"⚠️  포트 설정: {settings.api_port} (기대값: 9000)")
        print(f"   환경 변수 API_PORT=9000로 설정하거나 .env 파일 확인")
        return False


def print_summary(results: dict[str, bool]):
    """테스트 결과 요약"""
    print("\n" + "=" * 60)
    print("📊 테스트 결과 요약")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for name, result in results.items():
        status = "✅ 통과" if result else "❌ 실패"
        print(f"  {status}: {name}")
    
    print(f"\n총 {total}개 테스트 중 {passed}개 통과 ({passed*100//total}%)")
    
    if passed == total:
        print("\n🎉 모든 테스트 통과! 통합 준비 완료!")
    else:
        print("\n⚠️  일부 테스트 실패. 위의 오류 메시지를 확인하세요.")


async def main():
    """메인 테스트 함수"""
    print("=" * 60)
    print("DWP Backend 통합 테스트")
    print("=" * 60)
    print(f"Gateway URL: {GATEWAY_URL}")
    print(f"Aura-Platform URL: {AURA_PLATFORM_URL}")
    print(f"Tenant ID: {TENANT_ID}")
    print(f"User ID: {USER_ID}")
    
    results = {}
    
    # 테스트 실행
    results["포트 설정 확인"] = await test_port_configuration()
    results["Aura-Platform 헬스체크"] = await test_aura_platform_health()
    results["Redis 연결"] = await test_redis_connection()
    results["Gateway 라우팅"] = await test_gateway_routing()
    results["HITL 승인 API"] = await test_hitl_approval_api()
    results["HITL 거절 API"] = await test_hitl_reject_api()
    
    # 결과 요약
    print_summary(results)
    
    # 종료 코드
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
