#!/usr/bin/env python3
"""Redis Store 기본 작업 테스트"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import get_redis_store

async def test_redis_basic():
    print("=" * 60)
    print("🔍 Testing Redis Store Basic Operations")
    print("=" * 60)
    
    store = await get_redis_store()
    
    # 1. Set/Get 테스트
    print("\n1. Testing SET/GET...")
    await store.set("test_key", b"test_value", ttl=60)
    value = await store.get("test_key")
    assert value == b"test_value"
    print("  ✓ SET/GET works")
    
    # 2. JSON 테스트
    print("\n2. Testing JSON operations...")
    test_data = {"name": "Aura", "version": "0.2.0"}
    await store.set_json("test_json", test_data, ttl=60)
    loaded_data = await store.get_json("test_json")
    assert loaded_data == test_data
    print("  ✓ JSON SET/GET works")
    
    # 3. Exists 테스트
    print("\n3. Testing EXISTS...")
    exists = await store.exists("test_key")
    assert exists is True
    print("  ✓ EXISTS works")
    
    # 4. Delete 테스트
    print("\n4. Testing DELETE...")
    await store.delete("test_key")
    value = await store.get("test_key")
    assert value is None
    print("  ✓ DELETE works")
    
    # Cleanup
    await store.delete("test_json")
    
    print("\n" + "=" * 60)
    print("✅ All Redis basic tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_redis_basic())
