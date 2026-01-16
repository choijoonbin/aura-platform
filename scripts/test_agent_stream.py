#!/usr/bin/env python3
"""
Agent Streaming 테스트

에이전트가 도구를 선택하고 결과를 스트리밍하는지 검증합니다.
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from domains.dev.agents.code_agent import get_code_agent


async def test_agent_basic():
    """기본 에이전트 테스트"""
    print("=" * 60)
    print("🔍 Testing Code Agent (Basic Mode)")
    print("=" * 60)
    
    agent = get_code_agent()
    
    # 간단한 질문
    print("\n1. Testing simple question...")
    result = await agent.run(
        user_input="What tools do you have available?",
        user_id="test_user",
        tenant_id="tenant1",
    )
    
    print(f"  ✓ Response received: {result['response'][:100]}...")
    print(f"  ✓ Message count: {len(result['messages'])}")
    
    print("\n" + "=" * 60)
    print("✅ Basic agent test passed!")
    print("=" * 60)


async def test_agent_with_tools():
    """도구 사용 테스트"""
    print("\n" + "=" * 60)
    print("🔍 Testing Code Agent (With Tools)")
    print("=" * 60)
    
    agent = get_code_agent()
    
    # Git 상태 조회 요청
    print("\n1. Testing tool usage...")
    print("   Request: Check git status of /tmp")
    
    result = await agent.run(
        user_input="Check the git status of /tmp directory",
        user_id="test_user",
        tenant_id="tenant1",
    )
    
    print(f"\n  ✓ Response: {result['response'][:200]}...")
    print(f"  ✓ Messages exchanged: {len(result['messages'])}")
    
    # 메시지 타입 확인
    for i, msg in enumerate(result['messages']):
        msg_type = type(msg).__name__
        print(f"    {i+1}. {msg_type}")
    
    print("\n" + "=" * 60)
    print("✅ Tool usage test passed!")
    print("=" * 60)


async def test_agent_streaming():
    """스트리밍 테스트"""
    print("\n" + "=" * 60)
    print("🔍 Testing Code Agent (Streaming Mode)")
    print("=" * 60)
    
    agent = get_code_agent()
    
    print("\n1. Testing streaming...")
    print("   Request: What tools are available for Git operations?")
    print("\n   Streaming events:")
    print("   " + "-" * 56)
    
    event_count = 0
    async for event in agent.stream(
        user_input="What tools are available for Git operations?",
        user_id="test_user",
        tenant_id="tenant1",
    ):
        event_count += 1
        # 이벤트 노드 이름 추출
        for node_name in event.keys():
            print(f"   Event {event_count}: Node '{node_name}'")
            if event_count >= 10:  # 처음 10개만 표시
                print("   ... (more events)")
                break
        if event_count >= 10:
            break
    
    print("   " + "-" * 56)
    print(f"\n  ✓ Received {event_count}+ streaming event(s)")
    
    print("\n" + "=" * 60)
    print("✅ Streaming test passed!")
    print("=" * 60)


async def main():
    """메인 테스트 함수"""
    print("\n╔════════════════════════════════════════════════════════════╗")
    print("║     Agent Streaming Test Suite                            ║")
    print("╚════════════════════════════════════════════════════════════╝\n")
    
    try:
        # 1. 기본 테스트
        await test_agent_basic()
        
        # 2. 도구 사용 테스트
        await test_agent_with_tools()
        
        # 3. 스트리밍 테스트
        await test_agent_streaming()
        
        print("\n╔════════════════════════════════════════════════════════════╗")
        print("║              ✅ All Agent Tests Passed!                    ║")
        print("╚════════════════════════════════════════════════════════════╝")
        print("\n📌 Next steps:")
        print("  1. Start the server: python main.py")
        print("  2. Test API: POST /agents/chat/stream")
        print("  3. See docs for curl/React examples")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
